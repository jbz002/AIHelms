from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.v1.credentials import CreateCredentialRequest, UpdateCredentialRequest
from services.model_service import _apply_credential_to_litellm_params


def _credential(credential_values: dict | None) -> SimpleNamespace:
    return SimpleNamespace(
        credential_name="cred-1",
        credential_values=credential_values,
        credential_info={},
    )


def test_apply_credential_with_headers_copies_to_params():
    credential = _credential(
        {"api_key": "secret", "extra_headers": {"x-opencode-session": "s-001"}}
    )

    params = _apply_credential_to_litellm_params({"model": "m"}, credential)

    assert params["extra_headers"] == {"x-opencode-session": "s-001"}


def test_apply_credential_empty_headers_removes_existing_params_copy():
    credential = _credential({"api_key": "secret", "extra_headers": {}})

    params = _apply_credential_to_litellm_params(
        {"model": "m", "extra_headers": {"x-old": "1"}}, credential
    )

    assert "extra_headers" not in params


def test_apply_credential_without_headers_keeps_existing_params_copy():
    credential = _credential({"api_key": "secret"})

    params = _apply_credential_to_litellm_params(
        {"model": "m", "extra_headers": {"x-old": "1"}}, credential
    )

    assert params["extra_headers"] == {"x-old": "1"}


def test_create_credential_accepts_string_header_values():
    req = CreateCredentialRequest(
        credential_name="opencode-prod",
        credential_values={
            "api_key": "secret",
            "extra_headers": {"x-opencode-session": "test-session-001"},
        },
        provider_id=1,
    )

    assert req.credential_values["extra_headers"] == {
        "x-opencode-session": "test-session-001"
    }


def test_create_credential_rejects_non_dict_extra_headers():
    with pytest.raises(ValidationError):
        CreateCredentialRequest(
            credential_name="bad",
            credential_values={"extra_headers": "x-opencode-session"},
            provider_id=1,
        )


def test_update_credential_rejects_non_string_header_value():
    with pytest.raises(ValidationError):
        UpdateCredentialRequest(
            credential_values={"extra_headers": {"x-retry": 3}},
        )


def test_update_credential_rejects_blank_header_name():
    with pytest.raises(ValidationError):
        UpdateCredentialRequest(
            credential_values={"extra_headers": {"  ": "v"}},
        )
