"""AI 接口提取任务 + 结构化接口的数据访问层。

约定（同 document_repo / ai_policies_repo）：只 flush，不 commit；commit 在 service 层。
状态字段变更由 service 直接改 ORM 属性后 commit，不走 repo 的 update 函数。
"""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import DocumentApiEndpoint, DocumentApiSpec

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
