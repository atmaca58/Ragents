import asyncio
from pathlib import Path

import pytest

from ragents.catalog import AgentProfile, create_agent, enqueue_agent_task
from ragents.config import ConnectionSpec
from ragents.contracts import RunResult, Usage
from ragents.storage import TaskStateError, TaskStore
from ragents.task_service import TaskService
from ragents.verification import VerificationPlan


def test_memory_requires_verified_source_and_explicit_approval_before_context(tmp_path):
    from ragents.memory import MemoryService

    root = tmp_path / "profile"
    create_agent(root, AgentProfile(schema_version=3, id="analist", name="Analist", connection="local",
        connections={"local": ConnectionSpec(provider="ollama", model="test")}), "Kaynakları incele.")
    store = TaskStore(root / "data" / "ragents.db")
    task = enqueue_agent_task(store, root, "analist", "SQLite incele", verification=VerificationPlan(
        checks=({"type": "structured_output", "schema": {"type": "object", "required": ["ok"]}},)))

    async def runner(*args):
        return RunResult(agent_id="analist", output='{"ok": true}', usage=Usage(requests=1, tool_calls=0))

    run = asyncio.run(TaskService(store, runner=runner).execute(task.id))
    memory = MemoryService(store)
    entry = memory.propose("analist", "SQLite WAL kullanılıyor.", run.id, ("sqlite",))
    assert memory.select("analist", "sqlite") == ()
    memory.approve(entry.id, entry.revision)
    with pytest.raises(TaskStateError, match="revizyon"):
        memory.approve(entry.id, entry.revision)
    related = enqueue_agent_task(store, root, "analist", "SQLite indekslerini incele")
    unrelated = enqueue_agent_task(store, root, "analist", "Renkleri incele")
    assert "SQLite WAL kullanılıyor." in store.definition(related.id).config.agent.instructions
    assert "SQLite WAL kullanılıyor." not in store.definition(unrelated.id).config.agent.instructions
    assert any(source.kind == "memory" for source in store.definition(related.id).instruction.sources)
    approved = memory.get(entry.id)
    revised = memory.revise(entry.id, approved.revision, "SQLite kaydı düzeltildi.")
    assert memory.select("analist", "sqlite") == ()
    assert "SQLite WAL kullanılıyor." in store.definition(related.id).config.agent.instructions
    confirmed = memory.approve(revised.id, revised.revision)
    memory.archive(confirmed.id, confirmed.revision)
    assert memory.select("analist", "sqlite") == ()


def test_memory_rejects_source_without_independent_verification(tmp_path):
    from ragents.memory import MemoryService
    from ragents.config import load_config

    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "İncele")
    run = store.claim(task.id)
    store.succeed(run.id, RunResult(agent_id=task.agent_id, output="tamam",
                                  usage=Usage(requests=1, tool_calls=0)), 0.1)
    with pytest.raises(TaskStateError, match="doğrulanmış"):
        MemoryService(store).propose(task.agent_id, "Doğrulanmamış iddia", run.id, ("iddia",))
