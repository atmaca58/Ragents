"""Canlı WAL verisini SQLite backup API ile tutarlı olarak kopyalar."""
from pathlib import Path
from contextlib import closing
import sqlite3
import time

from ragents.storage import SCHEMA_VERSION, TaskStateError


def _validate_database(db: sqlite3.Connection, *, restoring: bool) -> None:
    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise TaskStateError("Veritabanı bütünlük kontrolünü geçemedi.")
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"tasks", "runs", "results"}.issubset(tables):
        raise TaskStateError("Dosya R Agents görev veritabanı değil.")
    if restoring and db.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
        raise TaskStateError("Yedek daha yeni bir uygulama sürümü gerektiriyor.")


def _copy_database(source: Path, target: Path, *, restoring: bool) -> Path:
    source, target = source.resolve(), target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with target.open("xb"):
            pass
    except FileExistsError:
        raise TaskStateError("Mevcut dosyanın üzerine yedek/geri yükleme yapılmaz.") from None
    started = time.monotonic()

    def progress(*_args):
        if time.monotonic() - started > 60:
            raise TaskStateError("Yedekleme süre sınırına ulaştı.")

    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as origin:
            _validate_database(origin, restoring=restoring)
            with closing(sqlite3.connect(target)) as destination:
                origin.backup(destination, pages=256, progress=progress, sleep=0.05)
                _validate_database(destination, restoring=restoring)
        target.chmod(0o600)
        return target
    except BaseException as error:
        target.unlink(missing_ok=True)
        if isinstance(error, sqlite3.Error):
            raise TaskStateError("Veritabanı okunamadı veya yedekleme tamamlanamadı.") from None
        raise


def backup_database(source: Path, target: Path) -> Path:
    return _copy_database(source, target, restoring=False)


def restore_database(source: Path, target: Path) -> Path:
    return _copy_database(source, target, restoring=True)
