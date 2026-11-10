import json
import logging
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

LITELLM_TIMEOUT = 10.0

NO_DEFAULT_MODELS = "no-default-models"


def normalize_models_for_litellm(models: list[str] | None) -> list[str] | None:
    """Keep None as no change and translate an explicit empty list to deny-all."""
    if models is None:
        return None
    normalized = list(
        dict.fromkeys(model for model in models if model != NO_DEFAULT_MODELS)
    )
    return normalized or [NO_DEFAULT_MODELS]


async def _request(
    method: str,
    path: str,
    json_data: dict | None = None,
    params: dict | None = None,
    timeout: float = LITELLM_TIMEOUT,
    auth_token: str | None = None,
) -> dict:
    url = f"{settings.litellm_url}{path}"
    headers = {"Authorization": f"Bearer {auth_token or settings.litellm_master_key}"}
    try:
        async with httpx.AsyncClient(timeout=timeout, proxy=None) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data,
                params=params,
            )
            if response.status_code >= 400:
                logger.error(
                    "litellm request failed",
                    extra={
                        "method": method,
                        "path": path,
                        "status": response.status_code,
                        "body": response.text,
                    },
                )
                raise LiteLLMError(
                    f"LiteLLM {method} {path} failed: {response.status_code}"
                )
            return response.json()
    except httpx.HTTPError as e:
        logger.error("litellm connection error: %s %s - %s", method, path, str(e))
        raise LiteLLMError(f"LiteLLM {method} {path} connection error: {e}") from e


class LiteLLMError(Exception):
    pass


async def chat_completion(
    model: str,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 1200,
    timeout: float = 60.0,
    response_format: dict | None = None,
    api_key: str | None = None,
    user: str | None = None,
    metadata: dict | None = None,
    extra_body: dict | None = None,
) -> dict:
    data = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        data["response_format"] = response_format
    if user:
        data["user"] = user
    if metadata:
        data["metadata"] = metadata
    if extra_body:
        data["extra_body"] = extra_body
    return await _request(
        "POST",
        "/chat/completions",
        json_data=data,
        timeout=timeout,
        auth_token=api_key,
    )


async def chat_completion_stream(
    model: str,
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 1200,
    timeout: float = 120.0,
    api_key: str | None = None,
    user: str | None = None,
    metadata: dict | None = None,
    extra_body: dict | None = None,
) -> AsyncIterator[dict]:
    """流式 chat completion，逐个 yield OpenAI 形态的 chunk 字典。

    用于 SSE 打字机输出。调用方自行从 choices[0].delta.content / usage /
    finish_reason 取值。遇到 `data: [DONE]` 终止。
    """
    data: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if user:
        data["user"] = user
    if metadata:
        data["metadata"] = metadata
    if extra_body:
        data["extra_body"] = extra_body
    url = f"{settings.litellm_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key or settings.litellm_master_key}"}
    try:
        async with httpx.AsyncClient(timeout=timeout, proxy=None) as client:
            async with client.stream("POST", url, headers=headers, json=data) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    logger.error(
                        "litellm stream failed",
                        extra={
                            "status": resp.status_code,
                            "body": body.decode(errors="replace"),
                        },
                    )
                    raise LiteLLMError(
                        f"LiteLLM stream POST /chat/completions failed: {resp.status_code}"
                    )
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:") :].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:
                        continue
    except httpx.HTTPError as e:
        logger.error("litellm stream connection error: %s", str(e))
        raise LiteLLMError(
            f"LiteLLM stream POST /chat/completions connection error: {e}"
        ) from e


async def create_user(user_id: str, user_email: str) -> dict:
    data = {
        "user_id": user_id,
        "user_email": user_email,
        "user_role": "internal_user",
    }
    return await _request("POST", "/user/new", json_data=data)


async def delete_user(user_id: str) -> None:
    await _request("POST", "/user/delete", json_data={"user_ids": [user_id]})


async def create_team(team_alias: str, metadata: dict | None = None) -> dict:
    data: dict = {"team_alias": team_alias}
    if metadata:
        data["metadata"] = metadata
    return await _request("POST", "/team/new", json_data=data)


async def update_team(team_id: str, team_alias: str) -> dict:
    data = {"team_id": team_id, "team_alias": team_alias}
    return await _request("POST", "/team/update", json_data=data)


