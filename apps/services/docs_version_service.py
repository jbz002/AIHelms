"""文档库版本级删除编排。

平台 DB 先批量级联删除 + 刷新文档计数 + commit，再尽力同步 docs-mcp（外部
失败仅记日志，不回滚——平台 DB 是唯一数据源，外部为同步目标）。此顺序避免
「外部已删 + 本地回滚」的不一致窗口。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from repositories import (
    crawl_task_repo,
    crawled_page_repo,
    doc_upload_repo,
    document_api_repo,
    document_library_repo,
    document_repo,
)
from services import document_library_service
from services.docs_mcp_client import DocsMcpError, docs_mcp_client

logger = logging.getLogger(__name__)


async def delete_version(
    session: AsyncSession, library_name: str, version: str
) -> None:
    """删除整个版本：平台 DB 版本级硬删 + 刷计数 + commit，再删 docs-mcp 版本。

    specs/endpoints 跟随 documents 的 ondelete=CASCADE 自动清除。
    若删的是该库最后一个版本（docs-mcp 库消失），连带清平台库级残留
    （api_jobs + document_libraries 行），实现「删末版本即删整库」。

    latest 解析为 None（库在 docs-mcp 已空/丢失，如删空壳库）时，跳过版本级
    删除，直接清平台 DB 库级残留 + 尽力同步 docs-mcp，避免 404 阻断删除。
    """
    resolved = await docs_mcp_client.resolve_version(library_name, version)
    if resolved is None:
        await _force_cleanup_library(session, library_name)
        return
    await _cancel_active_jobs(session, library_name, resolved)
    await document_repo.delete_by_library_version(session, library_name, resolved)
    await crawled_page_repo.delete_by_library_version(session, library_name, resolved)
    await crawl_task_repo.delete_by_library_version(session, library_name, resolved)
    await doc_upload_repo.delete_by_library_version(session, library_name, resolved)
    await document_library_service.refresh_document_counts(session, library_name)
    await session.commit()
    try:
        await docs_mcp_client.remove_version(library_name, resolved)
    except DocsMcpError:
        logger.warning(
            "docs-mcp remove_version failed after DB commit",
            extra={"library": library_name, "version": resolved},
        )
    await _cleanup_library_if_empty(session, library_name)


async def _docs_mcp_library_has_versions(library_name: str) -> bool:
    """docs-mcp 中该库是否仍有版本。库不存在视为无版本。

    list_libraries 失败时返回 True（保守不触发库级清理，避免误删库行）。
    """
    try:
        libraries = await docs_mcp_client.list_libraries()
    except DocsMcpError:
        logger.warning(
            "list_libraries failed during version delete cleanup",
            extra={"library": library_name},
        )
        return True
    for lib in libraries:
        if lib.get("library") == library_name:
            return bool(lib.get("versions"))
    return False


async def _cleanup_library_if_empty(session: AsyncSession, library_name: str) -> None:
    """删版本后若 docs-mcp 该库无剩余版本，连带清平台库级残留。

    docs-mcp 中 library 是 versions 的聚合，versions 全删则 library 从 /api/libraries
    自然消失。平台 DB 同步清空：document_api_jobs（库级任务无 version 列）+ 全部
    版本级表（幂等，上方已按版本删过）+ document_libraries 行。
    """
    if await _docs_mcp_library_has_versions(library_name):
        return
    library = await document_library_repo.find_by_name(session, library_name)
    if library is None:
        return
    await document_repo.delete_by_library(session, library_name)
    await doc_upload_repo.delete_by_library(session, library_name)
    await crawled_page_repo.delete_by_library(session, library_name)
    await crawl_task_repo.delete_by_library(session, library_name)
    await document_api_repo.delete_jobs_by_library(session, library_name)
    await document_library_repo.delete_library(session, library.id)
    await session.commit()


async def _force_cleanup_library(session: AsyncSession, library_name: str) -> None:
    """库在 docs-mcp 已无可用版本时，无条件清平台 DB 库级残留 + 尽力同步 docs-mcp。

    用于「删空壳库」：latest 解析为 None，_cleanup_library_if_empty 的 docs-mcp
    版本存在性判断不再可靠（空壳可能仍带 version 桶但 0 文档），直接按平台 DB
    库名清理，再尽力删 docs-mcp 残留版本向量。
    """
    library = await document_library_repo.find_by_name(session, library_name)
    if library is None:
        return
    await document_repo.delete_by_library(session, library_name)
    await doc_upload_repo.delete_by_library(session, library_name)
    await crawled_page_repo.delete_by_library(session, library_name)
    await crawl_task_repo.delete_by_library(session, library_name)
    await document_api_repo.delete_jobs_by_library(session, library_name)
    await document_library_repo.delete_library(session, library.id)
    await session.commit()
    await document_library_service.remove_docs_mcp_library(library_name)


async def _cancel_active_jobs(
    session: AsyncSession, library_name: str, version: str
) -> None:
    """删版本前取消活跃爬取 job，避免 docs-mcp 内存留幽灵 job。

    pending/crawling/paused 任务持 live docs-mcp job；不先 cancel 则删 version 行
    后 job 失去 DB 依附成幽灵（仍占并发槽，重启才清）。ingesting 阶段 docs-mcp
    job 已结束，无需 cancel。
    """
    tasks = await crawl_task_repo.find_active_by_library_version(
        session, library_name, version
    )
    for task in tasks:
        if not task.job_id:
            continue
        try:
            await docs_mcp_client.cancel_job(task.job_id)
        except DocsMcpError:
            logger.warning(
                "delete_version: cancel job %s failed, proceed to delete",
                task.job_id,
                extra={"library": library_name, "version": version},
                exc_info=True,
            )


async def delete_version_documents(
    session: AsyncSession, library_name: str, version: str
) -> None:
    """删除版本下所有文档（保留版本记录）：与删整版本对称，清理 documents +
    crawled_pages + crawl_tasks + doc_upload_records，再清 docs-mcp 版本文档。

    crawl_tasks/upload_records 跟随删除，避免任务壳指向已删页面造成元数据漂移。

    latest 解析为 None（库在 docs-mcp 已空/丢失）时无版本文档可删，直接成功。
    """
    resolved = await docs_mcp_client.resolve_version(library_name, version)
    if resolved is None:
        return
    await document_repo.delete_by_library_version(session, library_name, resolved)
    await crawled_page_repo.delete_by_library_version(session, library_name, resolved)
    await crawl_task_repo.delete_by_library_version(session, library_name, resolved)
    await doc_upload_repo.delete_by_library_version(session, library_name, resolved)
    await document_library_service.refresh_document_counts(session, library_name)
    await session.commit()
    try:
        await docs_mcp_client.remove_version_documents(library_name, resolved)
    except DocsMcpError:
        logger.warning(
            "docs-mcp remove_version_documents failed after DB commit",
            extra={"library": library_name, "version": resolved},
        )
