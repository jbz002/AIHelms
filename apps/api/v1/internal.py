from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_db
from repositories import model_repo

router = APIRouter()


@router.get("/model-anthropic-map", summary="查询模型方言与能力映射")
async def get_model_anthropic_map(session: AsyncSession = Depends(get_db)):
    """供 openresty 网关拉取模型方言与能力映射。

    无鉴权：靠 docker internal 网络隔离（openresty 直连 aihelms:8000）+ nginx 公网入口
    屏蔽 ``/api/v1/internal/*``。返回每个活跃模型（含未发布，因路由按部署不按发布）的
    标志，lua 两处消费：

    - 请求阶段：has_anthropic/has_openai 决定 body.model 是否加 (Anthropic) 后缀、
      supports_vision 决定是否剥掉非视觉模型的 image block
    - /v1/models 响应阶段：supports_* 全集 + mode 注入每条模型对象（OpenAI 标准无
      能力字段，litellm 不吐，由平台侧补）
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
                    "model_id": m.model_id,
                    "has_anthropic": m.model_id in anthropic_set,
                    "has_openai": m.model_id in openai_set,
                    "mode": m.mode,
                    "supports_vision": bool(m.supports_vision),
                    "supports_function_calling": bool(m.supports_function_calling),
                    "supports_reasoning": bool(m.supports_reasoning),
                    "supports_response_schema": bool(m.supports_response_schema),
                    "supports_parallel_function_calling": bool(
                        m.supports_parallel_function_calling
                    ),
                    "supports_tool_choice": bool(m.supports_tool_choice),
                }
                for m in models
            ]
        },
    }
