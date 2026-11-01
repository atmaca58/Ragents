from datetime import datetime, timezone
from pathlib import Path

from ragents.config import load_config
from ragents.storage import TaskStore
import pytest


def test_schedule_survives_restart_and_fires_missed_slot_only_once(tmp_path):
    from ragents.schedules import ScheduleService, ScheduleTiming

    store = TaskStore(tmp_path / "tasks.db")
    template = store.enqueue(load_config(Path("examples/ollama.yaml")), "Günlük rapor", enabled=False)
    start = datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc)
    service = ScheduleService(store)
    schedule = service.create(template.id, ScheduleTiming(cron="0 9 * * *", timezone="Europe/Istanbul"), now=start)
    restarted = ScheduleService(TaskStore(store.path))
    after = datetime(2026, 11, 3, 7, 0, tzinfo=timezone.utc)
    fired = restarted.tick(now=after)
    assert len(fired) == 1
    assert restarted.tick(now=after) == []
    assert len(store.queued(100)) == 1
    assert store.get(template.id).enabled is False
    assert restarted.get(schedule.id).next_at == "2026-11-04T06:00:00+00:00"


def test_crash_after_enqueue_does_not_duplicate_one_time_job(tmp_path, monkeypatch):
    from ragents.schedules import ScheduleService, ScheduleTiming

    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "Rapor", enabled=False)
    service = ScheduleService(store)
    now = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)
    schedule = service.create(task.id, ScheduleTiming(at=now), now=now)
    enqueue = store.enqueue

    def crash(*args, **kwargs):
        enqueue(*args, **kwargs)
        raise RuntimeError("simulated crash after durable enqueue")

    monkeypatch.setattr(store, "enqueue", crash)
    with pytest.raises(RuntimeError):
        service.tick(now=now)
    restarted = ScheduleService(TaskStore(store.path))
    assert len(restarted.tick(now=now)) == 1
    assert len(store.queued(100)) == 1
    assert restarted.get(schedule.id).enabled is False


def test_no_catch_up_skips_old_slots_without_queuing(tmp_path):
    from ragents.schedules import ScheduleService, ScheduleTiming

    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue(load_config(Path("examples/ollama.yaml")), "Rapor", enabled=False)
    start = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)
    service = ScheduleService(store)
    record = service.create(task.id, ScheduleTiming(at=start, catch_up=False), now=start)
    assert service.tick(now=datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)) == []
    assert store.queued(100) == []
    assert service.get(record.id).enabled is False
