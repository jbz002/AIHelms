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


# ---------------------------------------------------------------------------
# 聚合视图：从 registry 派生 provider / mode / capability 全集，驱动前端动态下拉
# ---------------------------------------------------------------------------


def _provider_keys() -> set[str]:
    """registry 中出现的所有 litellm_provider 原始值（小写）。

    normalize 用作成员关卡：仅对 registry 原生 provider 派生前缀，
    legacy 平台抽象（google/volcengine/dashscope）不在集合内 → 返回 None，避免误派生。
    """
    keys: set[str] = set()
    for entry in _models().values():
        p = entry.get("litellm_provider")
        if isinstance(p, str) and p:
            keys.add(p.lower())
    return keys


def normalize_litellm_prefix(provider: str) -> str | None:
    """把 registry 的 litellm_provider 折叠成 LiteLLM 路由前缀。

    仅对 registry 原生 provider 生效；未知/legacy 返回 None（交由覆盖表或兜底处理）。
    多数 provider 前缀 == litellm_provider（identity），少数子类需折叠：
    vertex_ai-* / bedrock_* / amazon_nova / cohere_chat / fireworks_ai-* / text-completion-*
    """
    p = (provider or "").strip().lower()
    if not p or p not in _provider_keys():
        return None
    if p.startswith("vertex_ai-"):
        return "vertex_ai"
    if p.startswith("bedrock_") or p == "amazon_nova":
        return "bedrock"
    if p == "cohere_chat":
        return "cohere"
    if p.startswith("fireworks_ai-"):
        return "fireworks_ai"
    if p.startswith("text-completion-"):
        return p[len("text-completion-") :]
    return p


# 友好显示名（缺失则 value.replace("_"," ").title()）
_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "azure": "Azure",
    "vertex_ai": "Vertex AI",
    "bedrock": "AWS Bedrock",
    "gemini": "Google Gemini",
    "deepseek": "DeepSeek",
    "groq": "Groq",
    "mistral": "Mistral",
    "together_ai": "Together AI",
    "fireworks_ai": "Fireworks AI",
    "cohere": "Cohere",
    "perplexity": "Perplexity",
    "xai": "xAI",
    "openrouter": "OpenRouter",
    "ollama": "Ollama",
    "dashscope": "百炼 DashScope",
    "moonshot": "Moonshot",
    "minimax": "MiniMax",
    "zai": "Z.ai",
    "volcengine": "火山引擎",
    "tencent": "腾讯混元",
    "novita": "Novita",
    "deepinfra": "DeepInfra",
    "nebius": "Nebius",
    "cerebras": "Cerebras",
    "sambanova": "SambaNova",
    "watsonx": "Watsonx",
    "databricks": "Databricks",
    "github_copilot": "GitHub Copilot",
    "voyage": "Voyage AI",
    "jina_ai": "Jina AI",
    "elevenlabs": "ElevenLabs",
    "deepgram": "Deepgram",
    "snowflake": "Snowflake",
    "replicate": "Replicate",
    "cloudflare": "Cloudflare",
    "nvidia_nim": "NVIDIA NIM",
    "ai21": "AI21",
    "oci": "Oracle OCI",
    "azure_ai": "Azure AI",
    "vercel_ai_gateway": "Vercel AI Gateway",
}


def _display_name(value: str) -> str:
    return _PROVIDER_DISPLAY_NAMES.get(value) or value.replace("_", " ").title()


def providers() -> list[dict]:
    """registry 派生的 provider 全集，按模型数降序。

    返回 [{value(=折叠后前缀), count, label}]，驱动供应商下拉与 logo 选择器。
    """
    counter: dict[str, int] = {}
    for entry in _models().values():
        raw = entry.get("litellm_provider")
        if not isinstance(raw, str) or not raw:
            continue
        prefix = normalize_litellm_prefix(raw)
        if prefix:
            counter[prefix] = counter.get(prefix, 0) + 1
    items = [
        {"value": k, "count": c, "label": _display_name(k)} for k, c in counter.items()
    ]
    items.sort(key=lambda x: (-x["count"], x["value"]))
    return items


def modes() -> list[dict]:
    """registry 派生的 mode 全集，按模型数降序。"""
    counter: dict[str, int] = {}
    for entry in _models().values():
        m = entry.get("mode")
        if isinstance(m, str) and m:
            counter[m] = counter.get(m, 0) + 1
    items = [{"value": k, "count": c} for k, c in counter.items()]
    items.sort(key=lambda x: (-x["count"], x["value"]))
    return items


# registry supports_* 中非「能力」语义的位：推理强度档位 / 输出配置。
# 它们表示「支持某配置值」而非「模型能做什么」，不作为能力标签暴露。
_NON_CAPABILITY_SUPPORTS = frozenset(
    {
        "xhigh_reasoning_effort",
        "max_reasoning_effort",
        "minimal_reasoning_effort",
        "none_reasoning_effort",
        "adaptive_thinking",
        "output_config",
        "parallel_tool_use_config",
    }
)


def capabilities() -> list[dict]:
    """registry 派生的能力位全集（去 supports_ 前缀，排除 effort/config 配置位），按命中模型数降序。"""
    counter: dict[str, int] = {}
    for entry in _models().values():
        for k, v in entry.items():
            if k.startswith("supports_") and v is True:
                cap = k[len("supports_") :]
                if cap in _NON_CAPABILITY_SUPPORTS:
                    continue
                counter[cap] = counter.get(cap, 0) + 1
    items = [{"key": k, "count": c} for k, c in counter.items()]
    items.sort(key=lambda x: (-x["count"], x["key"]))
    return items


def meta() -> dict:
    """registry 元数据聚合，供 GET /models/registry-meta 一次性返回。"""
    return {
        "providers": providers(),
        "modes": modes(),
        "capabilities": capabilities(),
        "model_count": len(_models()),
    }


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
