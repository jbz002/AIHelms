"""把「逐人授权」收敛成角色授权（一次性演进脚本，默认 dry-run）。

背景：P1 等价迁移把现网 `ai_keys.mcps` 反推成了逐人 grant（45 人 × 2 个业务 server）。
逐人授权的问题是**新员工不会自动获得**（新建 Key 按 grants 编译，只有公共 docs）。
把成员都在同一个角色里的逐人授权上提成角色授权后：存量用户无变化（并集），
新员工随角色自动获得。

规则（保守）：
- 只处理「主体是 user、目标已存在、且用户属于指定角色」的 grant；
- 先按角色补 grant（幂等），再撤销被覆盖的逐人 grant；
- 不属于该角色的用户（如管理员）保留其逐人 grant；
- 支持 `--target-type server|toolset` 限定，默认 server。

运行：
    docker exec -w /app/apps aihelms-app python -m scripts.consolidate_mcp_grants_to_role
    docker exec -w /app/apps aihelms-app python -m scripts.consolidate_mcp_grants_to_role --apply
"""

import asyncio
import sys

from sqlalchemy import select

from core.database import async_session
from models.db import McpGrant, Role, UserRole
from repositories import mcp_authz_repo
from services import mcp_authz_service


async def main() -> None:
    apply = "--apply" in sys.argv
    role_name = "user"
    if "--role" in sys.argv:
        role_name = sys.argv[sys.argv.index("--role") + 1]
    target_type = "server"
    if "--target-type" in sys.argv:
        target_type = sys.argv[sys.argv.index("--target-type") + 1]

    if not apply:
        print("（默认 dry-run；加 --apply 才写库并重编译）")

    async with async_session() as session:
        role = (
            await session.execute(select(Role).where(Role.name == role_name))
        ).scalar_one_or_none()
        if role is None:
            print(f"role not found: {role_name}")
            return
        members = {
            uid
            for (uid,) in (
                await session.execute(
                    select(UserRole.user_id).where(UserRole.role_id == role.id)
                )
            ).all()
        }
        print(f"role {role.name}#{role.id} members={len(members)}")

        grants = await mcp_authz_repo.list_grants(
            session, subject_type="user", target_type=target_type
        )
        convertible = [g for g in grants if g.subject_id in members]
        skipped = [g for g in grants if g.subject_id not in members]
        targets = sorted({g.target_id for g in convertible})
        print(
            f"user grants({target_type})={len(grants)} convertible={len(convertible)} "
            f"skipped(非成员)={len(skipped)} targets={targets}"
        )
        for g in skipped:
            print(
                f"  keep user:{g.subject_id} -> {g.target_type}:{g.target_id}（不在角色内）"
            )

        created = existed = 0
        for target_id in targets:
            existing = await mcp_authz_repo.find_active_grant(
                session, "role", role.id, target_type, target_id
            )
            if existing:
                existed += 1
                continue
            print(f"ADD role:{role.id} -> {target_type}:{target_id}")
            created += 1
            if apply:
                await mcp_authz_repo.create_grant(
                    session,
                    McpGrant(
                        subject_type="role",
                        subject_id=role.id,
                        target_type=target_type,
                        target_id=target_id,
                        effect="allow",
                        reason=f"由逐人授权收敛（{role.name} 角色）",
                    ),
                )
        revoked = 0
        for g in convertible:
            revoked += 1
            if apply:
                await mcp_authz_repo.revoke_grant(session, g)
        if apply:
            await session.commit()
            result = await mcp_authz_service.sync_keys_for_subject(
                session,
                "role",
                role.id,
                push=True,
                summary=f"逐人授权收敛为角色授权（{role.name}）",
            )
            await session.commit()
            print("recompile:", result)
        else:
            await session.rollback()

        print(
            f"role_grants_created={created} existed={existed} user_grants_revoked={revoked} "
            f"apply={apply}"
        )


if __name__ == "__main__":
    asyncio.run(main())
