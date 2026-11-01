import json
import sqlite3
from pathlib import Path

import pytest

from ragents.catalog import AgentProfile, create_agent, enqueue_agent_task
from ragents.config import ConnectionSpec, load_config
from ragents.contracts import RunResult, Usage
from ragents.storage import TaskDefinition, TaskStateError, TaskStore
from ragents.task_markdown import export_markdown, import_markdown


def make_store(tmp_path) -> TaskStore:
    return TaskStore(tmp_path / "ragents.db")


def config():
    return load_config(Path("examples/ollama.yaml"))


def finish(store: TaskStore, task_id: str) -> None:
    run = store.claim(task_id)
    store.succeed(
        run.id,
        RunResult(agent_id="ornek-ajan", output="Tamam", usage=Usage(requests=1, tool_calls=0)),
        0.1,
    )


def make_agent_root(tmp_path) -> Path:
    root = tmp_path / "profile"
    create_agent(
        root,
        AgentProfile(
            schema_version=3, id="arastirmaci", name="Araştırmacı",
            connection="primary",
            connections={"primary": ConnectionSpec(provider="ollama", model="test-model")},
        ),
        "Kısa yanıt ver.",
    )
    return root


def test_priority_dependencies_enabled_and_claim_ordering(tmp_path):
    store = make_store(tmp_path)
    base = store.enqueue(config(), "Düşük öncelik", title="Düşük", priority=1)
    high = store.enqueue(config(), "Yüksek öncelik", title="Yüksek", priority=9)
    dependent = store.enqueue(
        config(), "Bağımlı", title="Bağımlı", priority=100, dependencies=(base.id,),
    )
    disabled = store.enqueue(
        config(), "Devre dışı", title="Devre dışı", priority=200, enabled=False,
    )
    assert [task.id for task in store.queued(10)] == [high.id, base.id]
    assert dependent.id not in [task.id for task in store.queued(10)]
    assert disabled.id not in [task.id for task in store.queued(10)]
    assert store.blocked_by(dependent.id) == (base.id,)
    assert not store.ready(dependent.id)

    with pytest.raises(TaskStateError, match="bağımlı olduğu"):
        store.claim(dependent.id)
    with pytest.raises(TaskStateError, match="devre dışı"):
        store.claim(disabled.id)

    finish(store, high.id)
    assert [task.id for task in store.queued(10)] == [base.id]
    finish(store, base.id)
    assert [task.id for task in store.queued(10)] == [dependent.id]
    assert store.ready(dependent.id)
    assert store.blocked_by(dependent.id) == ()


def test_dependency_cycles_self_and_missing_targets_are_rejected(tmp_path):
    store = make_store(tmp_path)
    first = store.enqueue(config(), "Birinci", title="Birinci")
    second = store.enqueue(config(), "İkinci", title="İkinci")

    with pytest.raises(TaskStateError, match="kendisine"):
        store.edit(first.id, dependencies=(first.id,))
    with pytest.raises(TaskStateError, match="bulunamadı"):
        store.edit(first.id, dependencies=("yok",))

    store.edit(first.id, dependencies=(second.id,))
    with pytest.raises(TaskStateError, match="döngü"):
        store.edit(second.id, dependencies=(first.id,))


def test_edit_increments_revision_and_preserves_previous_definition(tmp_path):
    store = make_store(tmp_path)
    task = store.enqueue(
        config(), "İlk görev metni", title="İlk başlık", description="İlk açıklama",
        priority=2,
    )
    assert task.definition_revision == 1
    assert store.revisions(task.id)[0].reason == "enqueue"

    edited = store.edit(
        task.id, title="Yeni başlık", description="Yeni açıklama", priority=7,
        prompt="Yeni görev metni",
    )
    assert edited.definition_revision == 2
    assert edited.title == "Yeni başlık"
    assert edited.priority == 7
    assert store.definition(task.id).prompt == "Yeni görev metni"
    history = store.revisions(task.id)
    assert [revision.revision for revision in history] == [1, 2]
    assert history[0].title == "İlk başlık"
    assert history[0].definition.prompt == "İlk görev metni"
    assert history[1].title == "Yeni başlık"
    assert history[1].definition.prompt == "Yeni görev metni"

    unchanged = store.edit(task.id, title="Yeni başlık")
    assert unchanged.definition_revision == 2
    assert len(store.revisions(task.id)) == 2


def test_running_succeeded_and_archived_tasks_cannot_be_edited(tmp_path):
    store = make_store(tmp_path)
    running = store.enqueue(config(), "Çalışan", title="Çalışan")
    store.claim(running.id)
    with pytest.raises(TaskStateError, match="Çalışan"):
        store.edit(running.id, title="Değişmez")

    succeeded = store.enqueue(config(), "Tamamlanan", title="Tamamlanan")
    finish(store, succeeded.id)
    with pytest.raises(TaskStateError, match="Tamamlanmış"):
        store.edit(succeeded.id, title="Değişmez")

    archived = store.enqueue(config(), "Arşiv", title="Arşiv")
    store.request_cancel(archived.id)
    store.archive(archived.id)
    with pytest.raises(TaskStateError, match="Arşivlenmiş"):
        store.edit(archived.id, title="Değişmez")


