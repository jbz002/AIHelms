"""管理员操作 MCP server：FastMCP 实例与 ASGI app 工厂。"""

from fastmcp import FastMCP

from mcp_admin.auth import AdminKeyVerifier

# 先建实例，工具模块注册时从本模块导入此 mcp
mcp = FastMCP("aihelms_admin_mcp", auth=AdminKeyVerifier())

# 导入工具模块触发 @mcp.tool 注册
from mcp_admin import tools  # noqa: E402,F401

_mcp_app = None


def create_admin_mcp_app():
    """返回可挂载到 FastAPI 的 Starlette ASGI app（单例，无状态 streamable HTTP）。

    单例：父 FastAPI app 的 lifespan 与 mount 必须共用同一个 app 实例，
    否则 StreamableHTTPSessionManager 的 task group 不会被初始化。
    """
    global _mcp_app
    if _mcp_app is None:
        _mcp_app = mcp.http_app(path="/mcp", transport="http", stateless_http=True)
    return _mcp_app
