import asyncio
from pathlib import Path

import pytest

from ragents.config import load_config
from ragents.contracts import RunResult, Usage
from ragents.storage import TaskStore
from ragents.task_service import TaskService


def test_execution_persists_result_usage_and_selected_model(tmp_path):
    config = load_config(Path("examples/chatgpt-luna.yaml"))
    store = TaskStore(tmp_path / "ragents.db")
    task = store.enqueue(config, "Görev")

    async def runner(config, prompt, connection_id, workspace):
        assert prompt == "Görev"
        return RunResult(agent_id=config.agent.id, output="Sonuç", usage=Usage(
            requests=1, tool_calls=0, input_tokens=12, output_tokens=3,
        ))

    run = asyncio.run(TaskService(store, runner=runner).execute(task.id))
    reopened = TaskStore(store.path)
    assert reopened.get(task.id).status == "succeeded"
    saved = reopened.runs(task.id)[0]
    assert saved.id == run.id
    assert saved.model == "gpt-6-luna"
    assert saved.usage.input_tokens == 12
    assert saved.usage.cost_usd is None
    assert reopened.result(run.id).output == "Sonuç"


def test_failure_is_recorded_without_raw_exception_or_fabricated_usage(tmp_path):
    store = TaskStore(tmp_path / "ragents.db")
    task = store.enqueue(load_config(Path("examples/chatgpt-luna.yaml")), "Görev")

    async def runner(config, prompt, connection_id, workspace):
        raise RuntimeError("secret-key-and-provider-prompt")

    with pytest.raises(RuntimeError):
        asyncio.run(TaskService(store, runner=runner).execute(task.id))
    assert store.get(task.id).status == "failed"
    saved = store.runs(task.id)[0]
    assert saved.error_code == "execution_failed"
    assert saved.usage is None
    assert saved.duration_seconds is not None
    assert store.result(saved.id) is None
    with store.connect() as db:
        assert "secret-key-and-provider-prompt" not in str([tuple(row) for row in db.execute("SELECT * FROM runs")])


@pytest.mark.parametrize("error,status,code", [
    (asyncio.CancelledError(), "cancelled", "cancelled"),
    (TimeoutError(), "failed", "timeout"),
])
def test_timeout_and_cancellation_leave_terminal_records(tmp_path, error, status, code):
    store = TaskStore(tmp_path / "ragents.db")
    task = store.enqueue(load_config(Path("examples/chatgpt-luna.yaml")), "Görev")

    async def runner(config, prompt, connection_id, workspace):
        raise error

    with pytest.raises(type(error)):
        asyncio.run(TaskService(store, runner=runner).execute(task.id))
    assert store.get(task.id).status == status
    assert store.runs(task.id)[0].error_code == code


def test_recovery_only_marks_runs_whose_process_lock_is_free(tmp_path):
    store = TaskStore(tmp_path / "ragents.db")
    config = load_config(Path("examples/chatgpt-luna.yaml"))
    active = store.enqueue(config, "Aktif görev")
    stale = store.enqueue(config, "Kesilmiş görev")
    service = TaskService(store)
    lock = service.lock(active.id)
    with lock:
        store.claim(active.id)
        stale_run = store.claim(stale.id)
        assert service.recover() == [stale.id]
        assert store.get(active.id).status == "running"
        assert store.get(stale.id).status == "interrupted"
        assert store.run(stale_run.id).error_code == "process_interrupted"
    assert service.recover() == [active.id]


def test_retry_is_explicit_and_keeps_previous_attempt(tmp_path):
    store = TaskStore(tmp_path / "ragents.db")
    task = store.enqueue(load_config(Path("examples/chatgpt-luna.yaml")), "Görev")
    first = store.claim(task.id)
    store.fail(first.id, "timeout", 1.0)
    assert store.retry(task.id).status == "queued"
    second = store.claim(task.id)
    assert second.id != first.id
    assert len(store.runs(task.id)) == 2
    assert store.run(first.id).status == "failed"
