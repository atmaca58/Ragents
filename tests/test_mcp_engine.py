import asyncio

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from ragents.contracts import RunRequest
from ragents.engines.native import NativeEngine
from ragents.mcp_client import RemoteTool, ToolGateway


def test_model_receives_only_selected_schema_and_calls_gateway(agent_spec):
    tool = RemoteTool(server="office", name="search", description="Posta ara",
                      input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})
    calls = []

    async def invoke(selected, arguments):
        calls.append((selected.name, arguments))
        return "Bulunan posta"

    def respond(messages, info):
        assert [item.name for item in info.function_tools] == ["office__search"]
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart("office__search", {"query": "rapor"})])
        assert returns[-1].content == "Bulunan posta"
        return ModelResponse(parts=[TextPart("Tamam")])

    result = asyncio.run(NativeEngine(FunctionModel(respond)).run(
        RunRequest(agent=agent_spec.model_copy(update={"tools": ()}), prompt="Posta ara"),
        gateway=ToolGateway([tool], invoke),
    ))
    assert calls == [("search", {"query": "rapor"})]
    assert result.usage.tool_calls == 1
    assert result.tools.selected == 1
    assert result.tools.schema_chars == tool.schema_chars()
