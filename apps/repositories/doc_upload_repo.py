"""doc_upload_records 表的数据库操作。"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import DocUploadRecord


async def create(session: AsyncSession, record: DocUploadRecord) -> DocUploadRecord:
    session.add(record)
    await session.flush()
    await session.refresh(record)
    return record


async def find_by_id(
    session: AsyncSession, record_id: int
) -> DocUploadRecord | None:
    result = await session.execute(
        select(DocUploadRecord).where(DocUploadRecord.id == record_id)
    )
    return result.scalar_one_or_none()


async def list_by_library(
    session: AsyncSession,
    library: str,
    page: int = 1,
    page_size: int = 20,
) -> list[DocUploadRecord]:
    stmt = (
        select(DocUploadRecord)
        .where(DocUploadRecord.library == library)
        .order_by(DocUploadRecord.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_by_library(session: AsyncSession, library: str) -> int:
    stmt = select(func.count()).where(DocUploadRecord.library == library)
    result = await session.execute(stmt)
    return result.scalar_one()


async def update_status(
    session: AsyncSession,
    record_id: int,
    status: str,
    chunk_count: int = 0,
    error_message: str = "",
) -> None:
    record = await find_by_id(session, record_id)
    if record is None:
        return
    record.status = status
    record.chunk_count = chunk_count
    record.error_message = error_message
    await session.flush()
