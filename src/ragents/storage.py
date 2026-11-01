from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
from typing import Any, Iterator, Literal
import uuid

from pydantic import Field, ValidationError, field_validator, model_validator

from ragents.config import (
    COMMAND_TOOL_NAMES, ProjectConfig, Spec, WORKSPACE_TOOL_NAMES, WRITE_TOOL_NAMES,
)
from ragents.contracts import RunResult, Usage
from ragents.instructions import InstructionSnapshot
from ragents.verification import VerificationPlan, VerificationRecord
from ragents.workspace import ArtifactDraft, WorkspaceGrant
from ragents.programmatic import ProgrammaticJob


TaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "interrupted"]
TASK_COLUMNS = (
    "id, agent_id, connection_id, status, title, description, priority, enabled, "
    "archived_at, definition_revision, created_at, updated_at"
)
MAX_TASK_DEPENDENCIES = 32
UNSET = object()
SCHEMA_VERSION = 8


class TaskStateError(RuntimeError):
    """Kullanıcıya gösterilebilir görev durumu hatası."""


def default_task_title(prompt: str) -> str:
    line = next((part.strip() for part in prompt.splitlines() if part.strip()), "")
    return line[:200] or "Görev"


def _validation_message(error: ValidationError) -> str:
    first = error.errors()[0]
    return str(first.get("msg", "geçersiz değer"))


