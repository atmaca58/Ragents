"""macOS Seatbelt ve Linux bubblewrap sandbox backend'leri."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any

try:
    import resource
except ImportError:  # Windows'ta bu modül yalnız test/keşif için içe aktarılabilir.
    resource = None  # type: ignore[assignment]

from ragents.errors import SandboxError
from ragents.sandbox import (
    OutputCollector, SandboxCapabilities, SandboxControl, SandboxPolicy, SandboxResult,
    cleanup_temp_dir, create_temp_dir, resolve_executable, sandbox_environment,
)


def terminate_process_group(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass


class PosixSandboxBackend:
    """Ortak POSIX süreç, çıktı, zaman aşımı ve iptal davranışı."""

    name = "posix"
    notes: tuple[str, ...] = ()

    def __init__(self, binary: Path | None = None):
        self.binary = binary

    def _binary(self) -> Path | None:
        return self.binary

    def availability(self) -> tuple[bool, str | None]:
        if os.name == "nt":
            return False, "POSIX sandbox backend'i Windows'ta kullanılamaz."
        binary = self._binary()
        if binary is None or not binary.is_file():
            return False, self._missing_message()
        if not os.access(binary, os.X_OK):
            return False, f"Sandbox backend'i çalıştırılabilir değil: {binary}"
        return True, None

    def _missing_message(self) -> str:
        return "POSIX sandbox backend'i bulunamadı."

    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            backend=self.name, filesystem=True, network=True, process=True,
            resources=True, hard_cancel=True, read_isolation=False, notes=self.notes,
        )

    def _command(
        self, argv: Sequence[str], policy: SandboxPolicy, root: Path, temp: Path,
        environment: dict[str, str],
    ) -> list[str]:
        raise NotImplementedError

    def _preexec(self, policy: SandboxPolicy):
        if resource is None:
            return None

        def apply() -> None:
            try:
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            except (OSError, ValueError):
                pass
            cpu = max(1, int(policy.timeout_seconds) + 1)
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
            except (OSError, ValueError):
                pass
            if sys.platform.startswith("linux"):
                memory = policy.max_memory_mb * 1024 * 1024
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
                except (OSError, ValueError):
                    pass

        return apply

    def run(
        self, argv: Sequence[str], policy: SandboxPolicy, *,
        input: bytes | None = None, control: SandboxControl,
    ) -> SandboxResult:
        available, reason = self.availability()
        if not available:
            raise SandboxError(reason or "Sandbox backend kullanılamıyor.")
        root = policy.checked_root()
        temp = create_temp_dir()
        binary = self._binary()
        if binary is None:
            raise SandboxError(self._missing_message())
        environment = sandbox_environment(
            policy, temp,
            path=":".join((str(Path(sys.executable).parent), "/usr/local/bin", "/usr/bin",
                           "/bin", "/usr/sbin", "/sbin")),
        )
        executable = resolve_executable(argv, path=environment["PATH"], cwd=root)
        command = [*self._command([str(executable), *argv[1:]], policy, root, temp, environment)]
        started = time.perf_counter()
        process: subprocess.Popen[bytes] | None = None
        reader_threads: list[threading.Thread] = []
        writer_thread: threading.Thread | None = None
        stdout_collector: OutputCollector | None = None
        stderr_collector: OutputCollector | None = None
        timed_out = False
        cancelled = False
        def terminate() -> None:
            terminate_process_group(process)

        terminator = terminate
        try:
            with control.launching():
                process = subprocess.Popen(
                    command, cwd=policy.checked_cwd(), env=environment,
                    stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    start_new_session=True, preexec_fn=self._preexec(policy), close_fds=True,
                )
                control.register(terminate)

            def on_output_limit() -> None:
                terminate()

            if process.stdout is None or process.stderr is None:
                raise SandboxError("Sandbox çıktı boruları açılamadı.")
            stdout_collector = OutputCollector(policy.max_output_bytes, on_output_limit)
            stderr_collector = OutputCollector(policy.max_output_bytes, on_output_limit)
            for stream, collector in (
                (process.stdout, stdout_collector), (process.stderr, stderr_collector),
            ):
                thread = threading.Thread(target=collector.pump, args=(stream,), daemon=True)
                thread.start()
                reader_threads.append(thread)
            if input is not None and process.stdin is not None:
                def write_input() -> None:
                    try:
                        process.stdin.write(input)
                        process.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass

                writer_thread = threading.Thread(target=write_input, daemon=True)
                writer_thread.start()

            control.register(terminate)
            deadline = time.monotonic() + policy.timeout_seconds
            while True:
                if control.cancelled.is_set():
                    cancelled = True
                    terminate()
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    terminate()
                    break
                try:
                    process.wait(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if control.cancelled.is_set():
                cancelled = True
            if process.poll() is None:
                terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            terminate()
            control.unregister(terminator)
            if process is not None:
                for thread in reader_threads:
                    thread.join(timeout=5)
                if writer_thread is not None:
                    writer_thread.join(timeout=5)
                for stream in (process.stdout, process.stderr, process.stdin):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass
                if process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
            cleanup_temp_dir(temp)

        if stdout_collector is None or stderr_collector is None or process is None:
            raise SandboxError("Sandbox alt süreci başlatılamadı.")
        return SandboxResult(
            backend=self.name, workspace=str(root), exit_code=process.returncode,
            stdout=stdout_collector.text(), stderr=stderr_collector.text(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            timed_out=timed_out, cancelled=cancelled,
            output_truncated=stdout_collector.truncated or stderr_collector.truncated,
            network_allowed=policy.network,
            writable=bool(policy.checked_writable_paths()),
            writable_paths=tuple(str(path) for path in policy.checked_writable_paths()),
        )


class MacOSSeatbeltBackend(PosixSandboxBackend):
    name = "macos-seatbelt"
    notes = (
        "sandbox-exec yazma ve ağ kurallarını uygular; okuma izolasyonu bu backend'de yoktur.",
        "Süreç ağacı yeni oturum/process group ile sonlandırılır; süreç sayısı üst sınırı yoktur.",
    )

    def __init__(self, binary: Path | None = None):
        super().__init__(binary or Path("/usr/bin/sandbox-exec"))

    def _missing_message(self) -> str:
        return (
            "macOS Seatbelt backend'i (/usr/bin/sandbox-exec) bulunamadı. "
            "Desteklenmeyen platformda sandbox olmadan çalıştırma yapılmaz."
        )

    def _command(
        self, argv: Sequence[str], policy: SandboxPolicy, root: Path, temp: Path,
        environment: dict[str, str],
    ) -> list[str]:
        binary = self._binary()
        if binary is None:
            raise SandboxError(self._missing_message())
        return [str(binary), "-p", seatbelt_profile(policy, root, temp), "--", *argv]


def seatbelt_profile(policy: SandboxPolicy, root: Path, temp: Path) -> str:
    def quote(value: Path) -> str:
        text = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{text}"'

    lines = ["(version 1)", "(allow default)"]
    if not policy.network:
        lines.append("(deny network*)")
    lines.append("(deny file-write*)")
    allowed = ["  (subpath " + quote(temp) + ")", '  (literal "/dev/null")',
               '  (literal "/dev/stdout")', '  (literal "/dev/stderr")']
    for writable in policy.checked_writable_paths():
        if writable != temp:
            allowed.insert(0, "  (subpath " + quote(writable) + ")")
    lines.append("(allow file-write*")
    lines.extend(allowed)
    lines.append(")")
    return "\n".join(lines) + "\n"


class LinuxBubblewrapBackend(PosixSandboxBackend):
    name = "linux-bubblewrap"
    notes = (
        "bubblewrap ağ, PID/IPC/UTS namespace'lerini ve yazma sınırlarını uygular; "
        "kök salt okunur bağlanır, yalnız workspace ve geçici dizin yazılabilir.",
        "Süreç sayısı üst sınırı yoktur; bellek/CPU RLIMIT ile sınırlandırılır.",
        "bubblewrap kurulu değilse veya user namespace kapalıysa çalıştırma reddedilir.",
    )

    def __init__(self, binary: Path | None = None):
        super().__init__(binary or (Path(found) if (found := shutil.which("bwrap")) else None))

    def _missing_message(self) -> str:
        return (
            "Linux bubblewrap backend'i (bwrap) bulunamadı. "
            "bubblewrap kurun; sandbox olmadan çalıştırma yapılmaz."
        )

    def _command(
        self, argv: Sequence[str], policy: SandboxPolicy, root: Path, temp: Path,
        environment: dict[str, str],
    ) -> list[str]:
        binary = self._binary()
        if binary is None:
            raise SandboxError(self._missing_message())
        args = [
            str(binary), "--die-with-parent", "--new-session",
            "--unshare-ipc", "--unshare-uts", "--unshare-pid", "--hostname", "ragents-sandbox",
            "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
            "--dir", "/sandbox-tmp", "--bind", str(temp), "/sandbox-tmp",
            "--chdir", str(policy.checked_cwd()), "--clearenv",
        ]
        if not policy.network:
            args.append("--unshare-net")
        writable_paths = policy.checked_writable_paths()
        if root in writable_paths:
            args.extend(["--bind", str(root), str(root)])
        else:
            args.extend(["--ro-bind", str(root), str(root)])
            for writable in writable_paths:
                args.extend(["--bind", str(writable), str(writable)])
        for name, value in sorted(environment.items()):
            args.extend(["--setenv", name, value])
        args.extend(["--", *argv])
        return args
