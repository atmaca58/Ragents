import asyncio
import json

import httpx2
import pytest
from pydantic_ai import models
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai_chatgpt import OpenAIChatGPTCredentials, OpenAIChatGPTProvider

from ragents.contracts import RunRequest
from ragents.engines.native import NativeEngine


def test_chatgpt_uses_responses_dialect_and_does_not_fallback_on_denial(agent_spec, monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer test-access"
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["store"] is False
        assert "max_output_tokens" not in body
        return httpx2.Response(403, json={"detail": "Plan erişimi yok"})

    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            provider = OpenAIChatGPTProvider(
                credentials=OpenAIChatGPTCredentials(
                    client_id="test-client", access_token="test-access", refresh_token="test-refresh",
                    scope="chatgpt.tokens.use.direct",
                ), http_client=client,
            )
            provider.client.max_retries = 0
            async with provider.client:
                model = OpenAIResponsesModel("gpt-5.4", provider=provider)
                engine = NativeEngine(model, request_token_cap=False)
                await engine.run(RunRequest(agent=agent_spec, prompt="Merhaba"))

    # Yalnız bu testte, tamamı bellek içi MockTransport olan sağlayıcı açılır.
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    with pytest.raises(ModelHTTPError) as failure:
        asyncio.run(run())
    assert failure.value.status_code == 403
    assert len(requests) == 1
