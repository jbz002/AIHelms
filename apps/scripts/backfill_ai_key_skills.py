"""一次性回填：清理主 Key skills JSONB 中的孤儿 skill id。

背景：set_hidden / 可见性变更历史未同步 ai_keys，治理下架后主 Key 仍残留 skill id，
用户端"我的AI身份"因 /skills/published 查不到而展示成 #id。

清理范围（保守，避免误删审批个人授予）：
- skill 已被删除（find_by_ids 查不到）
- skill.hidden == True（治理下架）

保留：requires_approval / 未发布 / unlisted / private 的 skill id —— 这些可能来自
资源申请审批的个人授予（resource_application_service），不在此处清理。

幂等，可重复执行。运行：cd apps && uv run python -m scripts.backfill_ai_key_skills
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from core.database import async_session
from models.db import AiKey
from repositories import skill_repo


async def main() -> None:
    async with async_session() as session:
        result = await session.execute(
            select(AiKey).where(
                AiKey.key_type.in_(["personal_main", "dept_main", "project_main"]),
                AiKey.is_active == True,  # noqa: E712
            )
        )
        keys = list(result.scalars().all())

        all_ids: set[int] = set()
        for k in keys:
            for sid in k.skills or []:
                try:
                    all_ids.add(int(sid))
                except (TypeError, ValueError):
                    continue
        skills = {s.id: s for s in await skill_repo.find_by_ids(session, list(all_ids))}

        total_removed = 0
        touched_keys = 0
        for k in keys:
            if not k.skills:
                continue
            kept: list = []
            removed: list = []
            for sid in k.skills:
                try:
                    sid_int = int(sid)
                except (TypeError, ValueError):
                    kept.append(sid)
                    continue
                skill = skills.get(sid_int)
                # 删除或治理下架 → 清理；其余保留（含审批个人授予）
                if skill is None or skill.hidden:
                    removed.append(sid)
                else:
                    kept.append(sid)
            if removed:
                k.skills = kept
                flag_modified(k, "skills")
                total_removed += len(removed)
                touched_keys += 1
                print(f"key {k.id}: removed orphan skill ids {removed}")

        await session.commit()
        print(
            f"done. removed {total_removed} orphan skill refs "
            f"across {touched_keys} of {len(keys)} main keys."
        )


if __name__ == "__main__":
    asyncio.run(main())
