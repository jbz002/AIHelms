"""平台级 LLM 调用统一入口。

管理员发起的平台运维调用（文档接口提取 / 文档分类 / Skill 安全审查复核 /
文档搜索摘要）默认归因到发起管理员的个人主 Key：日志管理显示真实管理员 +
主 Key，成本/Token 进入管理员名下。

主 Key 不存在、未启用、未同步到 LiteLLM 或无权调目标模型时，回退
LITELLM_MASTER_KEY（日志显示「平台系统」/「****」，master key 不外露）。

普通用户业务调用（跑 Agent、Skill 下载 token、资源申请关联）仍走个人主 Key，
见 ai_key_service / ai_key_repo，不在本模块范围。
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from repositories import ai_key_repo


def get_platform_api_key() -> str:
    """返回平台业务调用兜底用的 LiteLLM key（复用 master key）。

    master key 未配置时返回空串，调用方据此抛出明确错误。
    """
    return settings.litellm_master_key or ""


def platform_user(user: Any) -> str:
    """平台调用的 LiteLLM user 字段：优先发起人 litellm_user_id，否则平台标识。

    保留发起人归属便于 LiteLLM 日志追溯；发起人无 litellm_user_id 时用 platform_llm_user。
    """
    litellm_user_id = getattr(user, "litellm_user_id", "") or ""
    return litellm_user_id or settings.platform_llm_user


def _identity(user: Any, key: str, default: Any = None) -> Any:
    """从 user 取字段，兼容 ORM 对象与 JWT dict。"""
    if isinstance(user, dict):
        return user.get(key, default)
    return getattr(user, key, default)


def _key_authorizes(key: Any, model_name: str) -> bool:
    """主 Key 的 models 列表是否包含目标模型（LiteLLM 鉴权前置检查）。"""
    models = getattr(key, "models", None) or []
    return bool(model_name) and model_name in list(models)


async def resolve_call_identity(
    session: AsyncSession, user: Any, model_name: str
) -> tuple[str, str]:
    """解析平台默认模型调用的 (api_key, litellm_user_id)。

    优先归因到发起管理员的个人主 Key：日志管理可显示真实管理员 + 主 Key。
    主 Key 缺失/停用/未同步/无权调 model_name 时，回退 master key。
    """
    user_id = _identity(user, "id", 0)
    if user_id:
        main_key = await ai_key_repo.find_personal_main(session, int(user_id))
        if (
            main_key
            and getattr(main_key, "is_active", False)
            and getattr(main_key, "litellm_key_id", "")
            and _key_authorizes(main_key, model_name)
        ):
            litellm_user_id = (
                _identity(user, "litellm_user_id", "") or settings.platform_llm_user
            )
            return main_key.litellm_key_id, litellm_user_id
    return get_platform_api_key(), platform_user(user)
