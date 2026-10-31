import asyncio
from contextlib import asynccontextmanager
import json

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from ragents.cli import main
from ragents.engines.native import NativeEngine
from ragents.storage import TaskStore
from ragents.task_service import TaskService
from ragents.worker import Worker, WorkerOptions


def test_generated_profile_client_can_submit_and_receive_worker_result(tmp_path, monkeypatch, capsys):
    directory = tmp_path / "profile"
    assert main(["setup", "--non-interactive", "--provider", "ollama", "--model", "test-model",
                 "--directory", str(directory)]) == 0
    capsys.readouterr()
    entry = json.loads((directory / "mcp-client.json").read_text(encoding="utf-8"))["mcpServers"]["r-agents"]
    params = StdioServerParameters(command=entry["command"], args=entry["args"])

    @asynccontextmanager
    async def engine(connection):
        assert connection.model == "test-model"
        yield NativeEngine(FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart("Profil çalışıyor.")])))

    monkeypatch.setattr("ragents.application.open_engine", engine)

    async def scenario():
        async with Client(params, mode="legacy", read_timeout_seconds=10) as client:
            agents = await client.call_tool("list_agents", {})
            assert agents.structured_content["agents"][0]["id"] == "assistant"
            submitted = await client.call_tool("submit_task", {
                "agent_id": "assistant", "prompt": "Merhaba", "key": "profile-flow",
            })
            assert not submitted.is_error
            task_id = submitted.structured_content["task"]["id"]
            store = TaskStore(directory / "data" / "ragents.db")
            await Worker(TaskService(store), WorkerOptions(poll_seconds=0.01)).run(once=True)
            state = await client.call_tool("get_task", {"task_id": task_id})
            assert state.structured_content["task"]["status"] == "succeeded"
            result = await client.call_tool("get_result", {"run_id": state.structured_content["runs"][0]["id"]})
            assert result.structured_content["result"]["output"] == "Profil çalışıyor."

    asyncio.run(scenario())
