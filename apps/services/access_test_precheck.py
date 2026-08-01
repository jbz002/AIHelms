from sqlalchemy.ext.asyncio import AsyncSession

from models.db import AiKey, Model, ModelDeployment
from repositories import ai_key_repo, model_repo
from services import platform_llm
from services.access_test_error_mapper import build_error_detail


async def resolve_test_identity(session: AsyncSession, user_id: int) -> AiKey | None:
    key = await ai_key_repo.find_personal_main(session, user_id)
    if not key or not key.is_active or not key.litellm_key_id:
        return None
    return key


async def precheck_access_test(
    session: AsyncSession,
    user_id: int,
    model: Model | None,
    test_model: str,
    is_admin: bool,
) -> tuple[str | None, dict[str, object] | None]:
    """返回 (api_key, error_detail)。成功时 api_key 非空、error_detail 为 None。

    管理员优先归因到个人主 Key（需授权目标模型），无权或缺失时回退 master key，
    与平台默认模型调用统一；普通用户走个人主 Key 并校验模型授权/发布状态。
    """
    if is_admin:
        return await _precheck_admin(session, user_id, model, test_model)
    return await _precheck_user(session, user_id, model, test_model)


async def _precheck_admin(
    session: AsyncSession, user_id: int, model: Model | None, test_model: str
) -> tuple[str | None, dict[str, object] | None]:
    platform_key, _ = await platform_llm.resolve_call_identity(
        session, {"id": user_id}, test_model
    )
    if not platform_key:
        return None, build_error_detail("no_platform_key")
    if not model:
        return platform_key, None
    if not model.is_active:
        return None, build_error_detail("no_active_deployment")
    deployments = await model_repo.find_deployments_by_model(session, model.id)
    if not any(_deployment_available(deployment) for deployment in deployments):
        return None, build_error_detail("no_active_deployment")
    return platform_key, None


async def _precheck_user(
    session: AsyncSession,
    user_id: int,
    model: Model | None,
    test_model: str,
) -> tuple[str | None, dict[str, object] | None]:
    key = await resolve_test_identity(session, user_id)
    if not key:
        return None, build_error_detail("no_identity")
    if not _model_authorized(key, test_model):
        return None, build_error_detail("model_not_authorized")
    if not model or not model.is_active or not model.is_published:
        return None, build_error_detail("model_not_published")
    deployments = await model_repo.find_deployments_by_model(session, model.id)
    if not any(_deployment_available(deployment) for deployment in deployments):
        return None, build_error_detail("no_active_deployment")
    return key.litellm_key_id, None


def _model_authorized(key: AiKey, model_id: str) -> bool:
    model_ids = key.models or []
    return "*" in model_ids or model_id in model_ids


def _deployment_available(deployment: ModelDeployment) -> bool:
    credential = deployment.credential
    return deployment.is_active and (credential is None or credential.is_active)
