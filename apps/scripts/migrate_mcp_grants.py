"""P1 等价迁移：把现网 ai_keys.mcps 反推成 mcp_grants（行为不变）。

口径：
- 公共且进网关的 server → `public` + `server` 级 allow（人人可用）。
- 每个主 Key 的 mcps 里、**非公共**的 server → 按 Key 归属反推主体授权：
  owner_type=user → user 级；owner_type=department → dept 级；project 暂不支持（跳过并上报）。
- 场景 Key 不反推：它们不参与编译，mcps 继续手工维护。

幂等：同一主体 + 目标的生效授权已存在则跳过。默认 dry-run，`--apply` 才写库。

运行：docker exec -w /app/apps aihelms-app python -m scripts.migrate_mcp_grants [--apply]
"""

import asyncio
import sys

from sqlalchemy import select

from core.database import async_session
from models.db import AiKey, McpGrant, McpServer
from repositories import mcp_authz_repo

MAIN_KEY_TYPES = ("personal_main", "dept_main", "project_main")


async def main() -> None:
    apply = "--apply" in sys.argv
    if not apply:
        print("（默认 dry-run；加 --apply 才写库）")

    async with async_session() as session:
        servers = list((await session.execute(select(McpServer))).scalars().all())
        gateway = {
            s.id: s
            for s in servers
            if s.is_published and not s.requires_approval and s.sync_to_litellm
        }
        public_ids = {sid for sid, s in gateway.items() if s.is_public}
        print(
            f"gateway servers: {[(sid, s.server_name) for sid, s in gateway.items()]}"
        )
        print(f"public servers: {[gateway[i].server_name for i in sorted(public_ids)]}")

        planned: list[tuple[str, int | None, int, str]] = []
        for sid in sorted(public_ids):
            planned.append(("public", None, sid, "公共 server 全员可用"))

        keys = list(
            (await session.execute(select(AiKey).order_by(AiKey.id))).scalars().all()
        )
        skipped_owner = []
        for key in keys:
            if key.key_type not in MAIN_KEY_TYPES:
                continue
            for sid in key.mcps or []:
                if sid in public_ids or sid not in gateway:
                    continue
                if key.owner_type == "user":
                    planned.append(("user", key.owner_id, sid, f"来自 Key {key.id}"))
                elif key.owner_type == "department":
                    planned.append(("dept", key.owner_id, sid, f"来自 Key {key.id}"))
                else:
                    skipped_owner.append((key.id, key.key_type, key.owner_type, sid))

        created = existed = 0
        for subject_type, subject_id, target_id, reason in planned:
            existing = await mcp_authz_repo.find_active_grant(
                session, subject_type, subject_id, "server", target_id
            )
            if existing:
                existed += 1
                continue
            name = (
                gateway[target_id].server_name
                if target_id in gateway
                else str(target_id)
            )
            print(f"ADD grant {subject_type}:{subject_id} -> server {name}")
            created += 1
            if apply:
                await mcp_authz_repo.create_grant(
                    session,
                    McpGrant(
                        subject_type=subject_type,
                        subject_id=subject_id,
                        target_type="server",
                        target_id=target_id,
                        effect="allow",
                        reason=reason,
                    ),
                )
        if apply:
            await session.commit()
        else:
            await session.rollback()

        print(
            f"planned={len(planned)} created={created} existed={existed} "
            f"skipped_owner={len(skipped_owner)} apply={apply}"
        )
        for item in skipped_owner[:10]:
            print("  skip (owner_type 暂不支持):", item)


if __name__ == "__main__":
    asyncio.run(main())
