"""AI Hub 服务间集成（RFC 7523 JWT Bearer Assertion）。

AI Hub 后端用 RS256 私钥签断言（iss/aud/sub/jti/iat/exp），
本服务验签换短期集成令牌，再供其拉取用户 AI 身份。
集成令牌 payload 带 token_use="integration"，与普通登录 JWT 双向隔离。
"""

import asyncio
import logging
import re
import time
from datetime import timedelta

from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import async_session
from core.redis_client import get_redis
from core.security import create_access_token
from exceptions import ForbiddenError, UnauthorizedError
from models.db import AdminAuditLog, User
from repositories import user_repo
from services import ai_key_service, litellm_client, user_service

logger = logging.getLogger(__name__)

INTEGRATION_TOKEN_USE = "integration"

_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN PUBLIC KEY-----.*?-----END PUBLIC KEY-----", re.DOTALL
)

# 公钥解析缓存：以配置原文为 key，monkeypatch settings 后自动失效
_public_key_cache: dict[str, list[str]] = {}


def _load_public_keys() -> list[str]:
    raw = settings.aihub_integration_public_keys.replace("\\n", "\n")
    cached = _public_key_cache.get(raw)
    if cached is not None:
        return cached
    keys = _PEM_BLOCK_RE.findall(raw)
    if not keys:
        raise RuntimeError("AI Hub 集成公钥未配置(aihub_integration_public_keys 为空)")
    _public_key_cache.clear()
    _public_key_cache[raw] = keys
    return keys


def _reject(reason: str) -> UnauthorizedError:
    """校验失败细节只进日志，对外统一模糊化 401。"""
    logger.warning("assertion rejected: %s", reason)
    return UnauthorizedError("断言无效或已过期")


def _validate_assertion_claims(payload: dict) -> tuple[str, int]:
    """校验 sub/jti/iat/exp 契约，返回 (jti, exp)。"""
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise _reject("sub missing")
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        raise _reject("jti missing (replay protection requires it)")
    iat = payload.get("iat")
    exp = payload.get("exp")
    if not isinstance(iat, int) or not isinstance(exp, int):
        raise _reject("iat/exp missing")
    now = int(time.time())
    if iat > now + settings.aihub_integration_iat_leeway_seconds:
        raise _reject(f"iat in future beyond leeway: {iat}")
    lifetime = exp - iat
    if lifetime > settings.aihub_integration_max_assertion_seconds:
        raise _reject(f"lifetime {lifetime}s exceeds max")
    return jti, exp


def verify_aihub_assertion(assertion: str) -> dict:
    """RS256 验签 + iss/aud/exp 校验（jose 自动）+ claims 契约校验。"""
    payload = None
    last_error: Exception | None = None
    for pem in _load_public_keys():
        try:
            # algorithms 硬编码防算法混淆（攻击者用我方公钥内容当 HS256 密钥）
            payload = jwt.decode(
                assertion,
                pem,
                algorithms=["RS256"],
                audience=settings.aihub_integration_aud,
                issuer=settings.aihub_integration_iss,
            )
            break
        except JWTError as exc:
            last_error = exc
    if payload is None:
        raise _reject(f"signature/iss/aud/exp invalid: {last_error}")
    return payload


async def check_and_record_jti(jti: str, ttl_seconds: int) -> None:
    """Redis SETNX 防重放：key 已存在 = 断言被重放。Redis 故障 fail-open。"""
    key = f"aihelms:integration:assertion_jti:{jti}"
    try:
        client = get_redis()
        acquired = await client.set(key, "1", nx=True, ex=max(ttl_seconds, 60))
        if not acquired:
            raise _reject(f"jti replayed: {jti[:12]}")
    except UnauthorizedError:
        raise
    except Exception:  # noqa: BLE001
        logger.error("jti replay check failed (fail-open)", exc_info=True)


async def check_token_endpoint_rate_limit(ip: str) -> None:
    """token 端点每 IP 固定窗口限速（唯一无 Bearer 保护的公网入口）。0 = 关闭。"""
    limit = settings.aihub_integration_rate_limit_per_minute
    if limit <= 0:
        return
    key = f"aihelms:integration:rate_limit:{ip}"
    try:
        client = get_redis()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, 60)
        if count > limit:
            logger.warning("integration token rate limited: ip=%s count=%s", ip, count)
            raise ForbiddenError("请求过于频繁，请稍后重试")
    except ForbiddenError:
        raise
    except Exception:  # noqa: BLE001
        logger.error("rate limit check failed (fail-open)", exc_info=True)


async def _upsert_integration_user(session: AsyncSession, aihub_user_id: str) -> User:
    """断言只有 sub，占位建档（同 SSO 首登占位逻辑）；后续 SSO 登录会补全档案。"""
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


async def issue_integration_token(session: AsyncSession, assertion: str) -> dict:
    """断言 → 集成访问令牌。编排入口，router 唯一调用。"""
    if not settings.aihub_integration_enabled:
        raise ForbiddenError("集成通道未启用")
    payload = verify_aihub_assertion(assertion)
    jti, exp = _validate_assertion_claims(payload)
    ttl = max(exp - int(time.time()), 0) + 60
    await check_and_record_jti(jti, ttl_seconds=ttl)

    aihub_user_id = payload["sub"]
    user = await user_repo.find_user_by_aihub_user_id(session, aihub_user_id)
    if user is None:
        user = await _upsert_integration_user(session, aihub_user_id)
    if not user.is_active:
        logger.warning("integration token rejected: user disabled: %s", aihub_user_id)
        raise UnauthorizedError("用户已禁用")

    token = create_access_token(
        {
            "sub": str(user.id),
            "username": user.username,
            "aihub_user_id": aihub_user_id,
            "token_use": INTEGRATION_TOKEN_USE,
        },
        expires_delta=timedelta(
            minutes=settings.aihub_integration_token_expire_minutes
        ),
    )
    # upsert/provision 路径必须显式落库（get_db 不自动 commit）
    await session.commit()
    logger.info(
        "integration token issued",
        extra={"aihub_user_id": aihub_user_id, "user_id": user.id},
    )
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": settings.aihub_integration_token_expire_minutes * 60,
    }


def decode_integration_token(token: str) -> dict:
    """解码集成访问令牌（HS256，同本地 JWT 算法），仅接受 token_use=integration。"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except JWTError:
        raise UnauthorizedError("未认证或 token 已过期")
    if payload.get("token_use") != INTEGRATION_TOKEN_USE or not payload.get("sub"):
        raise UnauthorizedError("未认证或 token 已过期")
    user_id = int(payload["sub"])
    # is_admin 硬编码 False：集成通道永不产生管理员身份
    return {
        "id": user_id,
        "user_id": user_id,
        "username": payload.get("username", ""),
        "aihub_user_id": payload.get("aihub_user_id", ""),
        "identity_type": INTEGRATION_TOKEN_USE,
        "is_admin": False,
        "permissions": [],
    }


async def get_integration_identity_data(
    session: AsyncSession, identity: dict, ip: str
) -> dict:
    """返回用户全量 AI 身份（复用 web 端 get_my_keys），并异步落审计。"""
    data = await ai_key_service.get_my_keys(session, identity["user_id"])
    key_count = sum(len(items or []) for items in data.values())
    asyncio.create_task(
        record_identity_pull_audit(
            user_id=identity["user_id"],
            username=identity["username"],
            aihub_user_id=identity["aihub_user_id"],
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
                        identity_type=INTEGRATION_TOKEN_USE,
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
