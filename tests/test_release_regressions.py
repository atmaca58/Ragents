"""Ürün kabulünü engelleyen denetim bulgularının regresyonları."""
from pathlib import Path
from contextlib import asynccontextmanager
import json
import asyncio
import threading

import pytest
from pydantic import ValidationError

from ragents.config import ConnectionSpec
from ragents.workspace import Workspace, WorkspaceGrant
from ragents.task_service import TaskService
from ragents.contracts import RunResult, Usage
from ragents import application
from ragents.cli import main
from ragents.config import load_config
from ragents.engines.native import NativeEngine
from ragents.storage import TaskStore
from ragents.verification import VerificationPlan
from pydantic_ai.models.test import TestModel
from ragents.catalog import AgentProfile, create_agent, enqueue_agent_task
from ragents.task_markdown import export_markdown, import_markdown


@pytest.mark.parametrize("url", [
    "http://user:secret@localhost:11434/v1",
    "http://localhost:11434/v1?api_key=secret",
    "http://localhost:11434/v1#secret",
])
def test_connection_rejects_secrets_in_endpoint(url):
    with pytest.raises(ValidationError):
        ConnectionSpec(provider="ollama", model="test", base_url=url)
    assert ConnectionSpec(
        provider="ollama", model="test", base_url="http://localhost:11434/v1",
    ).base_url is not None


def test_read_file_pages_beyond_first_byte_window(tmp_path):
    source = tmp_path / "large.py"
    source.write_text("".join(f"{i:04d} " + "x" * 100 + "\n" for i in range(1000)), encoding="utf-8")
    page = Workspace(tmp_path).read_file("large.py", start_line=801, max_lines=2)
    assert page["content"].splitlines()[0].startswith("0800 ")
    assert page["end_line"] == 802


def test_cli_returns_failure_when_saved_result_fails_verification(tmp_path, monkeypatch, capsys):
    @asynccontextmanager
    async def engine(_connection):
        yield NativeEngine(TestModel(custom_output_text="not json"))

    monkeypatch.setattr(application, "open_engine", engine)
    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "JSON üret", verification=
        VerificationPlan(checks=({"type": "structured_output", "schema": {"type": "object"}},)))
    assert main(["tasks", "--db", str(store.path), "run", task.id]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["error_code"] == "verification_failed"
    assert payload["result"]["output"] == "not json"


def test_cancel_during_snapshot_never_starts_runner(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    root = tmp_path / "workspace"
    root.mkdir()
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "Görev",
                         workspace=WorkspaceGrant(root=root))
    entered, release = threading.Event(), threading.Event()
    calls = []

    def snapshot(_workspace):
        entered.set()
        assert release.wait(5)
        return {}

    async def runner(*_args):
        calls.append("started")
        return RunResult(agent_id="ornek-ajan", output="ok", usage=Usage(requests=1, tool_calls=0))

    monkeypatch.setattr(Workspace, "snapshot", snapshot)

    async def scenario():
        execution = asyncio.create_task(TaskService(store, runner=runner).execute(task.id))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            store.request_cancel(task.id)
        finally:
            release.set()
        await asyncio.gather(execution, return_exceptions=True)
        assert calls == []
        assert store.get(task.id).status == "cancelled"

    asyncio.run(scenario())


def test_markdown_roundtrip_preserves_duplicate_titles_and_dependency_ids(tmp_path):
    root = tmp_path / "profile"
    create_agent(root, AgentProfile(schema_version=3, id="writer", name="Yazar",
                 connection="local", connections={"local": ConnectionSpec(provider="ollama", model="test")}),
                 "Kısa yanıt ver.")
    store = TaskStore(tmp_path / "tasks.db")
    first = enqueue_agent_task(store, root, "writer", "Aynı başlık\nBirinci")
    enqueue_agent_task(store, root, "writer", "Aynı başlık\nİkinci", dependencies=(first.id,))
    restored = import_markdown(TaskStore(tmp_path / "restored.db"), root, export_markdown(store))
    assert len(restored) == 2
    target = TaskStore(tmp_path / "restored.db")
    assert target.dependencies(restored[1].id) == (restored[0].id,)
    assert restored[0].title == restored[1].title
