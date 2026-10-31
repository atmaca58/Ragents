import asyncio

import pytest
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

from ragents.contracts import RunRequest
from ragents.engines.native import NativeEngine


def test_native_run_works_without_cli_or_network(agent_spec):
    engine = NativeEngine(TestModel(custom_output_text="Örnek yanıt"))
    result = asyncio.run(engine.run(RunRequest(agent=agent_spec, prompt="Merhaba")))
    assert result.agent_id == agent_spec.id
    assert result.output == "Örnek yanıt"
    assert result.usage.requests == 1
    assert result.usage.cost_usd is None


def test_only_explicitly_allowed_tool_can_be_called(agent_spec):
    def respond(messages, info):
        if len(messages) == 1:
            assert [tool.name for tool in info.function_tools] == ["text_stats"]
            return ModelResponse(parts=[ToolCallPart("text_stats", {"text": "merhaba dünya"})])
        assert messages[-1].parts[0].content == {"characters": 13, "words": 2}
        return ModelResponse(parts=[TextPart("Araç sonucu doğrulandı")])

    enabled = agent_spec.model_copy(update={"tools": ("text_stats",)})
    result = asyncio.run(NativeEngine(FunctionModel(respond)).run(
        RunRequest(agent=enabled, prompt="Metni say")
    ))
    assert result.usage.tool_calls == 1
    assert result.output == "Araç sonucu doğrulandı"


@pytest.mark.parametrize("limit_field,limit_value", [("request_limit", 1), ("tool_calls_limit", 0)])
def test_budget_stops_tool_loop(agent_spec, limit_field, limit_value):
    calls = []

    def respond(messages, info):
        calls.append(1)
        return ModelResponse(parts=[ToolCallPart("text_stats", {"text": "test"})])

    budget = agent_spec.budget.model_copy(update={limit_field: limit_value})
    enabled = agent_spec.model_copy(update={"tools": ("text_stats",), "budget": budget})
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(NativeEngine(FunctionModel(respond)).run(RunRequest(agent=enabled, prompt="Say")))
    assert len(calls) == 1


def test_deadline_cancels_waiting_model(agent_spec):
    stopped = []

    async def respond(messages, info):
        try:
            await asyncio.sleep(10)
            return ModelResponse(parts=[TextPart("Geç yanıt")])
        finally:
            stopped.append(True)

    budget = agent_spec.budget.model_copy(update={"timeout_seconds": 0.03})
    limited = agent_spec.model_copy(update={"budget": budget})
    with pytest.raises(TimeoutError):
        asyncio.run(NativeEngine(FunctionModel(respond)).run(RunRequest(agent=limited, prompt="Bekle")))
    assert stopped == [True]


def test_reported_output_over_budget_is_rejected(agent_spec):
    def respond(messages, info):
        return ModelResponse(parts=[TextPart("Yanıt")], usage=RequestUsage(output_tokens=100))

    budget = agent_spec.budget.model_copy(update={"output_tokens_limit": 10})
    limited = agent_spec.model_copy(update={"budget": budget})
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(NativeEngine(FunctionModel(respond)).run(RunRequest(agent=limited, prompt="Yanıtla")))
