import asyncio

from filelock import FileLock, Timeout
from pydantic import Field

from ragents.config import Spec
from ragents.storage import TaskStateError
from ragents.task_service import TaskService


class WorkerOptions(Spec):
    concurrency: int = Field(default=2, ge=1, le=64)
    poll_seconds: float = Field(default=0.5, ge=0.01, le=60)
    shutdown_seconds: float = Field(default=10, ge=0, le=3600)


class Worker:
    def __init__(self, service: TaskService, options: WorkerOptions | None = None):
        self.service = service
        self.options = options or WorkerOptions()
        self.active: dict[str, asyncio.Task] = {}

    async def run(self, *, stop: asyncio.Event | None = None, once: bool = False) -> None:
        stop = stop or asyncio.Event()
        path = self.service.store.path
        # Tek supervisor: aynı DB için ikinci worker farklı bir limit açamaz.
        lock = FileLock(path.with_name(path.name + ".worker.lock"), timeout=0)
        try:
            lock.acquire()
        except Timeout:
            raise TaskStateError("Bu veritabanı için worker zaten çalışıyor.") from None
        try:
            self.service.recover()
            await self.dispatch(stop, once)
        finally:
            try:
                await self.shutdown()
            finally:
                lock.release()

    async def dispatch(self, stop: asyncio.Event, once: bool) -> None:
        while not stop.is_set():
            self.reap()
            capacity = self.options.concurrency - len(self.active)
            queued = self.service.store.queued(capacity) if capacity else []
            for task in queued:
                self.active[task.id] = asyncio.create_task(self.service.execute(task.id))
            if once and not queued and not self.active:
                return
            try:
                await asyncio.wait_for(stop.wait(), self.options.poll_seconds)
            except TimeoutError:
                pass

    def reap(self) -> None:
        for task_id, execution in list(self.active.items()):
            if execution.done():
                if not execution.cancelled():
                    execution.exception()  # Hata TaskService tarafından güvenli kodla kaydedildi.
                del self.active[task_id]

    async def shutdown(self) -> None:
        executions = list(self.active.values())
        if not executions:
            return
        _, pending = await asyncio.wait(executions, timeout=self.options.shutdown_seconds)
        for execution in pending:
            execution.cancel()
        await asyncio.gather(*executions, return_exceptions=True)
        self.active.clear()
