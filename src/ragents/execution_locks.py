"""Aynı makinedeki manuel ve worker işleri için ortak kaynak kilitleri."""
from contextlib import asynccontextmanager, ExitStack
import asyncio
import getpass
import hashlib
import os
from pathlib import Path
import tempfile

from filelock import FileLock, Timeout

from ragents.storage import TaskDefinition, TaskStateError, TaskStore


def resource_keys(store: TaskStore, definition: TaskDefinition) -> tuple[str, ...]:
    namespace = os.path.normcase(str(store.path.parent.resolve()))
    keys = [f"agent:{namespace}:{definition.config.agent.id}"]
    if definition.workspace is not None:
        keys.append("workspace:" + os.path.normcase(str(definition.workspace.root.resolve())))
    return tuple(sorted(keys))


def resource_lock(key: str) -> FileLock:
    # Veritabanı/profile kökünden bağımsız: iki ayrı DB aynı projeye yazabilir.
    user = hashlib.sha256(getpass.getuser().encode()).hexdigest()[:16]
    directory = Path(tempfile.gettempdir()) / f"ragents-locks-{user}"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return FileLock(directory / f"{digest}.lock", timeout=0)


def resources_available(keys: tuple[str, ...]) -> bool:
    try:
        with ExitStack() as stack:
            for key in keys:
                stack.enter_context(resource_lock(key))
            return True
    except Timeout:
        return False


@asynccontextmanager
async def execution_resources(store: TaskStore, task_id: str):
    definition = store.definition(task_id)
    locks = [resource_lock(key) for key in resource_keys(store, definition)]
    acquired = []
    try:
        for lock in locks:
            while True:
                task = store.get(task_id)
                if (task.status != "queued" or not task.enabled
                        or task.archived_at is not None or not store.ready(task_id)):
                    raise TaskStateError("Görev artık çalıştırılabilir durumda değil.")
                try:
                    lock.acquire()
                    acquired.append(lock)
                    break
                except Timeout:
                    await asyncio.sleep(0.05)
        yield
    finally:
        for lock in reversed(acquired):
            lock.release()
