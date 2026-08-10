"""平台内置模型注册表 loader。

数据源 apps/data/model_registry.json = LiteLLM 官方 model_prices_and_context_window.json 全量快照
(2983+ 模型 / 123 provider)。LiteLLM proxy 无公开 cost map 查询 API,平台维护快照,
符合「平台 DB 唯一数据源」。定期手动 re-fetch 该 JSON 即可更新。
"""

import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "model_registry.json"

# LiteLLM cost map 顶层的非 model 元数据 key,过滤掉
_META_KEYS = {"sample_spec"}


@lru_cache(maxsize=1)
def _raw() -> dict:
    try:
        with _REGISTRY_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.error("model registry malformed: %s", _REGISTRY_PATH)
            return {}
        return data
    except FileNotFoundError:
        logger.warning("model registry not found: %s", _REGISTRY_PATH)
        return {}
    except json.JSONDecodeError:
        logger.error("model registry invalid JSON: %s", _REGISTRY_PATH)
        return {}


def _models() -> dict[str, dict]:
    data = _raw()
    return {
        k: v for k, v in data.items() if k not in _META_KEYS and isinstance(v, dict)
    }


def lookup(name: str) -> dict | None:
    """按 LiteLLM model name 查注册表。精确 key 优先,失败按 basename 唯一匹配。

    basename 多 provider 同名时返回 None(前端提示用完整名)。
    """
    key = (name or "").strip().lower()
    if not key:
        return None
    models = _models()
    for raw_key, entry in models.items():
        if raw_key.lower() == key:
            return {"model_name": raw_key, **entry}
    basename = key.split("/")[-1]
    matches = [
        (raw_key, entry)
        for raw_key, entry in models.items()
        if raw_key.lower().split("/")[-1] == basename
    ]
    if len(matches) == 1:
        raw_key, entry = matches[0]
        return {"model_name": raw_key, **entry}
    return None


# LiteLLM 原始 USD/token 键 → 平台折算后的 ¥/百万token 键
_CNY_PRICING_MAP = {
    "input_cost_per_token": "input_cost_per_million_tokens_cny",
    "output_cost_per_token": "output_cost_per_million_tokens_cny",
    "cache_read_input_token_cost": "cache_read_input_cost_per_million_tokens_cny",
    "cache_creation_input_token_cost": "cache_creation_input_cost_per_million_tokens_cny",
    "output_cost_per_reasoning_token": "output_cost_per_reasoning_token_per_million_tokens_cny",
}


def lookup_with_cny_pricing(name: str) -> dict | None:
    """lookup + 附加 ¥/百万token 折算字段（部署表单回填官方价用）。"""
    entry = lookup(name)
    if not entry:
        return None
    rate = settings.usd_to_cny_rate
    for src, dst in _CNY_PRICING_MAP.items():
        val = entry.get(src)
        entry[dst] = (
            round(float(val) * rate * 1_000_000, 6) if val is not None else None
        )
    return entry


def search(keyword: str, limit: int = 20) -> list[str]:
    """关键字模糊匹配候选 model key。空关键字返回前 limit 个。"""
    kw = (keyword or "").strip().lower()
    keys = list(_models().keys())
    if not kw:
        return keys[:limit]
    return [k for k in keys if kw in k.lower()][:limit]


# 官方 cost map 中非模型元数据 key，校验 payload 时排除
_REGISTRY_MIN_MODELS = 1000


async def refresh_from_remote() -> bool:
    """启动时从官方 LiteLLM cost map 拉最新快照覆盖本地 JSON。

    国内服务器访问 GitHub raw 易超时：短超时 + 失败静默降级用旧快照，绝不阻断启动。
    文件新于 model_registry_refresh_min_age_hours 则跳过（dev 热重载节流）。
    """
    if not settings.model_registry_auto_update:
        return False
    min_age = settings.model_registry_refresh_min_age_hours
    if min_age > 0 and _REGISTRY_PATH.exists():
        age_hours = (time.time() - _REGISTRY_PATH.stat().st_mtime) / 3600
        if age_hours < min_age:
            logger.info(
                "model registry fresh (%.1fh < %dh), skip fetch", age_hours, min_age
            )
            return False
    # 多源依次尝试：官方 raw 国内常超时，jsDelivr 镜像兜底
    urls = [u.strip() for u in settings.model_registry_url.split(",") if u.strip()]
    data: dict | None = None
    async with httpx.AsyncClient(
        timeout=settings.model_registry_fetch_timeout, trust_env=False
    ) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as e:
                logger.warning("model registry fetch failed from %s: %s", url, e)
                continue
            if isinstance(payload, dict) and len(payload) >= _REGISTRY_MIN_MODELS:
                data = payload
                break
            logger.warning(
                "model registry payload invalid from %s (len=%s)",
                url,
                len(payload) if isinstance(payload, dict) else type(payload).__name__,
            )
    if data is None:
        logger.warning("all model registry sources failed, keep local snapshot")
        return False
    tmp_path = _REGISTRY_PATH.with_suffix(".json.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, _REGISTRY_PATH)
    except OSError as e:
        logger.error("model registry write failed: %s", e)
        return False
    _raw.cache_clear()
    logger.info("model registry updated from remote: %d entries", len(data))
    return True
