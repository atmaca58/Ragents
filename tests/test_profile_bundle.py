import json
import zipfile
import pytest

from ragents.catalog import AgentProfile, create_agent, load_agent
from ragents.config import ConnectionSpec
from ragents.profile_bundle import export_profile, preview_import, import_profile
from ragents.storage import TaskStateError


def test_portable_profile_excludes_sessions_and_requires_workspace_mapping(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    create_agent(source, AgentProfile(schema_version=3, id="writer", name="Yazar", connection="local",
        connections={"local": ConnectionSpec(provider="ollama", model="test")}), "Kaynakları doğrula.")
    (source / "auth").mkdir()
    (source / "auth/token.enc").write_text("PRIVATE_TOKEN", encoding="utf-8")
    bundle = export_profile(source, tmp_path / "profile.ragents-profile")
    with zipfile.ZipFile(bundle) as archive:
        assert all(not name.startswith("auth/") for name in archive.namelist())
        assert b"PRIVATE_TOKEN" not in b"".join(archive.read(name) for name in archive.namelist())
    preview = preview_import(bundle, target, {"writer": str(target / "workspaces/writer")})
    assert preview["agents"] == ["writer"]
    assert not target.exists()
    import_profile(bundle, target, {"writer": str(target / "workspaces/writer")}, preview["operation_hash"])
    agent = load_agent(target, "writer")
    assert agent.profile.status == "disabled"
    assert agent.workspace == target / "workspaces/writer"
    with pytest.raises(TaskStateError, match="yeni"):
        import_profile(bundle, target, {"writer": str(target / "workspaces/writer")}, preview["operation_hash"])


def test_bundle_rejects_tampering_before_target_is_created(tmp_path):
    bundle = tmp_path / "bad.ragents-profile"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"schema_version": 1,
            "files": {"connections/catalog.json": "0" * 64}, "workspaces": []}))
        archive.writestr("connections/catalog.json", "{}")
    with pytest.raises(TaskStateError, match="hash"):
        preview_import(bundle, tmp_path / "target", {})
    assert not (tmp_path / "target").exists()


def test_history_import_rebases_task_workspace_and_disables_execution(tmp_path):
    from ragents.catalog import enqueue_agent_task
    from ragents.storage import TaskStore
    source, target = tmp_path / "source", tmp_path / "target"
    create_agent(source, AgentProfile(schema_version=3, id="writer", name="Yazar", connection="local",
        connections={"local": ConnectionSpec(provider="ollama", model="test")}), "Kaynakları doğrula.")
    store = TaskStore(source / "data/ragents.db")
    task = enqueue_agent_task(store, source, "writer", "Bekleyen iş")
    bundle = export_profile(source, tmp_path / "history.ragents-profile", include_history=True)
    mapping = {"writer": str(target / "workspaces/writer")}
    preview = preview_import(bundle, target, mapping)
    import_profile(bundle, target, mapping, preview["operation_hash"])
    imported = TaskStore(target / "data/ragents.db")
    assert not imported.get(task.id).enabled
    assert imported.definition(task.id).workspace.root == target / "workspaces/writer"
