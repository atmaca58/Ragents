from pathlib import Path
import sqlite3
from contextlib import closing
import pytest

from ragents.distribution import write_package_manifest
from ragents.installation import activate_version
from ragents.storage import TaskStore, TaskStateError


def test_failed_upgrade_restores_application_and_database_together(tmp_path):
    installation, profile = tmp_path / "app", tmp_path / "profile"
    old = installation / "versions/old"
    new = installation / "versions/new"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (installation / "current.txt").write_text("old", encoding="utf-8")
    (new / "application.txt").write_text("new", encoding="utf-8")
    write_package_manifest(new, "new")
    store = TaskStore(profile / "data/ragents.db")
    with store.connect() as db:
        db.execute("CREATE TABLE user_note (body TEXT)")
        db.execute("INSERT INTO user_note VALUES ('preserved')")
    def fail_health(version, root):
        with closing(sqlite3.connect(root / "data/ragents.db")) as db, db:
            db.execute("DELETE FROM user_note")
        raise RuntimeError("health failed")
    with pytest.raises(TaskStateError, match="geri"):
        activate_version(installation, profile, "new", health=fail_health)
    assert (installation / "current.txt").read_text() == "old"
    with closing(sqlite3.connect(profile / "data/ragents.db")) as db:
        assert db.execute("SELECT body FROM user_note").fetchone()[0] == "preserved"


def test_maintenance_blocks_existing_store_writes_without_destroying_data(tmp_path):
    from ragents.installation import profile_maintenance
    store = TaskStore(tmp_path / "data/ragents.db")
    with profile_maintenance(tmp_path):
        with pytest.raises(TaskStateError, match="bakım"):
            with store.connect() as db:
                db.execute("DELETE FROM tasks")
        with store.connect() as db:
            assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    assert not (tmp_path / "locks/maintenance.flag").exists()
