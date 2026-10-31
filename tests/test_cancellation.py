import asyncio
from pathlib import Path

from ragents.config import load_config
from ragents.storage import TaskStore
from ragents.task_service import TaskService
import pytest


def test_cancel_queued_task_does_not_create_attempt(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "Görev")
    assert store.request_cancel(task.id).status == "cancelled"
    assert store.runs(task.id) == []


def test_other_client_can_cancel_running_task_and_cleanup_runner(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "Görev")

    async def scenario():
        entered, cleaned = asyncio.Event(), asyncio.Event()

        async def runner(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        execution = asyncio.create_task(TaskService(store, runner=runner).execute(task.id))
        await asyncio.wait_for(entered.wait(), 1)
        TaskStore(store.path).request_cancel(task.id)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(execution, 2)
        assert cleaned.is_set()

    asyncio.run(scenario())
    assert store.get(task.id).status == "cancelled"
    assert store.runs(task.id)[0].error_code == "cancelled"


def test_cancellation_committed_before_success_wins(tmp_path):
    from ragents.contracts import RunResult, Usage

    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "Görev")
    run = store.claim(task.id)
    store.request_cancel(task.id)
    finished = store.succeed(run.id, RunResult(agent_id="ornek", output="Yanıt", usage=Usage(requests=1, tool_calls=0)), 0.1)
    assert finished.status == "cancelled"
    assert store.result(run.id) is None


def test_service_timeout_covers_runner_setup_and_leaves_failure_record(tmp_path):
    from ragents.config import ProjectConfig

    data = load_config(Path("examples/ollama.yaml")).model_dump()
    data["agent"]["budget"]["timeout_seconds"] = 0.03
    config = ProjectConfig.model_validate(data)
    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue(config, "Görev")

    async def runner(*args):
        await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        asyncio.run(TaskService(store, runner=runner).execute(task.id))
    assert store.get(task.id).status == "failed"
    assert store.runs(task.id)[0].error_code == "timeout"


def test_retry_does_not_inherit_previous_attempt_cancellation(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "Görev")
    first = store.claim(task.id)
    store.request_cancel(task.id)
    store.fail(first.id, "cancelled", 0, status="cancelled")
    store.retry(task.id)
    second = store.claim(task.id)
    assert not store.cancellation_requested(second.id)


def test_cancellation_during_runner_cleanup_never_leaves_running_record(tmp_path):
    from ragents.contracts import RunResult, Usage

    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "Görev")

    async def runner(config, *_args):
        execution = asyncio.current_task()
        asyncio.get_running_loop().call_soon(execution.cancel)
        return RunResult(agent_id=config.agent.id, output="Tamam", usage=Usage(requests=1, tool_calls=0))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(TaskService(store, runner=runner).execute(task.id))
    assert store.get(task.id).status == "cancelled"