class TaskMetadata(Spec):
    """Görevin tanım dışındaki sıralama ve yaşam döngüsü alanları."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    priority: int = Field(default=0, ge=-1000, le=1000)
    enabled: bool = True
    dependencies: tuple[str, ...] = Field(default=(), max_length=MAX_TASK_DEPENDENCIES)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        text = " ".join(value.split())
        if not text:
            raise ValueError("Görev başlığı boş olamaz.")
        return text

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("dependencies")
    @classmethod
    def validate_dependencies(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Görev bağımlılıkları tekrarlanamaz.")
        for item in value:
            if not item or len(item) > 64:
                raise ValueError("Görev bağımlılığı kimliği geçersiz.")
        return tuple(sorted(value))


class TaskSnapshot(Spec):
    id: str
    agent_id: str
    connection_id: str
    status: TaskStatus
    title: str
    description: str = ""
    priority: int = 0
    enabled: bool = True
    archived_at: str | None = None
    definition_revision: int = 1
    created_at: str
    updated_at: str


class TaskDefinition(Spec):
    config: ProjectConfig
    prompt: str = Field(min_length=1, max_length=32000, pattern=r"\S")
    connection_id: str
    instruction: InstructionSnapshot | None = None
    workspace: WorkspaceGrant | None = None
    verification: VerificationPlan | None = None
    programmatic: ProgrammaticJob | None = None
    team_run_id: str | None = None
    team_step_id: str | None = None

    @model_validator(mode="after")
    def validate_instruction(self) -> "TaskDefinition":
        if (self.programmatic is not None and self.programmatic.handler == "workspace_inventory"
                and self.workspace is None):
            raise ValueError("Dosya envanteri için workspace gereklidir.")
        if self.instruction is not None:
            digest = hashlib.sha256(self.config.agent.instructions.encode("utf-8")).hexdigest()
            if digest != self.instruction.revision:
                raise ValueError("Görev talimat snapshot'ı metinle eşleşmiyor.")
        tools = set(self.config.agent.tools)
        if self.workspace is None and WORKSPACE_TOOL_NAMES.intersection(tools):
            raise ValueError("Workspace araçları için görev workspace'i tanımlı olmalıdır.")
        if self.workspace is not None:
            if tools & WRITE_TOOL_NAMES and not self.workspace.writable_paths:
                raise ValueError("Dosya yazma araçları için yazılabilir dizin tanımlı olmalıdır.")
            if tools & COMMAND_TOOL_NAMES and not self.workspace.commands:
                raise ValueError("Komut aracı için izinli komut listesi tanımlı olmalıdır.")
        if self.verification is not None and self.verification.requires_workspace:
            if self.workspace is None:
                raise ValueError("Dosya/komut doğrulaması için görev workspace'i tanımlı olmalıdır.")
        return self


class TaskRevision(Spec):
    task_id: str
    revision: int = Field(ge=1)
    title: str
    description: str
    priority: int
    enabled: bool
    dependencies: tuple[str, ...]
    definition: TaskDefinition
    created_at: str
    reason: str


class Artifact(Spec):
    id: str
    task_id: str
    run_id: str
    agent_id: str
    path: str
    sha256: str | None = None
    size_bytes: int = Field(ge=0)
    producer: str
    created_at: str

    @model_validator(mode="after")
    def validate_path(self) -> "Artifact":
        path = PurePosixPath(self.path)
        if (path.is_absolute() or ".." in path.parts or not self.path
                or ":" in self.path or "\\" in self.path):
            raise ValueError("Artifact yolu workspace'e göre göreli olmalıdır.")
        return self


def _core_definition(definition: TaskDefinition) -> dict[str, Any]:
    return definition.model_dump(mode="json", exclude={"instruction"})


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


def maintenance_flag(database: Path) -> Path:
    parent = database.resolve().parent
    root = parent.parent if parent.name == "data" else parent
    return root / "locks/maintenance.flag"


class TaskStore:
    def __init__(self, path: Path, *, allow_maintenance: bool = False):
        self.path = path.resolve()
        self.allow_maintenance = allow_maintenance
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
                raise TaskStateError("Veritabanı daha yeni bir R Agents sürümüne ait.")
            db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, connection_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled','interrupted')),
                title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
                priority INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
                archived_at TEXT, definition_revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                definition_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
                idempotency_key TEXT UNIQUE
            )""")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}
            for name, definition in (
                ("title", "TEXT NOT NULL DEFAULT ''"),
                ("description", "TEXT NOT NULL DEFAULT ''"),
                ("priority", "INTEGER NOT NULL DEFAULT 0"),
                ("enabled", "INTEGER NOT NULL DEFAULT 1"),
                ("archived_at", "TEXT"),
                ("definition_revision", "INTEGER NOT NULL DEFAULT 1"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
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
            db.execute("""CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                run_id TEXT NOT NULL REFERENCES runs(id), agent_id TEXT NOT NULL,
                path TEXT NOT NULL, sha256 TEXT, size_bytes INTEGER NOT NULL,
                producer TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(run_id, path)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS verifications (
                run_id TEXT PRIMARY KEY REFERENCES runs(id),
                task_id TEXT NOT NULL REFERENCES tasks(id),
                status TEXT NOT NULL CHECK(status IN ('passed','failed','error')),
                record_json TEXT NOT NULL, created_at TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS task_dependencies (
                task_id TEXT NOT NULL REFERENCES tasks(id),
                depends_on TEXT NOT NULL REFERENCES tasks(id),
                PRIMARY KEY(task_id, depends_on),
                CHECK(task_id != depends_on)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS task_revisions (
                task_id TEXT NOT NULL REFERENCES tasks(id),
                revision INTEGER NOT NULL,
                title TEXT NOT NULL, description TEXT NOT NULL,
                priority INTEGER NOT NULL, enabled INTEGER NOT NULL,
                dependencies_json TEXT NOT NULL, definition_json TEXT NOT NULL,
                created_at TEXT NOT NULL, reason TEXT NOT NULL,
                PRIMARY KEY(task_id, revision)
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS tasks_queue ON tasks(status, created_at, id)")
            db.execute("CREATE INDEX IF NOT EXISTS tasks_priority_queue ON tasks(status, priority DESC, created_at, id)")
            db.execute("CREATE INDEX IF NOT EXISTS artifacts_task_id ON artifacts(task_id)")
            db.execute("CREATE INDEX IF NOT EXISTS verifications_task_id ON verifications(task_id)")
            db.execute("CREATE INDEX IF NOT EXISTS task_dependencies_target ON task_dependencies(depends_on)")
            self._migrate_tasks(db)
            db.execute("""CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY, template_task_id TEXT NOT NULL REFERENCES tasks(id),
                timing_json TEXT NOT NULL, definition_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
                next_at TEXT, enabled INTEGER NOT NULL, revision INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS schedule_fires (
                schedule_id TEXT NOT NULL REFERENCES schedules(id), slot TEXT NOT NULL,
                revision INTEGER NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(id),
                PRIMARY KEY(schedule_id, revision, slot)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS memory_entries (
                id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, body TEXT NOT NULL,
                source_run_id TEXT NOT NULL REFERENCES runs(id), keywords_json TEXT NOT NULL,
                status TEXT NOT NULL, revision INTEGER NOT NULL, sha256 TEXT NOT NULL,
                updated_at TEXT NOT NULL, UNIQUE(agent_id, sha256)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS memory_revisions (
                entry_id TEXT NOT NULL REFERENCES memory_entries(id), revision INTEGER NOT NULL,
                record_json TEXT NOT NULL, PRIMARY KEY(entry_id, revision)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS setup_requests (
                id TEXT PRIMARY KEY, record_json TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS team_runs (
                id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE,
                fingerprint TEXT NOT NULL, record_json TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS artifact_snapshots (
                artifact_id TEXT PRIMARY KEY REFERENCES artifacts(id), record_json TEXT NOT NULL)""")
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.path.chmod(0o600)

    def _migrate_tasks(self, db: sqlite3.Connection) -> None:
        rows = db.execute(
            f"SELECT {TASK_COLUMNS}, definition_json FROM tasks ORDER BY created_at, id"
        ).fetchall()
        for row in rows:
            try:
                definition = TaskDefinition.model_validate_json(row["definition_json"])
            except ValidationError:
                definition = None
            updates: dict[str, Any] = {}
            if not row["title"]:
                updates["title"] = default_task_title(definition.prompt if definition else "")
            if row["definition_revision"] < 1:
                updates["definition_revision"] = 1
            if updates:
                assignments = ", ".join(f"{key}=?" for key in updates)
                db.execute(
                    f"UPDATE tasks SET {assignments} WHERE id=?",
                    (*updates.values(), row["id"]),
                )
            if definition is None:
                continue
            exists = db.execute(
                "SELECT 1 FROM task_revisions WHERE task_id=?", (row["id"],),
            ).fetchone()
            if exists is None:
                self._insert_revision(
                    db, row["id"], 1, self._metadata(db, row["id"]), definition,
                    row["created_at"], "migration",
                )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        maintenance = maintenance_flag(self.path)
        writes = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
                  sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE,
                  sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_DROP_INDEX}
        def authorize(action, first, second, database, trigger):
            if not self.allow_maintenance and maintenance.exists() and (
                    action in writes or action == sqlite3.SQLITE_PRAGMA and second is not None):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        try:
            with db:
                yield db
        except sqlite3.DatabaseError:
            if not self.allow_maintenance and maintenance.exists():
                raise TaskStateError("Profil bakım modunda; güncelleme bitene kadar yazma ve çalıştırma kapalı.") from None
            raise
        finally:
            db.close()

    def enqueue(
        self, config: ProjectConfig, prompt: str, connection_id: str | None = None,
        *, idempotency_key: str | None = None,
        instruction: InstructionSnapshot | None = None,
        workspace: WorkspaceGrant | None = None,
        verification: VerificationPlan | None = None,
        title: str | None = None, description: str = "", priority: int = 0,
        enabled: bool = True, dependencies: tuple[str, ...] = (),
        programmatic: ProgrammaticJob | None = None,
        team_run_id: str | None = None, team_step_id: str | None = None,
    ) -> TaskSnapshot:
        from ragents.contracts import RunRequest

        RunRequest(agent=config.agent, prompt=prompt, workspace=workspace)
        selected = connection_id or config.agent.connection
        if selected not in config.connections:
            raise TaskStateError("Seçilen bağlantı tanımlı değil.")
        definition = TaskDefinition(
            config=config, prompt=prompt, connection_id=selected,
            instruction=instruction, workspace=workspace, verification=verification,
            programmatic=programmatic, team_run_id=team_run_id, team_step_id=team_step_id,
        )
        try:
            metadata = TaskMetadata(
                title=title or default_task_title(prompt), description=description,
                priority=priority, enabled=enabled, dependencies=tuple(dependencies),
            )
        except ValidationError as error:
            raise TaskStateError("Görev metadatası geçersiz: " + _validation_message(error)) from None
        payload = json.dumps(definition.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        core_payload = json.dumps(
            _core_definition(definition), ensure_ascii=False, sort_keys=True,
        )
        fingerprint = hashlib.sha256(core_payload.encode("utf-8")).hexdigest()
        task_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                existing = db.execute(
                    f"SELECT {TASK_COLUMNS}, fingerprint, definition_json "
                    "FROM tasks WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    previous = TaskDefinition.model_validate_json(existing["definition_json"])
                    previous_metadata = TaskMetadata(
                        title=existing["title"], description=existing["description"],
                        priority=existing["priority"], enabled=bool(existing["enabled"]),
                        dependencies=self._dependencies(db, existing["id"]),
                    )
                    if (_core_definition(previous) != _core_definition(definition)
                            or previous_metadata != metadata):
                        raise TaskStateError("Aynı görev anahtarı farklı içerikle kullanılamaz.")
                    return self.snapshot(db, existing["id"])
            self._validate_dependencies(db, task_id, metadata.dependencies)
            db.execute(
                """INSERT INTO tasks
                   (id, agent_id, connection_id, status, title, description, priority,
                    enabled, archived_at, definition_revision, created_at, updated_at,
                    definition_json, fingerprint, idempotency_key)
                   VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, NULL, 1, ?, ?, ?, ?, ?)""",
                (
                    task_id, config.agent.id, selected, metadata.title,
                    metadata.description, metadata.priority, int(metadata.enabled),
                    now, now, payload, fingerprint, idempotency_key,
                ),
            )
            self._set_dependencies(db, task_id, metadata.dependencies)
            self._insert_revision(db, task_id, 1, metadata, definition, now, "enqueue")
            return self.snapshot(db, task_id)

    def _dependencies(self, db: sqlite3.Connection, task_id: str) -> tuple[str, ...]:
        return tuple(
            row[0] for row in db.execute(
                "SELECT depends_on FROM task_dependencies WHERE task_id=? ORDER BY depends_on",
                (task_id,),
            )
        )

    def _set_dependencies(
        self, db: sqlite3.Connection, task_id: str, dependencies: tuple[str, ...],
    ) -> None:
        db.execute("DELETE FROM task_dependencies WHERE task_id=?", (task_id,))
        db.executemany(
            "INSERT INTO task_dependencies (task_id, depends_on) VALUES (?, ?)",
            [(task_id, dependency) for dependency in dependencies],
        )

    def _validate_dependencies(
        self, db: sqlite3.Connection, task_id: str, dependencies: tuple[str, ...],
    ) -> None:
        for dependency in dependencies:
            if dependency == task_id:
                raise TaskStateError("Görev kendisine bağımlı olamaz.")
            if db.execute("SELECT 1 FROM tasks WHERE id=?", (dependency,)).fetchone() is None:
                raise TaskStateError(f"Bağımlı görev bulunamadı: {dependency}.")
        for dependency in dependencies:
            stack = [dependency]
            seen: set[str] = set()
            while stack:
                current = stack.pop()
                if current == task_id:
                    raise TaskStateError("Görev bağımlılıkları döngü oluşturamaz.")
                if current in seen:
                    continue
                seen.add(current)
                stack.extend(
                    row[0] for row in db.execute(
                        "SELECT depends_on FROM task_dependencies WHERE task_id=?",
                        (current,),
                    )
                )

    def _metadata(self, db: sqlite3.Connection, task_id: str) -> TaskMetadata:
        row = db.execute(
            f"SELECT {TASK_COLUMNS} FROM tasks WHERE id=?", (task_id,),
        ).fetchone()
        if row is None:
            raise TaskStateError("Görev bulunamadı.")
        return TaskMetadata(
            title=row["title"] or "Görev", description=row["description"],
            priority=row["priority"], enabled=bool(row["enabled"]),
            dependencies=self._dependencies(db, task_id),
        )

    def _insert_revision(
        self, db: sqlite3.Connection, task_id: str, revision: int,
        metadata: TaskMetadata, definition: TaskDefinition, created_at: str,
        reason: str,
    ) -> None:
        db.execute(
            """INSERT INTO task_revisions
               (task_id, revision, title, description, priority, enabled,
                dependencies_json, definition_json, created_at, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id, revision, metadata.title, metadata.description,
                metadata.priority, int(metadata.enabled),
                json.dumps(list(metadata.dependencies), ensure_ascii=False),
                definition.model_dump_json(), created_at, reason,
            ),
        )

    def snapshot(self, db: sqlite3.Connection, task_id: str) -> TaskSnapshot:
        row = db.execute(f"SELECT {TASK_COLUMNS} FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise TaskStateError("Görev bulunamadı.")
        return TaskSnapshot.model_validate(dict(row))

    def get(self, task_id: str) -> TaskSnapshot:
        with self.connect() as db:
            return self.snapshot(db, task_id)

    def list(
        self, *, status: TaskStatus | None = None, limit: int = 50,
        include_archived: bool = False, archived_only: bool = False,
    ) -> list[TaskSnapshot]:
        if not 1 <= limit <= 1000:
            raise TaskStateError("Liste sınırı 1 ile 1000 arasında olmalıdır.")
        query = f"SELECT {TASK_COLUMNS} FROM tasks"
        clauses: list[str] = []
        params: list[str | int] = []
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        if archived_only:
            clauses.append("archived_at IS NOT NULL")
        elif not include_archived:
            clauses.append("archived_at IS NULL")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
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

    def dependencies(self, task_id: str) -> tuple[str, ...]:
        with self.connect() as db:
            self.snapshot(db, task_id)
            return self._dependencies(db, task_id)

    def _blocked_by(self, db: sqlite3.Connection, task_id: str) -> tuple[str, ...]:
        return tuple(
            row[0] for row in db.execute(
                """SELECT d.depends_on FROM task_dependencies d
                   JOIN tasks t ON t.id=d.depends_on
                   WHERE d.task_id=? AND t.status != 'succeeded'
                   ORDER BY d.depends_on""",
                (task_id,),
            )
        )

    def blocked_by(self, task_id: str) -> tuple[str, ...]:
        with self.connect() as db:
            self.snapshot(db, task_id)
            return self._blocked_by(db, task_id)

    def ready(self, task_id: str) -> bool:
        return not self.blocked_by(task_id)

    def queued(self, limit: int) -> list[TaskSnapshot]:
        if not 1 <= limit <= 1000:
            raise TaskStateError("Kuyruk sınırı 1 ile 1000 arasında olmalıdır.")
        with self.connect() as db:
            return [TaskSnapshot.model_validate(dict(row)) for row in db.execute(
                f"""SELECT {TASK_COLUMNS} FROM tasks t
                    WHERE t.status='queued' AND t.enabled=1 AND t.archived_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM task_dependencies d
                          JOIN tasks dep ON dep.id=d.depends_on
                          WHERE d.task_id=t.id AND dep.status != 'succeeded'
                      )
                    ORDER BY t.priority DESC, t.created_at, t.id LIMIT ?""",
                (limit,),
            )]

    def edit(
        self, task_id: str, *, title: str | None = None,
        description: str | None = None, priority: int | None = None,
        enabled: bool | None = None, dependencies: tuple[str, ...] | None = None,
        prompt: str | None = None,
        verification: VerificationPlan | None | object = UNSET,
        reason: str = "edit",
    ) -> TaskSnapshot:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self.snapshot(db, task_id)
            if task.archived_at is not None:
                raise TaskStateError("Arşivlenmiş görev düzenlenemez.")
            if task.status == "running":
                raise TaskStateError("Çalışan görevin tanımı değiştirilemez.")
            if task.status == "succeeded":
                raise TaskStateError("Tamamlanmış görevin tanımı değiştirilemez.")
            current_definition = TaskDefinition.model_validate_json(
                db.execute(
                    "SELECT definition_json FROM tasks WHERE id=?", (task_id,),
                ).fetchone()[0]
            )
            if current_definition.team_run_id is not None:
                raise TaskStateError("Ekip alt görevi yalnız ekip koordinatöründen yönetilebilir.")
            changes: dict[str, Any] = {}
            if prompt is not None:
                changes["prompt"] = prompt
            if verification is not UNSET:
                changes["verification"] = verification
            if changes:
                try:
                    new_definition = TaskDefinition.model_validate({
                        **current_definition.model_dump(mode="python"), **changes,
                    })
                except ValidationError as error:
                    raise TaskStateError(
                        "Görev tanımı geçersiz: " + _validation_message(error)
                    ) from None
            else:
                new_definition = current_definition
            current_dependencies = self._dependencies(db, task_id)
            new_dependencies = (
                current_dependencies if dependencies is None else tuple(dependencies)
            )
            try:
                metadata = TaskMetadata(
                    title=task.title if title is None else title,
                    description=task.description if description is None else description,
                    priority=task.priority if priority is None else priority,
                    enabled=task.enabled if enabled is None else enabled,
                    dependencies=new_dependencies,
                )
            except ValidationError as error:
                raise TaskStateError("Görev metadatası geçersiz: " + _validation_message(error)) from None
            unchanged_metadata = TaskMetadata(
                title=task.title, description=task.description,
                priority=task.priority, enabled=task.enabled,
                dependencies=current_dependencies,
            )
            if (metadata == unchanged_metadata
                    and _core_definition(new_definition) == _core_definition(current_definition)):
                return task
            self._validate_dependencies(db, task_id, metadata.dependencies)
            payload = json.dumps(
                new_definition.model_dump(mode="json"), ensure_ascii=False, sort_keys=True,
            )
            core_payload = json.dumps(
                _core_definition(new_definition), ensure_ascii=False, sort_keys=True,
            )
            fingerprint = hashlib.sha256(core_payload.encode("utf-8")).hexdigest()
            now = utc_now()
            revision = task.definition_revision + 1
            db.execute(
                """UPDATE tasks SET title=?, description=?, priority=?, enabled=?,
                   definition_revision=?, updated_at=?, definition_json=?, fingerprint=?
                   WHERE id=?""",
                (
                    metadata.title, metadata.description, metadata.priority,
                    int(metadata.enabled), revision, now, payload, fingerprint, task_id,
                ),
            )
            self._set_dependencies(db, task_id, metadata.dependencies)
            self._insert_revision(
                db, task_id, revision, metadata, new_definition, now, reason,
            )
            return self.snapshot(db, task_id)

    def archive(self, task_id: str) -> TaskSnapshot:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self.snapshot(db, task_id)
            if task.archived_at is not None:
                return task
            if task.status in ("queued", "running"):
                raise TaskStateError("Sıradaki veya çalışan görev arşivlenemez; önce iptal edin.")
            now = utc_now()
            db.execute(
                "UPDATE tasks SET archived_at=?, updated_at=? WHERE id=?",
                (now, now, task_id),
            )
            return self.snapshot(db, task_id)

    def restore(self, task_id: str) -> TaskSnapshot:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self.snapshot(db, task_id)
            if task.archived_at is None:
                raise TaskStateError("Görev arşivlenmiş değil.")
            db.execute(
                "UPDATE tasks SET archived_at=NULL, updated_at=? WHERE id=?",
                (utc_now(), task_id),
            )
            return self.snapshot(db, task_id)

    def revisions(self, task_id: str) -> list[TaskRevision]:
        with self.connect() as db:
            self.snapshot(db, task_id)
            rows = db.execute(
                "SELECT * FROM task_revisions WHERE task_id=? ORDER BY revision",
                (task_id,),
            ).fetchall()
        return [
            TaskRevision(
                task_id=row["task_id"], revision=row["revision"], title=row["title"],
                description=row["description"], priority=row["priority"],
                enabled=bool(row["enabled"]),
                dependencies=tuple(json.loads(row["dependencies_json"])),
                definition=TaskDefinition.model_validate_json(row["definition_json"]),
                created_at=row["created_at"], reason=row["reason"],
            )
            for row in rows
        ]

    def retry(self, task_id: str) -> TaskSnapshot:
        if self.definition(task_id).team_run_id is not None:
            raise TaskStateError("Ekip alt görevi tek başına yeniden çalıştırılamaz; yeni ekip çalışması oluşturun.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self.snapshot(db, task_id)
            if task.archived_at is not None:
                raise TaskStateError("Arşivlenmiş görev yeniden sıraya alınamaz; önce geri yükleyin.")
            if task.status not in ("failed", "interrupted", "cancelled"):
                raise TaskStateError("Yalnız başarısız, kesilmiş veya iptal edilmiş görev yeniden sıraya alınabilir.")
            db.execute("UPDATE tasks SET status='queued', updated_at=? WHERE id=?", (utc_now(), task_id))
            return self.snapshot(db, task_id)

    def request_cancel(self, task_id: str) -> TaskSnapshot:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self.snapshot(db, task_id)
            if task.archived_at is not None:
                raise TaskStateError("Arşivlenmiş görev iptal edilemez.")
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
            if db.execute("SELECT 1 FROM cancellations WHERE run_id=?", (run_id,)).fetchone() is not None:
                return True
            row = db.execute("SELECT t.definition_json FROM tasks t JOIN runs r ON t.id=r.task_id WHERE r.id=?", (run_id,)).fetchone()
            definition = TaskDefinition.model_validate_json(row[0]) if row else None
            if definition is None or definition.team_run_id is None:
                return False
            row = db.execute("SELECT record_json FROM team_runs WHERE id=?", (definition.team_run_id,)).fetchone()
            parent = json.loads(row[0]) if row else None
            if parent is None or parent["status"] != "running":
                return True
            return datetime.now(timezone.utc).timestamp() >= (
                datetime.fromisoformat(parent["started_at"]).timestamp() + parent["spec"]["budget"]["timeout_seconds"])

    def claim(self, task_id: str) -> RunSnapshot:
        run_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self.snapshot(db, task_id)
            if task.status != "queued":
                raise TaskStateError("Yalnız sıradaki görev çalıştırılabilir; yeniden denemek için retry kullanın.")
            if task.archived_at is not None:
                raise TaskStateError("Arşivlenmiş görev çalıştırılamaz.")
            if not task.enabled:
                raise TaskStateError("Görev devre dışı; çalıştırmak için önce etkinleştirin.")
            blocked = self._blocked_by(db, task_id)
            if blocked:
                raise TaskStateError(
                    "Görev bağımlı olduğu görevler tamamlanmadan çalıştırılamaz: "
                    + ", ".join(blocked)
                )
            definition = TaskDefinition.model_validate_json(db.execute(
                "SELECT definition_json FROM tasks WHERE id=?", (task_id,),
            ).fetchone()[0])
            if definition.team_run_id:
                row = db.execute("SELECT record_json FROM team_runs WHERE id=?", (definition.team_run_id,)).fetchone()
                parent = json.loads(row[0]) if row else None
                if parent is None or parent["status"] != "running":
                    raise TaskStateError("Ekip çalışması etkin değil.")
                deadline = datetime.fromisoformat(parent["started_at"]).timestamp() + parent["spec"]["budget"]["timeout_seconds"]
                if datetime.now(timezone.utc).timestamp() >= deadline:
                    raise TaskStateError("Ekip çalışma süresi doldu.")
            connection = definition.config.connections[definition.connection_id]
            provider = "programmatic" if definition.programmatic else connection.provider
            model = definition.programmatic.handler if definition.programmatic else connection.model
            db.execute("UPDATE tasks SET status='running', updated_at=? WHERE id=?", (now, task_id))
            db.execute("INSERT INTO runs (id, task_id, status, provider, model, started_at) VALUES (?, ?, 'running', ?, ?, ?)",
                       (run_id, task_id, provider, model, now))
        return RunSnapshot(id=run_id, task_id=task_id, status="running", provider=provider,
                           model=model, started_at=now)

    def succeed(
        self, run_id: str, result: RunResult, duration_seconds: float,
        *, verification: VerificationRecord | None = None,
    ) -> RunSnapshot:
        if verification is not None and verification.status != "passed":
            raise TaskStateError("Başarılı çalışma yalnız geçmiş doğrulama kaydıyla kapatılabilir.")
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
            if verification is not None:
                self._insert_verification(db, row[0], run_id, verification)
        return self.run(run_id)

    def fail_verification(
        self, run_id: str, result: RunResult, duration_seconds: float,
        verification: VerificationRecord,
    ) -> RunSnapshot:
        if verification.status == "passed":
            raise TaskStateError("Geçmiş doğrulama kaydı başarısız sonuç olarak yazılamaz.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT task_id FROM runs WHERE id=? AND status='running'", (run_id,)).fetchone()
            if row is None:
                raise TaskStateError("Çalışma aktif değil.")
            now = utc_now()
            cancelled = db.execute("SELECT 1 FROM cancellations WHERE run_id=?", (run_id,)).fetchone() is not None
            status = "cancelled" if cancelled else "failed"
            error_code = "cancelled" if cancelled else f"verification_{verification.status}"
            db.execute("INSERT INTO results VALUES (?, ?)", (run_id, result.model_dump_json()))
            db.execute(
                "UPDATE runs SET status=?, finished_at=?, duration_seconds=?, usage_json=?, error_code=? WHERE id=?",
                (status, now, duration_seconds, result.usage.model_dump_json(), error_code, run_id),
            )
            db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, now, row[0]))
            self._insert_verification(db, row[0], run_id, verification)
        return self.run(run_id)

    def _insert_verification(
        self, db: sqlite3.Connection, task_id: str, run_id: str,
        record: VerificationRecord,
    ) -> None:
        if record.task_id != task_id or record.run_id != run_id:
            raise TaskStateError("Doğrulama kaydı görevle eşleşmiyor.")
        db.execute(
            "INSERT INTO verifications (run_id, task_id, status, record_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (record.run_id, task_id, record.status, record.model_dump_json(), record.created_at),
        )

    def verification(self, run_id: str) -> VerificationRecord | None:
        with self.connect() as db:
            row = db.execute("SELECT record_json FROM verifications WHERE run_id=?", (run_id,)).fetchone()
        return VerificationRecord.model_validate_json(row[0]) if row else None

    def verifications(self, task_id: str) -> list[VerificationRecord]:
        self.get(task_id)
        with self.connect() as db:
            return [
                VerificationRecord.model_validate_json(row[0])
                for row in db.execute(
                    "SELECT record_json FROM verifications WHERE task_id=? ORDER BY created_at, run_id",
                    (task_id,),
                )
            ]

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

    def record_artifacts(
        self, run_id: str, agent_id: str, drafts: tuple[ArtifactDraft, ...], *,
        producer: str = "workspace_scan", upsert: bool = False,
    ) -> None:
        if not drafts:
            return
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT task_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise TaskStateError("Artifact için çalışma bulunamadı.")
            created_at = utc_now()
            for draft in drafts:
                relative = PurePosixPath(draft.path)
                if (relative.is_absolute() or ".." in relative.parts or not draft.path
                        or ":" in draft.path or "\\" in draft.path):
                    raise TaskStateError("Artifact yolu workspace'e göre göreli olmalıdır.")
                conflict = (
                    "ON CONFLICT(run_id, path) DO UPDATE SET "
                    "sha256=excluded.sha256, size_bytes=excluded.size_bytes, "
                    "producer=excluded.producer"
                ) if upsert else ""
                verb = "INSERT" if upsert else "INSERT OR IGNORE"
                db.execute(
                    f"""{verb} INTO artifacts
                       (id, task_id, run_id, agent_id, path, sha256, size_bytes, producer, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) {conflict}""",
                    (
                        uuid.uuid4().hex, row["task_id"], run_id, agent_id, draft.path,
                        draft.sha256, draft.size_bytes, producer, created_at,
                    ),
                )

    def artifacts(self, task_id: str) -> list[Artifact]:
        self.get(task_id)
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM artifacts WHERE task_id=? ORDER BY path, run_id", (task_id,),
            )
            return [Artifact.model_validate(dict(row)) for row in rows]
