from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db
from repositories import model_repo

router = APIRouter()


@router.get("/model-anthropic-map", summary="查询模型方言映射")
async def get_model_anthropic_map(session: AsyncSession = Depends(get_db)):
    """供 openresty 网关拉取模型方言映射。

    无鉴权：靠 docker internal 网络隔离（openresty 直连 aihelms:8000）+ nginx 公网入口
    屏蔽 ``/api/v1/internal/*``。返回每个活跃模型（含未发布，因路由按部署不按发布）的
    has_anthropic/has_openai 标志，lua 据此决定 body.model 是否加 (Anthropic) 后缀。
    """
    models = await model_repo.find_all_active(session, published_only=False)
    model_ids = [m.model_id for m in models]
    anthropic_set = await model_repo.find_model_ids_with_anthropic_deployments(
        session, model_ids
    )
    openai_set = await model_repo.find_model_ids_with_openai_deployments(
        session, model_ids
    )
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "models": [
                {
                    "model_id": mid,
                    "has_anthropic": mid in anthropic_set,
                    "has_openai": mid in openai_set,
                }
                for mid in model_ids
            ]
        },
    }
