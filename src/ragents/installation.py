"""Yan yana uygulama sürümleri; şema sağlığı başarısızsa uygulama+DB geri dönüşü."""
from contextlib import closing
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

from filelock import FileLock, Timeout

from ragents.auth import atomic_write
from ragents.backups import backup_database
from ragents.distribution import verify_package, file_hash
from ragents.profile_paths import profile_root, database_path
from ragents.storage import TaskStore, TaskStateError, maintenance_flag


PROFILE_METADATA = ("agents", "connections", "teams", "auth")


@contextmanager
def profile_maintenance(profile):
    database = database_path(profile)
    database.parent.mkdir(parents=True, exist_ok=True)
    flag = maintenance_flag(database)
    flag.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(profile / "locks/maintenance.lock", timeout=0):
        if database.exists():
            with closing(sqlite3.connect(database)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                flag.touch()
        else:
            flag.touch()
        try:
            yield
        finally:
            flag.unlink(missing_ok=True)


def _health(version, profile):
    result = subprocess.run([str(version / "python/python.exe"), "-I", "-m", "ragents", "installation",
        "health", "--root", str(profile)], capture_output=True, timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    if result.returncode:
        raise TaskStateError("Yeni uygulama sağlık kontrolünden geçemedi.")


def _stop_profile(profile):
    directory = profile / "data"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "supervisor.stop").touch()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with FileLock(directory / "supervisor.lock", timeout=0), FileLock(directory / "ragents.db.worker.lock", timeout=0):
                return
        except Timeout:
            time.sleep(0.1)
    raise TaskStateError("Arka plan süreçleri durmadı; güncelleme başlamadı.")


def _backup(profile, backup):
    backup.mkdir(parents=True)
    database = database_path(profile)
    if database.exists():
        # Aktif manuel çalışmayı kilidinden ayırt et; eski kesilmiş kayıtlar yedeklenebilir.
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            active = db.execute("SELECT id FROM tasks WHERE status='running'").fetchall()
        for (identity,) in active:
            try:
                with FileLock(database.parent / "locks" / f"task-{identity}.lock", timeout=0):
                    pass
            except Timeout:
                raise TaskStateError("Manuel bir görev çalışıyor; güncellemeden önce iptal edin.") from None
        (backup / "data").mkdir()
        backup_database(database, backup / "data/ragents.db")
    for name in PROFILE_METADATA:
        source = profile / name
        if source.exists():
            if source.is_symlink() or source.is_junction() or any(path.is_symlink() or path.is_junction() for path in source.rglob("*")):
                raise TaskStateError("Yedeklenecek profil bağlantılı yol içeriyor.")
            shutil.copytree(source, backup / name, ignore=shutil.ignore_patterns("*.lock"))
    hashes = {path.relative_to(backup).as_posix(): file_hash(path) for path in backup.rglob("*") if path.is_file()}
    (backup / "backup-manifest.json").write_text(json.dumps({"profile": str(profile), "files": hashes}), encoding="utf-8")


def _restore(profile, backup):
    manifest = json.loads((backup / "backup-manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        path = backup / name
        if not path.resolve().is_relative_to(backup.resolve()) or file_hash(path) != expected:
            raise TaskStateError("Geri dönüş yedeğinin hash doğrulaması başarısız.")
    retired = backup / "failed-version-data"
    retired.mkdir()
    for name in (*PROFILE_METADATA, "data"):
        target = profile / name
        if target.exists():
            if not target.resolve().is_relative_to(profile.resolve()) or target.is_symlink() or target.is_junction():
                raise TaskStateError("Geri dönüş hedefi profil dışına çıkıyor.")
            os.rename(target, retired / name)
        if (backup / name).exists():
            shutil.copytree(backup / name, target)


def activate_version(installation: Path, profile: Path, version: str, *, health=_health):
    installation, profile = installation.resolve(), profile.resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,63}", version):
        raise TaskStateError("Uygulama sürümü geçersiz.")
    candidate = installation / "versions" / version
    if not candidate.resolve().is_relative_to(installation / "versions") or candidate.is_symlink() or candidate.is_junction():
        raise TaskStateError("Uygulama sürümü kurulum kökünün dışında.")
    manifest = verify_package(candidate)
    if manifest["version"] != version:
        raise TaskStateError("Paket sürümü manifestle eşleşmiyor.")
    with FileLock(installation / ".update.lock"), profile_maintenance(profile):
        current = installation / "current.txt"
        previous = current.read_text(encoding="utf-8").strip() if current.exists() else None
        if previous == version:
            return {"active_version": version, "changed": False}
        _stop_profile(profile)
        backup = installation / "backups" / uuid.uuid4().hex
        _backup(profile, backup)
        journal = {"previous": previous, "candidate": version, "profile": str(profile), "backup": str(backup), "status": "checking"}
        atomic_write(installation / "update-journal.json", json.dumps(journal).encode())
        try:
            health(candidate, profile)
            atomic_write(current, version.encode())
        except Exception:
            _restore(profile, backup)
            if previous is not None:
                atomic_write(current, previous.encode())
            journal["status"] = "rolled_back"
            atomic_write(installation / "update-journal.json", json.dumps(journal).encode())
            raise TaskStateError("Yeni sürüm başarısız; uygulama ve profil verisi birlikte geri alındı.") from None
        journal["status"] = "succeeded"
        atomic_write(installation / "update-journal.json", json.dumps(journal).encode())
        return {"active_version": version, "previous_version": previous, "backup": str(backup), "changed": True}


def add_installation_parser(commands):
    parser = commands.add_parser("installation", help="Kurucu sağlık ve uygulama/veri geri dönüşü")
    actions = parser.add_subparsers(dest="installation_action", required=True)
    health = actions.add_parser("health")
    health.add_argument("--root", type=Path)
    activate = actions.add_parser("activate")
    activate.add_argument("--root", type=Path)
    activate.add_argument("--installation-root", type=Path, required=True)
    activate.add_argument("--version", required=True)


def dispatch_installation(args):
    root = profile_root(args.root)
    if args.installation_action == "health":
        store = TaskStore(database_path(root), allow_maintenance=True)
        from ragents.task_service import TaskService
        TaskService(store).recover()
        with store.connect() as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise TaskStateError("Profil DB sağlık kontrolü başarısız.")
        return {"healthy": True, "model_requests": 0}
    return activate_version(args.installation_root, root, args.version)
