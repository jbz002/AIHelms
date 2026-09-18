"""docling_client 请求参数单测：OCR 语言与图片描述按配置下发。

网络层转发（超时/失败分支）依赖真实 docling-serve，留作 dev 手动验证。
"""

from core.config import settings
from services import docling_client as docling_client_module
from services.docling_client import DoclingClient


class FakeResponse:
    status_code = 200
    text = ""

    def json(self) -> dict:
        return {"status": "success", "document": {"md_content": "# 内容"}}


class FakeClient:
    """伪 httpx.AsyncClient，记录最后一次 post 的表单字段。"""

    def __init__(self) -> None:
        self.last_data: dict = {}

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    def post(self, url: str, **kwargs: object):
        async def _post() -> FakeResponse:
            self.last_data = kwargs["data"]
            return FakeResponse()

        return _post()


def _patch_httpx(monkeypatch) -> FakeClient:
    """把 docling_client 内的 httpx.AsyncClient 替换为 FakeClient。"""
    client = FakeClient()
    monkeypatch.setattr(docling_client_module.httpx, "AsyncClient", lambda **kw: client)
    return client


async def test_convert_file_sends_picture_description_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "docling_picture_description", True)
    monkeypatch.setattr(settings, "docling_picture_description_preset", "aihelms-vl")
    monkeypatch.setattr(settings, "docling_picture_description_area_threshold", 0.02)
    client = _patch_httpx(monkeypatch)

    md = await DoclingClient().convert_file(b"x", "a.pdf")

    assert md == "# 内容"
    assert client.last_data["do_picture_description"] == "true"
    assert client.last_data["picture_description_preset"] == "aihelms-vl"
    assert client.last_data["picture_description_area_threshold"] == "0.02"


async def test_convert_file_omits_picture_description_when_disabled(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "docling_picture_description", False)
    client = _patch_httpx(monkeypatch)

    await DoclingClient().convert_file(b"x", "a.pdf")

    assert "do_picture_description" not in client.last_data
    assert "picture_description_preset" not in client.last_data
    assert "picture_description_area_threshold" not in client.last_data


async def test_convert_file_sends_ocr_preset_and_lang(monkeypatch) -> None:
    """中文识别靠请求里的 ocr_preset/ocr_lang，serve 默认落英文模型。"""
    monkeypatch.setattr(settings, "docling_ocr_preset", "easyocr")
    monkeypatch.setattr(settings, "docling_ocr_lang", "ch_sim,en")
    client = _patch_httpx(monkeypatch)

    await DoclingClient().convert_file(b"x", "a.png", content_type="image/png")

    assert client.last_data["ocr_preset"] == "easyocr"
    assert client.last_data["ocr_lang"] == ["ch_sim", "en"]


async def test_convert_file_always_sends_ocr_flag(monkeypatch) -> None:
    client = _patch_httpx(monkeypatch)

    await DoclingClient().convert_file(b"x", "a.pdf", do_ocr=False)

    assert client.last_data["do_ocr"] == "false"
    assert client.last_data["to_formats"] == "md"
