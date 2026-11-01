from pathlib import Path
import pytest

from ragents.artifact_store import ArtifactStore
from ragents.catalog import AgentProfile, create_agent, enqueue_agent_task
from ragents.config import ConnectionSpec
from ragents.storage import TaskStore
from ragents.workspace import ArtifactDraft


def test_artifact_snapshot_remains_identical_when_workspace_changes(tmp_path):
    record = create_agent(tmp_path, AgentProfile(schema_version=3, id="writer", name="Yazar", connection="local",
        connections={"local": ConnectionSpec(provider="ollama", model="test")}), "Rapor yaz.")
    path = record.workspace / "report.txt"
    path.write_text("Evidence", encoding="utf-8")
    import hashlib
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    store = TaskStore(tmp_path / "data/ragents.db")
    task = enqueue_agent_task(store, tmp_path, "writer", "Rapor")
    run = store.claim(task.id)
    store.record_artifacts(run.id, "writer", [ArtifactDraft("report.txt", 8, sha)])
    artifacts = ArtifactStore(tmp_path, store)
    artifacts.capture(run.id, store.definition(task.id).workspace, "unverified")
    path.write_text("Changed", encoding="utf-8")
    identity = store.artifacts(task.id)[0].id
    assert artifacts.read(identity)["content"] == "Evidence"
    assert artifacts.read(identity)["sha256"] == sha
