"""090 迁移人工预检（只读 dry-run）：单名称收敛三清单。

部署 090 前人工过目用，回答三个问题：
  A. 哪些 skill 会被改名（现名 → 终名）？
  B. 哪些 skill frontmatter 缺失/非法、现名也不合法，将落 'skill-<id>' 兜底？
  C. 哪些目标名有冲突组，谁保留、谁被加 '-<id>' 后缀？

规则与 docker/db/migrations/090_skill_name_unify_unique.sql 完全等价（确定性）；
要改判定就同时改两处。
用法（任意位置）：

    # 默认读 apps 配置的 DSN；也可用环境变量覆盖
    DATABASE_URL="postgresql://user:pass@localhost:5432/aihelms" \
        python dev/migrate_090_preflight.py

只读，不写任何数据。退出码恒 0（报告工具，不是门禁）。
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

import asyncpg

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

KEBAB_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def _dsn() -> str:
    env = os.environ.get("DATABASE_URL")
    if env:
        return env.replace("postgresql+asyncpg://", "postgresql://", 1)
    from core.config import settings  # noqa: PLC0415

    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _legal(name: str | None) -> bool:
    return (
        bool(name)
        and bool(KEBAB_RE.match(name))
        and "--" not in name
        and len(name) <= 64
    )


async def main() -> None:
    conn = await asyncpg.connect(_dsn())
    try:
        rows = await conn.fetch(
            "SELECT id, name, frontmatter->>'name' AS fm_name, is_published "
            "FROM aihelms.skills ORDER BY id"
        )
    finally:
        await conn.close()

    # 与 090 SQL 同规则的终名计算
    finals: dict[int, tuple[str, str, str]] = {}  # id -> (tgt, reason, final)
    for r in rows:
        fm, cur = r["fm_name"], r["name"]
        if _legal(fm):
            tgt, reason = fm, "frontmatter"
        elif _legal(cur):
            tgt, reason = cur, "现名保留(frontmatter 缺失/非法)"
        else:
            tgt, reason = f"skill-{r['id']}", "兜底 skill-<id>"
        finals[r["id"]] = (tgt, reason, tgt)

    # 冲突组消解：同 tgt 多行 → is_published 优先、id 小者胜，败者加后缀
    by_tgt: dict[str, list] = {}
    for r in rows:
        by_tgt.setdefault(finals[r["id"]][0], []).append(r)
    for tgt, group in by_tgt.items():
        if len(group) == 1:
            continue
        ordered = sorted(group, key=lambda r: (not r["is_published"], r["id"]))
        for loser in ordered[1:]:
            _, reason, _ = finals[loser["id"]]
            finals[loser["id"]] = (tgt, reason, f"{tgt}-{loser['id']}")

    renamed = [
        (r["id"], r["name"], f, reason)
        for r in rows
        for _, reason, f in [finals[r["id"]]]
        if f != r["name"]
    ]
    fallback = [
        (r["id"], r["name"], r["fm_name"])
        for r in rows
        if finals[r["id"]][1].startswith("兜底")
    ]
    conflicts = [
        (
            tgt,
            [
                (r["id"], r["name"], r["is_published"], finals[r["id"]][2])
                for r in group
            ],
        )
        for tgt, group in sorted(by_tgt.items())
        if len(group) > 1
    ]

    print(
        f"== 090 单名称收敛预检（共 {len(rows)} 个 skill，{len(renamed)} 个将改名）==\n"
    )
    print("-- A. 待改名（id, 现名 → 终名, 依据）--")
    for sid, cur, fin, reason in renamed:
        print(f"  #{sid}  {cur!r} -> {fin!r}   [{reason}]")
    if not renamed:
        print("  （无）")

    print(
        "\n-- B. 兜底 skill-<id>（frontmatter 与现名均非法/缺失，建议部署前人工补 frontmatter）--"
    )
    for sid, cur, fm in fallback:
        print(f"  #{sid}  现名={cur!r}  frontmatter name={fm!r}")
    if not fallback:
        print("  （无）")

    print("\n-- C. 目标名冲突组（保留者在前，败者加 '-<id>' 后缀）--")
    for tgt, group in conflicts:
        print(f"  目标 {tgt!r}:")
        for sid, cur, pub, fin in group:
            flag = "已发布" if pub else "未发布"
            suffix = "" if fin == tgt else "   ← 加后缀"
            print(f"    #{sid}  现名={cur!r} ({flag}){suffix}")
    if not conflicts:
        print("  （无）")

    print("\n确认无误后正常发版即可，090 会在启动时自动执行等价收敛。")


if __name__ == "__main__":
    asyncio.run(main())
