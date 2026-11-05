from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Provider

# Claude Code 客户端指纹（对齐 cc-switch impersonateClaudeCode）：部分 coding plan /
# 聚合上游做「Claude Code only」指纹检查。litellm 出站 UA 固定为 litellm/x.y.z
# （2026-10-26 dev 实测不透传客户端 UA），须在凭证级注入指纹头才能过闸。
# anthropic-beta 的 claude-code 标记被 litellm 已知 beta 白名单剥除（同日实测），
# 无法经 litellm 传递，仅注入以下两项。
IMPERSONATION_CLAUDE_CODE = "claude_code"
_CLAUDE_CODE_HEADERS = {
    "user-agent": "claude-cli/2.1.237 (external, cli)",
    "x-app": "cli",
}


def impersonation_headers(credential_info: dict | None, existing: dict | None) -> dict:
    """按凭证 client_identity 计算需注入的指纹头，合并进 existing（用户显式同名头优先）。"""
    info = credential_info or {}
    if info.get("client_identity") != IMPERSONATION_CLAUDE_CODE:
        return dict(existing or {})
    headers = dict(existing or {})
    for name, value in _CLAUDE_CODE_HEADERS.items():
        has_override = any(str(k).lower() == name for k in headers)
        if not has_override:
            headers[name] = value
    return headers


def _effective_auth_style(credential_info: dict, provider: str) -> str | None:
    """凭证认证风格：显式 auth_style 优先；vllm anthropic 端点默认 Bearer（历史特判）。"""
    style = credential_info.get("auth_style")
    if style:
        return str(style)
    if provider == "vllm":
        return "bearer"
    return None


def prepare_litellm_credential_values(
    credential_values: dict | None,
    credential_info: dict | None,
    provider_type: str | None,
) -> dict:
    """Build credential values for LiteLLM without mutating platform DB values."""
    values = dict(credential_values or {})
    info = credential_info or {}
    cred_format = (info.get("format") or "openai").lower()
    provider = (provider_type or "").lower()

    if cred_format == "anthropic":
        if _effective_auth_style(info, provider) == "bearer":
            api_key = values.get("api_key")
            if api_key:
                headers = dict(values.get("extra_headers") or {})
                has_authorization = any(
                    str(name).lower() == "authorization" for name in headers
                )
                if not has_authorization:
                    headers["authorization"] = f"Bearer {api_key}"
                values["extra_headers"] = headers
        impersonated = impersonation_headers(info, values.get("extra_headers"))
        if impersonated:
            values["extra_headers"] = impersonated

    return values


async def build_litellm_credential_values(
    session: AsyncSession,
    credential_values: dict | None,
    credential_info: dict | None,
    provider_id: int | None,
) -> dict:
    provider_type = None
    if provider_id:
        provider_type = await session.scalar(
            select(Provider.provider_type).where(Provider.id == provider_id)
        )
    return prepare_litellm_credential_values(
        credential_values=credential_values,
        credential_info=credential_info,
        provider_type=provider_type,
    )


async def build_litellm_credential_values_for_credential(
    session: AsyncSession,
    credential,
) -> dict:
    return await build_litellm_credential_values(
        session=session,
        credential_values=credential.credential_values or {},
        credential_info=credential.credential_info or {},
        provider_id=credential.provider_id,
    )
