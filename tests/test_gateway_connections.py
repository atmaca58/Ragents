import pytest
from pydantic import ValidationError

from ragents.config import ConnectionSpec
from ragents.providers import resolve_connection


@pytest.mark.parametrize("provider,endpoint", [
    ("opencode_go", "https://opencode.ai/inference/go/openai/v1"),
    ("opencode_zen", "https://opencode.ai/inference/openai/v1"),
])
def test_opencode_gateway_uses_own_explicit_key(provider, endpoint, monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", "gateway-secret")
    connection = ConnectionSpec(provider=provider, model="example-model", api_key_env="GATEWAY_KEY")
    assert resolve_connection(connection) == (endpoint, "gateway-secret")


@pytest.mark.parametrize("settings", [
    {"api_key_env": "OPENAI_API_KEY"}, {"api": "chat_completions"},
])
def test_chatgpt_cannot_be_misconfigured_as_api_key_chat_endpoint(settings):
    with pytest.raises(ValidationError):
        ConnectionSpec(provider="chatgpt", model="example-model", **settings)
