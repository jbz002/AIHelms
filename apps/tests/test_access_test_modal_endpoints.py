import asyncio
import base64
from types import SimpleNamespace

from api.v1 import access_test as access_test_router
from api.v1.access_test import TestAccessRequest
from repositories import model_repo
from services import access_test_service


class FakeResponse:
    """伪 httpx.Response,覆盖 status_code / content / text / headers / json()。"""

    def __init__(
        self,
        status_code: int = 200,
        json_data: dict | None = None,
        content: bytes = b"",
        text: str = "",
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.content = content
        self.text = text
        self.headers = headers or {}

    def json(self) -> dict:
        return self._json_data or {}


class FakeClient:
    """伪 httpx.AsyncClient,记录最后一次 post 的 url 与 kwargs。"""

    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.last_url: str = ""
        self.last_kwargs: dict = {}

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    def post(self, url: str, **kwargs: object):
        async def _post() -> FakeResponse:
            self.last_url = url
            self.last_kwargs = kwargs
            return self._response

        return _post()


def _patch_httpx(monkeypatch, response: FakeResponse) -> FakeClient:
    """把 access_test_service 内的 httpx.AsyncClient 替换为 FakeClient。"""
    client = FakeClient(response)
    monkeypatch.setattr(
        access_test_service.httpx, "AsyncClient", lambda **kw: client
    )
    return client


# --- test_image_generation ---


def test_image_generation_success(monkeypatch) -> None:
    response = FakeResponse(json_data={"data": [{"b64_json": "AAAA"}]})
    client = _patch_httpx(monkeypatch, response)
    result = asyncio.run(
        access_test_service.test_image_generation("dall-e-3", "a cat on the moon")
    )
    assert result["success"] is True
    assert result["b64_json"] == "AAAA"
    assert result["model"] == "dall-e-3"
    assert "/v1/images/generations" in client.last_url


def test_image_generation_no_data_returns_failure(monkeypatch) -> None:
    _patch_httpx(monkeypatch, FakeResponse(json_data={"data": []}))
    result = asyncio.run(
        access_test_service.test_image_generation("dall-e-3", "cat")
    )
    assert result["success"] is False


def test_image_generation_upstream_error_returns_failure(monkeypatch) -> None:
    _patch_httpx(
        monkeypatch, FakeResponse(status_code=403, text="forbidden")
    )
    result = asyncio.run(
        access_test_service.test_image_generation("dall-e-3", "cat")
    )
    assert result["success"] is False


# --- test_audio_speech ---


def test_audio_speech_success(monkeypatch) -> None:
    response = FakeResponse(
        content=b"\x49\x44\x33", headers={"content-type": "audio/mpeg"}
    )
    client = _patch_httpx(monkeypatch, response)
    result = asyncio.run(
        access_test_service.test_audio_speech("tts-1", "你好世界")
    )
    assert result["success"] is True
    assert result["b64_audio"] == base64.b64encode(b"\x49\x44\x33").decode("ascii")
    assert result["content_type"] == "audio/mpeg"
    assert "/v1/audio/speech" in client.last_url


def test_audio_speech_upstream_error_returns_failure(monkeypatch) -> None:
    _patch_httpx(monkeypatch, FakeResponse(status_code=500, text="boom"))
    result = asyncio.run(access_test_service.test_audio_speech("tts-1", "hi"))
    assert result["success"] is False


# --- test_audio_transcription ---


def test_audio_transcription_success_strips_data_url(monkeypatch) -> None:
    raw = b"audio-bytes-payload"
    data_url = "data:audio/mpeg;base64," + base64.b64encode(raw).decode("ascii")
    response = FakeResponse(json_data={"text": "你好"})
    client = _patch_httpx(monkeypatch, response)
    result = asyncio.run(
        access_test_service.test_audio_transcription("whisper-1", data_url)
    )
    assert result["success"] is True
    assert result["text"] == "你好"
    # data-URL 前缀已剥离并正确 base64 解码
    assert client.last_kwargs["files"]["file"][1] == raw
    assert client.last_kwargs["data"]["model"] == "whisper-1"
    assert "/v1/audio/transcriptions" in client.last_url


def test_audio_transcription_accepts_bare_base64(monkeypatch) -> None:
    raw = b"plain"
    bare = base64.b64encode(raw).decode("ascii")
    _patch_httpx(monkeypatch, FakeResponse(json_data={"text": "ok"}))
    result = asyncio.run(
        access_test_service.test_audio_transcription("whisper-1", bare)
    )
    assert result["success"] is True


def test_audio_transcription_upstream_error_returns_failure(monkeypatch) -> None:
    raw = base64.b64encode(b"x").decode("ascii")
    _patch_httpx(monkeypatch, FakeResponse(status_code=400, text="bad audio"))
    result = asyncio.run(
        access_test_service.test_audio_transcription("whisper-1", raw)
    )
    assert result["success"] is False


# --- dispatcher guard (/test 端点) ---


def test_dispatcher_guard_rejects_modal_mode(monkeypatch) -> None:
    async def fake_find(session, model_id):  # noqa: ANN001
        return SimpleNamespace(
            mode="image_generation", category="image", model_id="dall-e-3"
        )

    monkeypatch.setattr(model_repo, "find_by_model_id", fake_find)
    req = TestAccessRequest(model="dall-e-3")
    result = asyncio.run(
        access_test_router.test_access(req, None, {"id": 1, "is_admin": False})
    )
    assert result["data"]["success"] is False
    assert result["data"]["error_detail"]["category"] == "model_type_mismatch"
