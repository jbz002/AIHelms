from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.config import settings
from core.deps import get_current_user
from services import crawl_service

router = APIRouter(prefix="/crawl")


class CrawlRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    include_html: bool = False


@router.post("", summary="抓取网页")
async def crawl(req: CrawlRequest, _: dict = Depends(get_current_user)):
    """提交 URL，返回 Markdown（及可选 HTML）。

    仅 http/https 且公网可达的目标允许抓取。
    """
    if not settings.crawl4ai_enabled:
        raise HTTPException(status_code=403, detail="网页抓取功能未启用")
    result = await crawl_service.fetch_url(req.url, req.include_html)
    message = "抓取成功" if result["success"] else "抓取失败"
    return {"code": 200, "message": message, "data": result}
