import asyncio
from pathlib import Path

from mcp import Client

from ragents.config import load_config
from ragents.storage import TaskStore


def test_v2_mcp_is_read_only_by_default_and_reads_own_queue(tmp_path):
    from ragents.mcp_server import create_server

    store = TaskStore(tmp_path / "v2.db")
    config = load_config(Path("examples/ollama.yaml"))
    task = store.enqueue(config, "Örnek")

    async def scenario():
        async with Client(create_server(store, {config.agent.id: config})) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert tools == {"list_agents", "list_tasks", "get_task", "get_result"}
            result = await client.call_tool("get_task", {"task_id": task.id})
            assert not result.is_error
            assert result.structured_content["task"]["status"] == "queued"

    asyncio.run(scenario())


def test_execute_permission_queues_once_and_cancels_without_model_call(tmp_path):
    from ragents.mcp_server import create_server

    store = TaskStore(tmp_path / "v2.db")
    config = load_config(Path("examples/ollama.yaml"))

    async def scenario():
        async with Client(create_server(store, {config.agent.id: config}, allow_execute=True)) as client:
            arguments = {"agent_id": config.agent.id, "prompt": "İş", "key": "mcp-test"}
            first = await client.call_tool("submit_task", arguments)
            assert not first.is_error
            task_id = first.structured_content["task"]["id"]
            second = await client.call_tool("submit_task", arguments)
            assert second.structured_content["task"]["id"] == task_id
            assert store.get(task_id).status == "queued"
            result = await client.call_tool("cancel_task", {"task_id": task_id})
            assert result.structured_content["task"]["status"] == "cancelled"
            assert store.runs(task_id) == []

    asyncio.run(scenario())
