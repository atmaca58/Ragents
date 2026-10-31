import asyncio
from functools import partial
import json

import httpx2
from openai import AsyncOpenAI
from pydantic_ai import models
import pytest

from ragents import providers
from ragents.application import run_task
from ragents.config import ConnectionSpec, ProjectConfig


@pytest.mark.parametrize("provider,path", [
    ("opencode_go", "/inference/go/openai/v1/chat/completions"),
    ("opencode_zen", "/inference/openai/v1/chat/completions"),
])
def test_application_calls_gateway_without_external_agent(provider, path, agent_spec, monkeypatch):
    seen = []

    def respond(request):
        seen.append(request)
        assert request.url.host == "opencode.ai"
        assert request.url.path == path
        assert request.headers["authorization"] == "Bearer gateway-key"
        assert json.loads(request.content)["model"] == "kimi-k3"
        return httpx2.Response(200, json={
            "id": "test-chat", "model": "kimi-k3", "object": "chat.completion", "created": 0,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Gateway yanıtı"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
        })

    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            monkeypatch.setattr(providers, "AsyncOpenAI", partial(AsyncOpenAI, http_client=client))
            config = ProjectConfig(schema_version=2, agent=agent_spec, connections={
                "local": ConnectionSpec(provider="ollama", model="unused"),
                "gateway": ConnectionSpec(provider=provider, model="kimi-k3", api_key_env="TEST_GATEWAY_KEY"),
            })
            result = await run_task(config, "Merhaba", "gateway")
            assert result.agent_id == agent_spec.id
            assert result.output == "Gateway yanıtı"
            assert result.usage.input_tokens == 4

    monkeypatch.setenv("TEST_GATEWAY_KEY", "gateway-key")
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    asyncio.run(run())
    assert len(seen) == 1
