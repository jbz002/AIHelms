"""MCP 授权对账：AIHelms 期望值 vs LiteLLM 现状。

- `--check`（默认）：只报不写；有漂移 exit 1（沿用本项目 `--check` 惯例，可进定时任务）。
- `--apply`：以 AIHelms 为准覆盖回网关。

核心逻辑在 `services.mcp_authz_service.reconcile_all`（同一份代码也供
`POST /api/v1/mcp/reconcile` 使用）。公共 server 在 LiteLLM 侧本就对所有 key
可见（并集），比对时两侧剔除，避免噪音。

运行：docker exec -w /app/apps aihelms-app python -m scripts.reconcile_mcp_permissions [--apply]
"""

import asyncio
import json
import sys

from core.database import async_session
from services import mcp_authz_service


async def main() -> None:
    apply = "--apply" in sys.argv
    if not apply and "--check" not in sys.argv:
        print("（默认 --check：只报不写；加 --apply 才覆盖网关）")

    async with async_session() as session:
        result = await mcp_authz_service.reconcile_all(session, apply=apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["drift"] and not apply:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
