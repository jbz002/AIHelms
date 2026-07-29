"""一次性重建孤儿主 Key 的 LiteLLM key。

背景：ai_keys.litellm_key_id 在 LiteLLM DB 不存在（孤儿，如 LiteLLM DB 被重建过、
key 被手动删过）。sync_public_resource_to_all_keys 遍历主 Key 调 update_key 时，
孤儿 key 触发 404 "Key not found" → LiteLLMError → 502 阻断发布/同步。

本脚本对指定 key 在 LiteLLM 侧重新 create_key（保持 litellm_key_alias 不变），
并把平台 DB 的 models/mcps/metadata/限流全量写入新 LiteLLM key，最后回写
ai_keys.litellm_key_id。新 key 值与旧的不同，归属用户本地客户端需更新。

运行：cd apps && uv run python -m scripts.rebuild_litellm_key <key_id> [<key_id> ...]
"""

import asyncio
import sys

from core.database import async_session
from repositories import ai_key_repo
from services import ai_key_service, litellm_client


async def rebuild(session, key_id: int) -> bool:
    key = await ai_key_repo.find_by_id(session, key_id)
    if not key:
        print(f"key {key_id}: not found, skip")
        return False
    if not key.litellm_key_alias:
        print(f"key {key_id}: no litellm_key_alias, skip")
        return False

    team_id = await ai_key_service._resolve_owner(session, key.owner_type, key.owner_id)
    litellm_user_id = await ai_key_service._resolve_litellm_user(
        session, key.owner_type, key.owner_id
    )
    litellm_models, _ = await ai_key_service._expand_models_with_anthropic(
        session, key.models or [], None
    )
    mcp_names = await ai_key_service._resolve_mcp_server_names(session, key.mcps or [])
    metadata = await ai_key_service._build_key_metadata(session, key)

    result = await litellm_client.create_key(
        key_alias=key.litellm_key_alias,
        user_id=litellm_user_id,
        team_id=team_id,
        models=litellm_models,
        metadata=metadata,
        duration=(
            key.budget_duration if key.budget_duration and key.budget_limit else None
        ),
        allowed_mcp_servers=mcp_names if mcp_names else None,
        tpm_limit=key.tpm_limit,
        rpm_limit=key.rpm_limit,
        max_parallel_requests=key.max_parallel_requests,
    )
    key.litellm_key_id = result.get("key")
    await session.commit()
    print(f"key {key_id}: rebuilt, litellm_key_id={key.litellm_key_id}")
    return True


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m scripts.rebuild_litellm_key <key_id> [<key_id> ...]")
        return
    key_ids = [int(x) for x in sys.argv[1:]]
    async with async_session() as session:
        for kid in key_ids:
            try:
                await rebuild(session, kid)
            except Exception as e:  # noqa: BLE001
                print(f"key {kid}: FAILED {e}")


if __name__ == "__main__":
    asyncio.run(main())
