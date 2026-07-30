"""MCP 写工具审计落库（Q16 方案 a）。

MCP 全走单端点 POST /admin-mcp/mcp/ 的 JSON-RPC，父 app 的 AuditLogMiddleware 看到的
path 恒相同、无 route.summary，无法区分调用了哪个工具（规划 §6 Q16 方案 b 不可行）。
故由 audited_tool 装饰器在工具内显式落 admin_audit_logs，action 文案由 TOOL_ACTIONS
按 tool_name 映射，对齐「动词+资源」中文规范。
"""

import asyncio
import functools
import json
import logging
import time
from typing import Any, Awaitable, Callable

from core.audit import SENSITIVE_KEYS
from core.database import async_session
from mcp_admin._common import actor
from models.db import AdminAuditLog

logger = logging.getLogger(__name__)

REQUEST_SUMMARY_MAX = 4000

# tool_name -> 中文 action 文案（写工具落审计用；只读工具不落库）
TOOL_ACTIONS: dict[str, str] = {
    # users
    "admin_create_user": "创建用户",
    "admin_update_user": "更新用户",
    "admin_delete_user": "删除用户",
    "admin_reset_user_password": "重置用户密码",
    # models
    "admin_create_model": "创建模型",
    "admin_update_model": "更新模型",
    "admin_delete_model": "删除模型",
    "admin_publish_model": "更新模型发布状态",
    # ai_keys
    "admin_create_scene_key": "创建场景 Key",
    "admin_update_key": "更新 AI Key",
    "admin_toggle_key": "切换 Key 启用状态",
    "admin_delete_key": "删除 AI Key",
    # skills
    "admin_create_skill_from_url": "从 URL 创建 Skill",
    "admin_delete_skill": "删除 Skill",
    # mcp_servers
    "admin_refresh_mcp_tools": "刷新 MCP 工具列表",
    "admin_health_check_mcp": "MCP Server 健康检查",
    # efficiency（M1）
    "admin_refresh_efficiency": "刷新效能数据",
    "admin_create_efficiency_report": "生成分析报告",
    "admin_update_efficiency_suggestion": "更新建议状态",
    # providers（M1）
    "admin_create_provider": "创建供应商",
    "admin_update_provider": "更新供应商",
    "admin_delete_provider": "删除供应商",
    # dashboard（M1）
    "admin_refresh_dashboard": "刷新 Dashboard",
    # credentials（M3）
    "admin_create_credential": "创建凭证",
    "admin_update_credential": "更新凭证",
    "admin_delete_credential": "删除凭证",
    # model_ops（M3）
    "admin_create_deployment": "创建模型部署",
    "admin_update_deployment": "更新模型部署",
    "admin_delete_deployment": "删除模型部署",
    "admin_create_access_group": "创建访问组",
    "admin_update_access_group": "更新访问组",
    "admin_delete_access_group": "删除访问组",
    "admin_update_router_settings": "更新路由设置",
    "admin_resync_anthropic_deployments": "重同步 Anthropic 部署",
    # ai_key 补强（M3）
    "admin_batch_create_keys": "批量创建 AI 身份 Key",
    "admin_update_key_resources": "更新 Key 资源",
    "admin_set_model_limits": "设置模型限额",
    "admin_delete_model_limit": "删除模型限额",
    "admin_sync_public_resources": "同步公共资源到所有 Key",
    "admin_remove_public_resources": "移除所有 Key 的公共资源",
    # 部门（M4）
    "admin_create_department": "创建部门",
    "admin_update_department": "更新部门",
    "admin_delete_department": "删除部门",
    "admin_add_department_member": "添加部门成员",
    "admin_remove_department_member": "移除部门成员",
    "admin_update_department_managers": "更新部门主管",
    # 项目（M4）
    "admin_create_project": "创建项目",
    "admin_update_project": "更新项目",
    "admin_delete_project": "删除项目",
    "admin_add_project_member": "添加项目成员",
    "admin_remove_project_member": "移除项目成员",
    # 角色（M4）
    "admin_create_role": "创建角色",
    "admin_update_role": "更新角色",
    "admin_delete_role": "删除角色",
    "admin_update_role_permissions": "更新角色权限",
    # 用户归属（M4）
    "admin_update_user_roles": "更新用户角色",
    "admin_update_user_departments": "更新用户部门",
    "admin_update_user_projects": "更新用户项目",
    # skill 补强（M5）
    "admin_update_skill": "更新 Skill",
    "admin_set_skill_published": "设置 Skill 发布状态",
    "admin_set_skill_hidden": "设置 Skill 隐藏",
    "admin_create_skill_version": "创建 Skill 版本",
    "admin_activate_skill_version": "激活 Skill 版本",
    "admin_deprecate_skill_version": "弃用 Skill 版本",
    "admin_yank_skill_version": "下架 Skill 版本",
    "admin_restore_skill_version": "恢复 Skill 版本",
    "admin_create_skill_category": "创建 Skill 分类",
    "admin_delete_skill_category": "删除 Skill 分类",
    # mcp 补强（M5）
    "admin_create_mcp_server": "创建 MCP Server",
    "admin_update_mcp_server": "更新 MCP Server",
    "admin_delete_mcp_server": "删除 MCP Server",
    "admin_set_mcp_published": "设置 MCP 发布状态",
    "admin_create_mcp_version": "创建 MCP 版本",
    "admin_activate_mcp_version": "激活 MCP 版本",
    "admin_deprecate_mcp_version": "弃用 MCP 版本",
    "admin_update_mcp_tool_billing": "更新 MCP 工具计费",
    "admin_create_mcp_category": "创建 MCP 分类",
    "admin_delete_mcp_category": "删除 MCP 分类",
    # agent（M5）
    "admin_create_agent": "创建 Agent",
    "admin_update_agent": "更新 Agent",
    "admin_delete_agent": "删除 Agent",
    "admin_set_agent_published": "设置 Agent 发布状态",
    "admin_create_agent_category": "创建 Agent 分类",
    "admin_delete_agent_category": "删除 Agent 分类",
    "admin_create_agent_platform": "创建 Agent 平台",
    "admin_delete_agent_platform": "删除 Agent 平台",
    # api_key（M7）
    "admin_create_api_key": "创建平台 API Key",
    "admin_update_api_key": "更新平台 API Key",
    "admin_delete_api_key": "删除平台 API Key",
    # cli_token（M7）
    "admin_create_cli_token": "创建 CLI 令牌",
    "admin_update_cli_token": "更新 CLI 令牌",
    "admin_revoke_cli_token": "吊销 CLI 令牌",
    # platform_settings（M7）
    "admin_update_default_model": "更新默认模型",
    # export（M7）
    "admin_create_export_task": "创建导出任务",
    "admin_retry_export_task": "重试导出任务",
    "admin_cancel_export_task": "取消导出任务",
    "admin_cleanup_export_tasks": "清理导出任务",
}


