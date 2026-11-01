"""Yan etkisiz, tüm ürün yüzeylerinde ortak kullanıcı profili çözümü."""
import os
from pathlib import Path
import sys
from contextlib import contextmanager
from contextvars import ContextVar


_active_root: ContextVar[Path | None] = ContextVar("ragents_profile", default=None)


def profile_root(explicit: Path | str | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    active = _active_root.get()
    if active is not None:
        return active
    configured = os.environ.get("RAGENTS_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return (base / "RAgents" / "profiles" / "default").resolve()


def database_path(root: Path | str | None = None, explicit: Path | None = None) -> Path:
    return explicit.resolve() if explicit is not None else profile_root(root) / "data" / "ragents.db"


def protected_profile_paths(root: Path | str | None = None) -> tuple[Path, ...]:
    base = profile_root(root)
    return tuple(base / name for name in (
        "agents", "data", "auth", "locks", "teams", "connections", "approvals", "artifact-blobs", "logs",
        "ragents.yaml", "mcp-client.json", "codex-mcp.toml",
        "start-worker.py", "start-worker.ps1", "start-worker.sh",
    ))


@contextmanager
def profile_scope(root: Path | str | None = None):
    token = _active_root.set(profile_root(root))
    try:
        yield
    finally:
        _active_root.reset(token)
