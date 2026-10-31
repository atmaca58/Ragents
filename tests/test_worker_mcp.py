import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from ragents.config import ProjectConfig, load_config
from ragents.engines.native import NativeEngine
from ragents.storage import TaskStore
from ragents.task_service import TaskService
from ragents.worker import Worker, WorkerOptions


def test_queue_worker_native_engine_and_stdio_tool_complete_together(tmp_path, monkeypatch):
    data = load_config(Path("examples/ollama-mcp.yaml")).model_dump()
    data["mcp_servers"]["local-tools"]["command"] = sys.executable
    config = ProjectConfig.model_validate(data)
    store = TaskStore(tmp_path / "queue.db")
    task = store.enqueue(config, "kelime say")

    def respond(messages, info):
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        if not returns:
            assert [tool.name for tool in info.function_tools] == ["local-tools__text_stats"]
            return ModelResponse(parts=[ToolCallPart("local-tools__text_stats", {"text": "merhaba dünya"})])
        assert '"words": 2' in returns[-1].content
        return ModelResponse(parts=[TextPart("İki kelime.")])

    @asynccontextmanager
    async def model_connection(connection):
        yield NativeEngine(FunctionModel(respond))

    monkeypatch.setattr("ragents.application.open_engine", model_connection)
    asyncio.run(Worker(TaskService(store), WorkerOptions(poll_seconds=0.01)).run(once=True))
    assert store.get(task.id).status == "succeeded"
    run = store.runs(task.id)[0]
    result = store.result(run.id)
    assert result.output == "İki kelime."
    assert result.usage.requests == 2
    assert result.usage.tool_calls == 1
    assert result.tools.selected == 1


def test_cancelling_work_during_mcp_call_closes_connection_and_records_status(tmp_path):
    from mcp import Client
    from mcp.server.mcpserver import MCPServer
    from ragents.mcp_transport import open_gateway
    import pytest

    data = load_config(Path("examples/ollama.yaml")).model_dump()
    data["mcp_servers"] = {"tools": {"transport": "stdio", "command": "unused"}}
    data["agent"]["mcp_tools"] = [{"server": "tools", "name": "wait", "always": True}]
    config = ProjectConfig.model_validate(data)
    store = TaskStore(tmp_path / "queue.db")
    task = store.enqueue(config, "Görev")

    async def scenario():
        entered = asyncio.Event()
        server = MCPServer("slow-tool")

        @server.tool()
        async def wait() -> str:
            entered.set()
            await asyncio.Event().wait()
            return "Bitti"

        async def runner(config, prompt, connection):
            async with open_gateway(config, prompt, connector=lambda spec: Client(server)) as gateway:
                await gateway.call("tools__wait", {})

        execution = asyncio.create_task(TaskService(store, runner=runner).execute(task.id))
        await asyncio.wait_for(entered.wait(), 2)
        store.request_cancel(task.id)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(execution, 3)

    asyncio.run(scenario())
    assert store.get(task.id).status == "cancelled"
    assert store.runs(task.id)[0].error_code == "cancelled"
