from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterator, Literal
import uuid

from ragents.config import ProjectConfig, Spec
from ragents.contracts import RunResult, Usage


TaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "interrupted"]
TASK_COLUMNS = "id, agent_id, connection_id, status, created_at, updated_at"


class TaskStateError(RuntimeError):
    """Kullanıcıya gösterilebilir görev durumu hatası."""


class TaskSnapshot(Spec):
    id: str
    agent_id: str
    connection_id: str
    status: TaskStatus
    created_at: str
    updated_at: str


class TaskDefinition(Spec):
    config: ProjectConfig
    prompt: str
    connection_id: str


class RunSnapshot(Spec):
    id: str
    task_id: str
    status: TaskStatus
    provider: str
    model: str
    started_at: str
    finished_at: str | None = None
    duration_seconds: float | None = None
    usage: Usage | None = None
    error_code: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA user_version").fetchone()[0] > 2:
                raise TaskStateError("Veritabanı daha yeni bir R Agents sürümüne ait.")
            db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, connection_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled','interrupted')),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                definition_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
                idempotency_key TEXT UNIQUE
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                status TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT, duration_seconds REAL,
                usage_json TEXT, error_code TEXT
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS runs_task_id ON runs(task_id)")
            db.execute("""CREATE TABLE IF NOT EXISTS results (
                run_id TEXT PRIMARY KEY REFERENCES runs(id), result_json TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS cancellations (
                run_id TEXT PRIMARY KEY REFERENCES runs(id), requested_at TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS tasks_queue ON tasks(status, created_at, id)")
            db.execute("PRAGMA user_version=2")
        self.path.chmod(0o600)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(
        self, config: ProjectConfig, prompt: str, connection_id: str | None = None,
        *, idempotency_key: str | None = None,
    ) -> TaskSnapshot:
        from ragents.contracts import RunRequest

        RunRequest(agent=config.agent, prompt=prompt)
        selected = connection_id or config.agent.connection
        if selected not in config.connections:
            raise TaskStateError("Seçilen bağlantı tanımlı değil.")
        definition = TaskDefinition(config=config, prompt=prompt, connection_id=selected)
        payload = json.dumps(definition.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        task_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                existing = db.execute("SELECT id, fingerprint, definition_json FROM tasks WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if existing is not None:
                    if (existing["fingerprint"] != fingerprint
                            and TaskDefinition.model_validate_json(existing["definition_json"]) != definition):
                        raise TaskStateError("Aynı görev anahtarı farklı içerikle kullanılamaz.")
                    return self.snapshot(db, existing["id"])
            db.execute("INSERT INTO tasks VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?)", (
                task_id, config.agent.id, selected, now, now, payload, fingerprint, idempotency_key,
            ))
            return self.snapshot(db, task_id)

    def snapshot(self, db: sqlite3.Connection, task_id: str) -> TaskSnapshot:
        row = db.execute(f"SELECT {TASK_COLUMNS} FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise TaskStateError("Görev bulunamadı.")
        return TaskSnapshot.model_validate(dict(row))

    def get(self, task_id: str) -> TaskSnapshot:
        with self.connect() as db:
            return self.snapshot(db, task_id)

    def list(self, *, status: TaskStatus | None = None, limit: int = 50) -> list[TaskSnapshot]:
        if not 1 <= limit <= 1000:
            raise TaskStateError("Liste sınırı 1 ile 1000 arasında olmalıdır.")
        query = f"SELECT {TASK_COLUMNS} FROM tasks"
        params: list[str | int] = []
        if status is not None:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as db:
            return [TaskSnapshot.model_validate(dict(row)) for row in db.execute(query, params)]

    def definition(self, task_id: str) -> TaskDefinition:
        with self.connect() as db:
            row = db.execute("SELECT definition_json FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise TaskStateError("Görev bulunamadı.")
        return TaskDefinition.model_validate_json(row[0])

    def queued(self, limit: int) -> list[TaskSnapshot]:
        if not 1 <= limit <= 1000:
            raise TaskStateError("Kuyruk sınırı 1 ile 1000 arasında olmalıdır.")
        with self.connect() as db:
            return [TaskSnapshot.model_validate(dict(row)) for row in db.execute(
                f"SELECT {TASK_COLUMNS} FROM tasks WHERE status='queued' ORDER BY created_at, id LIMIT ?", (limit,),
            )]

    def retry(self, task_id: str) -> TaskSnapshot:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self.snapshot(db, task_id)
            if task.status not in ("failed", "interrupted", "cancelled"):
                raise TaskStateError("Yalnız başarısız, kesilmiş veya iptal edilmiş görev yeniden sıraya alınabilir.")
            db.execute("UPDATE tasks SET status='queued', updated_at=? WHERE id=?", (utc_now(), task_id))
            return self.snapshot(db, task_id)

    def request_cancel(self, task_id: str) -> TaskSnapshot:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self.snapshot(db, task_id)
            if task.status == "queued":
                db.execute("UPDATE tasks SET status='cancelled', updated_at=? WHERE id=?", (utc_now(), task_id))
            elif task.status == "running":
                db.execute("""INSERT OR IGNORE INTO cancellations SELECT id, ? FROM runs
                              WHERE task_id=? AND status='running'""", (utc_now(), task_id))
            elif task.status != "cancelled":
                raise TaskStateError("Tamamlanmış göreve iptal isteği gönderilemez.")
            return self.snapshot(db, task_id)

    def cancellation_requested(self, run_id: str) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM cancellations WHERE run_id=?", (run_id,)).fetchone() is not None

    def claim(self, task_id: str) -> RunSnapshot:
        run_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self.snapshot(db, task_id)
            if task.status != "queued":
                raise TaskStateError("Yalnız sıradaki görev çalıştırılabilir; yeniden denemek için retry kullanın.")
            definition = TaskDefinition.model_validate_json(db.execute(
                "SELECT definition_json FROM tasks WHERE id=?", (task_id,),
            ).fetchone()[0])
            connection = definition.config.connections[definition.connection_id]
            db.execute("UPDATE tasks SET status='running', updated_at=? WHERE id=?", (now, task_id))
            db.execute("INSERT INTO runs (id, task_id, status, provider, model, started_at) VALUES (?, ?, 'running', ?, ?, ?)",
                       (run_id, task_id, connection.provider, connection.model, now))
        return RunSnapshot(id=run_id, task_id=task_id, status="running", provider=connection.provider,
                           model=connection.model, started_at=now)

    def succeed(self, run_id: str, result: RunResult, duration_seconds: float) -> RunSnapshot:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT task_id FROM runs WHERE id=? AND status='running'", (run_id,)).fetchone()
            if row is None:
                raise TaskStateError("Çalışma aktif değil.")
            now = utc_now()
            cancelled = db.execute("SELECT 1 FROM cancellations WHERE run_id=?", (run_id,)).fetchone() is not None
            status = "cancelled" if cancelled else "succeeded"
            if not cancelled:
                db.execute("INSERT INTO results VALUES (?, ?)", (run_id, result.model_dump_json()))
            db.execute("UPDATE runs SET status=?, finished_at=?, duration_seconds=?, usage_json=?, error_code=? WHERE id=?",
                       (status, now, duration_seconds, result.usage.model_dump_json(), "cancelled" if cancelled else None, run_id))
            db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, now, row[0]))
        return self.run(run_id)

    def run(self, run_id: str) -> RunSnapshot:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise TaskStateError("Çalışma bulunamadı.")
        return self.run_snapshot(row)

    def fail(
        self, run_id: str, error_code: str, duration_seconds: float | None,
        *, status: Literal["failed", "cancelled", "interrupted"] = "failed",
    ) -> RunSnapshot:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT task_id FROM runs WHERE id=? AND status='running'", (run_id,)).fetchone()
            if row is None:
                raise TaskStateError("Çalışma aktif değil.")
            now = utc_now()
            db.execute("UPDATE runs SET status=?, finished_at=?, duration_seconds=?, error_code=? WHERE id=?",
                       (status, now, duration_seconds, error_code, run_id))
            db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, now, row[0]))
        return self.run(run_id)

    def run_snapshot(self, row: sqlite3.Row) -> RunSnapshot:
        data = dict(row)
        usage_json = data.pop("usage_json")
        data["usage"] = Usage.model_validate_json(usage_json) if usage_json else None
        return RunSnapshot.model_validate(data)

    def runs(self, task_id: str) -> list[RunSnapshot]:
        self.get(task_id)
        with self.connect() as db:
            return [self.run_snapshot(row) for row in db.execute(
                "SELECT * FROM runs WHERE task_id=? ORDER BY started_at, id", (task_id,),
            )]

    def result(self, run_id: str) -> RunResult | None:
        with self.connect() as db:
            row = db.execute("SELECT result_json FROM results WHERE run_id=?", (run_id,)).fetchone()
        return RunResult.model_validate_json(row[0]) if row else None
