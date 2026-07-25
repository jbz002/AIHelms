"""用户端接入文档 API。"""

from fastapi import APIRouter, Depends, Request

from core.deps import get_current_user
from core.public_urls import resolve_litellm_public_url
from services import docs_service

router = APIRouter(prefix="/docs", tags=["docs"])


@router.get("")
async def list_docs(
    request: Request,
    _: dict = Depends(get_current_user),
):
    return {
        "code": 200,
        "message": "ok",
        "data": docs_service.list_docs(
            litellm_url_override=resolve_litellm_public_url(request)
        ),
    }


@router.get("/{slug}")
async def get_doc(
    slug: str,
    request: Request,
    _: dict = Depends(get_current_user),
):
    doc = docs_service.get_doc(
        slug,
        litellm_url_override=resolve_litellm_public_url(request),
    )
    if not doc:
        return {"code": 404, "message": "文档不存在", "data": None}
    return {"code": 200, "message": "ok", "data": doc}
