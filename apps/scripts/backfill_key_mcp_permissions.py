"""P0 一次性回填：把 ai_keys.mcps 编译成 LiteLLM key 的 object_permission。

背景：AIHelms 一直把授权写在 `allowed_mcp_servers` 字段上，而 LiteLLM 只认
`object_permission.mcp_servers`（旧字段被网关完全忽略，PoC-0 K4 实测）——于是
「任意有效 key 可调任意已注册 server」。本脚本补齐两件事：

  步骤 0（--sync-public，默认开）：把「已发布 + 无需审批 + 可见性 all + 进网关」
      的 server 广播到全部主 Key 的 mcps。现网这一步会把 supply_cloud /
      product_order 补到 39 把存量 key 上（11-23 之后「创建即发布」不广播的
      历史遗留）。只增不减，对齐现网既成事实。
  步骤 1：按 key.mcps 计算 object_permission（显式授权 ∪ 公共 server），
      与 LiteLLM 现状比对后下发。
  步骤 2（--switch，单独一步、不在默认流程里）：把 mcp_servers.is_public 落到
      网关的 allow_all_keys —— 这才是真正「开始按人拦截」的那一下。必须在
      步骤 1 之后、并已逐人留档 tools/list 才执行。回滚 = 把 is_public 置回
      TRUE 重跑本步（或直接调 LiteLLM update 把 allow_all_keys 打开）。

顺序（不可颠倒，见 docs/MCP鉴权增强方案/04）：
    --apply 本脚本 → 逐人留档 tools/list → 再切 allow_all_keys
本脚本执行时 allow_all_keys 仍为 TRUE，线上行为不变。

孤儿 key（LiteLLM 返回 404 Key not found）跳过并列出：重建 key 会换掉明文，
不能在这里静默做，走 scripts/rebuild_litellm_key.py 人工确认。

运行（容器内）：
    cd /app && python -m scripts.backfill_key_mcp_permissions            # 只打印差异（默认）
    cd /app && python -m scripts.backfill_key_mcp_permissions --apply    # 真写
    cd /app && python -m scripts.backfill_key_mcp_permissions --apply --no-sync-public
"""

import asyncio
import sys

from sqlalchemy import select

from core.database import async_session
from models.db import AiKey, McpServer
from repositories import mcp_repo
from services import ai_key_service, litellm_client, mcp_service


def _names_of(mcps: list[int], servers_by_id: dict[int, McpServer]) -> list[str]:
    """mcps(ids) → 网关 server_name（目录登记型不进网关，跳过）。"""
    names: list[str] = []
    for mcp_id in mcps or []:
        server = servers_by_id.get(mcp_id)
        if server and server.sync_to_litellm and server.server_name not in names:
            names.append(server.server_name)
    return names


