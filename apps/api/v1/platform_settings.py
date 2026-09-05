from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from services import platform_settings_service
from services.platform_settings_service import DefaultKeyConfig

router = APIRouter(prefix="/platform-settings", tags=["平台设置"])


class UpdatePlatformSettingsRequest(BaseModel):
    """全量替换语义：default_key_* 未启用时传空值清空，未提交的字段回落默认。"""

    default_model_id: int | None = None
    default_key_budget_limit: Decimal | None = Field(None, ge=0)
    default_key_budget_hard_limit: bool = False
    default_key_budget_duration: str = Field("30d", pattern=r"^(1d|7d|30d)$")
    default_key_rate_limit_mode: str = Field("none", pattern=r"^(none|total)$")
    default_key_tpm_limit: int | None = Field(None, ge=1)
    default_key_rpm_limit: int | None = Field(None, ge=1)
    default_key_max_parallel_requests: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def check_rate_limit_mode(self) -> "UpdatePlatformSettingsRequest":
        rate_values = (
            self.default_key_tpm_limit,
            self.default_key_rpm_limit,
            self.default_key_max_parallel_requests,
        )
        if self.default_key_rate_limit_mode == "total" and all(
            v is None for v in rate_values
        ):
            raise ValueError("总限流模式下 TPM/RPM/最大并发至少配置一项")
        if self.default_key_rate_limit_mode == "none" and any(
            v is not None for v in rate_values
        ):
            raise ValueError("不限流模式下不能配置 TPM/RPM/最大并发")
        return self


@router.get("", summary="查询平台设置")
async def get_settings(
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("platform_settings:read")),
):
    data = await platform_settings_service.get_settings(session)
    return {"code": 200, "message": "ok", "data": data}


@router.put("", summary="更新平台设置")
async def update_settings(
    req: UpdatePlatformSettingsRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("platform_settings:config")),
):
    key_config = DefaultKeyConfig(
        budget_limit=req.default_key_budget_limit,
        budget_hard_limit=req.default_key_budget_hard_limit,
        budget_duration=req.default_key_budget_duration,
        rate_limit_mode=req.default_key_rate_limit_mode,
        tpm_limit=req.default_key_tpm_limit,
        rpm_limit=req.default_key_rpm_limit,
        max_parallel_requests=req.default_key_max_parallel_requests,
    )
    data = await platform_settings_service.update_settings(
        session, req.default_model_id, key_config, current_user
    )
    return {"code": 200, "message": "平台设置已更新", "data": data}
