"""AI Hub 服务间集成（HMAC 验签，方式六）。

AI Hub 后端每次请求带 HMAC-SHA256 签名头（X-AIHub-Timestamp/Signature/On-Behalf-Of），
core/aihub_verify.verify_aihub 验签后按 On-Behalf-Of 的 aihub_user_id
定位用户，供其拉取用户 AI 身份。
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import async_session
from exceptions import UnauthorizedError
from models.db import AdminAuditLog, User
from repositories import user_repo
from services import ai_key_service, litellm_client, user_service

logger = logging.getLogger(__name__)

INTEGRATION_AUDIT_TYPE = "integration"


async def _upsert_integration_user(session: AsyncSession, aihub_user_id: str) -> User:
    """未知用户占位建档（同 SSO 首登占位逻辑）；后续 SSO 登录会补全档案。"""
    user = await user_repo.upsert_user_from_aihub(
        session,
        aihub_user_id=aihub_user_id,
        username=f"aihub_{aihub_user_id[:8]}",
        email=f"{aihub_user_id}@aihub.local",
        display_name="",
        aihub_department_id=None,
        phone="",
    )
    # 不 provision 则新用户 personal 组恒为空；幂等，失败下次补建（同 SSO 路径容错）
    try:
        await user_service.provision_user_resources(session, user)
    except litellm_client.LiteLLMError:
        logger.exception("provision user resources failed, will retry next call")
    return user


async def get_user_by_aihub_id(session: AsyncSession, aihub_user_id: str) -> User:
    """按 aihub_user_id 定位用户；未知则占位建档（同 SSO 首登占位逻辑）。"""
    user = await user_repo.find_user_by_aihub_user_id(session, aihub_user_id)
    if user is None:
        user = await _upsert_integration_user(session, aihub_user_id)
        # upsert/provision 路径必须显式落库（get_db 不自动 commit）
        await session.commit()
    return user


async def get_integration_identity_data(
    session: AsyncSession, aihub_user_id: str, ip: str
) -> dict:
    """按 aihub_user_id 返回用户全量 AI 身份（复用 web 端 get_my_keys），并异步落审计。

    验签已在 core/aihub_verify 完成，此处只负责用户定位与建档。
    """
    user = await get_user_by_aihub_id(session, aihub_user_id)
    if not user.is_active:
        logger.warning(
            "integration identity rejected: user disabled: %s", aihub_user_id
        )
        raise UnauthorizedError("用户已禁用")

    data = await ai_key_service.get_my_keys(session, user.id)
    key_count = sum(len(items or []) for items in data.values())
    asyncio.create_task(
        record_identity_pull_audit(
            user_id=user.id,
            username=user.username,
            aihub_user_id=aihub_user_id,
            ip=ip,
            key_count=key_count,
        )
    )
    return data


async def record_identity_pull_audit(
    *, user_id: int, username: str, aihub_user_id: str, ip: str, key_count: int
) -> None:
    """敏感 key 外流事件写入管理员审计日志（不记 key 明文）。失败仅告警不影响业务。"""
    for attempt in range(2):
        try:
            async with async_session() as session:
                session.add(
                    AdminAuditLog(
                        user_id=user_id,
                        username=username,
                        identity_type=INTEGRATION_AUDIT_TYPE,
                        method="GET",
                        path="/api/v1/integration/identity",
                        action="集成拉取用户 AI 身份",
                        status_code=200,
                        ip=ip,
                        detail={"aihub_user_id": aihub_user_id, "key_count": key_count},
                    )
                )
                await session.commit()
            return
        except Exception:  # noqa: BLE001
            if attempt == 0:
                await asyncio.sleep(0.2)
                continue
            logger.warning("write integration audit log failed", exc_info=True)