def test_archive_restore_filters_list_queue_and_retry(tmp_path):
    store = make_store(tmp_path)
    task = store.enqueue(config(), "Arşivlenecek", title="Arşivlenecek")
    with pytest.raises(TaskStateError, match="önce iptal"):
        store.archive(task.id)
    store.request_cancel(task.id)
    archived = store.archive(task.id)
    assert archived.archived_at is not None
    assert store.list(limit=10) == []
    assert [item.id for item in store.list(limit=10, archived_only=True)] == [task.id]
    assert store.list(limit=10, include_archived=True)[0].id == task.id
    assert store.queued(10) == []
    with pytest.raises(TaskStateError, match="Arşivlenmiş"):
        store.retry(task.id)
    with pytest.raises(TaskStateError, match="Arşivlenmiş"):
        store.request_cancel(task.id)

    restored = store.restore(task.id)
    assert restored.archived_at is None
    assert store.list(limit=10)[0].id == task.id
    assert store.retry(task.id).status == "queued"


def test_markdown_export_import_round_trip_with_dependencies(tmp_path):
    root = make_agent_root(tmp_path)
    first_store = make_store(tmp_path / "first")
    base = enqueue_agent_task(
        first_store, root, "arastirmaci", "Temel analizi yaz.", title="Temel",
        description="İlk adım", priority=3,
    )
    dependent = enqueue_agent_task(
        first_store, root, "arastirmaci", "Raporu temel analize dayanarak yaz.",
        title="Rapor", priority=8, dependencies=(base.id,),
    )
    markdown = export_markdown(first_store)
    assert "<!-- ragents:task:start -->" in markdown
    assert "title: Temel" in markdown
    assert f"depends_on:\n- {base.id}" in markdown
    assert "Raporu temel analize dayanarak yaz." in markdown

    second_store = make_store(tmp_path / "second")
    imported = import_markdown(second_store, root, markdown)
    assert [task.title for task in imported] == ["Temel", "Rapor"]
    assert imported[0].priority == 3
    assert second_store.dependencies(imported[1].id) == (imported[0].id,)
    assert second_store.blocked_by(imported[1].id) == (imported[0].id,)


def test_markdown_import_rejects_cycles_duplicates_and_unknown_fields(tmp_path):
    root = make_agent_root(tmp_path)
    store = make_store(tmp_path)
    cycle = """
<!-- ragents:task:start -->
---
title: A
agent: arastirmaci
depends_on: [B]
---
A metni
<!-- ragents:task:end -->
<!-- ragents:task:start -->
---
title: B
agent: arastirmaci
depends_on: [A]
---
B metni
<!-- ragents:task:end -->
"""
    with pytest.raises(TaskStateError, match="döngü"):
        import_markdown(store, root, cycle)

    duplicate = """
<!-- ragents:task:start -->
---
title: A
agent: arastirmaci
---
Birinci
<!-- ragents:task:end -->
<!-- ragents:task:start -->
---
title: A
agent: arastirmaci
---
İkinci
<!-- ragents:task:end -->
"""
    with pytest.raises(TaskStateError, match="yinelenen"):
        import_markdown(store, root, duplicate)

    unknown = """
<!-- ragents:task:start -->
---
title: A
agent: arastirmaci
bilinmeyen: değer
---
Metin
<!-- ragents:task:end -->
"""
    with pytest.raises(TaskStateError, match="geçersiz"):
        import_markdown(store, root, unknown)

    missing = """
<!-- ragents:task:start -->
---
title: A
agent: arastirmaci
depends_on: [Yok]
---
Metin
<!-- ragents:task:end -->
"""
    with pytest.raises(TaskStateError, match="Markdown içinde yok"):
        import_markdown(store, root, missing)


def test_cli_add_edit_list_show_and_archive_metadata(tmp_path, capsys):
    from ragents.cli import main

    db = tmp_path / "ragents.db"
    base = ["tasks", "--db", str(db)]
    assert main([
        *base, "add", "--config", "examples/chatgpt-luna.yaml", "--title", "İlk",
        "--description", "Açıklama", "--priority", "4", "Görev metni",
    ]) == 0
    task = json.loads(capsys.readouterr().out)["task"]
    assert task["title"] == "İlk"
    assert task["priority"] == 4

    assert main([*base, "edit", task["id"], "--title", "Düzenlendi", "--priority", "9"]) == 0
    edited = json.loads(capsys.readouterr().out)["task"]
    assert edited["title"] == "Düzenlendi"
    assert edited["definition_revision"] == 2

    assert main([*base, "show", task["id"]]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["revision_history"][0]["revision"] == 1
    assert shown["revision_history"][1]["revision"] == 2
    assert shown["ready"] is True

    assert main([*base, "cancel", task["id"]]) == 0
    capsys.readouterr()
    assert main([*base, "archive", task["id"]]) == 0
    archived = json.loads(capsys.readouterr().out)["task"]
    assert archived["archived_at"] is not None
    assert main([*base, "list"]) == 0
    assert json.loads(capsys.readouterr().out)["tasks"] == []
    assert main([*base, "list", "--archived-only"]) == 0
    assert len(json.loads(capsys.readouterr().out)["tasks"]) == 1


def test_v4_database_backfills_title_and_initial_revision(tmp_path):
    path = tmp_path / "old.db"
    project = config()
    definition = TaskDefinition(
        config=project, prompt="Eski görev metni", connection_id=project.agent.connection,
    )
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE tasks (
        id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, connection_id TEXT NOT NULL,
        status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        definition_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
        idempotency_key TEXT UNIQUE
    )""")
    db.execute(
        "INSERT INTO tasks VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, NULL)",
        ("old", project.agent.id, project.agent.connection, "now", "now",
         definition.model_dump_json(), "fingerprint"),
    )
    db.execute("PRAGMA user_version=4")
    db.commit()
    db.close()

    store = TaskStore(path)
    migrated = store.get("old")
    assert migrated.title == "Eski görev metni"
    assert migrated.definition_revision == 1
    assert migrated.enabled is True
    revisions = store.revisions("old")
    assert len(revisions) == 1
    assert revisions[0].reason == "migration"
    with store.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
