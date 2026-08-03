from types import SimpleNamespace

import pytest

from core.config import settings
from exceptions import ValidationError
from services import model_service


def _model(**kwargs):
    """构造一个带 mode/category 属性的伪 Model 对象。"""
    return SimpleNamespace(**kwargs)


# --- _validate_mode_category ---


def test_validate_mode_audio_requires_explicit_mode() -> None:
    with pytest.raises(ValidationError):
        model_service._validate_mode_category(None, "audio")
    with pytest.raises(ValidationError):
        model_service._validate_mode_category("chat", "audio")


def test_validate_mode_audio_accepts_speech_and_transcription() -> None:
    assert model_service._validate_mode_category("audio_speech", "audio") == "audio_speech"
    assert (
        model_service._validate_mode_category("audio_transcription", "audio")
        == "audio_transcription"
    )


def test_validate_mode_image_falls_back_when_missing() -> None:
    assert model_service._validate_mode_category(None, "image") == "image_generation"


def test_validate_mode_video_falls_back_when_missing() -> None:
    assert model_service._validate_mode_category(None, "video") == "video_generation"


def test_validate_mode_chat_default() -> None:
    assert model_service._validate_mode_category(None, "chat") == "chat"


# --- _resolve_litellm_mode ---


def test_resolve_mode_prefers_explicit_mode() -> None:
    m = _model(mode="audio_transcription", category="audio")
    assert model_service._resolve_litellm_mode(m) == "audio_transcription"


def test_resolve_mode_falls_back_by_category() -> None:
    assert model_service._resolve_litellm_mode(_model(mode=None, category="image")) == "image_generation"
    assert model_service._resolve_litellm_mode(_model(mode=None, category="video")) == "video_generation"
    assert model_service._resolve_litellm_mode(_model(mode=None, category="chat")) == "chat"
    assert model_service._resolve_litellm_mode(_model(mode=None, category="unknown")) is None


# --- _convert_modal_cost_for_litellm ---


def test_convert_modal_cost_image_yuan_to_usd_per_image() -> None:
    # cost_per_call 以 ¥/张 计，折算为 USD/张
    params = model_service._convert_modal_cost_for_litellm(
        {}, mode="image_generation", cost_per_call=7.0
    )
    assert params["output_cost_per_image"] == pytest.approx(7.0 / settings.usd_to_cny_rate)


def test_convert_modal_cost_skips_audio_and_video() -> None:
    # audio/video 细粒度键不自动折算，保持平台侧 per_call 结算
    for mode in ("audio_speech", "audio_transcription", "video_generation"):
        params = model_service._convert_modal_cost_for_litellm(
            {"model": "x"}, mode=mode, cost_per_call=5.0
        )
        assert "output_cost_per_image" not in params


def test_convert_modal_cost_skips_when_no_cost_per_call() -> None:
    params = model_service._convert_modal_cost_for_litellm(
        {}, mode="image_generation", cost_per_call=None
    )
    assert "output_cost_per_image" not in params


# --- _build_sync_model_info ---


def test_build_sync_model_info_injects_mode_and_active() -> None:
    deployment = SimpleNamespace(model_info={"description": "demo"})
    model = _model(mode="image_generation", category="image")
    info = model_service._build_sync_model_info(deployment, model, active=True)
    assert info["active"] is True
    assert info["mode"] == "image_generation"
    assert info["description"] == "demo"


def test_build_sync_model_info_omits_mode_when_unresolvable() -> None:
    deployment = SimpleNamespace(model_info={})
    model = _model(mode=None, category="unknown")
    info = model_service._build_sync_model_info(deployment, model, active=False)
    assert info["active"] is False
    assert "mode" not in info
