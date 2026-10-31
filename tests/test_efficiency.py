import asyncio

import pytest
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from ragents.config import AgentSpec
from ragents.contracts import ConversationTurn, RunRequest
from ragents.engines.native import NativeEngine


def test_reported_input_budget_is_enforced(agent_spec):
    data = agent_spec.model_dump()
    data["budget"]["input_tokens_limit"] = 10
    agent = AgentSpec.model_validate(data)

    def respond(messages, info):
        return ModelResponse(parts=[TextPart("Yanıt")], usage=RequestUsage(input_tokens=11))

    with pytest.raises(UsageLimitExceeded):
        asyncio.run(NativeEngine(FunctionModel(respond)).run(RunRequest(agent=agent, prompt="Merhaba")))


def test_oldest_complete_turns_are_dropped_before_model_call(agent_spec):
    data = agent_spec.model_dump()
    data["context"] = {"max_request_chars": 1600, "max_history_turns": 1}
    agent = AgentSpec.model_validate(data)

    def respond(messages, info):
        contents = [part.content for message in messages for part in message.parts]
        assert "eski soru" not in contents
        assert "yeni soru" in contents
        assert "yeni yanıt" in contents
        assert "asıl görev" in contents
        return ModelResponse(parts=[TextPart("Tamam")])

    result = asyncio.run(NativeEngine(FunctionModel(respond)).run(RunRequest(
        agent=agent, prompt="asıl görev", history=(
            ConversationTurn(prompt="eski soru", output="eski yanıt"),
            ConversationTurn(prompt="yeni soru", output="yeni yanıt"),
        ),
    )))
    assert result.context.dropped_turns == 1


def test_total_token_budget_includes_input_and_output(agent_spec):
    data = agent_spec.model_dump()
    data["budget"]["total_tokens_limit"] = 10
    agent = AgentSpec.model_validate(data)

    def respond(messages, info):
        return ModelResponse(parts=[TextPart("Yanıt")], usage=RequestUsage(input_tokens=6, output_tokens=5))

    with pytest.raises(UsageLimitExceeded):
        asyncio.run(NativeEngine(FunctionModel(respond)).run(RunRequest(agent=agent, prompt="Merhaba")))


def test_each_request_uses_only_remaining_output_allowance(agent_spec):
    seen_caps = []

    def respond(messages, info):
        seen_caps.append(info.model_settings["max_tokens"])
        if len(seen_caps) == 1:
            return ModelResponse(parts=[ToolCallPart("text_stats", {"text": "test"})],
                                 usage=RequestUsage(input_tokens=5, output_tokens=7))
        return ModelResponse(parts=[TextPart("Tamam")], usage=RequestUsage(input_tokens=5, output_tokens=2))

    data = agent_spec.model_dump()
    data["tools"] = ["text_stats"]
    data["budget"]["output_tokens_limit"] = 10
    agent = AgentSpec.model_validate(data)
    result = asyncio.run(NativeEngine(FunctionModel(respond)).run(RunRequest(agent=agent, prompt="Say")))
    assert seen_caps == [10, 3]
    assert result.usage.output_tokens == 9
