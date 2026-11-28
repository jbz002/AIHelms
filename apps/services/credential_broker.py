"""P2-F4 · Token Broker：把「用户 → 目标平台的短时委托票」集中到 AIHelms。

迁移前这段逻辑长在 ai-assistant 的 `quanyu_identity.py` 里，换票密钥
`QUANYU_APP_SECRET` 也跟着散落在每个子应用。收归这里之后：

    mcp_proxy（服务令牌） → POST /api/v1/mcp/credentials/exchange
      → 主体解析：aihub_user_id → AI Hub 用户档案 → 钉钉 unionid / userid
      → 提供方换票：POST {quanyu_auth_url}/aiIdentity/exchange
      ← { header, token, expires_in }

契约见 `03` §6。三条硬约束：

1. **票不进日志**：审计只记主体、目标、结果码与耗时；这是 02 §7 的红线。
2. **票进 Redis**（契约要求），键 `subject|target|actor.kind`，TTL = `expires_in − margin`；
   按 key 加分布式锁防击穿，锁抢不到时短暂重查，仍没有就直换（可用性优先于去重）。
3. **失败全部收敛成稳定码**（`target_unknown` / `subject_not_bound` /
   `provider_unavailable`），上游报文一律不外泄。

开关：``MCP_CREDENTIAL_BROKER_ENABLED``（默认关）。关闭时接口 404，老路径不受影响。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.distributed_lock import redis_lock
from core.redis_client import get_redis
from exceptions import LockBusyError
from models.db import CredentialExchangeLog

logger = logging.getLogger(__name__)

# 出站身份头：需与业务平台（SCP ai.access.token-header）和 AIHelms MCP extra_headers 一致
DELEGATION_HEADER = "X-AI-Delegation"

# 结果码（稳定码，文案由调用方本地化）
R_EXCHANGED = "exchanged"
R_TARGET_UNKNOWN = "target_unknown"
R_SUBJECT_NOT_BOUND = "subject_not_bound"
R_PROVIDER_UNAVAILABLE = "provider_unavailable"

_CACHE_PREFIX = "aihelms:cred:"
_LOCK_PREFIX = "aihelms:lock:cred:"
_LOCK_TTL = 10  # 秒；换票本身 5s 超时，留一倍余量
_LOCK_WAIT_POLLS = 3
_LOCK_WAIT_INTERVAL = 0.05


class CredentialError(Exception):
    """换票失败（携带稳定码；message 只用于服务端日志，不回显上游报文）。"""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message


@dataclass
class ExchangedCredential:
    header: str
    token: str
    expires_in: int


@dataclass
class CredentialResult:
    ok: bool
    reason_code: str
    header: str | None = None
    token: str | None = None
    expires_in: int | None = None
    provider: str = ""
    cached: bool = False

    def to_dict(self) -> dict:
        """给调用方的响应体（**含票**）；审计与日志不要用这个。"""
        if not self.ok:
            return {
                "ok": False,
                "reason_code": self.reason_code,
                "provider": self.provider,
            }
        return {
            "ok": True,
            "reason_code": self.reason_code,
            "header": self.header,
            "token": self.token,
            "expires_in": self.expires_in,
            "provider": self.provider,
            "cached": self.cached,
        }


# ----------------------------------------------------------------------
# 目标平台解析
# ----------------------------------------------------------------------


def target_app_for(target: str) -> str:
    """MCP server_name → 目标平台 appId；不在映射内返回空串（= target_unknown）。

    配置了 ``quanyu_target_app_ids``（"server_name:appId" 逗号分隔）即按白名单严格匹配：
    未命中的 server（如文档检索）不需要全域身份，调用方据此跳过换票、不注入身份头。
    映射整体为空时才沿用单目标形态 ``quanyu_target_app_id``。
    """
    mapping = [item.strip() for item in (settings.quanyu_target_app_ids or "").split(",")]
    mapping = [item for item in mapping if item]
    name = (target or "").strip()
    if mapping:
        for item in mapping:
            if ":" not in item:
                continue
            key, _, app_id = item.partition(":")
            if key.strip() == name and app_id.strip():
                return app_id.strip()
        return ""
    return (settings.quanyu_target_app_id or "").strip()


# ----------------------------------------------------------------------
# 提供方抽象
# ----------------------------------------------------------------------


class CredentialProvider(Protocol):
    """凭据提供方。后续可加 oauth / id_jag，注册进 ``_PROVIDERS`` 即可。"""

    name: str

    def supports(self, target: str) -> bool: ...

    async def exchange(
        self, subject_type: str, subject_id: str, app_id: str
    ) -> ExchangedCredential: ...


class QuanyuProvider:
    """全域（quanyu）认证中心：钉钉身份 → 目标平台短时委托票。"""

    name = "quanyu"

    def supports(self, target: str) -> bool:
        return bool(target_app_for(target))

    async def exchange(
        self, subject_type: str, subject_id: str, app_id: str
    ) -> ExchangedCredential:
        dt_type, dt_value = await _resolve_dingtalk_identity(subject_id)
        token, expires_in = await _call_quanyu_exchange(dt_type, dt_value, app_id)
        return ExchangedCredential(header=DELEGATION_HEADER, token=token, expires_in=expires_in)


_PROVIDERS: list[CredentialProvider] = [QuanyuProvider()]


def _provider_for(target: str) -> CredentialProvider | None:
    for provider in _PROVIDERS:
        if provider.supports(target):
            return provider
    return None


def is_configured() -> bool:
    return bool(
        settings.quanyu_auth_url
        and settings.quanyu_app_id
        and settings.quanyu_app_secret
    )


# ----------------------------------------------------------------------
# 主体解析：aihub_user_id → 钉钉身份
# ----------------------------------------------------------------------


async def _resolve_dingtalk_identity(aihub_user_id: str) -> tuple[str, str]:
    """取 (subjectType, subjectValue)。连接键是钉钉 ID，不受重名/改名影响。"""
    base = (settings.ai_hub_url or "").strip().rstrip("/")
    key = (settings.ai_hub_app_key or "").strip()
    if not base or not key:
        raise CredentialError(
            R_PROVIDER_UNAVAILABLE, "AI_HUB_URL / AI_HUB_APP_KEY 未配置，无法解析主体"
        )

    url = f"{base}/api/v1/common/users/{aihub_user_id}"
    try:
        async with httpx.AsyncClient(
            timeout=settings.quanyu_timeout_seconds, trust_env=False
        ) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        # 只带异常类型名，绝不带请求头/URL 里的凭据
        raise CredentialError(
            R_PROVIDER_UNAVAILABLE, f"AI Hub 主体查询失败（{type(exc).__name__}）"
        ) from exc

    if resp.status_code == 404:
        raise CredentialError(R_SUBJECT_NOT_BOUND, "AI Hub 中不存在该用户")
    if resp.status_code != 200:
        raise CredentialError(
            R_PROVIDER_UNAVAILABLE, f"AI Hub 主体查询返回 {resp.status_code}"
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise CredentialError(R_PROVIDER_UNAVAILABLE, "AI Hub 返回内容无法解析") from exc
    if not isinstance(data, dict):
        raise CredentialError(R_PROVIDER_UNAVAILABLE, "AI Hub 返回内容非对象")

    union_id = str(data.get("dingtalk_union_id") or "").strip()
    if union_id:
        return "dingtalk_unionid", union_id
    dingtalk_user_id = str(data.get("dingtalk_user_id") or "").strip()
    if dingtalk_user_id:
        return "dingtalk_userid", dingtalk_user_id

    raise CredentialError(R_SUBJECT_NOT_BOUND, "该用户没有钉钉身份（未绑定全域账号）")


# ----------------------------------------------------------------------
# 换票
# ----------------------------------------------------------------------


async def _call_quanyu_exchange(
    subject_type: str, subject_value: str, app_id: str
) -> tuple[str, int]:
    base = (settings.quanyu_auth_url or "").strip().rstrip("/")
    payload = {
        "appId": settings.quanyu_app_id,
        "appSecret": settings.quanyu_app_secret,
        "targetAppId": app_id,
        "subjectType": subject_type,
        "subjectValue": subject_value,
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.quanyu_timeout_seconds, trust_env=False
        ) as client:
            resp = await client.post(f"{base}/aiIdentity/exchange", json=payload)
    except httpx.HTTPError as exc:
        raise CredentialError(
            R_PROVIDER_UNAVAILABLE, f"换票请求失败（{type(exc).__name__}）"
        ) from exc

    if resp.status_code != 200:
        raise CredentialError(R_PROVIDER_UNAVAILABLE, f"换票 HTTP {resp.status_code}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise CredentialError(R_PROVIDER_UNAVAILABLE, "换票返回内容无法解析") from exc
    if not isinstance(body, dict):
        raise CredentialError(R_PROVIDER_UNAVAILABLE, "换票返回内容非对象")

    if body.get("code") != 200:
        msg = str(body.get("msg") or "")
        # 未绑定全域账号是可区分的业务失败，其余一律按提供方不可用处理
        code = R_SUBJECT_NOT_BOUND if "未绑定" in msg else R_PROVIDER_UNAVAILABLE
        raise CredentialError(code, f"换票被拒绝（msg={msg or '空'}）")

    data = body.get("data") or {}
    token = str(data.get("token") or "").strip()
    try:
        expires_in = int(data.get("expiresIn") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    if not token or expires_in <= 0:
        raise CredentialError(R_PROVIDER_UNAVAILABLE, "换票未返回有效委托票")
    return token, expires_in


# ----------------------------------------------------------------------
# 缓存（Redis；不可用时降级为直换）
# ----------------------------------------------------------------------


def _cache_key(
    subject_type: str, subject_id: str, target: str, actor_kind: str
) -> str:
    return f"{_CACHE_PREFIX}{subject_type}:{subject_id}|{target}|{actor_kind}"


async def _cache_get(key: str) -> str | None:
    try:
        raw = await get_redis().get(key)
    except Exception as exc:  # noqa: BLE001 —— 缓存故障不阻断主链路
        logger.warning("[broker] Redis 读取失败（%s），跳过缓存", type(exc).__name__)
        return None
    return str(raw) if raw else None


async def _cache_put(key: str, token: str, ttl: int) -> None:
    if ttl <= 0:
        return
    try:
        await get_redis().set(key, token, ex=ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[broker] Redis 写入失败（%s）", type(exc).__name__)


async def invalidate(
    *, subject_type: str, subject_id: str, target: str, actor_kind: str = "human"
) -> bool:
    """票据被下游拒绝时作废缓存（下次调用重新换票）。返回是否真的删了键。"""
    key = _cache_key(subject_type, subject_id, target, actor_kind)
    try:
        return bool(await get_redis().delete(key))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[broker] Redis 删除失败（%s）", type(exc).__name__)
        return False


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------


async def exchange(
    session: AsyncSession | None,
    *,
    subject_type: str,
    subject_id: str,
    target: str,
    actor_kind: str = "human",
    log: bool = True,
) -> CredentialResult:
    """取该主体对目标平台的委托票（缓存优先，失败收敛成稳定码）。"""
    started = time.monotonic()
    result = await _exchange_inner(
        subject_type=subject_type,
        subject_id=subject_id,
        target=target,
        actor_kind=actor_kind,
    )
    if log and session is not None:
        await _audit(
            session,
            subject_type=subject_type,
            subject_id=subject_id,
            actor_kind=actor_kind,
            target=target,
            result=result,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    return result


async def _exchange_inner(
    *, subject_type: str, subject_id: str, target: str, actor_kind: str
) -> CredentialResult:
    provider = _provider_for(target)
    if provider is None:
        return CredentialResult(
            ok=False, reason_code=R_TARGET_UNKNOWN, provider=""
        )
    if not is_configured():
        logger.error("[broker] 未配置 quanyu_auth_url / app_id / app_secret")
        return CredentialResult(
            ok=False, reason_code=R_PROVIDER_UNAVAILABLE, provider=provider.name
        )

    app_id = target_app_for(target)
    margin = max(settings.quanyu_token_refresh_margin_seconds, 0)
    key = _cache_key(subject_type, subject_id, target, actor_kind)

    cached = await _cache_get(key)
    if cached:
        return _ok(cached, provider.name, cached=True)

    try:
        async with redis_lock(f"{_LOCK_PREFIX}{key}", ttl=_LOCK_TTL):
            cached = await _cache_get(key)
            if cached:
                return _ok(cached, provider.name, cached=True)
            return await _exchange_and_store(
                provider, subject_type, subject_id, app_id, key, margin
            )
    except LockBusyError:
        # 别人正在换：等一下再看缓存，别把认证中心打爆
        for _ in range(_LOCK_WAIT_POLLS):
            await asyncio.sleep(_LOCK_WAIT_INTERVAL)
            cached = await _cache_get(key)
            if cached:
                return _ok(cached, provider.name, cached=True)
        logger.info("[broker] 等锁超时，直换（subject=%s target=%s）", subject_type, target)
        return await _exchange_and_store(
            provider, subject_type, subject_id, app_id, key, margin
        )


def _ok(token: str, provider: str, *, cached: bool) -> CredentialResult:
    return CredentialResult(
        ok=True,
        reason_code=R_EXCHANGED,
        header=DELEGATION_HEADER,
        token=token,
        expires_in=None,  # 命中缓存时不给剩余时长，调用方按 403 触发 invalidate
        provider=provider,
        cached=cached,
    )


async def _exchange_and_store(
    provider: CredentialProvider,
    subject_type: str,
    subject_id: str,
    app_id: str,
    key: str,
    margin: int,
) -> CredentialResult:
    try:
        cred = await provider.exchange(subject_type, subject_id, app_id)
    except CredentialError as exc:
        # 只记稳定码与一句话，不回显上游报文/凭据
        logger.info("[broker] 换票失败（%s, %s）", exc.code, exc.message)
        return CredentialResult(ok=False, reason_code=exc.code, provider=provider.name)

    await _cache_put(key, cred.token, cred.expires_in - margin)
    return CredentialResult(
        ok=True,
        reason_code=R_EXCHANGED,
        header=cred.header,
        token=cred.token,
        expires_in=cred.expires_in,
        provider=provider.name,
        cached=False,
    )


async def _audit(
    session: AsyncSession,
    *,
    subject_type: str,
    subject_id: str,
    actor_kind: str,
    target: str,
    result: CredentialResult,
    latency_ms: int,
) -> None:
    """落审计：**不记票**。写失败不影响换票结果（审计可用性次优先）。"""
    try:
        session.add(
            CredentialExchangeLog(
                subject_type=subject_type[:20],
                subject_id=str(subject_id)[:64],
                actor_kind=actor_kind[:20],
                target=(target or "")[:64],
                provider=(result.provider or "quanyu")[:32],
                result="allow" if result.ok else "deny",
                reason_code=result.reason_code[:64],
                cached=result.cached,
                expires_in=result.expires_in,
                latency_ms=latency_ms,
            )
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[broker] 审计写入失败（%s）", type(exc).__name__)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
