"""用户自助 MCP 工具包：导入子模块触发 @mcp.tool 注册。"""

from mcp_web.tools import (  # noqa: F401
    applications,
    identity,
    market,
)
