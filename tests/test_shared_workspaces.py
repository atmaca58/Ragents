from ragents.setup_plans import SetupPlan, SetupPlanService
from ragents.catalog import load_agent, enqueue_agent_task
from ragents.storage import TaskStore
from ragents.execution_locks import resource_keys


def test_locally_approved_agents_can_share_exact_workspace_and_lock(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    root = tmp_path / "profile"
    store = TaskStore(root / "data/ragents.db")
    service = SetupPlanService(root, store)
    plan = SetupPlan.model_validate({"schema_version": 1,
        "connections": {"local": {"provider": "ollama", "model": "test"}},
        "shared_workspaces": {"project": str(project)},
        "agents": [{"id": identity, "name": identity, "instructions": "Kurallara uy.",
                    "connection": {"id": "local"}, "shared_workspace_id": "project"}
                   for identity in ("developer", "reviewer")]})
    request = service.propose(plan)
    service.approve_local(request.id, request.operation_hash)
    service.apply(request.id)
    first = enqueue_agent_task(store, root, "developer", "Geliştir.")
    second = enqueue_agent_task(store, root, "reviewer", "Denetle.")
    assert load_agent(root, "developer").workspace == project
    assert load_agent(root, "reviewer").workspace == project
    assert set(resource_keys(store, store.definition(first.id))) & set(resource_keys(store, store.definition(second.id)))
