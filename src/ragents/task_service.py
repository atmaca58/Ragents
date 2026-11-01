from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
import asyncio
import time

from filelock import FileLock, Timeout

from ragents.application import run_task
from ragents.config import ProjectConfig
from ragents.contracts import RunResult
from ragents.errors import (
    AuthError, ContextLimitError, ProviderAccessError, SandboxError, WorkspaceError,
)
from ragents.storage import RunSnapshot, TaskDefinition, TaskStateError, TaskStore
from ragents.mcp_client import MCPAccessError
from ragents.verification import VerificationRecord, Verifier
from ragents.workspace import Workspace, WorkspaceGrant
from ragents.execution_locks import execution_resources
from ragents.programmatic import run_programmatic


Runner = Callable[
    [ProjectConfig, str, str | None, WorkspaceGrant | None], Awaitable[RunResult]
]


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
        resources = AsyncExitStack()
        try:
            await resources.enter_async_context(execution_resources(self.store, task_id))
            run = self.store.claim(task_id)
            definition = self.store.definition(task_id)
            started = time.perf_counter()
            try:
                workspace = (
                    Workspace(definition.workspace.root, definition.workspace.protected_paths)
                    if definition.workspace is not None else None
                )
                before = await asyncio.to_thread(workspace.snapshot) if workspace else None
                result = await self.invoke(run.id, definition)
                if workspace is not None and before is not None:
                    drafts = await asyncio.to_thread(workspace.collect_artifacts, before)
                    if drafts:
                        self.store.record_artifacts(run.id, definition.config.agent.id, drafts)
                if result.artifacts:
                    self.store.record_artifacts(
                        run.id, definition.config.agent.id, result.artifacts,
                        producer="file_tool", upsert=True,
                    )
                verification = await self.verify(
                    run.id, task_id, definition, workspace, result,
                )
                if definition.workspace is not None:
                    from ragents.artifact_store import ArtifactStore
                    parent = self.store.path.parent
                    root = parent.parent if parent.name == "data" else parent
                    await asyncio.to_thread(ArtifactStore(root, self.store).capture, run.id,
                                            definition.workspace, verification.status if verification else "unverified")
                if verification is not None and verification.status != "passed":
                    return self.store.fail_verification(
                        run.id, result, time.perf_counter() - started, verification,
                    )
            except (asyncio.CancelledError, KeyboardInterrupt):
                self.store.fail(run.id, "cancelled", time.perf_counter() - started, status="cancelled")
                raise
            except Exception as error:
                self.store.fail(run.id, failure_code(error), time.perf_counter() - started)
                raise
            return self.store.succeed(
                run.id, result, time.perf_counter() - started, verification=verification,
            )
        finally:
            try:
                await resources.aclose()
            finally:
                lock.release()

    async def invoke(self, run_id: str, definition: TaskDefinition) -> RunResult:
        self.check_cancellation(run_id)
        watcher = asyncio.create_task(self.watch_cancellation(run_id, asyncio.current_task()))
        try:
            async with asyncio.timeout(definition.config.agent.budget.timeout_seconds):
                if definition.programmatic is not None:
                    return await run_programmatic(definition.programmatic, definition.config.agent.id,
                                                  definition.workspace)
                return await self.runner(
                    definition.config, definition.prompt, definition.connection_id,
                    definition.workspace,
                )
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    async def verify(
        self, run_id: str, task_id: str, definition: TaskDefinition,
        workspace: Workspace | None, result: RunResult,
    ) -> VerificationRecord | None:
        if definition.verification is None:
            return None
        self.check_cancellation(run_id)
        watcher = asyncio.create_task(self.watch_cancellation(run_id, asyncio.current_task()))
        try:
            return await Verifier(workspace, definition.workspace).run(
                definition.verification, result, run_id=run_id, task_id=task_id,
            )
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    async def watch_cancellation(self, run_id: str, execution: asyncio.Task) -> None:
        while True:
            if self.store.cancellation_requested(run_id):
                execution.cancel()
                return
            await asyncio.sleep(0.1)

    def check_cancellation(self, run_id: str) -> None:
        if self.store.cancellation_requested(run_id):
            raise asyncio.CancelledError

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
    codes = {
        TimeoutError: "timeout", ContextLimitError: "context_limit", AuthError: "auth",
        MCPAccessError: "mcp", SandboxError: "sandbox", WorkspaceError: "workspace",
    }
    return next((code for kind, code in codes.items() if isinstance(error, kind)), "execution_failed")
