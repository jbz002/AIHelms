from services import access_test_service
from services.access_test_service import _to_anthropic_image, _to_anthropic_messages


def test_anthropic_message_string_content_passes_through() -> None:
    result = _to_anthropic_messages([{"role": "user", "content": "hi"}])
    assert result == [{"role": "user", "content": "hi"}]


def test_anthropic_message_text_block_mapped() -> None:
    result = _to_anthropic_messages(
        [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
    )
    assert result == [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]


def test_anthropic_image_data_url_converts_to_base64_source() -> None:
    block = _to_anthropic_image("data:image/png;base64,QUJD")
    assert block == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
    }


def test_anthropic_image_http_url_converts_to_url_source() -> None:
    block = _to_anthropic_image("https://example.com/a.png")
    assert block == {
        "type": "image",
        "source": {"type": "url", "url": "https://example.com/a.png"},
    }


def test_anthropic_image_url_block_in_messages_converted() -> None:
    result = _to_anthropic_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,AA=="},
                    },
                ],
            }
        ]
    )
    assert result == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": "AA==",
                    },
                },
            ],
        }
    ]


class _FakeResponse:
    def __init__(
        self, status_code: int, json_data: dict | None = None, text: str = ""
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self) -> dict:
        return self._json or {}


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.posted_url = ""
        self.posted_kwargs: dict = {}

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def post(self, url: str, **kwargs: object) -> _FakeResponse:
        self.posted_url = url
        self.posted_kwargs = kwargs
        return self._response


async def test_sync_anthropic_success_joins_text_blocks(monkeypatch) -> None:
    resp = _FakeResponse(
        200,
        json_data={
            "model": "claude-test",
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": " world"},
            ],
            "usage": {"input_tokens": 5, "output_tokens": 3},
        },
    )
    fake = _FakeAsyncClient(resp)
    monkeypatch.setattr(access_test_service.httpx, "AsyncClient", lambda **kw: fake)

    result = await access_test_service._sync_anthropic(
        "claude-test", [{"role": "user", "content": "hi"}], 100, "key"
    )

    assert result["success"] is True
    assert result["content"] == "Hello world"
    assert result["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 3,
        "total_tokens": 8,
    }
    assert "/v1/messages" in fake.posted_url
    assert fake.posted_kwargs["headers"]["x-api-key"] == "key"


async def test_sync_anthropic_non_200_returns_failure(monkeypatch) -> None:
    resp = _FakeResponse(401, text='{"error":"invalid"}')
    fake = _FakeAsyncClient(resp)
    monkeypatch.setattr(access_test_service.httpx, "AsyncClient", lambda **kw: fake)

    result = await access_test_service._sync_anthropic(
        "m", [{"role": "user", "content": "hi"}], 100, "key"
    )

    assert result["success"] is False
    assert result["error_detail"]["status_code"] == 401


async def test_model_sync_dispatches_anthropic_to_messages_endpoint(
    monkeypatch,
) -> None:
    resp = _FakeResponse(
        200,
        json_data={
            "model": "m",
            "content": [{"type": "text", "text": "ok"}],
            "usage": {},
        },
    )
    fake = _FakeAsyncClient(resp)
    monkeypatch.setattr(access_test_service.httpx, "AsyncClient", lambda **kw: fake)

    result = await access_test_service.test_model_sync(
        "m", [{"role": "user", "content": "hi"}], 100, "key", protocol="anthropic"
    )

    assert result["success"] is True
    assert result["content"] == "ok"
    assert "/v1/messages" in fake.posted_url
