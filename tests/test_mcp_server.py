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


def test_mcp_submit_task_freezes_structured_verification_and_rejects_workspace_checks(tmp_path):
    from ragents.mcp_server import create_server

    store = TaskStore(tmp_path / "v2.db")
    config = load_config(Path("examples/ollama.yaml"))

    async def scenario():
        async with Client(create_server(store, {config.agent.id: config}, allow_execute=True)) as client:
            result = await client.call_tool("submit_task", {
                "agent_id": config.agent.id, "prompt": "JSON üret", "key": "verify",
                "verification": {"checks": [{
                    "type": "structured_output",
                    "schema": {"type": "object", "required": ["ok"]},
                }]},
            })
            assert not result.is_error
            task_id = result.structured_content["task"]["id"]
            definition = store.definition(task_id)
            assert definition.verification is not None
            assert definition.verification.checks[0].type == "structured_output"

            state = await client.call_tool("get_task", {"task_id": task_id})
            assert state.structured_content["verifications"] == []

            rejected = await client.call_tool("submit_task", {
                "agent_id": config.agent.id, "prompt": "Dosya", "key": "verify-file",
                "verification": {"checks": [{"type": "file", "path": "x.txt"}]},
            })
            assert rejected.is_error

    asyncio.run(scenario())


def test_mcp_submit_task_accepts_priority_title_and_dependencies(tmp_path):
    from ragents.mcp_server import create_server

    store = TaskStore(tmp_path / "v2.db")
    config = load_config(Path("examples/ollama.yaml"))
    base = store.enqueue(config, "Temel görev", title="Temel")

    async def scenario():
        async with Client(create_server(store, {config.agent.id: config}, allow_execute=True)) as client:
            result = await client.call_tool("submit_task", {
                "agent_id": config.agent.id, "prompt": "Bağımlı görev", "key": "metadata",
                "title": "Rapor", "description": "Temelden sonra", "priority": 7,
                "depends_on": [base.id],
            })
            assert not result.is_error
            task = result.structured_content["task"]
            assert task["title"] == "Rapor"
            assert task["priority"] == 7
            assert task["definition_revision"] == 1
            assert store.dependencies(task["id"]) == (base.id,)
            assert store.blocked_by(task["id"]) == (base.id,)

            state = await client.call_tool("get_task", {"task_id": task["id"]})
            assert state.structured_content["task"]["title"] == "Rapor"
            assert state.structured_content["dependencies"] == [base.id]

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
