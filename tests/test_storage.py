import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from ragents.config import load_config
from ragents.instructions import InstructionSnapshot
from ragents.storage import TaskStateError, TaskStore


def test_queued_task_survives_reopening_database(tmp_path):
    path = tmp_path / "ragents.db"
    config = load_config(Path("examples/chatgpt-luna.yaml"))
    task = TaskStore(path).enqueue(config, "Bir görev", idempotency_key="job-1")
    reopened = TaskStore(path)
    assert reopened.get(task.id).status == "queued"
    definition = reopened.definition(task.id)
    assert definition.prompt == "Bir görev"
    assert definition.config == config


def test_instruction_snapshot_is_stored_and_does_not_break_idempotency(tmp_path):
    store = TaskStore(tmp_path / "ragents.db")
    config = load_config(Path("examples/chatgpt-luna.yaml"))
    instructions = config.agent.instructions
    snapshot = InstructionSnapshot(
        revision=hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
        total_chars=len(instructions), sources=(),
    )
    first = store.enqueue(config, "Görev", idempotency_key="snapshot-key", instruction=snapshot)
    definition = store.definition(first.id)
    assert definition.instruction == snapshot
    assert store.enqueue(config, "Görev", idempotency_key="snapshot-key").id == first.id

    with pytest.raises(ValidationError, match="eşleşmiyor"):
        store.enqueue(
            config, "Görev",
            instruction=InstructionSnapshot(
                revision="0" * 64, total_chars=0, sources=(),
            ),
        )


def test_duplicate_key_reuses_task_but_rejects_different_content(tmp_path):
    store = TaskStore(tmp_path / "ragents.db")
    config = load_config(Path("examples/chatgpt-luna.yaml"))
    first = store.enqueue(config, "Görev", idempotency_key="same-key")
    assert store.enqueue(config, "Görev", idempotency_key="same-key").id == first.id
    with pytest.raises(TaskStateError):
        store.enqueue(config, "Başka görev", idempotency_key="same-key")
    assert len(store.list()) == 1


def test_concurrent_claims_create_only_one_attempt(tmp_path):
    store = TaskStore(tmp_path / "ragents.db")
    task = store.enqueue(load_config(Path("examples/chatgpt-luna.yaml")), "Görev")

    def claim():
        try:
            return store.claim(task.id).id
        except TaskStateError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(lambda _: claim(), range(2)))
    assert sum(attempt is not None for attempt in attempts) == 1
    assert len(store.runs(task.id)) == 1


def test_successful_task_cannot_be_requeued_by_retry(tmp_path):
    from ragents.contracts import RunResult, Usage

    store = TaskStore(tmp_path / "ragents.db")
    task = store.enqueue(load_config(Path("examples/chatgpt-luna.yaml")), "Görev")
    run = store.claim(task.id)
    store.succeed(run.id, RunResult(agent_id="luna", output="Tamam", usage=Usage(requests=1, tool_calls=0)), 0.1)
    with pytest.raises(TaskStateError):
        store.retry(task.id)


def test_database_schema_version_and_artifacts_table(tmp_path):
    store = TaskStore(tmp_path / "ragents.db")
    with store.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 8
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert "artifacts" in tables
    assert "verifications" in tables


def test_newer_database_schema_is_rejected(tmp_path):
    import sqlite3

    path = tmp_path / "future.db"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version=9")
    db.close()
    with pytest.raises(TaskStateError, match="daha yeni"):
        TaskStore(path)


def test_api_key_value_is_not_written_to_task_or_run_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "do-not-persist-this-key")
    store = TaskStore(tmp_path / "ragents.db")
    task = store.enqueue(load_config(Path("examples/opencode-go.yaml")), "Görev")
    store.claim(task.id)
    with store.connect() as db:
        assert "do-not-persist-this-key" not in "\n".join(db.iterdump())
