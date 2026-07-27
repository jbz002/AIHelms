"""平台内置模型注册表 loader。

数据源 apps/data/model_registry.json = LiteLLM 官方 model_prices_and_context_window.json 全量快照
(2983+ 模型 / 123 provider)。LiteLLM proxy 无公开 cost map 查询 API,平台维护快照,
符合「平台 DB 唯一数据源」。定期手动 re-fetch 该 JSON 即可更新。
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

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


def search(keyword: str, limit: int = 20) -> list[str]:
    """关键字模糊匹配候选 model key。空关键字返回前 limit 个。"""
    kw = (keyword or "").strip().lower()
    keys = list(_models().keys())
    if not kw:
        return keys[:limit]
    return [k for k in keys if kw in k.lower()][:limit]
