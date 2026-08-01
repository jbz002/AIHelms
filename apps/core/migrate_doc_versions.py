"""一次性数据迁移：消除「无版本」桶，version='' → '1.0.0'。

背景：documents.version 历史允许留空（落 docs-mcp unversioned 桶），与新版本
管理语义冲突（新增版本留空会追加到同一无版本桶）。新版强制 X.Y.Z 必填，本脚本
把存量 '' 数据双侧搬迁到 1.0.0，并回填 document_libraries.active_version。

双层搬迁（平台 DB + docs-mcp 都改，否则版本串不一致 → 搜索落空）：
  1. 快照该库 version='' 的 documents（content 平台 DB 持有，作重灌源）
  2. ingest_raw 重灌到 1.0.0 桶（同 ingest_url，docs-mcp 按 (version,url) 建新页）
  3. remove_version(lib, '') 删旧无版本桶（best-effort，失败仅告警）
  4. 平台三表 documents/doc_upload_records/crawl_tasks version='' → '1.0.0'
  5. active_version = 该库 semver 最大值；无 semver 则 '1.0.0'

幂等：重跑找不到 version='' 行即跳过；ingest_raw 按 url 覆盖，remove 404 已捕获。
手动执行：./dev/migrate-doc-versions
"""

import asyncio
import logging

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import async_session
from models.db import CrawlTask, Document, DocumentLibrary, DocUploadRecord
from services.docs_mcp_client import DocsMcpError, docs_mcp_client
from services.docs_version import DOCS_VERSION_RE

logger = logging.getLogger(__name__)

TARGET_VERSION = "1.0.0"
INGEST_BYTE_BUDGET = 200_000  # 单批字节上限，留余量低于 docs-mcp Fastify 1MB bodyLimit
MAX_BATCH_DOCS = 3  # 单批文档数上限：embedding 慢，控量使单次 ingest_raw 在超时内
INGEST_TIMEOUT = 180.0  # 灌入超时（秒），远大于常规 30s，吸收分块+向量化耗时


def _parse_semver(version: str) -> tuple[int, ...] | None:
    """X.Y.Z(可选 v 前缀) → (major,minor,patch)；不匹配返回 None。"""
    if not DOCS_VERSION_RE.match(version):
        return None
    parts = version.lstrip("v").split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


async def _reingest_unversioned(library_name: str, docs: list[Document]) -> None:
    """把 '' 桶文档按字节预算+文档数双约束分批重灌到 1.0.0 桶。

    embedding 是慢操作，单批过大易超时；故同时限字节与条数，并放宽灌入超时。
    """
    batch: list[dict] = []
    batch_bytes = 0

    async def flush() -> None:
        nonlocal batch, batch_bytes
        if not batch:
            return
        await docs_mcp_client.ingest_raw(
            library_name, TARGET_VERSION, batch, timeout=INGEST_TIMEOUT
        )
        logger.info(
            "ingest_raw %s -> %s: %d docs", library_name, TARGET_VERSION, len(batch)
        )
        batch = []
        batch_bytes = 0

    for doc in docs:
        content = doc.content or ""
        payload = {
            "url": doc.ingest_url or f"aihelms://document/{doc.id}",
            "title": doc.title or "untitled",
            "contentType": "text/markdown",
            "content": content,
        }
        if batch and (
            batch_bytes + len(content) > INGEST_BYTE_BUDGET
            or len(batch) >= MAX_BATCH_DOCS
        ):
            await flush()
        batch.append(payload)
        batch_bytes += len(content)
    await flush()


async def _migrate_library(session: AsyncSession, library: DocumentLibrary) -> None:
    name = library.name
    name_lower = name.lower()
    # 库名大小写不敏感匹配（与 document_repo / docs-mcp 归一化一致），
    # 避免历史混用大小写（如「内部API」vs「内部api」）导致漏迁。
    rows = (
        (
            await session.execute(
                select(Document).where(
                    func.lower(Document.library) == name_lower,
                    Document.version == "",
                )
            )
        )
        .scalars()
        .all()
    )

    if rows:
        logger.info(
            "migrating %s: %d unversioned docs -> %s", name, len(rows), TARGET_VERSION
        )
        await _reingest_unversioned(name, list(rows))
        try:
            await docs_mcp_client.remove_version(name, "")
        except DocsMcpError as e:
            logger.warning("remove_version('') failed for %s: %s", name, e)

    for model in (Document, DocUploadRecord, CrawlTask):
        await session.execute(
            update(model)
            .where(func.lower(model.library) == name_lower, model.version == "")
            .values(version=TARGET_VERSION)
        )

    distinct = [
        row[0]
        for row in (
            await session.execute(
                select(Document.version)
                .where(func.lower(Document.library) == name_lower)
                .distinct()
            )
        ).all()
    ]
    semvers = [v for v in (_parse_semver(x) for x in distinct) if v]
    active = ".".join(str(p) for p in max(semvers)) if semvers else TARGET_VERSION
    library.active_version = active
    await session.flush()
    logger.info("library %s active_version=%s", name, active)


async def run_doc_version_migration() -> None:
    """遍历所有文档库执行搬迁。单库失败不阻断其它库。"""
    async with async_session() as session:
        libraries = (await session.execute(select(DocumentLibrary))).scalars().all()
        for library in libraries:
            try:
                await _migrate_library(session, library)
            except Exception:
                logger.exception("migrate library failed: %s", library.name)
        await session.commit()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(run_doc_version_migration())
