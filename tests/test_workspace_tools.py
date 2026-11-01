import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from ragents.config import AgentSpec, ProjectConfig, load_config
from ragents.contracts import RunRequest
from ragents.engines.native import NativeEngine
from ragents.storage import TaskStore
from ragents.workspace import WorkspaceGrant


def make_agent(*tools):
    return AgentSpec(
        id="arastirmaci", name="Araştırmacı", instructions="Kısa yanıt ver.",
        connection="primary", tools=tools,
    )


def test_workspace_tools_are_exposed_only_when_granted(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "rapor.md").write_text("# Rapor\nİçerik", encoding="utf-8")
    grant = WorkspaceGrant(root=workspace)
    agent = make_agent("list_files", "read_file")

    def respond(messages, info):
        returns = [part for message in messages for part in message.parts
                   if isinstance(part, ToolReturnPart)]
        if not returns:
            assert [tool.name for tool in info.function_tools] == ["list_files", "read_file"]
            return ModelResponse(parts=[ToolCallPart("read_file", {"path": "rapor.md"})])
        assert returns[-1].content["content"].startswith("# Rapor")
        return ModelResponse(parts=[TextPart("Okundu.")])

    result = asyncio.run(NativeEngine(FunctionModel(respond)).run(
        RunRequest(agent=agent, prompt="Raporu oku", workspace=grant),
    ))
    assert result.output == "Okundu."
    assert result.usage.tool_calls == 1


def test_workspace_tool_without_grant_is_rejected_before_model_call(tmp_path):
    agent = make_agent("read_file")
    with pytest.raises(ValidationError, match="workspace tanımlı"):
        RunRequest(agent=agent, prompt="Oku")

    data = load_config(Path("examples/ollama.yaml")).model_dump()
    data["agent"]["tools"] = ["read_file"]
    config = ProjectConfig.model_validate(data)
    with pytest.raises(ValidationError, match="workspace tanımlı"):
        TaskStore(tmp_path / "queue.db").enqueue(config, "Oku")


def test_workspace_tool_error_does_not_leak_outside_content(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("dışarıdaki gizli içerik", encoding="utf-8")
    agent = make_agent("read_file")

    def respond(messages, info):
        return ModelResponse(parts=[ToolCallPart("read_file", {"path": "../secret.txt"})])

    with pytest.raises(Exception) as error:
        asyncio.run(NativeEngine(FunctionModel(respond)).run(
            RunRequest(agent=agent, prompt="Gizli dosyayı oku", workspace=WorkspaceGrant(root=workspace)),
        ))
    assert "dışarıdaki gizli içerik" not in str(error.value)
