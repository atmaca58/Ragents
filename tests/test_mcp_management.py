import asyncio
from pathlib import Path

from mcp import Client

from ragents.config import ProjectConfig, load_config
from ragents.mcp_server import create_server
from ragents.storage import TaskStore


def configuration():
    data = load_config(Path("examples/ollama.yaml")).model_dump()
    data["connections"]["luna"] = {"provider": "chatgpt", "model": "gpt-6-luna"}
    return ProjectConfig.model_validate(data)


def test_client_discovers_safe_connections_and_selects_task_model(tmp_path):
    config = configuration()
    store = TaskStore(tmp_path / "queue.db")

    async def scenario():
        async with Client(create_server(store, {config.agent.id: config}, allow_execute=True)) as client:
            listed = await client.call_tool("list_agents", {})
            agent = listed.structured_content["agents"][0]
            assert agent["connections"] == [
                {"id": name, "provider": value.provider, "model": value.model}
                for name, value in config.connections.items()
            ]
            submitted = await client.call_tool("submit_task", {
                "agent_id": config.agent.id, "prompt": "Kısa yanıt", "key": "selected-model",
                "connection_id": "luna",
            })
            assert not submitted.is_error
            task = submitted.structured_content["task"]
            assert task["connection_id"] == "luna"
            assert store.definition(task["id"]).connection_id == "luna"
            assert store.runs(task["id"]) == []
            invalid = await client.call_tool("submit_task", {
                "agent_id": config.agent.id, "prompt": "Görev", "key": "invalid",
                "connection_id": "unregistered",
            })
            assert invalid.is_error
            changed = await client.call_tool("submit_task", {
                "agent_id": config.agent.id, "prompt": "Kısa yanıt", "key": "selected-model",
                "connection_id": config.agent.connection,
            })
            assert changed.is_error
            assert len(store.list()) == 1

    asyncio.run(scenario())


def test_management_client_cancels_active_worker_and_has_no_result(tmp_path):
    from ragents.task_service import TaskService
    from ragents.worker import Worker, WorkerOptions

    config = configuration()
    store = TaskStore(tmp_path / "cancel.db")

    async def scenario():
        entered, cleaned, stop = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def runner(config, prompt, connection, workspace):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        async with Client(create_server(store, {config.agent.id: config}, allow_execute=True)) as client:
            response = await client.call_tool("submit_task", {
                "agent_id": config.agent.id, "prompt": "Uzun iş", "key": "cancel-active",
            })
            task_id = response.structured_content["task"]["id"]
            worker = asyncio.create_task(Worker(TaskService(store, runner=runner),
                                              WorkerOptions(poll_seconds=0.01)).run(stop=stop))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                cancelled = await client.call_tool("cancel_task", {"task_id": task_id})
                assert not cancelled.is_error
                async with asyncio.timeout(3):
                    while True:
                        state = await client.call_tool("get_task", {"task_id": task_id})
                        if state.structured_content["task"]["status"] == "cancelled":
                            break
                        await asyncio.sleep(0.01)
                assert cleaned.is_set()
                run = state.structured_content["runs"][0]
                missing = await client.call_tool("get_result", {"run_id": run["id"]})
                assert missing.is_error
            finally:
                stop.set()
                await asyncio.wait_for(worker, 3)

    asyncio.run(scenario())


def test_http_rejects_untrusted_host_and_browser_origin(tmp_path):
    import httpx2
    from ragents.mcp_http_server import management_app

    app = management_app(create_server(TaskStore(tmp_path / "guard.db"), {}))

    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as http:
                invalid_host = await http.post("http://evil.example/mcp", json={})
                assert invalid_host.status_code == 421
                invalid_origin = await http.post("http://127.0.0.1:8765/mcp", json={},
                                                 headers={"Origin": "https://evil.example"})
                assert invalid_origin.status_code == 403

    asyncio.run(scenario())


def test_http_client_submits_worker_completes_and_client_reads_result(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    import httpx2
    from mcp.client.streamable_http import streamable_http_client
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel
    from ragents.application import run_task
    from ragents.engines.native import NativeEngine
    from ragents.mcp_http_server import management_app
    from ragents.task_service import TaskService
    from ragents.worker import Worker, WorkerOptions

    config = configuration()
    store = TaskStore(tmp_path / "http.db")
    app = management_app(create_server(store, {config.agent.id: config}, allow_execute=True))
    selected = []

    @asynccontextmanager
    async def engine(connection):
        selected.append(connection.model)
        yield NativeEngine(FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart("Hazır.")])))

    monkeypatch.setattr("ragents.application.open_engine", engine)

    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as http:
                async with Client(streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http), mode="legacy") as client:
                    submitted = await client.call_tool("submit_task", {
                        "agent_id": config.agent.id, "prompt": "Yanıt ver", "key": "http-task", "connection_id": "luna",
                    })
                    assert not submitted.is_error
                    task_id = submitted.structured_content["task"]["id"]
                    pending = await client.call_tool("get_task", {"task_id": task_id})
                    assert pending.structured_content["task"]["status"] == "queued"
                    await Worker(TaskService(store, runner=run_task), WorkerOptions(poll_seconds=0.01)).run(once=True)
                    finished = await client.call_tool("get_task", {"task_id": task_id})
                    assert finished.structured_content["task"]["status"] == "succeeded"
                    run = finished.structured_content["runs"][0]
                    result = await client.call_tool("get_result", {"run_id": run["id"]})
                    assert result.structured_content["result"]["output"] == "Hazır."
                    assert result.structured_content["result"]["usage"]["requests"] == 1
                    repeated = await client.call_tool("submit_task", {
                        "agent_id": config.agent.id, "prompt": "Yanıt ver", "key": "http-task", "connection_id": "luna",
                    })
                    assert repeated.structured_content["task"]["id"] == task_id
                    assert selected == ["gpt-6-luna"]

    asyncio.run(scenario())
