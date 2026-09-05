"""平台设置 service。

单例 default_model_id：平台级 LLM 调用（文档搜索 AI 总结等）的默认模型。
解析优先级：DB 单例 > env PLATFORM_DEFAULT_MODEL_ID；未配或模型失效返回 None。

default_key_*：新用户自动创建个人主 Key 时的默认预算/限流，
被 ai_key_service.create_personal_main_key 套用（仅统一预算 + 总限流粒度）。
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings as app_settings
from exceptions import NotFoundError
from repositories import model_repo, platform_settings_repo


@dataclass
class DefaultKeyConfig:
    """新用户个人主 Key 的默认预算/限流配置。"""

    budget_limit: Decimal | None
    budget_hard_limit: bool
    budget_duration: str
    rate_limit_mode: str
    tpm_limit: int | None
    rpm_limit: int | None
    max_parallel_requests: int | None


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
        "default_key_budget_limit": (
            str(s.default_key_budget_limit)
            if s.default_key_budget_limit is not None
            else None
        ),
        "default_key_budget_hard_limit": s.default_key_budget_hard_limit,
        "default_key_budget_duration": s.default_key_budget_duration,
        "default_key_rate_limit_mode": s.default_key_rate_limit_mode,
        "default_key_tpm_limit": s.default_key_tpm_limit,
        "default_key_rpm_limit": s.default_key_rpm_limit,
        "default_key_max_parallel_requests": s.default_key_max_parallel_requests,
        "updated_by": s.updated_by,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


async def update_settings(
    session: AsyncSession,
    model_id: int | None,
    key_config: DefaultKeyConfig,
    current_user: dict,
) -> dict:
    if model_id is not None:
        model = await model_repo.find_by_id(session, model_id)
        if model is None:
            raise NotFoundError("模型", model_id)
    s = await platform_settings_repo.get_settings(session)
    s.default_model_id = model_id
    s.default_key_budget_limit = key_config.budget_limit
    s.default_key_budget_hard_limit = key_config.budget_hard_limit
    s.default_key_budget_duration = key_config.budget_duration
    s.default_key_rate_limit_mode = key_config.rate_limit_mode
    s.default_key_tpm_limit = key_config.tpm_limit
    s.default_key_rpm_limit = key_config.rpm_limit
    s.default_key_max_parallel_requests = key_config.max_parallel_requests
    s.updated_by = int(current_user["id"])
    s.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(s)
    return await get_settings(session)


async def update_default_model_only(
    session: AsyncSession, model_id: int | None, current_user: dict
) -> dict:
    """仅更新默认模型，保留现有 default_key_* 配置不变（MCP 工具入口）。"""
    s = await platform_settings_repo.get_settings(session)
    key_config = DefaultKeyConfig(
        budget_limit=s.default_key_budget_limit,
        budget_hard_limit=s.default_key_budget_hard_limit,
        budget_duration=s.default_key_budget_duration or "30d",
        rate_limit_mode=s.default_key_rate_limit_mode,
        tpm_limit=s.default_key_tpm_limit,
        rpm_limit=s.default_key_rpm_limit,
        max_parallel_requests=s.default_key_max_parallel_requests,
    )
    return await update_settings(session, model_id, key_config, current_user)


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


async def resolve_default_key_config(session: AsyncSession) -> DefaultKeyConfig | None:
    """返回新用户主 Key 默认预算/限流；预算与限流均未启用时返回 None。"""
    s = await platform_settings_repo.get_settings(session)
    budget_active = s.default_key_budget_limit is not None
    rate_active = s.default_key_rate_limit_mode != "none"
    if not budget_active and not rate_active:
        return None
    duration = s.default_key_budget_duration or "30d"
    return DefaultKeyConfig(
        budget_limit=s.default_key_budget_limit,
        budget_hard_limit=s.default_key_budget_hard_limit if budget_active else False,
        budget_duration=duration if budget_active else "30d",
        rate_limit_mode=s.default_key_rate_limit_mode,
        tpm_limit=s.default_key_tpm_limit if rate_active else None,
        rpm_limit=s.default_key_rpm_limit if rate_active else None,
        max_parallel_requests=(
            s.default_key_max_parallel_requests if rate_active else None
        ),
    )
