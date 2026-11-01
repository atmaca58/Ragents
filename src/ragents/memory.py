"""Doğrulama kaynağı ve açık onay taşıyan sürümlü proje kayıtları."""
import hashlib
import json
from typing import Literal
import uuid

from pydantic import Field, field_validator

from ragents.config import Spec
from ragents.instructions import MemoryDocument
from ragents.relevance import keywords_match
from ragents.storage import TaskStateError, TaskStore, utc_now


class MemoryEntry(Spec):
    id: str
    agent_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    body: str = Field(min_length=1, max_length=2000)
    source_run_id: str
    keywords: tuple[str, ...] = Field(min_length=1, max_length=30)
    status: Literal["proposed", "approved", "archived"] = "proposed"
    revision: int = Field(default=1, ge=1)
    sha256: str

    @field_validator("body")
    @classmethod
    def validate_body(cls, value):
        if not value.strip():
            raise ValueError("Hafıza kaydı boş olamaz.")
        return value.strip()

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, value):
        if any(not item.strip() or len(item) > 60 for item in value):
            raise ValueError("Hafıza anahtar sözcüğü 1–60 karakter olmalıdır.")
        return tuple(dict.fromkeys(item.strip().casefold() for item in value))


def _digest(body: str) -> str:
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


class MemoryService:
    def __init__(self, store: TaskStore):
        self.store = store

    def _check_source(self, agent_id: str, source_run_id: str):
        run = self.store.run(source_run_id)
        verification = self.store.verification(source_run_id)
        if (run.status != "succeeded" or verification is None or verification.status != "passed"
                or self.store.get(run.task_id).agent_id != agent_id):
            raise TaskStateError("Hafıza kaynağı aynı ajanın bağımsız doğrulanmış başarılı çalışması olmalıdır.")

    @staticmethod
    def _entry(row) -> MemoryEntry:
        return MemoryEntry(id=row["id"], agent_id=row["agent_id"], body=row["body"],
                           source_run_id=row["source_run_id"], keywords=tuple(json.loads(row["keywords_json"])),
                           status=row["status"], revision=row["revision"], sha256=row["sha256"])

    def get(self, identity: str) -> MemoryEntry:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM memory_entries WHERE id=?", (identity,)).fetchone()
            if row is None:
                raise TaskStateError("Hafıza kaydı bulunamadı.")
            return self._entry(row)

    def propose(self, agent_id: str, body: str, source_run_id: str, keywords: tuple[str, ...]) -> MemoryEntry:
        self._check_source(agent_id, source_run_id)
        entry = MemoryEntry(id=uuid.uuid4().hex, agent_id=agent_id, body=body,
                            source_run_id=source_run_id, keywords=keywords, sha256=_digest(body))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM memory_entries WHERE agent_id=? AND sha256=?",
                                  (agent_id, entry.sha256)).fetchone()
            if existing is not None:
                return self._entry(existing)
            if db.execute("SELECT count(*) FROM memory_entries WHERE agent_id=? AND status!='archived'",
                          (agent_id,)).fetchone()[0] >= 1000:
                raise TaskStateError("Ajan başına en fazla 1000 etkin hafıza kaydı tutulur.")
            db.execute("INSERT INTO memory_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                entry.id, agent_id, entry.body, source_run_id, json.dumps(entry.keywords),
                entry.status, entry.revision, entry.sha256, utc_now()))
            self._history(db, entry)
        return entry

    @staticmethod
    def _history(db, entry: MemoryEntry):
        db.execute("INSERT INTO memory_revisions VALUES (?, ?, ?)",
                   (entry.id, entry.revision, entry.model_dump_json()))

    def approve(self, identity: str, revision: int) -> MemoryEntry:
        entry = self.get(identity)
        if entry.revision != revision or entry.status != "proposed":
            raise TaskStateError("Hafıza revizyonu değişti veya kayıt onay beklemiyor.")
        self._check_source(entry.agent_id, entry.source_run_id)
        return self._change(entry, status="approved")

    def revise(self, identity: str, revision: int, body: str) -> MemoryEntry:
        entry = self.get(identity)
        if entry.revision != revision:
            raise TaskStateError("Hafıza revizyonu değişti.")
        # İçerik değişirse önceki onay yeni metne taşınmaz.
        return self._change(entry, body=body, sha256=_digest(body), status="proposed")

    def archive(self, identity: str, revision: int) -> MemoryEntry:
        entry = self.get(identity)
        if entry.revision != revision:
            raise TaskStateError("Hafıza revizyonu değişti.")
        return self._change(entry, status="archived")

    def _change(self, entry: MemoryEntry, **changes) -> MemoryEntry:
        updated = MemoryEntry.model_validate({**entry.model_dump(), **changes, "revision": entry.revision + 1})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            duplicate = db.execute("SELECT id FROM memory_entries WHERE agent_id=? AND sha256=? AND id!=?",
                                   (updated.agent_id, updated.sha256, entry.id)).fetchone()
            if duplicate is not None:
                raise TaskStateError("Bu içerikte başka bir hafıza kaydı var.")
            changed = db.execute("UPDATE memory_entries SET body=?, status=?, revision=?, sha256=?, updated_at=? WHERE id=? AND revision=?",
                                 (updated.body, updated.status, updated.revision, updated.sha256, utc_now(), entry.id, entry.revision)).rowcount
            if not changed:
                raise TaskStateError("Hafıza revizyonu değişti.")
            self._history(db, updated)
        return updated

    def list(self, agent_id: str) -> list[MemoryEntry]:
        with self.store.connect() as db:
            return [self._entry(row) for row in db.execute(
                "SELECT * FROM memory_entries WHERE agent_id=? ORDER BY updated_at DESC, id LIMIT 1000", (agent_id,))]

    def select(self, agent_id: str, prompt: str) -> tuple[MemoryDocument, ...]:
        selected, chars = [], 0
        with self.store.connect() as db:
            entries = [self._entry(row) for row in db.execute(
                "SELECT * FROM memory_entries WHERE agent_id=? AND status='approved' ORDER BY updated_at DESC, id LIMIT 1000",
                (agent_id,))]
        for entry in entries:
            if not keywords_match(entry.keywords, prompt):
                continue
            if chars + len(entry.body) > 3000 or len(selected) >= 8:
                continue
            selected.append(MemoryDocument(entry.id, entry.revision, entry.body,
                                            hashlib.sha256(entry.body.encode("utf-8")).hexdigest()))
            chars += len(entry.body)
        return tuple(selected)
