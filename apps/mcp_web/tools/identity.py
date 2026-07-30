"""身份查询工具。"""

from pydantic import BaseModel

from core.database import async_session
from exceptions import NotFoundError, ValidationError
from mcp_web._common import actor_id, error_text, json_dumps
from mcp_web.server import mcp
from services import ai_key_service


class GetMyIdentityInput(BaseModel):
    """web_get_my_identity 无参数（占位模型，保持工具入参单 Pydantic 模型范式）。"""

    model_config = {"str_strip_whitespace": True}


@mcp.tool(
    name="web_get_my_identity",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def web_get_my_identity(params: GetMyIdentityInput) -> str:
    """查询我的 AI 身份：个人/部门/项目主 Key 及每个 Key 绑定的模型、MCP、Skill、Agent。

    返回 JSON：{personal:[...], department:[...], project:[...]}。
    """
    async with async_session() as session:
        try:
            data = await ai_key_service.get_my_keys(session, actor_id())
        except (NotFoundError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)
