from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_current_user, get_db
from models.db import Model
from repositories import model_repo
from services import access_test_service
from services.access_test_error_mapper import build_error_detail, build_failure
from services.access_test_precheck import precheck_access_test

router = APIRouter(prefix="/access-test", tags=["access-test"])

STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


class TestAccessRequest(BaseModel):
    model: str = Field(..., min_length=1, description="模型 ID（如 claude-opus-4-6）")
    messages: list[dict] = Field(
        default_factory=lambda: [{"role": "user", "content": "hi"}],
        description="消息列表",
    )
    stream: bool = Field(default=True, description="是否流式输出")
    max_tokens: int = Field(default=100, ge=1, le=4096, description="最大输出 token 数")


class TestEmbeddingRequest(BaseModel):
    model: str = Field(..., min_length=1, description="Embedding 模型 ID")
    text: str = Field(default="你好世界", description="测试文本")


class TestRerankRequest(BaseModel):
    model: str = Field(..., min_length=1, description="Rerank 模型 ID")
    query: str = Field(default="什么是人工智能？", description="查询文本")
    documents: list[str] = Field(
        default_factory=lambda: [
            "人工智能是计算机科学的一个分支",
            "今天天气很好",
            "机器学习是AI的核心技术",
        ],
        description="待排序文档列表",
    )


