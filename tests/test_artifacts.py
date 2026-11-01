import asyncio
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ragents.cli import main
from ragents.config import load_config
from ragents.contracts import RunResult, Usage
from ragents.errors import WorkspaceError
from ragents.storage import Artifact, TaskStore
from ragents.task_service import TaskService
from ragents.workspace import WorkspaceGrant


def make_task(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = TaskStore(tmp_path / "ragents.db")
    config = load_config(Path("examples/ollama.yaml"))
    task = store.enqueue(config, "Görev", workspace=WorkspaceGrant(root=workspace))
    return store, task, config, workspace


def result(config):
    return RunResult(
        agent_id=config.agent.id, output="Sonuç", usage=Usage(requests=1, tool_calls=0),
    )


def test_successful_run_records_new_and_changed_workspace_files(tmp_path):
    store, task, config, workspace = make_task(tmp_path)
    (workspace / "eski.txt").write_text("ilk", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("gizli", encoding="utf-8")

    async def runner(config, prompt, connection, grant):
        (workspace / "yeni.txt").write_text("yeni içerik", encoding="utf-8")
        (workspace / "eski.txt").write_text("değişti", encoding="utf-8")
        try:
            (workspace / "link.txt").symlink_to(outside)
        except OSError:
            pass
        return result(config)

    run = asyncio.run(TaskService(store, runner=runner).execute(task.id))
    artifacts = store.artifacts(task.id)
    assert [artifact.path for artifact in artifacts] == ["eski.txt", "yeni.txt"]
    assert all(artifact.task_id == task.id for artifact in artifacts)
    assert all(artifact.run_id == run.id for artifact in artifacts)
    assert all(artifact.agent_id == config.agent.id for artifact in artifacts)
    assert all(artifact.producer == "workspace_scan" for artifact in artifacts)
    assert artifacts[0].sha256 == hashlib.sha256("değişti".encode("utf-8")).hexdigest()
    assert len(artifacts[1].sha256) == 64


def test_failed_run_does_not_create_artifacts(tmp_path):
    store, task, config, workspace = make_task(tmp_path)

    async def runner(config, prompt, connection, grant):
        (workspace / "yarim.txt").write_text("yarım", encoding="utf-8")
        raise RuntimeError("başarısız")

    with pytest.raises(RuntimeError):
        asyncio.run(TaskService(store, runner=runner).execute(task.id))
    assert store.artifacts(task.id) == []


def test_missing_workspace_fails_run_with_workspace_code(tmp_path):
    store, task, config, workspace = make_task(tmp_path)
    shutil.rmtree(workspace)
    with pytest.raises(WorkspaceError):
        asyncio.run(TaskService(store).execute(task.id))
    assert store.get(task.id).status == "failed"
    assert store.runs(task.id)[0].error_code == "workspace"


def test_tasks_show_and_mcp_expose_artifacts(tmp_path, capsys):
    store, task, config, workspace = make_task(tmp_path)
    (workspace / "rapor.txt").write_text("rapor", encoding="utf-8")

    async def runner(config, prompt, connection, grant):
        (workspace / "rapor.txt").write_text("yeni rapor", encoding="utf-8")
        return result(config)

    asyncio.run(TaskService(store, runner=runner).execute(task.id))
    assert main(["tasks", "--db", str(store.path), "show", task.id]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifacts"][0]["path"] == "rapor.txt"

    from mcp import Client
    from ragents.mcp_server import create_server

    async def scenario():
        async with Client(create_server(store, {config.agent.id: config})) as client:
            response = await client.call_tool("get_task", {"task_id": task.id})
            assert response.structured_content["artifacts"][0]["path"] == "rapor.txt"

    asyncio.run(scenario())


def test_artifact_migration_from_v2_and_path_validation(tmp_path):
    store, task, config, workspace = make_task(tmp_path)
    with store.connect() as db:
        db.execute("DROP TABLE artifacts")
        db.execute("PRAGMA user_version=2")
    reopened = TaskStore(store.path)
    assert reopened.artifacts(task.id) == []
    with reopened.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 8

    with pytest.raises(ValueError, match="göreli"):
        Artifact(
            id="x", task_id=task.id, run_id="run", agent_id=config.agent.id,
            path="../x", size_bytes=1, producer="workspace_scan", created_at="now",
        )
