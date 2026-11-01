import asyncio

from mcp import Client

from ragents.catalog import AgentProfile, create_agent, transition_agent
from ragents.config import ConnectionSpec
from ragents.mcp_server import create_server
from ragents.storage import TaskStore


def test_mcp_setup_draft_never_has_local_approval_tool(tmp_path):
    from test_setup_plans import plan_data
    from ragents.setup_plans import SetupPlanService
    store = TaskStore(tmp_path / "data/ragents.db")

    async def scenario():
        async with Client(create_server(store, {}, root=tmp_path, allow_manage=True)) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert {"propose_setup", "get_setup", "apply_setup"} <= names
            assert "approve_setup" not in names
            result = await client.call_tool("propose_setup", {"plan": plan_data()})
            assert not result.is_error
            identity = result.structured_content["approval"]["id"]
            refused = await client.call_tool("apply_setup", {"approval_id": identity})
            assert refused.is_error
            assert SetupPlanService(tmp_path, store).get(identity).status == "pending"

    asyncio.run(scenario())


def test_mcp_discovers_catalog_and_queues_workspace_verification_without_model(tmp_path):
    root = tmp_path / "profile"
    record = create_agent(root, AgentProfile(schema_version=3, id="analist", name="Analist",
        connection="local", connections={"local": ConnectionSpec(provider="ollama", model="test")}),
        "Kaynakları göster.")
    store = TaskStore(root / "data" / "ragents.db")

    async def scenario():
        async with Client(create_server(store, {}, root=root, allow_execute=True)) as client:
            listed = await client.call_tool("list_agents", {})
            assert listed.structured_content["agents"][0]["id"] == "analist"
            result = await client.call_tool("submit_task", {
                "agent_id": "analist", "prompt": "Rapor yaz.", "key": "catalog-report",
                "verification": {"checks": [{"type": "file", "path": "report.txt"}]},
            })
            assert not result.is_error
            task = result.structured_content["task"]
            definition = store.definition(task["id"])
            assert definition.workspace.root == record.workspace
            assert definition.instruction is not None
            assert definition.verification.checks[0].path == "report.txt"
            assert store.runs(task["id"]) == []
            transition_agent(root, "analist", "disable")
            refused = await client.call_tool("submit_task", {
                "agent_id": "analist", "prompt": "İkinci", "key": "disabled-agent",
            })
            assert refused.is_error

    asyncio.run(scenario())


def test_mcp_memory_write_permission_never_grants_approval_or_execution(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")

    async def scenario():
        async with Client(create_server(store, {}, root=tmp_path, allow_write=True)) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert "propose_memory" in names
            assert "list_memory" in names
            assert names.isdisjoint({"approve_memory", "submit_task", "create_schedule", "set_schedule_enabled"})
        async with Client(create_server(store, {}, root=tmp_path, allow_execute=True)) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert "set_schedule_enabled" in names
            assert "propose_memory" not in names

    asyncio.run(scenario())


def test_mcp_can_schedule_programmatic_job_without_model(tmp_path):
    from datetime import datetime, timezone
    from pathlib import Path
    from ragents.config import load_config
    from ragents.schedules import ScheduleService
    from ragents.task_service import TaskService

    config = load_config(Path("examples/ollama.yaml"))
    store = TaskStore(tmp_path / "tasks.db")
    after = datetime(2030, 1, 1, tzinfo=timezone.utc)

    async def scenario():
        async with Client(create_server(store, {config.agent.id: config}, root=tmp_path,
                                         allow_execute=True)) as client:
            template = await client.call_tool("submit_task", {"agent_id": config.agent.id,
                "prompt": "Yerel sağlık özeti", "key": "health", "enabled": False,
                "programmatic": {"handler": "runtime_health"}})
            assert not template.is_error
            scheduled = await client.call_tool("create_schedule", {
                "template_task_id": template.structured_content["task"]["id"],
                "timing": {"at": after.isoformat()},
            })
            assert not scheduled.is_error
            ids = ScheduleService(store).tick(now=after)
            assert len(ids) == 1
            run = await TaskService(store).execute(ids[0])
            assert run.provider == "programmatic"
            assert run.usage.requests == 0
            assert store.result(run.id) is not None

    asyncio.run(scenario())
