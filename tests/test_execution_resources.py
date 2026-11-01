import asyncio
from pathlib import Path

import pytest

from ragents.config import load_config
from ragents.contracts import RunResult, Usage
from ragents.storage import TaskStore
from ragents.task_service import TaskService
from ragents.workspace import WorkspaceGrant


@pytest.mark.parametrize("shared", ["workspace", "agent"])
def test_tasks_serialize_shared_resources_before_claim(tmp_path, shared):
    config = load_config(Path("examples/ollama.yaml"))
    left_root, right_root = tmp_path / "left", tmp_path / "right"
    left_root.mkdir()
    right_root.mkdir()
    first_store = TaskStore(tmp_path / "first.db")
    second_store = TaskStore(tmp_path / "second.db") if shared == "workspace" else first_store
    first = first_store.enqueue(config, "first", workspace=WorkspaceGrant(root=left_root))
    second = second_store.enqueue(config, "second", workspace=WorkspaceGrant(
        root=left_root if shared == "workspace" else right_root))

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def runner(_config, prompt, *_args):
            calls.append(prompt)
            if prompt == "first":
                entered.set()
                await release.wait()
            return RunResult(agent_id=config.agent.id, output="ok", usage=Usage(requests=1, tool_calls=0))

        left = asyncio.create_task(TaskService(first_store, runner=runner).execute(first.id))
        await asyncio.wait_for(entered.wait(), 3)
        right = asyncio.create_task(TaskService(second_store, runner=runner).execute(second.id))
        try:
            await asyncio.sleep(0.15)
            assert calls == ["first"]
            assert second_store.get(second.id).status == "queued"
        finally:
            release.set()
            await asyncio.gather(left, right, return_exceptions=True)
        assert calls == ["first", "second"]

    asyncio.run(scenario())


def test_worker_runs_independent_project_before_waiting_on_busy_workspace(tmp_path):
    from ragents.worker import Worker, WorkerOptions

    store = TaskStore(tmp_path / "queue.db")
    config = load_config(Path("examples/ollama.yaml"))
    first_root, other_root = tmp_path / "first", tmp_path / "other"
    first_root.mkdir()
    other_root.mkdir()
    for identity, root in (("first", first_root), ("blocked", first_root), ("other", other_root)):
        specific = config.model_copy(update={"agent": config.agent.model_copy(update={"id": identity})})
        store.enqueue(specific, identity, workspace=WorkspaceGrant(root=root))

    async def scenario():
        release, independent = asyncio.Event(), asyncio.Event()

        async def runner(config, prompt, *_args):
            if prompt == "first":
                await release.wait()
            elif prompt == "other":
                independent.set()
            return RunResult(agent_id=config.agent.id, output="ok", usage=Usage(requests=1, tool_calls=0))

        worker = asyncio.create_task(Worker(TaskService(store, runner=runner),
            WorkerOptions(concurrency=2, poll_seconds=0.01)).run(once=True))
        try:
            await asyncio.wait_for(independent.wait(), 1)
        finally:
            release.set()
            await worker

    asyncio.run(scenario())