def audited_tool(
    tool_name: str,
) -> Callable[[Callable[..., Awaitable[str]]], Callable[..., Awaitable[str]]]:
    """写工具审计装饰器，包在 @mcp.tool 内层。

    记录调用耗时与成败状态，异步落 admin_audit_logs。actor 取自请求 access_token；
    审计失败仅告警，不影响业务结果。返回值以「错误」开头视为业务失败（status 400），
    抛异常视为服务器错误（status 500）。
    """

    def decorator(
        fn: Callable[..., Awaitable[str]],
    ) -> Callable[..., Awaitable[str]]:
        @functools.wraps(fn)
        async def wrapper(params: Any) -> str:
            start = time.monotonic()
            actor_info = _safe_actor()
            status_code = 200
            try:
                result = await fn(params)
                if isinstance(result, str) and result.startswith("错误"):
                    status_code = 400
                return result
            except Exception:
                status_code = 500
                raise
            finally:
                duration_ms = int((time.monotonic() - start) * 1000)
                asyncio.create_task(
                    _write_audit(
                        actor_info=actor_info,
                        tool_name=tool_name,
                        status_code=status_code,
                        request_summary=_summarize(params),
                        duration_ms=duration_ms,
                    )
                )

        return wrapper

    return decorator


def _safe_actor() -> dict:
    try:
        return actor()
    except Exception:  # noqa: BLE001
        return {
            "user_id": 0,
            "username": "",
            "api_key_id": None,
            "is_super_admin": False,
        }


def _summarize(params: Any) -> str:
    try:
        dumped = params.model_dump()
    except Exception:  # noqa: BLE001
        return "<non-serializable params>"
    try:
        return json.dumps(_redact(dumped), ensure_ascii=False, default=str)[
            :REQUEST_SUMMARY_MAX
        ]
    except Exception:  # noqa: BLE001
        return "<non-serializable params>"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in SENSITIVE_KEYS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


async def _write_audit(
    *,
    actor_info: dict,
    tool_name: str,
    status_code: int,
    request_summary: str,
    duration_ms: int,
) -> None:
    action = TOOL_ACTIONS.get(tool_name, tool_name)
    try:
        async with async_session() as session:
            session.add(
                AdminAuditLog(
                    user_id=actor_info["user_id"],
                    username=actor_info["username"],
                    identity_type="api_key",
                    method="POST",
                    path=f"/admin-mcp/mcp#{tool_name}",
                    action=action,
                    status_code=status_code,
                    ip="",
                    user_agent="mcp-client",
                    duration_ms=duration_ms,
                    request_summary=request_summary,
                    request_id="",
                    detail={
                        "tool": tool_name,
                        "api_key_id": actor_info.get("api_key_id"),
                    },
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("mcp audit write failed: tool=%s", tool_name, exc_info=True)