@router.post("/test", summary="模型连通性测试")
async def test_access(
    req: TestAccessRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # 自动判断模型类型
    model_id = req.model
    model_obj = await model_repo.find_by_model_id(session, model_id)
    if not model_obj and "/" in model_id:
        model_obj = await model_repo.find_by_model_id(session, model_id.split("/")[-1])
    category = model_obj.category if model_obj else "chat"
    test_model = model_obj.model_id if model_obj and model_obj.model_id else model_id
    if model_obj and model_obj.mode in {
        "image_generation",
        "audio_speech",
        "audio_transcription",
        "video_generation",
    }:
        return {
            "code": 200,
            "message": "模型测试完成",
            "data": build_failure(build_error_detail("model_type_mismatch")),
        }
    user_api_key, error_detail = await precheck_access_test(
        session,
        current_user["id"],
        model_obj,
        test_model,
        is_admin=current_user["is_admin"],
    )
    if error_detail:
        return _build_error_response(error_detail, category, req.stream)

    if category == "embedding":
        text = (
            req.messages[0].get("content", "你好世界") if req.messages else "你好世界"
        )
        result = await access_test_service.test_embedding(
            model=test_model,
            text=text,
            api_key=user_api_key,
        )
        return {"code": 200, "message": "Embedding 测试完成", "data": result}

    if category == "rerank":
        query = (
            req.messages[0].get("content", "什么是人工智能？")
            if req.messages
            else "什么是人工智能？"
        )
        result = await access_test_service.test_rerank(
            model=test_model,
            query=query,
            documents=[
                "人工智能是计算机科学的一个分支",
                "今天天气很好",
                "机器学习是AI的核心技术",
            ],
            api_key=user_api_key,
        )
        return {"code": 200, "message": "Rerank 测试完成", "data": result}

    if req.stream:
        return StreamingResponse(
            access_test_service.test_model_stream(
                model=test_model,
                messages=req.messages,
                max_tokens=req.max_tokens,
                api_key=user_api_key,
            ),
            media_type="text/event-stream",
            headers=STREAM_HEADERS,
        )
    result = await access_test_service.test_model_sync(
        model=test_model,
        messages=req.messages,
        max_tokens=req.max_tokens,
        api_key=user_api_key,
    )
    return {"code": 200, "message": "模型测试完成", "data": result}


def _build_error_response(
    error_detail: dict[str, object],
    category: str,
    stream: bool,
) -> dict[str, object] | StreamingResponse:
    if category == "chat" and stream:
        return StreamingResponse(
            access_test_service.test_error_stream(error_detail),
            media_type="text/event-stream",
            headers=STREAM_HEADERS,
        )
    return {
        "code": 200,
        "message": "模型测试完成",
        "data": build_failure(error_detail),
    }


async def _resolve_model(
    session: AsyncSession, model_id: str
) -> tuple[Model | None, str]:
    model_obj = await model_repo.find_by_model_id(session, model_id)
    if not model_obj and "/" in model_id:
        model_obj = await model_repo.find_by_model_id(session, model_id.split("/")[-1])
    test_model = model_obj.model_id if model_obj and model_obj.model_id else model_id
    return model_obj, test_model


@router.post("/test-embedding", summary="Embedding 测试")
async def test_embedding(
    req: TestEmbeddingRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    model_obj, test_model = await _resolve_model(session, req.model)
    user_api_key, error_detail = await precheck_access_test(
        session,
        current_user["id"],
        model_obj,
        test_model,
        is_admin=current_user["is_admin"],
    )
    if error_detail:
        return {
            "code": 200,
            "message": "Embedding 测试完成",
            "data": build_failure(error_detail),
        }
    result = await access_test_service.test_embedding(
        model=test_model,
        text=req.text,
        api_key=user_api_key,
    )
    return {"code": 200, "message": "Embedding 测试完成", "data": result}


@router.post("/test-rerank", summary="Rerank 测试")
async def test_rerank(
    req: TestRerankRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    model_obj, test_model = await _resolve_model(session, req.model)
    user_api_key, error_detail = await precheck_access_test(
        session,
        current_user["id"],
        model_obj,
        test_model,
        is_admin=current_user["is_admin"],
    )
    if error_detail:
        return {
            "code": 200,
            "message": "Rerank 测试完成",
            "data": build_failure(error_detail),
        }
    result = await access_test_service.test_rerank(
        model=test_model,
        query=req.query,
        documents=req.documents,
        api_key=user_api_key,
    )
    return {"code": 200, "message": "Rerank 测试完成", "data": result}


class TestImageGenRequest(BaseModel):
    model: str = Field(..., min_length=1, description="文生图模型 ID")
    prompt: str = Field(default="一只在月球上的猫", description="生成提示词")


class TestAudioSpeechRequest(BaseModel):
    model: str = Field(..., min_length=1, description="语音合成模型 ID")
    text: str = Field(default="你好世界", description="合成文本")


class TestAudioTranscriptionRequest(BaseModel):
    model: str = Field(..., min_length=1, description="语音识别模型 ID")
    audio_base64: str = Field(
        ...,
        min_length=1,
        description="音频 data-URL(data:audio/...;base64,...)或裸 base64",
    )


@router.post("/test-image-generation", summary="文生图测试")
async def test_image_generation(
    req: TestImageGenRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    model_obj, test_model = await _resolve_model(session, req.model)
    user_api_key, error_detail = await precheck_access_test(
        session,
        current_user["id"],
        model_obj,
        test_model,
        is_admin=current_user["is_admin"],
    )
    if error_detail:
        return {
            "code": 200,
            "message": "文生图测试完成",
            "data": build_failure(error_detail),
        }
    result = await access_test_service.test_image_generation(
        model=test_model,
        prompt=req.prompt,
        api_key=user_api_key,
    )
    return {"code": 200, "message": "文生图测试完成", "data": result}


@router.post("/test-audio-speech", summary="语音合成测试")
async def test_audio_speech(
    req: TestAudioSpeechRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    model_obj, test_model = await _resolve_model(session, req.model)
    user_api_key, error_detail = await precheck_access_test(
        session,
        current_user["id"],
        model_obj,
        test_model,
        is_admin=current_user["is_admin"],
    )
    if error_detail:
        return {
            "code": 200,
            "message": "语音合成测试完成",
            "data": build_failure(error_detail),
        }
    result = await access_test_service.test_audio_speech(
        model=test_model,
        text=req.text,
        api_key=user_api_key,
    )
    return {"code": 200, "message": "语音合成测试完成", "data": result}


@router.post("/test-audio-transcription", summary="语音识别测试")
async def test_audio_transcription(
    req: TestAudioTranscriptionRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    model_obj, test_model = await _resolve_model(session, req.model)
    user_api_key, error_detail = await precheck_access_test(
        session,
        current_user["id"],
        model_obj,
        test_model,
        is_admin=current_user["is_admin"],
    )
    if error_detail:
        return {
            "code": 200,
            "message": "语音识别测试完成",
            "data": build_failure(error_detail),
        }
    result = await access_test_service.test_audio_transcription(
        model=test_model,
        audio_base64=req.audio_base64,
        api_key=user_api_key,
    )
    return {"code": 200, "message": "语音识别测试完成", "data": result}
