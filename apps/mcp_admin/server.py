"""管理员操作 MCP server：FastMCP 实例与 ASGI app 工厂。"""

from fastmcp import FastMCP
from fastmcp.server.transforms.search import (
    RegexSearchTransform,
    serialize_tools_for_output_markdown,
)

from mcp_admin.auth import AdminKeyVerifier

# 先建实例，工具模块注册时从本模块导入此 mcp
mcp = FastMCP("aihelms_admin_mcp", auth=AdminKeyVerifier())

# 导入工具模块触发 @mcp.tool 注册
from mcp_admin import tools  # noqa: E402,F401

# 高频只读工具常驻 tools/list，其余走 search_tools 按需发现。
# 目的：tools/list 从 172 工具 ~24K token 压到 ~1-2K。
# stateless_http 下 search 模式不依赖 session，非钉工具经 call_tool proxy 调用。
ALWAYS_VISIBLE = [
    "admin_list_users",
    "admin_get_user",
    "admin_list_models",
    "admin_get_dashboard",
    "admin_list_mcp_servers",
    "admin_list_keys",
]

mcp.add_transform(
    RegexSearchTransform(
        always_visible=ALWAYS_VISIBLE,
        search_result_serializer=serialize_tools_for_output_markdown,
    )
)

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