async def block_team(team_id: str) -> dict:
    data = {"team_id": team_id}
    return await _request("POST", "/team/block", json_data=data)


async def unblock_team(team_id: str) -> dict:
    data = {"team_id": team_id}
    return await _request("POST", "/team/unblock", json_data=data)


async def delete_team(team_id: str) -> None:
    await _request("POST", "/team/delete", json_data={"team_ids": [team_id]})


async def add_team_member(team_id: str, user_id: str) -> dict:
    data = {
        "team_id": team_id,
        "member": {"role": "user", "user_id": user_id},
    }
    return await _request("POST", "/team/member_add", json_data=data)


async def remove_team_member(team_id: str, user_id: str) -> None:
    data = {"team_id": team_id, "user_id": user_id}
    await _request("POST", "/team/member_delete", json_data=data)


# --- Key Management ---


async def create_key(
    key_alias: str,
    user_id: str | None = None,
    team_id: str | None = None,
    models: list[str] | None = None,
    max_budget: float | None = None,
    metadata: dict | None = None,
    duration: str | None = None,
    allowed_mcp_servers: list[str] | None = None,
    tpm_limit: int | None = None,
    rpm_limit: int | None = None,
    max_parallel_requests: int | None = None,
) -> dict:
    data: dict = {"key_alias": key_alias}
    if user_id:
        data["user_id"] = user_id
    if team_id:
        data["team_id"] = team_id
    data["models"] = normalize_models_for_litellm(models or [])
    if max_budget is not None:
        data["max_budget"] = max_budget
    if metadata:
        data["metadata"] = metadata
    if duration:
        data["duration"] = duration
    if allowed_mcp_servers is not None:
        data["allowed_mcp_servers"] = allowed_mcp_servers
    if tpm_limit is not None:
        data["tpm_limit"] = tpm_limit
    if rpm_limit is not None:
        data["rpm_limit"] = rpm_limit
    if max_parallel_requests is not None:
        data["max_parallel_requests"] = max_parallel_requests
    return await _request("POST", "/key/generate", json_data=data)


async def delete_key(key_id: str) -> None:
    await _request("POST", "/key/delete", json_data={"keys": [key_id]})


async def update_key(
    key_id: str,
    models: list[str] | None = None,
    max_budget: float | None = None,
    metadata: dict | None = None,
    allowed_mcp_servers: list[str] | None = None,
    tpm_limit: int | None = None,
    rpm_limit: int | None = None,
    max_parallel_requests: int | None = None,
    sync_rate_limits: bool = False,
) -> dict:
    data: dict = {"key": key_id}
    if models is not None:
        data["models"] = normalize_models_for_litellm(models)
    if max_budget is not None:
        data["max_budget"] = max_budget
    if metadata is not None:
        data["metadata"] = metadata
    if allowed_mcp_servers is not None:
        data["allowed_mcp_servers"] = allowed_mcp_servers
    if sync_rate_limits or tpm_limit is not None:
        data["tpm_limit"] = tpm_limit
    if sync_rate_limits or rpm_limit is not None:
        data["rpm_limit"] = rpm_limit
    if sync_rate_limits or max_parallel_requests is not None:
        data["max_parallel_requests"] = max_parallel_requests
    return await _request("POST", "/key/update", json_data=data)


async def update_key_budget(key_id: str, max_budget: float | None) -> dict:
    data: dict = {"key": key_id, "max_budget": max_budget}
    return await _request("POST", "/key/update", json_data=data)


async def get_key_info(key_id: str) -> dict:
    return await _request("GET", "/key/info", params={"key": key_id})


async def list_models() -> list[dict]:
    result = await _request("GET", "/model/info")
    if isinstance(result, dict) and "data" in result:
        return result["data"]
    if isinstance(result, list):
        return result
    return []


async def add_model(
    model_name: str,
    litellm_params: dict,
    model_info: dict | None = None,
) -> dict:
    data: dict = {
        "model_name": model_name,
        "litellm_params": litellm_params,
    }
    if model_info:
        data["model_info"] = model_info
    return await _request("POST", "/model/new", json_data=data)


async def delete_model(litellm_model_id: str) -> None:
    await _request("POST", "/model/delete", json_data={"id": litellm_model_id})


