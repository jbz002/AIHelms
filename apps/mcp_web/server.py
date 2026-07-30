"""用户自助 MCP server：FastMCP 实例与 ASGI app 工厂。"""

from fastmcp import FastMCP
from fastmcp.server.transforms.search import (
    RegexSearchTransform,
    serialize_tools_for_output_markdown,
)

from mcp_web.auth import UserKeyVerifier

# 先建实例，工具模块注册时从本模块导入此 mcp
mcp = FastMCP("aihelms_web_mcp", auth=UserKeyVerifier())

# 导入工具模块触发 @mcp.tool 注册
from mcp_web import tools  # noqa: E402,F401

# 高频只读工具常驻 tools/list，其余走 search_tools 按需发现。
ALWAYS_VISIBLE = [
    "web_get_my_identity",
    "web_search_published_skills",
    "web_search_published_mcps",
    "web_list_my_applications",
]

mcp.add_transform(
    RegexSearchTransform(
        always_visible=ALWAYS_VISIBLE,
        search_result_serializer=serialize_tools_for_output_markdown,
    )
)

_mcp_app = None


def create_web_mcp_app():
    """返回可挂载到 FastAPI 的 Starlette ASGI app（单例，无状态 streamable HTTP）。

    单例：父 FastAPI app 的 lifespan 与 mount 必须共用同一个 app 实例，
    否则 StreamableHTTPSessionManager 的 task group 不会被初始化。
    """
    global _mcp_app
    if _mcp_app is None:
        _mcp_app = mcp.http_app(path="/mcp", transport="http", stateless_http=True)
    return _mcp_app
