"""资源申请工具。"""

from pydantic import BaseModel, Field

from core.database import async_session
from exceptions import ConflictError, NotFoundError, ValidationError
from mcp_web._audit import audited_tool
from mcp_web._common import PageInput, actor_id, error_text, json_dumps
from mcp_web.server import mcp
from services import resource_application_service


class ApplyResourceInput(BaseModel):
    model_config = {"str_strip_whitespace": True}
    resource_type: str = Field(
        ..., pattern=r"^(model|mcp|skill|agent)$", description="资源类型"
    )
    resource_id: int = Field(..., ge=1, description="资源 ID")
    reason: str = Field(default="", max_length=500, description="申请理由")


class MyApplicationsInput(PageInput):
    """web_list_my_applications 仅分页参数。"""


@mcp.tool(
    name="web_apply_resource",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@audited_tool("web_apply_resource")
async def web_apply_resource(params: ApplyResourceInput) -> str:
    """申请使用一个资源（模型/MCP/Skill/Agent）。审批通过后资源授权到我的主 Key。

    同一资源已有未处理申请会冲突。返回新建的申请记录。
    """
    async with async_session() as session:
        try:
            data = await resource_application_service.create_application(
                session,
                actor_id(),
                params.resource_type,
                params.resource_id,
                params.reason,
                None,
            )
        except (NotFoundError, ConflictError, ValidationError) as e:
            return error_text(e)
    return json_dumps(data)


@mcp.tool(
    name="web_list_my_applications",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def web_list_my_applications(params: MyApplicationsInput) -> str:
    """查询我的资源申请列表及审批状态。返回 JSON：{items, total, page, page_size}。"""
    async with async_session() as session:
        data = await resource_application_service.list_applications(
            session,
            page=params.page,
            page_size=params.page_size,
            user_id=actor_id(),
        )
    return json_dumps(data)
