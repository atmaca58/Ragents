import asyncio
import pytest

from ragents.catalog import AgentProfile, create_agent
from ragents.config import ConnectionSpec
from ragents.contracts import RunResult, Usage
from ragents.storage import TaskStore
from ragents.task_service import TaskService
from ragents.teams import TeamSpec, TeamService
from ragents.worker import Worker, WorkerOptions


def team_environment(tmp_path):
    for identity in ("writer", "reviewer"):
        create_agent(tmp_path, AgentProfile(schema_version=3, id=identity, name=identity,
            connection="model", connections={"model": ConnectionSpec(provider="ollama", model="test")}),
            "Yalnız kendi görevini yap.")
    store = TaskStore(tmp_path / "data/ragents.db")
    service = TeamService(tmp_path, store)
    spec = TeamSpec.model_validate({"schema_version": 1, "id": "report-team", "name": "Rapor",
        "steps": [{"id": "write", "agent_id": "writer", "role": "producer", "prompt": "Rapor yaz."},
                  {"id": "check", "agent_id": "reviewer", "role": "verifier", "prompt": "Raporu denetle.",
                   "depends_on": ["write"], "verification": {"checks": [{"type": "structured_output", "schema": {"type": "object"}}]}}]})
    return store, service, spec


def test_team_runs_existing_queue_and_passes_predecessor_summary(tmp_path):
    store, service, spec = team_environment(tmp_path)
    parent = service.start(spec, key="report")
    prompts = []

    async def runner(config, prompt, connection, workspace):
        prompts.append(prompt)
        return RunResult(agent_id=config.agent.id, output='{"summary":"Doğrulandı"}',
                         usage=Usage(requests=1, tool_calls=0, input_tokens=10, output_tokens=10))

    asyncio.run(Worker(TaskService(store, runner=runner), WorkerOptions(poll_seconds=0.01)).run(once=True))
    result = service.get(parent["id"])
    assert result["status"] == "succeeded"
    assert result["usage"]["requests"] == 2
    assert "Doğrulandı" in prompts[1]
    assert len(store.list()) == 2
    assert service.start(spec, key="report")["id"] == parent["id"]


def test_cancelled_team_cannot_restart_child_by_retry(tmp_path):
    from ragents.storage import TaskStateError
    store, service, spec = team_environment(tmp_path)
    parent = service.start(spec, key="cancel")
    service.tick()
    child = service.get(parent["id"])["steps"]["write"]["task_id"]
    service.cancel(parent["id"])
    assert store.get(child).status == "cancelled"
    with pytest.raises(TaskStateError, match="Ekip"):
        store.retry(child)


def test_team_rejects_cycles_and_nonindependent_verifier(tmp_path):
    from pydantic import ValidationError
    _, _, spec = team_environment(tmp_path)
    payload = spec.model_dump(mode="json")
    payload["steps"][0]["depends_on"] = ["check"]
    with pytest.raises(ValidationError, match="döngü"):
        TeamSpec.model_validate(payload)
    payload["steps"][0]["depends_on"] = []
    payload["steps"][1]["agent_id"] = "writer"
    with pytest.raises(ValidationError, match="bağımsız"):
        TeamSpec.model_validate(payload)


def test_parent_reservations_release_only_measured_usage(tmp_path):
    from ragents.teams import TeamBudget
    store, service, spec = team_environment(tmp_path)
    spec = spec.model_copy(update={"budget": TeamBudget(requests=2, total_tokens=200, tool_calls=0)})
    parent = service.start(spec, key="tight")
    limits = []

    async def runner(config, prompt, connection, workspace):
        limits.append(config.agent.budget.request_limit)
        return RunResult(agent_id=config.agent.id, output='{}',
                         usage=Usage(requests=1, tool_calls=0, input_tokens=10, output_tokens=10))

    asyncio.run(Worker(TaskService(store, runner=runner), WorkerOptions(poll_seconds=0.01)).run(once=True))
    record = service.get(parent["id"])
    assert limits == [2, 1]
    assert record["status"] == "succeeded"
    assert record["usage"] == {"requests": 2, "total_tokens": 40, "tool_calls": 0}


def test_team_permissions_only_narrow_agent_capabilities(tmp_path):
    store, service, spec = team_environment(tmp_path)
    payload = spec.model_dump(mode="json")
    payload["steps"][0]["permissions"] = {"allow_network": True, "commands": ["python"], "writable_paths": ["."]}
    parent = service.start(TeamSpec.model_validate(payload), key="permissions")
    service.tick()
    child = service.get(parent["id"])["steps"]["write"]["task_id"]
    grant = store.definition(child).workspace
    assert not grant.allow_network
    assert grant.commands == ()
    assert grant.writable_paths == ()
