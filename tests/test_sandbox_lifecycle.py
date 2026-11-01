import asyncio
import threading
import os
import sys
import pytest

from ragents.sandbox import Sandbox, SandboxPolicy, SandboxResult


class BarrierBackend:
    name = "barrier"

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def availability(self):
        self.entered.set()
        assert self.release.wait(5)
        return True, None

    def run(self, argv, policy, *, input, control):
        self.calls.append(tuple(argv))
        return SandboxResult(backend=self.name, workspace=str(policy.workspace),
                             exit_code=0, stdout="ok", stderr="", duration_ms=0)


def test_cancel_during_backend_preparation_never_launches_command(tmp_path):
    backend = BarrierBackend()
    sandbox = Sandbox(SandboxPolicy(workspace=tmp_path), backend=backend)

    async def scenario():
        execution = asyncio.create_task(sandbox.run_async(["python", "-V"]))
        assert await asyncio.to_thread(backend.entered.wait, 5)
        execution.cancel()
        await asyncio.sleep(0)
        backend.release.set()
        await asyncio.gather(execution, return_exceptions=True)
        await asyncio.to_thread(lambda: None)

    asyncio.run(scenario())
    assert backend.calls == []


@pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer testi")
def test_reused_windows_backend_does_not_reuse_previous_workspace_permissions(tmp_path):
    from ragents.sandbox_windows import WindowsAppContainerBackend

    backend = WindowsAppContainerBackend()
    first = tmp_path / "first"
    first.mkdir()
    result = Sandbox(SandboxPolicy(workspace=first, writable=True), backend=backend).run(
        [sys.executable, "-c", "open('secret.txt', 'w').write('private')"])
    assert result.exit_code == 0, result.stderr
    script = "try:\n open('secret.txt', 'w').write('changed')\n print('allowed')\nexcept PermissionError:\n print('denied')"
    result = Sandbox(SandboxPolicy(workspace=first), backend=backend).run([sys.executable, "-c", script])
    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == "denied"


def test_posix_cleanup_kills_group_even_after_parent_exited(monkeypatch):
    from ragents.sandbox_posix import terminate_process_group
    from types import SimpleNamespace
    import signal

    calls = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: calls.append((pid, sig)), raising=False)
    monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)
    parent = SimpleNamespace(pid=42, poll=lambda: 0)
    terminate_process_group(parent)
    assert calls == [(42, 9)]
