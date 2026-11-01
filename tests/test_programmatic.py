import asyncio
import json
from pathlib import Path

from ragents.config import load_config
from ragents.storage import TaskStore
from ragents.task_service import TaskService


def test_registered_programmatic_task_finishes_without_model(tmp_path):
    from ragents.programmatic import ProgrammaticJob

    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "Yerel sağlık özeti",
                         programmatic=ProgrammaticJob(handler="runtime_health"))

    async def no_model(*args):
        raise AssertionError("Programatik iş model çağırmamalı.")

    run = asyncio.run(TaskService(store, runner=no_model).execute(task.id))
    result = store.result(run.id)
    assert run.status == "succeeded"
    assert result.usage.requests == result.usage.tool_calls == 0
    assert result.usage.input_tokens is None
    assert json.loads(result.output)["handler"] == "runtime_health"
