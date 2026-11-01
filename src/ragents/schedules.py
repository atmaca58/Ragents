"""Kalıcı, tek slot telafili görev takvimi. Zamanı gelmeyen iş model çağırmaz."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import uuid

from croniter import croniter
from filelock import FileLock, Timeout
from pydantic import Field, model_validator

from ragents.config import Spec
from ragents.storage import TaskDefinition, TaskMetadata, TaskStateError, TaskStore


def utc_time(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise TaskStateError("Takvim zamanı saat dilimi içermelidir.")
    return current.astimezone(timezone.utc)


class ScheduleTiming(Spec):
    cron: str | None = Field(default=None, max_length=100)
    at: datetime | None = None
    timezone: str = Field(default="Europe/Istanbul", min_length=1, max_length=100)
    catch_up: bool = True

    @model_validator(mode="after")
    def validate_timing(self):
        if (self.cron is None) == (self.at is None):
            raise ValueError("Tek seferlik at veya cron alanından yalnız biri gereklidir.")
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Saat dilimi tanınmıyor.") from None
        if self.cron is not None and (len(self.cron.split()) != 5 or not croniter.is_valid(self.cron)):
            raise ValueError("Cron beş alanlı geçerli bir ifade olmalıdır.")
        if self.at is not None and self.at.tzinfo is None:
            raise ValueError("Tek seferlik zaman saat dilimi içermelidir.")
        return self

    def next_after(self, current: datetime) -> str | None:
        if self.at is not None:
            return None
        local = current.astimezone(ZoneInfo(self.timezone))
        return croniter(self.cron, local).get_next(datetime).astimezone(timezone.utc).isoformat()


class ScheduleSnapshot(Spec):
    id: str
    template_task_id: str
    timing: ScheduleTiming
    next_at: str | None
    enabled: bool
    revision: int


class ScheduleService:
    def __init__(self, store: TaskStore):
        self.store = store

    def lock(self):
        return FileLock(self.store.path.with_suffix(".schedules.lock"), timeout=0)

    def create(self, template_task_id: str, timing: ScheduleTiming, *, now: datetime | None = None) -> ScheduleSnapshot:
        current = utc_time(now)
        task = self.store.get(template_task_id)
        if task.enabled or task.status != "queued" or task.archived_at is not None:
            raise TaskStateError("Takvim şablonu devre dışı ve sırada bir görev olmalıdır.")
        definition = self.store.definition(task.id)
        metadata = TaskMetadata(title=task.title, description=task.description, priority=task.priority,
                                dependencies=self.store.dependencies(task.id))
        next_at = utc_time(timing.at).isoformat() if timing.at is not None else timing.next_after(current)
        identity = uuid.uuid4().hex
        with self.lock(), self.store.connect() as db:
            db.execute("INSERT INTO schedules VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?)", (
                identity, task.id, timing.model_dump_json(), definition.model_dump_json(),
                metadata.model_dump_json(), next_at, current.isoformat(),
            ))
        return self.get(identity)

    @staticmethod
    def snapshot(row) -> ScheduleSnapshot:
        return ScheduleSnapshot(id=row["id"], template_task_id=row["template_task_id"],
                                timing=ScheduleTiming.model_validate_json(row["timing_json"]),
                                next_at=row["next_at"], enabled=bool(row["enabled"]), revision=row["revision"])

    def get(self, identity: str) -> ScheduleSnapshot:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM schedules WHERE id=?", (identity,)).fetchone()
            if row is None:
                raise TaskStateError("Takvim kaydı bulunamadı.")
            return self.snapshot(row)

    def list(self) -> list[ScheduleSnapshot]:
        with self.store.connect() as db:
            return [self.snapshot(row) for row in db.execute("SELECT * FROM schedules ORDER BY created_at LIMIT 1000")]

    def set_enabled(self, identity: str, enabled: bool, revision: int) -> ScheduleSnapshot:
        with self.lock(), self.store.connect() as db:
            changed = db.execute("UPDATE schedules SET enabled=?, revision=revision+1 WHERE id=? AND revision=?",
                                 (int(enabled), identity, revision)).rowcount
            if not changed:
                raise TaskStateError("Takvim bulunamadı veya revizyon değişti.")
        return self.get(identity)

    def tick(self, *, now: datetime | None = None) -> list[str]:
        current = utc_time(now)
        lock = self.lock()
        try:
            lock.acquire()
        except Timeout:
            return []
        try:
            with self.store.connect() as db:
                rows = db.execute("SELECT * FROM schedules WHERE enabled=1 AND next_at<=? ORDER BY next_at LIMIT 100",
                                  (current.isoformat(),)).fetchall()
            fired = []
            for row in rows:
                task_id = self._fire(row, current)
                if task_id is not None:
                    fired.append(task_id)
            return fired
        finally:
            lock.release()

    def _fire(self, row, current: datetime) -> str | None:
        timing = ScheduleTiming.model_validate_json(row["timing_json"])
        due = datetime.fromisoformat(row["next_at"])
        next_at = timing.next_after(current)
        task_id = None
        if timing.catch_up or current - due <= timedelta(minutes=1):
            # Uzun kesintide yalnız en son slot telafi edilir; sonsuz geri tarama yok.
            slot = due
            if timing.cron is not None:
                local = (current + timedelta(microseconds=1)).astimezone(ZoneInfo(timing.timezone))
                slot = croniter(timing.cron, local).get_prev(datetime).astimezone(timezone.utc)
            definition = TaskDefinition.model_validate_json(row["definition_json"])
            metadata = TaskMetadata.model_validate_json(row["metadata_json"])
            task = self.store.enqueue(
                definition.config, definition.prompt, definition.connection_id,
                instruction=definition.instruction, workspace=definition.workspace,
                verification=definition.verification,
                programmatic=definition.programmatic,
                idempotency_key=f"schedule:{row['id']}:{slot.isoformat()}",
                **metadata.model_dump(),
            )
            task_id = task.id
            with self.store.connect() as db:
                db.execute("INSERT OR IGNORE INTO schedule_fires VALUES (?, ?, ?, ?)",
                           (row["id"], slot.isoformat(), row["revision"], task_id))
        with self.store.connect() as db:
            db.execute("UPDATE schedules SET next_at=?, enabled=? WHERE id=? AND revision=?",
                       (next_at, int(next_at is not None), row["id"], row["revision"]))
        return task_id
