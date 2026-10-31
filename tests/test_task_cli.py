import json
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic_ai.models.test import TestModel

from ragents import application
from ragents.cli import main
from ragents.engines.native import NativeEngine
from ragents.config import load_config
from ragents.storage import TaskStore


def test_cli_can_queue_and_inspect_task_without_model_or_credentials(tmp_path, capsys):
    base = ["tasks", "--db", str(tmp_path / "ragents.db")]
    assert main([*base, "add", "--config", "examples/chatgpt-luna.yaml", "Görev"]) == 0
    task = json.loads(capsys.readouterr().out)["task"]
    assert task["status"] == "queued"
    assert main([*base, "show", task["id"]]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["task"]["id"] == task["id"]
    assert saved["runs"] == []


def test_run_persists_and_reuses_completed_idempotent_task(tmp_path, capsys, monkeypatch):
    calls = []

    @asynccontextmanager
    async def open_test_engine(connection):
        calls.append(connection.model)
        yield NativeEngine(TestModel(custom_output_text="Yerel test sonucu"))

    monkeypatch.setattr(application, "open_engine", open_test_engine)
    path = tmp_path / "ragents.db"
    args = ["run", "--db", str(path), "--key", "job-1", "--config", "examples/chatgpt-luna.yaml", "Görev"]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["cached"] is False
    assert first["result"]["output"] == "Yerel test sonucu"
    assert TaskStore(path).get(first["task_id"]).status == "succeeded"
    assert main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["cached"] is True
    assert second["run_id"] == first["run_id"]
    assert calls == ["gpt-6-luna"]


def test_queued_task_can_be_run_and_its_result_read_from_cli(tmp_path, capsys, monkeypatch):
    @asynccontextmanager
    async def open_test_engine(connection):
        yield NativeEngine(TestModel(custom_output_text="Kalıcı yanıt"))

    monkeypatch.setattr(application, "open_engine", open_test_engine)
    path = tmp_path / "ragents.db"
    base = ["tasks", "--db", str(path)]
    assert main([*base, "add", "--config", "examples/chatgpt-luna.yaml", "Görev"]) == 0
    task_id = json.loads(capsys.readouterr().out)["task"]["id"]
    assert main([*base, "list"]) == 0
    assert json.loads(capsys.readouterr().out)["tasks"][0]["id"] == task_id
    assert main([*base, "run", task_id]) == 0
    run_id = json.loads(capsys.readouterr().out)["run_id"]
    assert main([*base, "result", run_id]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["output"] == "Kalıcı yanıt"


def test_cli_recovers_and_requeues_without_automatically_calling_model(tmp_path, capsys):
    path = tmp_path / "ragents.db"
    store = TaskStore(path)
    task = store.enqueue(load_config(Path("examples/chatgpt-luna.yaml")), "Görev")
    store.claim(task.id)
    base = ["tasks", "--db", str(path)]
    assert main([*base, "recover"]) == 0
    assert json.loads(capsys.readouterr().out)["recovered"] == [task.id]
    assert main([*base, "retry", task.id]) == 0
    assert json.loads(capsys.readouterr().out)["task"]["status"] == "queued"
    assert len(store.runs(task.id)) == 1
