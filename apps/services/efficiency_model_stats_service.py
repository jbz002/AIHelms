"""用户×模型用量统计服务（cc-switch 口径）。

指标定义：
- 真实消耗 Tokens = 新增输入 + 输出 + 缓存写入 + 缓存命中
- 缓存命中率 = 缓存命中 ÷（新增输入 + 缓存写入 + 缓存命中）
- 速度（tok/s）= Σ输出 ÷ Σ(耗时−首字)，仅统计合格请求（成功 + duration>ttft≥0）
- 首字 = ttft 中位数
"""

import asyncio
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from repositories import efficiency_model_stats_repo


def _merge_rows(summary_rows: list[dict], latency_rows: list[dict]) -> list[dict]:
    latency_by_model = {row["model"]: row for row in latency_rows}
    items: list[dict] = []
    for summary in summary_rows:
        request_count = summary["request_count"]
        successful = summary["successful_requests"]
        real_total = (
            summary["fresh_input_tokens"]
            + summary["output_tokens"]
            + summary["cache_creation_tokens"]
            + summary["cache_read_tokens"]
        )
        cacheable = (
            summary["fresh_input_tokens"]
            + summary["cache_creation_tokens"]
            + summary["cache_read_tokens"]
        )
        latency = latency_by_model.get(summary["model"])
        speed_tokens_per_sec = None
        first_token_ms = None
        speed_sample_count = 0
        if latency:
            speed_sample_count = latency["speed_samples"]
            if latency["speed_decode_ms"] > 0:
                speed_tokens_per_sec = round(
                    latency["speed_output_tokens"] / latency["speed_decode_ms"] * 1000,
                    1,
                )
            first_token_ms = latency["first_token_ms"]
        items.append(
            {
                "model": summary["model"],
                "platform_model_name": summary["platform_model_name"],
                "platform_model_id": summary["platform_model_id"],
                "request_count": request_count,
                "successful_requests": successful,
                "success_rate": (
                    round(successful / request_count * 100, 1)
                    if request_count > 0
                    else None
                ),
                "input_tokens": summary["input_tokens"],
                "output_tokens": summary["output_tokens"],
                "cache_read_tokens": summary["cache_read_tokens"],
                "cache_creation_tokens": summary["cache_creation_tokens"],
                "fresh_input_tokens": summary["fresh_input_tokens"],
                "real_total_tokens": real_total,
                "cache_hit_rate": (
                    round(summary["cache_read_tokens"] / cacheable * 100, 1)
                    if cacheable > 0
                    else None
                ),
                "internal_cost": round(summary["internal_cost"], 6),
                "avg_cost_per_request": (
                    round(summary["internal_cost"] / request_count, 4)
                    if request_count > 0
                    else None
                ),
                "avg_latency_ms": (
                    round(summary["total_duration_ms"] / successful, 1)
                    if successful > 0
                    else None
                ),
                "speed_tokens_per_sec": speed_tokens_per_sec,
                "speed_sample_count": speed_sample_count,
                "first_token_ms": (
                    round(first_token_ms, 1) if first_token_ms is not None else None
                ),
            }
        )
    return items


async def get_user_model_stats(
    session: AsyncSession, start_date: date, end_date: date, user_id: int
) -> dict:
    summary_rows, latency_rows = await asyncio.gather(
        efficiency_model_stats_repo.get_user_model_summary(
            session, start_date, end_date, user_id
        ),
        efficiency_model_stats_repo.get_user_model_latency(
            session, start_date, end_date, user_id
        ),
    )
    return {"items": _merge_rows(summary_rows, latency_rows)}
