"""存储删除补偿查询 router（运维查看孤儿文件补偿记录）。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db, require_permission
from repositories import storage_deletion_compensation_repo

router = APIRouter(prefix="/storage-compensations", tags=["资源审计"])


@router.get("", summary="查询存储删除补偿记录")
async def list_storage_compensations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = Query(None, pattern=r"^(pending|done|failed)$"),
    session: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("audit_log:read")),
):
    items, total = await storage_deletion_compensation_repo.list_all(
        session, page, page_size, status
    )
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "items": [
                {
                    "id": c.id,
                    "entity_type": c.entity_type,
                    "entity_id": c.entity_id,
                    "storage_path": c.storage_path,
                    "status": c.status,
                    "retries": c.retries,
                    "last_error": c.last_error,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "completed_at": (
                        c.completed_at.isoformat() if c.completed_at else None
                    ),
                }
                for c in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }
