"""P2 PDP：MCP 工具调用的差量策略决策。

**为什么需要它**：网关（LiteLLM `object_permission`）已经强制了「用户 × server × tool」的
静态授权，但那套权限表达不了三类东西：

1. **机器代人类**——服务账号代表某员工调用，必须有一条未过期的委托，
   且该 server 显式允许机器委托；
2. **写/敏感工具需要显式授权**——公共 server 在 P1 已被禁止包含非只读工具，
   所以这里的「显式」就是授权矩阵里的 server 级或工具束授权；
3. **下线 / 未过审的工具**——网关侧没有审核状态，只能在这里兜。

**只对差量策略调用**：只读工具 + 人类 actor 时，网关权限已是完整判定，mcp_proxy 不调本接口。
**fail-closed**：本服务不可用时，mcp_proxy 对差量策略对象一律拒绝；只读工具不受影响。

决策结果会落 `authz_decision_logs`（allow 与 deny 都记），不记工具入参与业务返回体。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import AuthzDecisionLog
from repositories import mcp_authz_repo, mcp_repo, service_account_repo
from services import mcp_authz_service, service_account_service

logger = logging.getLogger(__name__)

# ─── 原因码（稳定码，文案由调用方本地化）────────────────────────────────────

R_GRANTED = "granted"
R_PUBLIC_SERVER = "public_server"
R_NO_GRANT = "no_grant"
R_SERVER_OFFLINE = "server_offline"
R_TOOL_NOT_FOUND = "tool_not_found"
R_TOOL_NOT_APPROVED = "tool_not_approved"
R_MACHINE_SELF = "machine_self_no_grant"
R_MACHINE_NOT_ALLOWED = "machine_delegation_disabled"
R_DELEGATION_MISSING = "delegation_missing"
R_DELEGATION_EXPIRED = "delegation_expired"
R_DELEGATION_REVOKED = "delegation_revoked"

ACTOR_HUMAN = "human"
ACTOR_SERVICE = "service"

CACHE_TTL_SECONDS = 30


@dataclass
class Decision:
    decision: str
    reason_code: str
    policy_version: int | None = None
    obligations: dict = field(default_factory=dict)
    decision_id: str = ""
    cached: bool = False
    latency_ms: int = 0
    server_id: int | None = None
    tool_key: str | None = None

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "reason_code": self.reason_code,
            "policy_version": self.policy_version,
            "obligations": self.obligations,
            "decision_id": self.decision_id,
            "cached": self.cached,
            "latency_ms": self.latency_ms,
        }


# 进程内 LRU（这里用带过期的 dict 即可：key 里带 policy_version，撤销即自然失效）
_CACHE: dict[tuple, tuple[float, Decision]] = {}


def _cache_get(key: tuple) -> Decision | None:
    hit = _CACHE.get(key)
    if hit is None:
        return None
    expires_at, decision = hit
    if expires_at < time.monotonic():
        _CACHE.pop(key, None)
        return None
    return decision


def _cache_put(key: tuple, decision: Decision) -> None:
    if len(_CACHE) > 5000:  # 兜底清理，避免长跑进程无限增长
        now = time.monotonic()
        for k in [k for k, (exp, _) in _CACHE.items() if exp < now]:
            _CACHE.pop(k, None)
    _CACHE[key] = (time.monotonic() + CACHE_TTL_SECONDS, decision)


def clear_cache() -> None:
    _CACHE.clear()


# ─── 判定 ────────────────────────────────────────────────────────────────────


async def _user_authorization(
    session: AsyncSession, user_id: int
) -> tuple[set[int], dict[int, set[str]]]:
    """该用户此刻「按授权矩阵」能用的 server 与工具级限制（与编译产物同源）。"""
    context = await mcp_authz_service.load_context(session)
    subjects = await mcp_authz_service.subjects_for_user(session, user_id)
    grants = await mcp_authz_repo.find_grants_for_subjects(
        session, sorted(subjects, key=lambda s: (s[0], s[1] or 0))
    )
    views = [
        mcp_authz_service.GrantView(
            subject_type=g.subject_type,
            subject_id=g.subject_id,
            target_type=g.target_type,
            target_id=g.target_id,
            effect=g.effect,
        )
        for g in grants
    ]
    compiled = mcp_authz_service.compile_grants(
        views,
        subjects,
        server_names=context.server_names,
        published_ids=context.published_ids,
        public_ids=context.public_ids,
        approved_tools=context.approved_tools,
        toolset_items=context.toolset_items,
        toolset_names=context.toolset_names,
    )
    tools: dict[int, set[str]] = {}
    for name, names in (compiled.tool_permissions or {}).items():
        for server_id, server_name in context.server_names.items():
            if server_name == name:
                tools[server_id] = set(names)
    return set(compiled.server_ids), tools


async def _decide(
    session: AsyncSession,
    *,
    subject_type: str,
    subject_id: int | None,
    actor_kind: str,
    actor_service_account_id: int | None,
    server_name: str,
    tool_name: str | None,
    policy_version: int | None,
) -> Decision:
    def deny(reason: str, **kw) -> Decision:
        return Decision(
            decision="deny",
            reason_code=reason,
            policy_version=policy_version,
            decision_id=str(uuid.uuid4()),
            **kw,
        )

    server = await mcp_repo.find_server_by_name(session, server_name)
    if (
        server is None
        or not server.is_published
        or server.requires_approval
        or not server.sync_to_litellm
    ):
        return deny(R_SERVER_OFFLINE)

    tool = None
    if tool_name:
        for candidate in await mcp_repo.find_tools_by_server(session, server.id):
            if candidate.tool_name == tool_name:
                tool = candidate
                break
        if tool is None or not tool.is_active:
            return deny(R_TOOL_NOT_FOUND, server_id=server.id)
        if (tool.review_status or "approved") != "approved":
            return deny(R_TOOL_NOT_APPROVED, server_id=server.id, tool_key=tool.tool_key)

    tool_key = tool.tool_key if tool is not None else None

    # 没有数据主体：机器自身（P2 v1 没有服务账号自有授权的模型，一律拒）或匿名人类
    if subject_id is None:
        reason = R_MACHINE_SELF if actor_kind == ACTOR_SERVICE else R_NO_GRANT
        return deny(reason, server_id=server.id, tool_key=tool_key)

    if subject_type != "user":
        return deny(R_NO_GRANT, server_id=server.id, tool_key=tool_key)

    authorized_servers, tool_limits = await _user_authorization(session, subject_id)
    if server.id not in authorized_servers:
        return deny(R_NO_GRANT, server_id=server.id, tool_key=tool_key)
    limited = tool_limits.get(server.id)
    if limited is not None and tool_name is not None and tool_name not in limited:
        return deny(R_NO_GRANT, server_id=server.id, tool_key=tool_key)

    if actor_kind == ACTOR_SERVICE:
        if not server.allow_machine_delegation:
            return deny(R_MACHINE_NOT_ALLOWED, server_id=server.id, tool_key=tool_key)
        if actor_service_account_id is None:
            return deny(R_MACHINE_SELF, server_id=server.id, tool_key=tool_key)
        if not await service_account_service.delegation_allows(
            session, actor_service_account_id, subject_id, server.id, tool_name
        ):
            stale = await service_account_repo.find_any_delegation(
                session,
                actor_service_account_id,
                subject_id,
                server_id=server.id,
                tool_name=tool_name,
            )
            if stale is None:
                reason = R_DELEGATION_MISSING
            elif stale.revoked_at is not None:
                reason = R_DELEGATION_REVOKED
            else:
                reason = R_DELEGATION_EXPIRED
            return deny(reason, server_id=server.id, tool_key=tool_key)

    reason = R_PUBLIC_SERVER if server.is_public else R_GRANTED
    return Decision(
        decision="allow",
        reason_code=reason,
        policy_version=policy_version,
        obligations={"requires_approval": False},
        decision_id=str(uuid.uuid4()),
        server_id=server.id,
        tool_key=tool_key,
    )


async def authorize(
    session: AsyncSession,
    *,
    subject_type: str,
    subject_id: int | None,
    actor_kind: str,
    actor_service_account_id: int | None = None,
    server_name: str,
    tool_name: str | None = None,
    trace_id: str | None = None,
    log: bool = True,
) -> Decision:
    """决定一次调用是否放行，并落决策日志。"""
    started = time.perf_counter()
    policy_version = await mcp_authz_repo.current_policy_version(session)
    cache_key = (
        subject_type,
        subject_id,
        actor_kind,
        actor_service_account_id,
        server_name,
        tool_name,
        policy_version,
    )
    decision = _cache_get(cache_key)
    if decision is not None:
        decision = Decision(**{**decision.__dict__, "cached": True})
    else:
        decision = await _decide(
            session,
            subject_type=subject_type,
            subject_id=subject_id,
            actor_kind=actor_kind,
            actor_service_account_id=actor_service_account_id,
            server_name=server_name,
            tool_name=tool_name,
            policy_version=policy_version,
        )
        _cache_put(cache_key, decision)
    decision.latency_ms = int((time.perf_counter() - started) * 1000)

    if log:
        await log_decision(
            session,
            subject_type=subject_type,
            subject_id=subject_id,
            actor_kind=actor_kind,
            actor_service_account_id=actor_service_account_id,
            server_name=server_name,
            tool_name=tool_name,
            tool_key=decision.tool_key,
            decision=decision,
            trace_id=trace_id,
        )
        await session.commit()
    return decision


async def log_decision(
    session: AsyncSession,
    *,
    subject_type: str,
    subject_id: int | None,
    actor_kind: str,
    actor_service_account_id: int | None,
    server_name: str,
    tool_name: str | None,
    tool_key: str | None,
    decision: Decision,
    trace_id: str | None,
) -> None:
    session.add(
        AuthzDecisionLog(
            subject_type=subject_type,
            subject_id=subject_id,
            actor_kind=actor_kind,
            actor_service_account_id=actor_service_account_id,
            server_name=server_name,
            tool_name=tool_name,
            tool_key=tool_key,
            decision=decision.decision,
            reason_code=decision.reason_code,
            policy_version=decision.policy_version,
            trace_id=trace_id,
            latency_ms=decision.latency_ms,
        )
    )
