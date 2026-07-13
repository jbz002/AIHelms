"""网页抓取工具型 service：URL → Markdown/HTML，不落库。"""

import asyncio
import logging

from crawl4ai import AsyncWebCrawler

from core.config import settings
from core.url_safety import assert_safe_url

logger = logging.getLogger(__name__)


async def fetch_url(url: str, include_html: bool = False) -> dict:
    """抓取单个 URL，返回结构化结果。

    先经 SSRF 校验（阻塞式 DNS 解析，放到线程池）；crawl4ai 调用受
    settings.crawl_timeout 约束，超时或异常时返回 success=False 的结果，
    不抛异常（抓取失败是正常可预期的业务结果）。
    """
    await asyncio.to_thread(assert_safe_url, url)

    try:
        async with AsyncWebCrawler() as crawler:
            result = await asyncio.wait_for(
                crawler.arun(url), timeout=settings.crawl_timeout
            )
    except TimeoutError:
        logger.warning("crawl timeout: url=%s timeout=%ss", url, settings.crawl_timeout)
        return _error_result(url, f"抓取超时（{settings.crawl_timeout}秒）")
    except Exception:
        logger.exception("crawl failed: url=%s", url)
        return _error_result(url, "抓取过程中发生错误")

    metadata = result.metadata or {}
    return {
        "url": result.url or url,
        "success": result.success,
        "status_code": result.status_code,
        "title": metadata.get("title"),
        "markdown": str(result.markdown) if result.markdown is not None else "",
        "html": result.cleaned_html if include_html else None,
        "error_message": result.error_message if not result.success else None,
    }


def _error_result(url: str, message: str) -> dict:
    return {
        "url": url,
        "success": False,
        "status_code": None,
        "title": None,
        "markdown": None,
        "html": None,
        "error_message": message,
    }