def _current_permission(info: dict | None) -> list[str] | None:
    """从 /key/info 响应里取现有 object_permission.mcp_servers（取不到 = None）。"""
    if not isinstance(info, dict):
        return None

    def find(node):
        if isinstance(node, dict):
            if "mcp_servers" in node and isinstance(node["mcp_servers"], list):
                return node["mcp_servers"]
            for value in node.values():
                found = find(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = find(value)
                if found is not None:
                    return found
        return None

    return find(info)


def _fmt(label: str, key: AiKey, added: list[str], removed: list[str]) -> str:
    return (
        f"key {key.id} [{key.key_type}] alias={key.litellm_key_alias or '-'} "
        f"owner={key.owner_type}:{key.owner_id} {label} "
        f"+{added or '[]'} -{removed or '[]'}"
    )


async def main() -> None:
    apply = "--apply" in sys.argv
    sync_public = "--no-sync-public" not in sys.argv
    if not apply and "--dry-run" not in sys.argv:
        print("（默认 dry-run；加 --apply 才会写 LiteLLM / 改库）")

    async with async_session() as session:
        servers = list(
            (
                await session.execute(
                    select(McpServer)
                    .where(
                        McpServer.is_published == True,  # noqa: E712
                        McpServer.requires_approval == False,  # noqa: E712
                        McpServer.visibility_type == "all",
                        McpServer.sync_to_litellm == True,  # noqa: E712
                    )
                    .order_by(McpServer.id)
                )
            )
            .scalars()
            .all()
        )
        all_servers = list((await session.execute(select(McpServer))).scalars().all())
        servers_by_id = {s.id: s for s in all_servers}
        public_names = await mcp_repo.find_public_server_names(session)
        print(
            f"gateway servers (published/all/no-approval): "
            f"{[(s.id, s.server_name) for s in servers]}"
        )
        print(f"public servers (is_public): {public_names}")
        print(f"mode: {'APPLY' if apply else 'DRY-RUN'}, sync_public={sync_public}")

        keys = list(
            (
                await session.execute(
                    select(AiKey)
                    .where(AiKey.litellm_key_id.isnot(None))
                    .order_by(AiKey.id)
                )
            )
            .scalars()
            .all()
        )
        print(f"keys with litellm_key_id: {len(keys)}")

        # ── 步骤 0：补齐授权（只增不减）────────────────────────────────────
        if sync_public:
            for server in servers:
                if apply:
                    updated = await ai_key_service.sync_public_resource_to_all_keys(
                        session, "mcps", server.id
                    )
                    print(f"step0 {server.server_name}: broadcast to {updated} keys")
                else:
                    would = sum(
                        1
                        for k in keys
                        if k.key_type.endswith("_main")
                        and k.is_active
                        and server.id not in (k.mcps or [])
                    )
                    print(
                        f"step0 {server.server_name}: would broadcast to {would} main keys"
                    )
        if apply:
            await session.commit()

        # ── 步骤 1：计算并下发 object_permission──────────────────────────
        ok = skipped = failed = unchanged = 0
        for key in keys:
            mcps = list(key.mcps or [])
            if not apply and sync_public:
                main_types = ("personal_main", "dept_main", "project_main")
                if key.key_type in main_types and key.is_active:
                    for server in servers:
                        if server.id not in mcps:
                            mcps.append(server.id)
            target = _names_of(mcps, servers_by_id)
            target = list(dict.fromkeys([*target, *public_names]))
            try:
                info = await litellm_client.get_key_info(key.litellm_key_id)
            except litellm_client.LiteLLMError as exc:
                skipped += 1
                print(
                    f"key {key.id} alias={key.litellm_key_alias or '-'}: SKIP ({exc})"
                )
                continue
            have = _current_permission(info)
            added = [n for n in target if n not in (have or [])]
            removed = [n for n in (have or []) if n not in target]
            # 公共 server 由 allow_all_keys 兜底，集合差异里剔除后判断是否真的要写
            effective_added = [n for n in added if n not in public_names]
            effective_removed = [n for n in removed if n not in public_names]
            if have is not None and not effective_added and not effective_removed:
                unchanged += 1
                continue
            print(_fmt("UPDATE" if apply else "WOULD UPDATE", key, added, removed))
            if not apply:
                continue
            try:
                await litellm_client.update_key(
                    key_id=key.litellm_key_id,
                    object_permission={"mcp_servers": target},
                )
                ok += 1
            except litellm_client.LiteLLMError as exc:
                failed += 1
                print(f"key {key.id}: FAILED {exc}")

        print(
            f"done: applied={ok} unchanged={unchanged} skipped={skipped} "
            f"failed={failed} total={len(keys)}"
        )

        # ── 步骤 2（--switch）：is_public → 网关 allow_all_keys ──────────
        if "--switch" in sys.argv:
            for server in all_servers:
                if not server.sync_to_litellm:
                    continue
                if not apply:
                    print(
                        f"step2 {server.server_name}: would set "
                        f"allow_all_keys={bool(server.is_public)}"
                    )
                    continue
                try:
                    await mcp_service._push_server_config_to_litellm(server, server)
                    await session.commit()
                    print(
                        f"step2 {server.server_name}: allow_all_keys="
                        f"{bool(server.is_public)}"
                    )
                except litellm_client.LiteLLMError as exc:
                    print(f"step2 {server.server_name}: FAILED {exc}")
        elif not apply:
            await session.rollback()
        else:
            print("（未加 --switch：本次只下发 key 权限，未改网关公共开关）")


if __name__ == "__main__":
    asyncio.run(main())
