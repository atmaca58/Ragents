from pathlib import Path

import pytest

from ragents.config import load_config
from ragents.storage import TaskStateError, TaskStore


def test_backup_captures_wal_and_restores_to_fresh_database(tmp_path):
    from ragents.backups import backup_database, restore_database

    store = TaskStore(tmp_path / "live" / "tasks.db")
    with store.connect() as writer:
        task = store.enqueue(load_config(Path("examples/ollama.yaml")), "Saklanacak görev")
        backup = backup_database(store.path, tmp_path / "backup.db")
    restored = restore_database(backup, tmp_path / "restored" / "tasks.db")
    assert TaskStore(restored).get(task.id).title == task.title
    with pytest.raises(TaskStateError, match="üzerine"):
        restore_database(backup, store.path)
    assert store.get(task.id).status == "queued"


def test_profile_backup_is_available_from_cli(tmp_path, capsys):
    from ragents.cli import main
    import json

    root = tmp_path / "profile"
    store = TaskStore(root / "data" / "ragents.db")
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "Görev")
    target = tmp_path / "snapshot.db"
    assert main(["profile", "--root", str(root), "backup", "--output", str(target)]) == 0
    assert json.loads(capsys.readouterr().out)["backup"] == str(target)
    assert TaskStore(target).get(task.id).id == task.id
