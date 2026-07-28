"""AI 接口提取任务 + 结构化接口的数据访问层。

约定（同 document_repo / ai_policies_repo）：只 flush，不 commit；commit 在 service 层。
状态字段变更由 service 直接改 ORM 属性后 commit，不走 repo 的 update 函数。
"""

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import (
    Document,
    DocumentApiBatchJob,
    DocumentApiCategoryJob,
    DocumentApiEndpoint,
    DocumentApiSpec,
)

# ── 提取任务 ──────────────────────────────────────────────────────────────────


async def create_spec(session: AsyncSession, spec: DocumentApiSpec) -> DocumentApiSpec:
    session.add(spec)
    await session.flush()
    await session.refresh(spec)
    return spec


async def find_by_id(session: AsyncSession, spec_pk: int) -> DocumentApiSpec | None:
    result = await session.execute(
        select(DocumentApiSpec).where(DocumentApiSpec.id == spec_pk)
    )
    return result.scalar_one_or_none()


async def find_by_spec_id(
    session: AsyncSession, spec_id: str
) -> DocumentApiSpec | None:
    result = await session.execute(
        select(DocumentApiSpec).where(DocumentApiSpec.spec_id == spec_id)
    )
    return result.scalar_one_or_none()


async def find_active_by_document(
    session: AsyncSession, document_id: int
) -> DocumentApiSpec | None:
    """该文档是否有进行中的提取任务（queued/running）—— 冲突守卫。"""
    result = await session.execute(
        select(DocumentApiSpec)
        .where(
            DocumentApiSpec.document_id == document_id,
            DocumentApiSpec.status.in_(["queued", "running"]),
        )
        .order_by(DocumentApiSpec.created_at.desc(), DocumentApiSpec.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_latest_by_document(
    session: AsyncSession, document_id: int
) -> DocumentApiSpec | None:
    """该文档最近一次提取任务（任意状态）—— 前端轮询状态用。"""
    result = await session.execute(
        select(DocumentApiSpec)
        .where(DocumentApiSpec.document_id == document_id)
        .order_by(DocumentApiSpec.created_at.desc(), DocumentApiSpec.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_latest_completed_by_document(
    session: AsyncSession, document_id: int
) -> DocumentApiSpec | None:
    """该文档最近一次成功提取任务——增量比对 content_hash 用。"""
    result = await session.execute(
        select(DocumentApiSpec)
        .where(
            DocumentApiSpec.document_id == document_id,
            DocumentApiSpec.status == "completed",
        )
        .order_by(DocumentApiSpec.created_at.desc(), DocumentApiSpec.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ── 结构化接口（source of truth）──────────────────────────────────────────────


async def replace_for_document(
    session: AsyncSession, document_id: int, endpoints: list[DocumentApiEndpoint]
) -> None:
    """替换某文档的全部接口：先删旧，再插新。仅在新任务成功时调用。"""
    await session.execute(
        delete(DocumentApiEndpoint).where(
            DocumentApiEndpoint.document_id == document_id
        )
    )
    for endpoint in endpoints:
        session.add(endpoint)
    await session.flush()


async def list_by_document(
    session: AsyncSession, document_id: int
) -> list[DocumentApiEndpoint]:
    result = await session.execute(
        select(DocumentApiEndpoint)
        .where(DocumentApiEndpoint.document_id == document_id)
        .order_by(DocumentApiEndpoint.path, DocumentApiEndpoint.method)
    )
    return list(result.scalars().all())


async def count_by_document(session: AsyncSession, document_id: int) -> int:
    result = await session.execute(
        select(func.count(DocumentApiEndpoint.id)).where(
            DocumentApiEndpoint.document_id == document_id
        )
    )
    return result.scalar_one()


# ── 库级接口查询（联 Document 取 library，弱关联用 func.lower 归一）────────────


async def list_by_library(
    session: AsyncSession, library_name: str
) -> list[DocumentApiEndpoint]:
    """该库全部接口（跨文档）。按 category、path、method 排序，左侧折叠展示用。"""
    result = await session.execute(
        select(DocumentApiEndpoint)
        .join(Document, DocumentApiEndpoint.document_id == Document.id)
        .where(func.lower(Document.library) == library_name.lower())
        .order_by(
            DocumentApiEndpoint.category,
            DocumentApiEndpoint.path,
            DocumentApiEndpoint.method,
        )
    )
    return list(result.scalars().all())


async def count_by_library(session: AsyncSession, library_name: str) -> int:
    result = await session.execute(
        select(func.count(DocumentApiEndpoint.id))
        .join(Document, DocumentApiEndpoint.document_id == Document.id)
        .where(func.lower(Document.library) == library_name.lower())
    )
    return result.scalar_one()


async def bulk_update_category(
    session: AsyncSession, updates: list[tuple[int, str]]
) -> None:
    """按 endpoint id 批量回写 category（AI 分类结果）。仅 flush。"""
    for endpoint_id, category in updates:
        await session.execute(
            update(DocumentApiEndpoint)
            .where(DocumentApiEndpoint.id == endpoint_id)
            .values(category=category[:200])
        )
    await session.flush()


# ── 库级批量提取任务 ──────────────────────────────────────────────────────────


async def create_batch_job(
    session: AsyncSession, job: DocumentApiBatchJob
) -> DocumentApiBatchJob:
    session.add(job)
    await session.flush()
    await session.refresh(job)
    return job


async def find_batch_by_id(
    session: AsyncSession, job_pk: int
) -> DocumentApiBatchJob | None:
    result = await session.execute(
        select(DocumentApiBatchJob).where(DocumentApiBatchJob.id == job_pk)
    )
    return result.scalar_one_or_none()


async def find_active_batch_by_library(
    session: AsyncSession, library_name: str
) -> DocumentApiBatchJob | None:
    """该库是否有进行中的批量提取任务（queued/running）—— 冲突守卫。"""
    result = await session.execute(
        select(DocumentApiBatchJob)
        .where(
            func.lower(DocumentApiBatchJob.library) == library_name.lower(),
            DocumentApiBatchJob.status.in_(["queued", "running"]),
        )
        .order_by(DocumentApiBatchJob.created_at.desc(), DocumentApiBatchJob.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_latest_batch_by_library(
    session: AsyncSession, library_name: str
) -> DocumentApiBatchJob | None:
    """该库最近一次批量提取任务（任意状态）—— 前端轮询状态用。"""
    result = await session.execute(
        select(DocumentApiBatchJob)
        .where(func.lower(DocumentApiBatchJob.library) == library_name.lower())
        .order_by(DocumentApiBatchJob.created_at.desc(), DocumentApiBatchJob.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ── 库级 AI 分类任务 ──────────────────────────────────────────────────────────


async def create_category_job(
    session: AsyncSession, job: DocumentApiCategoryJob
) -> DocumentApiCategoryJob:
    session.add(job)
    await session.flush()
    await session.refresh(job)
    return job


async def find_category_by_id(
    session: AsyncSession, job_pk: int
) -> DocumentApiCategoryJob | None:
    result = await session.execute(
        select(DocumentApiCategoryJob).where(DocumentApiCategoryJob.id == job_pk)
    )
    return result.scalar_one_or_none()


async def find_active_category_by_library(
    session: AsyncSession, library_name: str
) -> DocumentApiCategoryJob | None:
    """该库是否有进行中的分类任务（queued/running）—— 冲突守卫。"""
    result = await session.execute(
        select(DocumentApiCategoryJob)
        .where(
            func.lower(DocumentApiCategoryJob.library) == library_name.lower(),
            DocumentApiCategoryJob.status.in_(["queued", "running"]),
        )
        .order_by(
            DocumentApiCategoryJob.created_at.desc(), DocumentApiCategoryJob.id.desc()
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_latest_category_by_library(
    session: AsyncSession, library_name: str
) -> DocumentApiCategoryJob | None:
    """该库最近一次分类任务（任意状态）—— 前端轮询状态用。"""
    result = await session.execute(
        select(DocumentApiCategoryJob)
        .where(func.lower(DocumentApiCategoryJob.library) == library_name.lower())
        .order_by(
            DocumentApiCategoryJob.created_at.desc(), DocumentApiCategoryJob.id.desc()
        )
        .limit(1)
    )
    return result.scalar_one_or_none()
