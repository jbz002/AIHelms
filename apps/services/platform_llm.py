"""平台级 LLM 调用统一入口。

管理员发起的平台运维调用（文档接口提取 / Skill 安全审查 / 模型连通性测试）
统一走 LITELLM_MASTER_KEY：LiteLLM 全权 key，能调所有模型、无配额限制，
对管理员无感，无需配置个人 AI 身份。

普通用户业务调用（跑 Agent、Skill 下载 token、资源申请关联）仍走个人主 Key，
见 ai_key_service / ai_key_repo，不在本模块范围。
"""

from typing import Any

from core.config import settings


def get_platform_api_key() -> str:
    """返回平台业务调用用的 LiteLLM key（复用 master key）。

    master key 未配置时返回空串，调用方据此抛出明确错误。
    """
    return settings.litellm_master_key or ""


def platform_user(user: Any) -> str:
    """平台调用的 LiteLLM user 字段：优先发起人 litellm_user_id，否则平台标识。

    保留发起人归属便于 LiteLLM 日志追溯；发起人无 litellm_user_id 时用 platform_llm_user。
    """
    litellm_user_id = getattr(user, "litellm_user_id", "") or ""
    return litellm_user_id or settings.platform_llm_user
