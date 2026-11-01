"""Workspace'ten bağımsız, hash'le doğrulanan değişmez artifact kopyaları."""
import hashlib
import json
import mimetypes
from pathlib import Path

from ragents.errors import WorkspaceError
from ragents.storage import TaskStateError
from ragents.workspace import Workspace, MAX_HASH_BYTES
from ragents.auth import atomic_write


class ArtifactStore:
    def __init__(self, root, store):
        self.root, self.store = Path(root).resolve(), store

    def capture(self, run_id, grant, verification_status):
        workspace = Workspace(grant.root, grant.protected_paths, readable_paths=grant.readable_paths)
        run = self.store.run(run_id)
        for artifact in self.store.artifacts(run.task_id):
            if artifact.run_id != run_id or artifact.sha256 is None:
                continue
            names = Path(artifact.path).parts
            if any(name.lower().startswith(".env") or name.lower() in ("auth", "credentials", "secrets", "id_rsa", "id_ed25519")
                   or name.lower().endswith((".pem", ".key", ".pfx", ".p12")) for name in names):
                continue
            source = workspace._target(artifact.path, access="read")
            if not source.is_file() or source.stat().st_size > MAX_HASH_BYTES:
                continue
            content = source.read_bytes()
            sha = hashlib.sha256(content).hexdigest()
            if sha != artifact.sha256 or len(content) != artifact.size_bytes:
                raise WorkspaceError("Artifact içeriği doğrulama sırasında değişti.")
            directory = self.root / "artifact-blobs" / sha[:2]
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / sha
            if not path.exists():
                atomic_write(path, content)
            elif hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise WorkspaceError("Artifact deposunda mevcut içerik bozuk.")
            record = {"artifact_id": artifact.id, "sha256": sha, "size_bytes": len(content),
                      "content_type": mimetypes.guess_type(artifact.path)[0] or "application/octet-stream",
                      "verification_status": verification_status}
            with self.store.connect() as db:
                db.execute("INSERT OR IGNORE INTO artifact_snapshots VALUES (?,?)", (artifact.id, json.dumps(record)))

    def read(self, identity, *, offset=0, max_bytes=16000):
        if offset < 0 or not 1 <= max_bytes <= 65536:
            raise TaskStateError("Artifact okuma aralığı geçersiz.")
        with self.store.connect() as db:
            row = db.execute("SELECT record_json FROM artifact_snapshots WHERE artifact_id=?", (identity,)).fetchone()
        if row is None:
            raise TaskStateError("Bu artifact için değişmez içerik kopyası yok.")
        record = json.loads(row[0])
        path = self.root / "artifact-blobs" / record["sha256"][:2] / record["sha256"]
        if path.is_symlink() or path.is_junction() or path.parent.is_symlink() or path.parent.is_junction():
            raise TaskStateError("Artifact deposunda bağlantılı yol reddedildi.")
        if path.stat().st_size > MAX_HASH_BYTES:
            raise TaskStateError("Artifact boyutu sınırı aşıyor.")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != record["sha256"]:
            raise TaskStateError("Artifact deposunun hash doğrulaması başarısız.")
        return record | {"content": content[offset:offset + max_bytes].decode("utf-8", errors="replace"),
                         "offset": offset, "truncated": offset + max_bytes < len(content), "untrusted_content": True}