async def update_model(
    litellm_model_id: str,
    model_name: str,
    litellm_params: dict,
    model_info: dict | None = None,
) -> dict:
    data: dict = {}
    if model_name:
        data["model_name"] = model_name
    if litellm_params:
        data["litellm_params"] = litellm_params
    if model_info is not None:
        data["model_info"] = model_info
    return await _request("PATCH", f"/model/{litellm_model_id}/update", json_data=data)


# --- Credential Management ---


async def create_credential(
    credential_name: str,
    credential_values: dict,
    credential_info: dict | None = None,
) -> dict:
    data: dict = {
        "credential_name": credential_name,
        "credential_values": credential_values,
        "credential_info": credential_info or {},
    }
    return await _request("POST", "/credentials", json_data=data)


async def update_credential(
    credential_name: str,
    credential_values: dict | None = None,
    credential_info: dict | None = None,
) -> dict:
    # LiteLLM's CredentialItem schema requires all three fields on PATCH.
    data: dict = {
        "credential_name": credential_name,
        "credential_values": credential_values or {},
        "credential_info": credential_info or {},
    }
    encoded_name = quote(credential_name, safe="")
    return await _request("PATCH", f"/credentials/{encoded_name}", json_data=data)


async def delete_credential(credential_name: str) -> None:
    encoded_name = quote(credential_name, safe="")
    await _request("DELETE", f"/credentials/{encoded_name}")


async def list_credentials() -> list[dict]:
    result = await _request("GET", "/credentials")
    if isinstance(result, dict) and "credentials" in result:
        return result["credentials"]
    return []


async def get_provider_fields() -> list[dict]:
    url = f"{settings.litellm_url}/public/providers/fields"
    try:
        async with httpx.AsyncClient(timeout=LITELLM_TIMEOUT, proxy=None) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                logger.error(
                    "litellm get_provider_fields failed: %s", response.status_code
                )
                return []
            return response.json()
    except httpx.HTTPError as e:
        logger.error("litellm get_provider_fields connection error: %s", str(e))
        return []


# --- Router Settings / Fallbacks ---
#
# LiteLLM v1.103 移除了 POST /router/settings（实测 405），全局路由参数只保留：
#   - POST /config/update  : 写入 LiteLLM 配置库，进程启动时加载（重启生效）
#   - POST /fallback       : 按模型设置 fallback，写库 + 内存热生效
# 平台据此拆分：fallback 链走 /fallback，其余参数走 /config/update。


async def get_router_settings() -> dict:
    return await _request("GET", "/router/settings")


async def check_health(model_name: str | None = None, timeout: float = 120.0) -> dict:
    """Actively probe deployments (optionally one model group) and return health detail.

    LiteLLM answers 503 when any probed endpoint is unhealthy, but the body still
    carries healthy_endpoints/unhealthy_endpoints; only >=400 other than 503 is an error.
    """
    url = f"{settings.litellm_url}/health"
    params = {"model": model_name} if model_name else None
    headers = {"Authorization": f"Bearer {settings.litellm_master_key}"}
    try:
        async with httpx.AsyncClient(timeout=timeout, proxy=None) as client:
            response = await client.get(url, headers=headers, params=params)
    except httpx.HTTPError as e:
        logger.error("litellm health check connection error: %s", str(e))
        raise LiteLLMError(f"LiteLLM GET /health connection error: {e}") from e
    if response.status_code >= 400 and response.status_code != 503:
        logger.error(
            "litellm health check failed",
            extra={"status": response.status_code, "body": response.text},
        )
        raise LiteLLMError(f"LiteLLM GET /health failed: {response.status_code}")
    try:
        return response.json()
    except ValueError as e:
        raise LiteLLMError("LiteLLM GET /health returned non-JSON body") from e


async def update_router_config(router_settings: dict) -> dict:
    """Persist global router settings; applied when LiteLLM restarts."""
    return await _request(
        "POST", "/config/update", json_data={"router_settings": router_settings}
    )


async def get_fallbacks(fallback_type: str = "general") -> dict[str, list[str]]:
    """Read the current fallback map: source model group -> ordered targets."""
    payload = await get_router_settings()
    current_values = (payload or {}).get("current_values") or {}
    field = {
        "general": "fallbacks",
        "context_window": "context_window_fallbacks",
        "content_policy": "content_policy_fallbacks",
    }.get(fallback_type, "fallbacks")
    entries = current_values.get(field) or []
    result: dict[str, list[str]] = {}
    if not isinstance(entries, list):
        return result
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for source, targets in entry.items():
            if isinstance(source, str) and isinstance(targets, list):
                result[source] = [t for t in targets if isinstance(t, str)]
    return result


