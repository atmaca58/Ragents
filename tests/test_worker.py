import asyncio
from pathlib import Path
import pytest

from ragents.config import load_config
from ragents.contracts import RunResult, Usage
from ragents.storage import TaskStore
from ragents.task_service import TaskService


def test_worker_drains_fifo_queue_with_bounded_concurrency(tmp_path):
    from ragents.worker import Worker, WorkerOptions

    store = TaskStore(tmp_path / "queue.db")
    config = load_config(Path("examples/ollama.yaml"))
    # Ajan başına seri yürütme korunurken bağımsız ajanlar worker limitini doldurur.
    tasks = [store.enqueue(config.model_copy(update={"agent": config.agent.model_copy(
        update={"id": f"agent-{index}"})}), str(index)) for index in range(5)]
    started, active, peak = [], 0, 0

    async def runner(config, prompt, connection_id, workspace):
        nonlocal active, peak
        started.append(prompt)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return RunResult(agent_id=config.agent.id, output=prompt, usage=Usage(requests=1, tool_calls=0))

    worker = Worker(TaskService(store, runner=runner), WorkerOptions(concurrency=2, poll_seconds=0.01))
    asyncio.run(worker.run(once=True))
    assert started == [str(index) for index in range(5)]
    assert peak == 2
    assert all(store.get(task.id).status == "succeeded" for task in tasks)


def test_second_supervisor_cannot_bypass_concurrency_limit(tmp_path):
    from ragents.worker import Worker, WorkerOptions
    from ragents.storage import TaskStateError

    store = TaskStore(tmp_path / "queue.db")

    async def scenario():
        stop = asyncio.Event()
        worker = asyncio.create_task(Worker(TaskService(store), WorkerOptions(poll_seconds=0.01)).run(stop=stop))
        await asyncio.sleep(0.02)
        try:
            with pytest.raises(TaskStateError, match="zaten"):
                await Worker(TaskService(store)).run(once=True)
        finally:
            stop.set()
            await worker

    asyncio.run(scenario())


def test_continuous_worker_accepts_later_work_and_stops_cleanly(tmp_path):
    from ragents.worker import Worker, WorkerOptions

    store = TaskStore(tmp_path / "queue.db")
    config = load_config(Path("examples/ollama.yaml"))

    async def scenario():
        stop, finished = asyncio.Event(), asyncio.Event()

        async def runner(config, prompt, connection, workspace):
            finished.set()
            return RunResult(agent_id=config.agent.id, output="Tamam", usage=Usage(requests=1, tool_calls=0))

        worker = asyncio.create_task(Worker(TaskService(store, runner=runner), WorkerOptions(poll_seconds=0.01)).run(stop=stop))
        await asyncio.sleep(0.03)
        task = store.enqueue(config, "Sonradan eklenen")
        await asyncio.wait_for(finished.wait(), 1)
        stop.set()
        await asyncio.wait_for(worker, 1)
        assert store.get(task.id).status == "succeeded"

    asyncio.run(scenario())


def test_shutdown_cancels_active_work_but_preserves_waiting_work(tmp_path):
    from ragents.worker import Worker, WorkerOptions

    store = TaskStore(tmp_path / "queue.db")
    config = load_config(Path("examples/ollama.yaml"))
    first = store.enqueue(config, "İlk")
    second = store.enqueue(config, "Bekleyen")

    async def scenario():
        stop, entered = asyncio.Event(), asyncio.Event()

        async def runner(*args):
            entered.set()
            await asyncio.Event().wait()

        options = WorkerOptions(concurrency=1, poll_seconds=0.01, shutdown_seconds=0)
        worker = asyncio.create_task(Worker(TaskService(store, runner=runner), options).run(stop=stop))
        await asyncio.wait_for(entered.wait(), 1)
        stop.set()
        await asyncio.wait_for(worker, 1)

    asyncio.run(scenario())
    assert store.get(first.id).status == "cancelled"
    assert store.get(second.id).status == "queued"


def test_worker_recovers_crash_without_replaying_and_continues_after_failure(tmp_path):
    from ragents.worker import Worker, WorkerOptions

    store = TaskStore(tmp_path / "queue.db")
    config = load_config(Path("examples/ollama.yaml"))
    crashed = store.enqueue(config, "Eski")
    store.claim(crashed.id)
    failed = store.enqueue(config, "Hata")
    good = store.enqueue(config, "Yeni")
    calls = []

    async def runner(config, prompt, connection, workspace):
        calls.append(prompt)
        if prompt == "Hata":
            raise RuntimeError("private provider details")
        return RunResult(agent_id=config.agent.id, output="Tamam", usage=Usage(requests=1, tool_calls=0))

    asyncio.run(Worker(TaskService(store, runner=runner), WorkerOptions(concurrency=1, poll_seconds=0.01)).run(once=True))
    assert calls == ["Hata", "Yeni"]
    assert store.get(crashed.id).status == "interrupted"
    assert store.get(failed.id).status == "failed"
    assert store.get(good.id).status == "succeeded"
