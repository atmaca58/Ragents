import asyncio

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from ragents.config import AgentSpec
from ragents.contracts import ConversationTurn, RunRequest
from ragents.engines.context import ContextGuard
from ragents.engines.native import NativeEngine
from ragents.errors import ContextLimitError


def limited_agent(agent_spec, **policy):
    data = agent_spec.model_dump()
    data["context"] = policy
    return AgentSpec.model_validate(data)


def test_oversized_task_is_rejected_without_calling_model(agent_spec):
    calls = []

    def respond(messages, info):
        calls.append(True)
        return ModelResponse(parts=[TextPart("Yanıt")])

    agent = limited_agent(agent_spec, max_request_chars=256)
    with pytest.raises(ContextLimitError):
        asyncio.run(NativeEngine(FunctionModel(respond)).run(RunRequest(agent=agent, prompt="x" * 500)))
    assert calls == []


def test_history_is_reduced_to_fit_character_budget(agent_spec):
    request = RunRequest(
        agent=limited_agent(agent_spec, max_request_chars=1000), prompt="görev",
        history=(ConversationTurn(prompt="eski" * 1000, output="yanıt"),),
    )
    guard = ContextGuard(request)
    assert guard.history(request) == []
    assert guard.report().dropped_turns == 1


def test_large_tool_output_is_marked_and_call_identity_is_preserved(agent_spec):
    request = RunRequest(agent=limited_agent(agent_spec, max_tool_output_chars=64), prompt="görev")
    guard = ContextGuard(request)
    original = ModelRequest(parts=[ToolReturnPart("lookup", "x" * 200, tool_call_id="call-1")])
    bounded = guard.process([original])
    part = bounded[0].parts[0]
    assert part.tool_call_id == "call-1"
    assert len(part.content) == 64
    assert "kısaltıldı" in part.content
    assert guard.report().trimmed_tool_results == 1
    guard.process(bounded)
    assert guard.report().trimmed_tool_results == 1
    assert original.parts[0].content == "x" * 200


def test_tool_loop_growth_is_checked_before_next_model_request(agent_spec):
    calls = []

    def respond(messages, info):
        calls.append(True)
        return ModelResponse(parts=[ToolCallPart("text_stats", {"text": "x" * 2000})])

    data = agent_spec.model_dump()
    data.update(tools=["text_stats"], context={"max_request_chars": 1000})
    agent = AgentSpec.model_validate(data)
    with pytest.raises(ContextLimitError):
        asyncio.run(NativeEngine(FunctionModel(respond)).run(RunRequest(agent=agent, prompt="Say")))
    assert len(calls) == 1