async def create_fallback(
    model: str,
    fallback_models: list[str],
    fallback_type: str = "general",
) -> dict:
    return await _request(
        "POST",
        "/fallback",
        json_data={
            "model": model,
            "fallback_models": fallback_models,
            "fallback_type": fallback_type,
        },
    )


async def delete_fallback(model: str, fallback_type: str = "general") -> dict:
    return await _request(
        "DELETE",
        f"/fallback/{quote(model, safe='')}",
        params={"fallback_type": fallback_type},
    )


# --- MCP Server Management ---


async def create_mcp_server(
    server_name: str,
    url: str,
    server_id: str | None = None,
    transport: str = "sse",
    auth_type: str | None = None,
    credentials: dict | None = None,
    description: str | None = None,
    instructions: str | None = None,
    allowed_tools: list[str] | None = None,
    extra_headers: list[str] | None = None,
    mcp_info: dict | None = None,
) -> dict:
    data: dict = {
        "server_name": server_name,
        "url": url,
        "transport": transport,
    }
    if server_id:
        data["server_id"] = server_id
    if auth_type:
        data["auth_type"] = auth_type
    if credentials:
        data["credentials"] = credentials
    if description:
        data["description"] = description
    if instructions:
        data["instructions"] = instructions
    if allowed_tools:
        data["allowed_tools"] = allowed_tools
    if extra_headers:
        data["extra_headers"] = extra_headers
    if mcp_info:
        data["mcp_info"] = mcp_info
    data["allow_all_keys"] = True
    return await _request("POST", "/v1/mcp/server", json_data=data)


async def update_mcp_server(
    server_id: str,
    server_name: str | None = None,
    url: str | None = None,
    transport: str | None = None,
    auth_type: str | None = None,
    credentials: dict | None = None,
    description: str | None = None,
    instructions: str | None = None,
    allowed_tools: list[str] | None = None,
    extra_headers: list[str] | None = None,
    mcp_info: dict | None = None,
    allow_all_keys: bool | None = None,
) -> dict:
    data: dict = {"server_id": server_id}
    if server_name is not None:
        data["server_name"] = server_name
    if url is not None:
        data["url"] = url
    if transport is not None:
        data["transport"] = transport
    if auth_type is not None:
        data["auth_type"] = auth_type
    if credentials is not None:
        data["credentials"] = credentials
    if description is not None:
        data["description"] = description
    if instructions is not None:
        data["instructions"] = instructions
    if allowed_tools is not None:
        data["allowed_tools"] = allowed_tools
    if extra_headers is not None:
        data["extra_headers"] = extra_headers
    if mcp_info is not None:
        data["mcp_info"] = mcp_info
    if allow_all_keys is not None:
        data["allow_all_keys"] = allow_all_keys
    return await _request("PUT", "/v1/mcp/server", json_data=data)


async def delete_mcp_server(server_id: str) -> None:
    await _request("DELETE", f"/v1/mcp/server/{server_id}")


async def get_mcp_tools(server_id: str | None = None) -> list[dict]:
    params = {}
    if server_id:
        params["server_id"] = server_id
    result = await _request("GET", "/v1/mcp/tools", params=params)
    if isinstance(result, dict) and "tools" in result:
        return result["tools"]
    if isinstance(result, list):
        return result
    return []


async def test_mcp_connection(
    url: str,
    transport: str = "sse",
    auth_type: str | None = None,
    credentials: dict | None = None,
) -> dict:
    data: dict = {"url": url, "transport": transport}
    if auth_type:
        data["auth_type"] = auth_type
    if credentials:
        data["credentials"] = credentials
    return await _request("POST", "/mcp-rest/test/connection", json_data=data)


async def list_mcp_tools_from_server(
    url: str,
    transport: str = "sse",
    auth_type: str | None = None,
    credentials: dict | None = None,
) -> list[dict]:
    data: dict = {"url": url, "transport": transport}
    if auth_type:
        data["auth_type"] = auth_type
    if credentials:
        data["credentials"] = credentials
    result = await _request("POST", "/mcp-rest/test/tools/list", json_data=data)
    if isinstance(result, dict) and "tools" in result:
        return result["tools"]
    if isinstance(result, list):
        return result
    return []
