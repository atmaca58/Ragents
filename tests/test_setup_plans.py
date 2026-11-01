import pytest

from ragents.setup_plans import SetupPlan, SetupPlanService
from ragents.storage import TaskStateError, TaskStore
from ragents.catalog import load_agent


def plan_data():
    return {
        "schema_version": 1,
        "connections": {"primary": {"provider": "ollama", "model": "test-model"}},
        "agents": [{"id": "analist", "name": "Analist", "instructions": "Kaynakları doğrula.",
                    "connection": {"id": "primary"}}],
    }


def test_setup_requires_local_approval_and_applies_once(tmp_path):
    root = tmp_path / "profile"
    service = SetupPlanService(root, TaskStore(root / "data/ragents.db"))
    request = service.propose(SetupPlan.model_validate(plan_data()))
    with pytest.raises(TaskStateError, match="onay"):
        service.apply(request.id)
    service.approve_local(request.id, request.operation_hash)
    first = service.apply(request.id)
    assert service.apply(request.id) == first
    assert load_agent(root, "analist").profile.connection == "primary"
    assert service.get(request.id).status == "applied"


def test_changed_catalog_invalidates_seen_approval(tmp_path):
    root = tmp_path / "profile"
    service = SetupPlanService(root, TaskStore(root / "data/ragents.db"))
    request = service.propose(SetupPlan.model_validate(plan_data()))
    directory = root / "connections"
    directory.mkdir()
    (directory / "catalog.json").write_text("{}", encoding="utf-8")
    with pytest.raises(TaskStateError, match="Profil değişti"):
        service.approve_local(request.id, request.operation_hash)


def test_protected_workspace_rejected_before_any_write(tmp_path):
    root = tmp_path / "profile"
    service = SetupPlanService(root, TaskStore(root / "data/ragents.db"))
    data = plan_data()
    data["agents"][0]["workspace"] = str(root / "auth" / "unsafe")
    with pytest.raises(TaskStateError, match="kimlik dizinini"):
        service.propose(SetupPlan.model_validate(data))
    assert not (root / "auth").exists()


def test_new_agents_use_catalog_connections_but_tasks_freeze_selected_model(tmp_path):
    from ragents.connection_catalog import ConnectionCatalog
    from ragents.catalog import enqueue_agent_task
    from ragents.config import ConnectionSpec
    store = TaskStore(tmp_path / "data/ragents.db")
    plans = SetupPlanService(tmp_path, store)
    request = plans.propose(SetupPlan.model_validate(plan_data()))
    plans.approve_local(request.id, request.operation_hash)
    plans.apply(request.id)
    first = enqueue_agent_task(store, tmp_path, "analist", "Birinci iş")
    ConnectionCatalog(tmp_path).put("primary", ConnectionSpec(provider="ollama", model="new-model"))
    second = enqueue_agent_task(store, tmp_path, "analist", "İkinci iş")
    assert store.definition(first.id).config.connections["primary"].model == "test-model"
    assert store.definition(second.id).config.connections["primary"].model == "new-model"


def test_interrupted_application_keeps_agents_unavailable_until_resumed(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "data/ragents.db")
    plans = SetupPlanService(tmp_path, store)
    request = plans.propose(SetupPlan.model_validate(plan_data()))
    plans.approve_local(request.id, request.operation_hash)
    mark = plans._mark_applied
    def interrupted(request):
        raise OSError("simulated crash")
    monkeypatch.setattr(plans, "_mark_applied", interrupted)
    with pytest.raises(OSError):
        plans.apply(request.id)
    with pytest.raises(TaskStateError, match="tamamlanmadı"):
        load_agent(tmp_path, "analist")
    monkeypatch.setattr(plans, "_mark_applied", mark)
    plans.apply(request.id)
    assert load_agent(tmp_path, "analist").profile.status == "active"
