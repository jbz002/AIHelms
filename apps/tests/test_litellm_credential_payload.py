from services.litellm_credential_payload import (
    impersonation_headers,
    prepare_litellm_credential_values,
)


def test_vllm_anthropic_adds_bearer_header_without_mutating_source():
    source = {"api_key": "secret", "api_base": "http://vllm.local"}

    result = prepare_litellm_credential_values(source, {"format": "anthropic"}, "vllm")

    assert result["extra_headers"] == {"authorization": "Bearer secret"}
    assert "extra_headers" not in source


def test_existing_authorization_header_is_not_overwritten_case_insensitive():
    result = prepare_litellm_credential_values(
        {
            "api_key": "secret",
            "extra_headers": {"Authorization": "Bearer custom", "x-trace": "1"},
        },
        {"format": "anthropic"},
        "vllm",
    )

    assert result["extra_headers"] == {
        "Authorization": "Bearer custom",
        "x-trace": "1",
    }


def test_non_vllm_anthropic_is_unchanged():
    result = prepare_litellm_credential_values(
        {"api_key": "secret"}, {"format": "anthropic"}, "anthropic"
    )

    assert result == {"api_key": "secret"}


def test_explicit_bearer_auth_style_injects_for_any_provider():
    result = prepare_litellm_credential_values(
        {"api_key": "secret"},
        {"format": "anthropic", "auth_style": "bearer"},
        "ollama",
    )

    assert result["extra_headers"] == {"authorization": "Bearer secret"}


def test_explicit_auth_style_overrides_vllm_default():
    result = prepare_litellm_credential_values(
        {"api_key": "secret"},
        {"format": "anthropic", "auth_style": "x-api-key"},
        "vllm",
    )

    assert result == {"api_key": "secret"}


def test_claude_code_identity_injects_fingerprint_headers():
    result = prepare_litellm_credential_values(
        {"api_key": "secret"},
        {"format": "anthropic", "client_identity": "claude_code"},
        "aggregator",
    )

    headers = result["extra_headers"]
    assert headers["user-agent"] == "claude-cli/2.1.237 (external, cli)"
    assert headers["x-app"] == "cli"


def test_user_extra_headers_win_over_impersonation():
    result = prepare_litellm_credential_values(
        {
            "api_key": "secret",
            "extra_headers": {"User-Agent": "my-custom-agent/1.0"},
        },
        {"format": "anthropic", "client_identity": "claude_code"},
        "aggregator",
    )

    headers = result["extra_headers"]
    assert headers["User-Agent"] == "my-custom-agent/1.0"
    assert headers["x-app"] == "cli"


def test_impersonation_headers_helper_no_identity_returns_copy():
    existing = {"x-trace": "1"}
    result = impersonation_headers({"client_identity": "passthrough"}, existing)

    assert result == existing
    assert result is not existing
