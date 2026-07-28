"""平台设置 service。

单例 default_model_id：平台级 LLM 调用（文档搜索 AI 总结等）的默认模型。
解析优先级：DB 单例 > env PLATFORM_DEFAULT_MODEL_ID；未配或模型失效返回 None。
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings as app_settings
from exceptions import NotFoundError
from repositories import model_repo, platform_settings_repo


async def get_settings(session: AsyncSession) -> dict:
    s = await platform_settings_repo.get_settings(session)
    default_model_name: str | None = None
    if s.default_model_id:
        model = await model_repo.find_by_id(session, s.default_model_id)
        if model:
            default_model_name = model.name
    return {
        "default_model_id": s.default_model_id,
        "default_model_name": default_model_name,
        "env_default_model_id": app_settings.platform_default_model_id,
        "updated_by": s.updated_by,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


async def update_default_model(
    session: AsyncSession, model_id: int | None, current_user: dict
) -> dict:
    if model_id is not None:
        model = await model_repo.find_by_id(session, model_id)
        if model is None:
            raise NotFoundError("模型", model_id)
    s = await platform_settings_repo.get_settings(session)
    s.default_model_id = model_id
    s.updated_by = int(current_user["id"])
    s.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(s)
    return await get_settings(session)


async def resolve_default_model(
    session: AsyncSession,
) -> tuple[int, str] | None:
    """返回 (model_id, litellm_model_name)；未配或模型失效返回 None。"""
    s = await platform_settings_repo.get_settings(session)
    model_id = s.default_model_id or app_settings.platform_default_model_id
    if not model_id:
        return None
    model = await model_repo.find_by_id(session, model_id)
    if model is None or not model.is_active:
        return None
    model_name = getattr(model, "model_id", "") or getattr(model, "name", "")
    if not model_name:
        return None
    return model_id, model_name
