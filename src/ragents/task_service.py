from collections.abc import Awaitable, Callable
import asyncio
import time

from filelock import FileLock, Timeout

from ragents.application import run_task
from ragents.config import ProjectConfig
from ragents.contracts import RunResult
from ragents.errors import AuthError, ContextLimitError, ProviderAccessError
from ragents.storage import RunSnapshot, TaskDefinition, TaskStateError, TaskStore
from ragents.mcp_client import MCPAccessError


Runner = Callable[[ProjectConfig, str, str | None], Awaitable[RunResult]]


class TaskService:
    def __init__(self, store: TaskStore, *, runner: Runner = run_task):
        self.store = store
        self.runner = runner

    def lock(self, task_id: str) -> FileLock:
        # Kimlik yalnız veritabanındaki kayıttan gelir; kullanıcı yolu olarak kullanılmaz.
        task = self.store.get(task_id)
        directory = self.store.path.parent / "locks"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return FileLock(directory / f"task-{task.id}.lock", timeout=0)

    async def execute(self, task_id: str) -> RunSnapshot:
        lock = self.lock(task_id)
        try:
            lock.acquire()
        except Timeout:
            raise TaskStateError("Görev başka bir işlemde çalışıyor.") from None
        try:
            run = self.store.claim(task_id)
            definition = self.store.definition(task_id)
            started = time.perf_counter()
            try:
                result = await self.invoke(run.id, definition)
            except (asyncio.CancelledError, KeyboardInterrupt):
                self.store.fail(run.id, "cancelled", time.perf_counter() - started, status="cancelled")
                raise
            except Exception as error:
                self.store.fail(run.id, failure_code(error), time.perf_counter() - started)
                raise
            return self.store.succeed(run.id, result, time.perf_counter() - started)
        finally:
            lock.release()

    async def invoke(self, run_id: str, definition: TaskDefinition) -> RunResult:
        watcher = asyncio.create_task(self.watch_cancellation(run_id, asyncio.current_task()))
        try:
            async with asyncio.timeout(definition.config.agent.budget.timeout_seconds):
                return await self.runner(definition.config, definition.prompt, definition.connection_id)
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    async def watch_cancellation(self, run_id: str, execution: asyncio.Task) -> None:
        while True:
            if self.store.cancellation_requested(run_id):
                execution.cancel()
                return
            await asyncio.sleep(0.1)

    def recover(self) -> list[str]:
        recovered = []
        for task in self.store.list(status="running", limit=1000):
            lock = self.lock(task.id)
            try:
                lock.acquire()
            except Timeout:
                continue
            try:
                if self.store.get(task.id).status != "running":
                    continue
                for run in self.store.runs(task.id):
                    if run.status == "running":
                        self.store.fail(run.id, "process_interrupted", None, status="interrupted")
                recovered.append(task.id)
            finally:
                lock.release()
        return recovered


def failure_code(error: Exception) -> str:
    if isinstance(error, ProviderAccessError):
        return f"provider_http_{error.status_code}"
    codes = {TimeoutError: "timeout", ContextLimitError: "context_limit", AuthError: "auth", MCPAccessError: "mcp"}
    return next((code for kind, code in codes.items() if isinstance(error, kind)), "execution_failed")
