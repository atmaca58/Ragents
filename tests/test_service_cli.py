import asyncio
import json
from pathlib import Path
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from ragents.cli import main
from ragents.config import load_config
from ragents.storage import TaskStore


def test_worker_command_drains_empty_temporary_queue(capsys, tmp_path):
    assert main(["worker", "--db", str(tmp_path / "empty.db"), "--once"]) == 0
    assert json.loads(capsys.readouterr().out)["worker"] == "stopped"


def test_cancel_command_persists_queued_cancellation(capsys, tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "Görev")
    assert main(["tasks", "--db", str(store.path), "cancel", task.id]) == 0
    assert json.loads(capsys.readouterr().out)["task"]["status"] == "cancelled"


def test_mcp_cli_stdio_has_clean_protocol_output_and_queues_only(tmp_path):
    database = tmp_path / "queue.db"
    params = StdioServerParameters(command=sys.executable, args=[
        "-m", "ragents", "mcp", "serve", "--db", str(database),
        "--config", str(Path("examples/ollama.yaml").resolve()), "--allow-execute",
    ])

    async def scenario():
        async with Client(params, mode="legacy", read_timeout_seconds=10) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert "submit_task" in tools
            result = await client.call_tool("submit_task", {
                "agent_id": "ornek-ajan", "prompt": "Test", "key": "stdio-test",
            })
            assert not result.is_error
            return result.structured_content["task"]["id"]

    task_id = asyncio.run(scenario())
    store = TaskStore(database)
    assert store.get(task_id).status == "queued"
    assert store.runs(task_id) == []


def test_mcp_http_cli_binds_loopback_and_keeps_execute_gate(tmp_path, monkeypatch, capsys):
    from uvicorn import Server

    observed = []

    async def serve(instance):
        observed.append(instance.config)
        app = instance.config.app
        async with app.router.lifespan_context(app):
            import httpx2
            from mcp.client.streamable_http import streamable_http_client
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as http:
                async with Client(streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http), mode="legacy") as client:
                    names = {tool.name for tool in (await client.list_tools()).tools}
                    assert "submit_task" not in names
                    assert "get_result" in names

    monkeypatch.setattr(Server, "serve", serve)
    assert main(["mcp", "serve", "--transport", "streamable-http", "--port", "8765",
                 "--db", str(tmp_path / "http.db"), "--config", "examples/ollama.yaml"]) == 0
    assert observed[0].host == "127.0.0.1"
    assert observed[0].port == 8765
    assert not capsys.readouterr().out
