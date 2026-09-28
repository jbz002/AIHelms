"""AI Hub 全量部门同步（取数方式参照 ai-assistant dept_sync）。

本地 departments 表历史上只靠 SSO 登录逐人补：一次登录只落创建者自己那
一个部门，整棵树从不完整。本服务以 AI Hub `GET /api/v1/common/departments`
（服务级 API Key，ak- 前缀）为权威源做全量 upsert：

- 只增改不删（本地手工建部门、历史部门均保留）
- 权威 id = AI Hub 的 `id`（写入 aihub_department_id）
- 层级按 dingtalk 父链映射回本地 parent_id（公司根 dt=1 不在返回里，
  其子节点 parent 保持 None 成为顶级，与 ai-assistant 同口径）

读取侧（get_department_tree / list_full_departments）带 TTL 节流的
ensure_synced：成功 10 分钟内不重拉，失败 1 分钟内不重试（aihub 不可达时
列表读取快速降级本地，不挂 15 秒超时）。
"""

import logging
import time
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.db import Department
from repositories import department_repo

logger = logging.getLogger(__name__)

DEPARTMENTS_PATH = "/api/v1/common/departments"
_TIMEOUT = 15.0

_SYNC_OK_TTL = 600.0  # 成功后 10 分钟内跳过重拉
_SYNC_FAIL_TTL = 60.0  # 失败后 1 分钟内不重试

_last_sync_ok_at = 0.0
_last_sync_fail_at = 0.0


class AIHubDepartmentError(Exception):
    """AI Hub 部门接口调用失败（文案不含凭据）。"""


def _as_str_id(value: Any) -> str | None:
    """AI Hub 各 id 字段统一转字符串（dingtalk id 返 int，比对必须同型）。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def fetch_aihub_departments() -> list[dict[str, Any]]:
    """调 AI Hub 拉全量部门（原始 JSON 列表）。失败抛 AIHubDepartmentError。"""
    base = (settings.ai_hub_url or "").strip().rstrip("/")
    key = (settings.ai_hub_app_key or "").strip()
    if not base or not key:
        raise AIHubDepartmentError(
            "AI_HUB_URL / AI_HUB_APP_KEY 未配置，无法获取 AI Hub 部门"
        )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{base}{DEPARTMENTS_PATH}",
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.HTTPError as exc:
        # 只带异常类型名，绝不带请求头 / URL 里的凭据
        raise AIHubDepartmentError(
            f"AI Hub 部门接口请求失败（{type(exc).__name__}）"
        ) from exc
    if resp.status_code != 200:
        raise AIHubDepartmentError(f"AI Hub 部门接口返回 {resp.status_code}")
    data = resp.json()
    if not isinstance(data, list):
        raise AIHubDepartmentError("AI Hub 部门接口返回非列表")
    return data


async def sync_departments(session: AsyncSession) -> dict[str, int]:
    """全量 upsert AI Hub 部门到本地 departments（幂等，不删）。返回统计。"""
    global _last_sync_ok_at, _last_sync_fail_at

    raw = await fetch_aihub_departments()
    usable: list[dict[str, Any]] = []
    for item in raw:
        aihub_id = _as_str_id(item.get("id"))
        if aihub_id:
            usable.append(item)
    if not usable:
        raise AIHubDepartmentError("AI Hub 返回 0 条可用部门，疑似接口异常——本次不同步")

    existing: dict[str, Department] = {
        d.aihub_department_id: d
        for d in await department_repo.find_all_active(session)
        if d.aihub_department_id
    }

    aihub_to_local: dict[str, Department] = {}
    inserted = updated = 0
    for item in usable:
        aihub_id = _as_str_id(item["id"]) or ""
        name = str(item.get("name") or "").strip() or aihub_id
        # 先取旧名再 upsert：session identity map 会让 upsert 前后拿到同一实例
        before = existing.get(aihub_id)
        before_name = before.name if before is not None else None
        dept = await department_repo.upsert_by_aihub_id(session, aihub_id, name)
        if dept is None:
            continue
        aihub_to_local[aihub_id] = dept
        if before is None:
            inserted += 1
        elif before_name != name:
            updated += 1

    linked = _link_parents(usable, aihub_to_local)

    await session.commit()
    _last_sync_ok_at = time.monotonic()
    logger.info(
        "aihub dept sync: fetched=%s inserted=%s updated=%s linked=%s",
        len(raw),
        inserted,
        updated,
        linked,
    )
    return {
        "fetched": len(raw),
        "inserted": inserted,
        "updated": updated,
        "linked": linked,
    }


def _link_parents(
    usable: list[dict[str, Any]], aihub_to_local: dict[str, Department]
) -> int:
    """按 dingtalk 父链回填本地 parent_id。父不在返回集合内（公司根）保持顶级。"""
    dt_to_aihub: dict[str, str] = {}
    for item in usable:
        dt = _as_str_id(item.get("dingtalk_dept_id"))
        aihub_id = _as_str_id(item.get("id"))
        if dt and aihub_id:
            dt_to_aihub[dt] = aihub_id

    linked = 0
    for item in usable:
        aihub_id = _as_str_id(item.get("id"))
        child = aihub_to_local.get(aihub_id or "")
        parent_dt = _as_str_id(item.get("parent_dingtalk_dept_id"))
        parent_aihub = dt_to_aihub.get(parent_dt) if parent_dt else None
        parent = aihub_to_local.get(parent_aihub or "")
        if child is None or parent is None or parent.id == child.id:
            continue
        if child.parent_id != parent.id:
            child.parent_id = parent.id
            linked += 1
    return linked


async def ensure_synced(session: AsyncSession) -> None:
    """读取前尽力同步（TTL 节流）。失败仅告警，调用方降级读本地。"""
    global _last_sync_fail_at

    now = time.monotonic()
    if now - _last_sync_ok_at < _SYNC_OK_TTL:
        return
    if now - _last_sync_fail_at < _SYNC_FAIL_TTL:
        return
    try:
        await sync_departments(session)
    except AIHubDepartmentError:
        _last_sync_fail_at = time.monotonic()
        logger.warning("aihub dept sync failed, fallback to local list", exc_info=True)


async def list_full_departments(session: AsyncSession) -> list[dict]:
    """全量部门扁平列表（选择器用）：先尽力同步，再读本地 active 全量。"""
    await ensure_synced(session)
    departments = await department_repo.find_all_active(session)
    return [
        {
            "id": d.id,
            "name": d.name,
            "parent_id": d.parent_id,
            "sort_order": d.sort_order,
        }
        for d in departments
    ]
