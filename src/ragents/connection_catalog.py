"""Model bağlantılarının kalıcı ve secret içermeyen ortak kataloğu."""
from pathlib import Path
import json

from filelock import FileLock
from pydantic import TypeAdapter

from ragents.config import ConnectionSpec
from ragents.auth import atomic_write
from ragents.storage import TaskStateError


class ConnectionCatalog:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / "connections/catalog.json"

    def read(self):
        return TypeAdapter(dict[str, ConnectionSpec]).validate_json(self.path.read_bytes()) if self.path.exists() else {}

    def put(self, identity, connection: ConnectionSpec):
        import re
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", identity):
            raise TaskStateError("Bağlantı kimliği geçersiz.")
        directory = self.root / "locks"
        directory.mkdir(parents=True, exist_ok=True)
        with FileLock(directory / "connections.lock"):
            if (directory / "maintenance.flag").exists():
                raise TaskStateError("Profil bakım modunda; bağlantı düzenlenemez.")
            connections = self.read()
            connections[identity] = connection
            atomic_write(self.path, json.dumps({key: value.model_dump(mode="json") for key, value in connections.items()},
                                               ensure_ascii=False).encode())
        return {"id": identity, "provider": connection.provider, "model": connection.model}
