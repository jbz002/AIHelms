"""一次性重灌：docs-mcp embedding 模型切换后，用平台 documents.content 重放全部文档。

背景：docs-mcp 侧 embedding 由 iFlytek xop3qwen8bembedding 换成经 AIHelms 网关的
qwen3-embedding-4b，旧向量已整体作废（vec 表已清空、documents.embedding 置 NULL）。
docs-mcp 没有「按已存文本重嵌」的能力，而 ingest_crawl_task 会按 content_hash 把已入库
页判为 duplicate 直接跳过，因此走这里：直接以 ingest_url 为键调 ingest_raw 覆盖重放。

平台 DB 是唯一数据源，documents.content 持有全文，不依赖重新抓取外部站点。

幂等：ingest_raw 按 (version,url) 覆盖，可重跑；失败批次只告警不中断，末尾汇总。
手动执行：./dev/reembed-docs-mcp
"""

import asyncio
import logging

from sqlalchemy import select

from core.database import async_session
from models.db import Document
from services.docs_mcp_client import DocsMcpError, docs_mcp_client

logger = logging.getLogger(__name__)

INGEST_BYTE_BUDGET = 200_000  # 单批字节上限，留余量低于 docs-mcp Fastify 1MB bodyLimit
MAX_BATCH_DOCS = 3  # 单批文档数上限：embedding 慢，控量使单次 ingest_raw 在超时内
INGEST_TIMEOUT = 180.0  # 灌入超时（秒），吸收分块+向量化耗时
PROGRESS_EVERY = 50  # 每处理多少篇文档打印一次进度


async def reembed_library(library: str, version: str, docs: list[Document]) -> dict:
    """按字节预算 + 文档数双约束分批重灌单个「库+版本」，返回统计。"""
    stats = {"docs": 0, "batches": 0, "failed_batches": 0, "skipped": 0}
    batch: list[dict] = []
    batch_bytes = 0

    async def flush() -> None:
        nonlocal batch, batch_bytes
        if not batch:
            return
        try:
            await docs_mcp_client.ingest_raw(
                library, version or None, batch, timeout=INGEST_TIMEOUT
            )
            stats["batches"] += 1
        except DocsMcpError:
            stats["failed_batches"] += 1
            logger.exception(
                "ingest_raw failed: %s@%s batch of %d docs", library, version, len(batch)
            )
        batch = []
        batch_bytes = 0

    for doc in docs:
        content = doc.content or ""
        if not content.strip():
            stats["skipped"] += 1
            continue
        if batch and (
            batch_bytes + len(content) > INGEST_BYTE_BUDGET
            or len(batch) >= MAX_BATCH_DOCS
        ):
            await flush()
        batch.append(
            {
                "url": doc.ingest_url or f"aihelms://document/{doc.id}",
                "title": doc.title or "untitled",
                "contentType": "text/markdown",
                "content": content,
            }
        )
        batch_bytes += len(content)
        stats["docs"] += 1
        if stats["docs"] % PROGRESS_EVERY == 0:
            logger.info(
                "progress %s@%s: %d docs, %d batches, %d failed",
                library,
                version,
                stats["docs"],
                stats["batches"],
                stats["failed_batches"],
            )
    await flush()
    return stats


async def run_reembed() -> None:
    """遍历平台全部文档重灌到 docs-mcp。单库失败不阻断其它库。"""
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(Document).order_by(Document.library, Document.version, Document.id)
                )
            )
            .scalars()
            .all()
        )
        logger.info("待重灌文档 %d 篇", len(rows))

        groups: dict[tuple[str, str], list[Document]] = {}
        for doc in rows:
            groups.setdefault((doc.library, doc.version or ""), []).append(doc)

        total = {"docs": 0, "batches": 0, "failed_batches": 0, "skipped": 0}
        for (library, version), docs in groups.items():
            logger.info("=== %s@%s: %d 篇 ===", library, version or "-", len(docs))
            try:
                stats = await reembed_library(library, version, docs)
            except Exception:
                logger.exception("reembed library failed: %s@%s", library, version)
                continue
            for key in total:
                total[key] += stats[key]

    logger.info(
        "重灌结束：文档 %d，批次 %d，失败批次 %d，跳过（空正文）%d",
        total["docs"],
        total["batches"],
        total["failed_batches"],
        total["skipped"],
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(run_reembed())
