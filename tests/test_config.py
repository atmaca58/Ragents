from pathlib import Path

import pytest
from pydantic import ValidationError

from ragents.config import ConnectionSpec
from ragents.config import load_config


def test_loads_example_agent_with_independent_connection():
    config = load_config(Path("examples/ollama.yaml"))
    assert config.agent.id == "ornek-ajan"
    assert config.agent.connection == "local"
    assert config.connections["local"].provider == "ollama"
    assert config.agent.budget.request_limit == 4


def test_openrouter_rejects_key_forwarding_to_custom_endpoint():
    with pytest.raises(ValidationError, match="OpenRouter"):
        ConnectionSpec(
            provider="openrouter", model="vendor/model", api_key_env="ROUTER_KEY",
            base_url="https://untrusted.example/v1",
        )
