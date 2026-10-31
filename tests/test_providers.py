import asyncio

import pytest

from ragents.config import ConnectionSpec
from ragents.providers import open_engine, resolve_connection


def test_missing_credentials_are_rejected_before_any_request(monkeypatch):
    monkeypatch.delenv("RAGENTS_TEST_KEY", raising=False)
    connection = ConnectionSpec(
        provider="openrouter", model="vendor/model", api_key_env="RAGENTS_TEST_KEY",
    )

    async def run():
        async with open_engine(connection):
            pytest.fail("Eksik anahtarla motor oluşturulmamalı")

    with pytest.raises(ValueError, match="RAGENTS_TEST_KEY"):
        asyncio.run(run())


def test_ollama_does_not_inherit_unrelated_cloud_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-secret")
    endpoint, key = resolve_connection(ConnectionSpec(provider="ollama", model="local-model"))
    assert endpoint == "http://localhost:11434/v1"
    assert key == "ollama-local"
