"""Windows, macOS ve Linux için ortak sandbox sözleşmesi."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import contextmanager
import asyncio
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
from typing import Any, Protocol

from pydantic import Field, field_validator, model_validator

from ragents.config import Spec
from ragents.errors import SandboxError
from ragents.workspace import Workspace


MAX_ARGV_ITEMS = 256
MAX_ARG_CHARS = 32_000
MAX_TOTAL_ARG_CHARS = 65_536
MAX_OUTPUT_BYTES = 1_048_576
DEFAULT_ENV_ALLOWLIST = ("LANG", "LC_ALL", "LC_CTYPE", "TZ")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SandboxUnavailable(SandboxError):
    """Seçilen platformda güvenli backend yok; izolasyonsuz çalıştırma yapılmaz."""


class SandboxPolicy(Spec):
    """Bir sandbox çalıştırmasının dosya, ağ, süreç ve çıktı sınırları."""

    workspace: Path
    writable: bool = False
    writable_paths: tuple[str, ...] = Field(default=(), max_length=32)
    cwd: Path | None = None
    network: bool = False
    timeout_seconds: float = Field(default=30, ge=0.1, le=3600)
    max_memory_mb: int = Field(default=1024, ge=32, le=16384)
    max_processes: int = Field(default=8, ge=1, le=128)
    max_output_bytes: int = Field(default=65_536, ge=1024, le=MAX_OUTPUT_BYTES)
    env_allowlist: tuple[str, ...] = Field(default=DEFAULT_ENV_ALLOWLIST, max_length=32)
    env: dict[str, str] = Field(default_factory=dict, max_length=32)
    runtime_roots: tuple[Path, ...] = Field(default=(), max_length=8)

    @field_validator("runtime_roots")
    @classmethod
    def validate_runtime_roots(cls, roots):
        if any(not root.is_absolute() or not root.is_dir() or root.is_symlink() or root.is_junction() for root in roots):
            raise ValueError("Araç çalışma zamanı kökü mevcut, mutlak ve bağlantısız dizin olmalıdır.")
        return tuple(root.resolve() for root in roots)

    @field_validator("env_allowlist")
    @classmethod
    def validate_allowlist(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for name in value:
            if not ENV_NAME.fullmatch(name):
                raise ValueError("Ortam değişkeni adı geçersiz.")
        return tuple(dict.fromkeys(value))

    @field_validator("env")
    @classmethod
    def validate_env(cls, value: dict[str, str]) -> dict[str, str]:
        for name, item in value.items():
            if not ENV_NAME.fullmatch(name):
                raise ValueError("Ortam değişkeni adı geçersiz.")
            if "\x00" in item or len(item) > 4096:
                raise ValueError("Ortam değişkeni değeri geçersiz veya çok uzun.")
        return value

    @field_validator("writable_paths")
    @classmethod
    def normalize_writable_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        from ragents.workspace import normalize_relative_path
        from ragents.errors import WorkspaceError

        try:
            paths = [normalize_relative_path(item) for item in value]
        except WorkspaceError as error:
            raise ValueError(str(error)) from None
        return tuple(dict.fromkeys(paths))

    @model_validator(mode="after")
    def validate_workspace(self) -> "SandboxPolicy":
        if not self.workspace.is_absolute():
            raise ValueError("Sandbox workspace yolu mutlak olmalıdır.")
        Workspace(self.workspace, writable_paths=self.writable_paths)
        if self.cwd is not None and not self.cwd.is_absolute():
            raise ValueError("Sandbox çalışma dizini mutlak olmalıdır.")
        return self

    def checked_root(self) -> Path:
        return Workspace(self.workspace).root

    def checked_writable_paths(self) -> tuple[Path, ...]:
        if self.writable:
            return (self.checked_root(),)
        if not self.writable_paths:
            return ()
        return Workspace(self.workspace, writable_paths=self.writable_paths).writable_roots

    def checked_cwd(self) -> Path:
        root = self.checked_root()
        if self.cwd is None:
            return root
        try:
            target = self.cwd.resolve()
            target.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            raise SandboxError("Sandbox çalışma dizini workspace içinde olmalıdır.") from None
        if not target.is_dir():
            raise SandboxError("Sandbox çalışma dizini mevcut bir dizin olmalıdır.")
        return target


class SandboxCapabilities(Spec):
    """Backend'in gerçekten uygulayabildiği güvenlik kontrolleri."""

    backend: str
    filesystem: bool
    network: bool
    process: bool
    resources: bool
    hard_cancel: bool
    read_isolation: bool
    notes: tuple[str, ...] = ()


class SandboxStatus(Spec):
    backend: str
    available: bool
    capabilities: SandboxCapabilities
    reason: str | None = None
    notes: tuple[str, ...] = ()


class SandboxResult(Spec):
    backend: str
    workspace: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    cancelled: bool = False
    output_truncated: bool = False
    network_allowed: bool = False
    writable: bool = False
    writable_paths: tuple[str, ...] = ()


class SandboxControl:
    """Çalışan süreç ağacını iptal etmek için ortak denetim."""

    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self._lock = threading.RLock()
        self._terminators: set[Callable[[], None]] = set()

    @contextmanager
    def launching(self):
        # İptal ile işletim sistemi süreç başlangıcı aynı sınırda sıralanır.
        with self._lock:
            if self.cancelled.is_set():
                raise SandboxError("Sandbox komutu başlatılmadan iptal edildi.")
            yield

    def register(self, terminator: Callable[[], None]) -> None:
        with self._lock:
            self._terminators.add(terminator)
        if self.cancelled.is_set():
            self._call(terminator)

    def unregister(self, terminator: Callable[[], None]) -> None:
        with self._lock:
            self._terminators.discard(terminator)

    def cancel(self) -> None:
        with self._lock:
            self.cancelled.set()
            terminators = tuple(self._terminators)
        for terminator in terminators:
            self._call(terminator)

    @staticmethod
    def _call(terminator: Callable[[], None]) -> None:
        try:
            terminator()
        except OSError:
            pass


class SandboxBackend(Protocol):
    name: str

    def capabilities(self) -> SandboxCapabilities: ...

    def availability(self) -> tuple[bool, str | None]: ...

    def run(
        self, argv: Sequence[str], policy: SandboxPolicy, *,
        input: bytes | None = None, control: SandboxControl,
    ) -> SandboxResult: ...


class OutputCollector:
    """Alt süreç çıktısını sınırlı bellekte toplar."""

    def __init__(self, limit: int, on_limit: Callable[[], None]) -> None:
        self.limit = limit
        self.on_limit = on_limit
        self.truncated = False
        self._data = bytearray()
        self._lock = threading.Lock()
        self._limit_fired = False

    def pump(self, stream: Any) -> None:
        while True:
            try:
                chunk = stream.read(4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            fire = False
            with self._lock:
                remaining = self.limit - len(self._data)
                if remaining > 0:
                    self._data.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.truncated = True
                    if not self._limit_fired:
                        self._limit_fired = True
                        fire = True
            if fire:
                self.on_limit()

    def text(self) -> str:
        with self._lock:
            return bytes(self._data).decode("utf-8", "replace")


def validate_argv(argv: Sequence[str]) -> list[str]:
    if not argv or len(argv) > MAX_ARGV_ITEMS:
        raise SandboxError("Sandbox komutu boş olamaz veya çok fazla argüman içeremez.")
    result: list[str] = []
    total = 0
    for item in argv:
        if not isinstance(item, str) or not item:
            raise SandboxError("Sandbox argümanları boş olmayan metinler olmalıdır.")
        if "\x00" in item or len(item) > MAX_ARG_CHARS:
            raise SandboxError("Sandbox argümanı geçersiz veya çok uzun.")
        total += len(item)
        if total > MAX_TOTAL_ARG_CHARS:
            raise SandboxError("Sandbox komutu çok uzun.")
        result.append(item)
    return result


def create_temp_dir() -> Path:
    directory = Path(tempfile.mkdtemp(prefix="ragents-sandbox-")).resolve()
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    return directory


def cleanup_temp_dir(directory: Path) -> None:
    shutil.rmtree(directory, ignore_errors=True)


def sandbox_environment(
    policy: SandboxPolicy, temp_dir: Path, *, path: str,
) -> dict[str, str]:
    """Yalnız güvenli ortam değişkenlerini ve açıkça verilenleri taşır."""
    environment: dict[str, str] = {}
    for name in policy.env_allowlist:
        if name in ("PATH", "HOME", "USERPROFILE", "TEMP", "TMP", "TMPDIR"):
            continue
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value
    environment.update(policy.env)
    temp = str(temp_dir)
    environment.update({
        "PATH": path,
        "HOME": temp,
        "USERPROFILE": temp,
        "TMPDIR": temp,
        "TEMP": temp,
        "TMP": temp,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_COLOR": "1",
    })
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        home = Path(temp)
        drive = home.drive or "C:"
        environment.update({
            "SystemRoot": system_root,
            "windir": system_root,
            "COMSPEC": os.path.join(system_root, "System32", "cmd.exe"),
            "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
            "LOCALAPPDATA": temp,
            "APPDATA": temp,
            "HOMEDRIVE": drive,
            "HOMEPATH": str(home)[len(drive):] or "\\",
        })
    return environment


def resolve_executable(argv: Sequence[str], *, path: str, cwd: Path) -> Path:
    command = Path(argv[0]).expanduser()
    if command.is_absolute() or command.parent != Path("."):
        candidate = command if command.is_absolute() else cwd / command
        if candidate.is_file():
            return candidate.resolve()
        raise SandboxError("Sandbox çalıştırılabilir dosyası bulunamadı.")
    found = shutil.which(argv[0], path=path)
    if found is None:
        raise SandboxError("Sandbox komutu PATH içinde bulunamadı.")
    return Path(found).resolve()


def runtime_paths() -> tuple[Path, ...]:
    """Sandbox alt sürecinin okuyabileceği Python/paket çalışma zamanı yolları."""
    paths = {
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path(sys.executable).parent,
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
    }
    return tuple(path for path in paths if path.exists())


class Sandbox:
    """Backend seçimini ve çalışan süreçlerin sert iptalini yönetir."""

    def __init__(self, policy: SandboxPolicy, *, backend: SandboxBackend | None = None):
        self.policy = policy
        self.backend = backend or select_backend()
        self._run_lock = threading.Lock()
        self._control_lock = threading.Lock()
        self._controls: set[SandboxControl] = set()

    def status(self) -> SandboxStatus:
        available, reason = self.backend.availability()
        capabilities = self.backend.capabilities()
        return SandboxStatus(
            backend=self.backend.name, available=available,
            capabilities=capabilities, reason=reason, notes=capabilities.notes,
        )

    def run(self, argv: Sequence[str], *, input: bytes | None = None) -> SandboxResult:
        return self._run(argv, input, self._new_control())

    def _new_control(self) -> SandboxControl:
        control = SandboxControl()
        with self._control_lock:
            self._controls.add(control)
        return control

    def _run(self, argv: Sequence[str], input: bytes | None, control: SandboxControl) -> SandboxResult:
        try:
            command = validate_argv(argv)
            available, reason = self.backend.availability()
            if not available:
                raise SandboxUnavailable(reason or "Sandbox backend kullanılamıyor.")
            with self._run_lock:
                if control.cancelled.is_set():
                    raise SandboxError("Sandbox komutu başlatılmadan iptal edildi.")
                return self.backend.run(command, self.policy, input=input, control=control)
        finally:
            with self._control_lock:
                self._controls.discard(control)

    async def run_async(self, argv: Sequence[str], *, input: bytes | None = None) -> SandboxResult:
        control = self._new_control()
        task = asyncio.create_task(asyncio.to_thread(self._run, argv, input, control))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            control.cancel()
            # Thread iptal edilemez; komut temizliği bitmeden görev kilidini bırakma.
            while not task.done():
                try:
                    await asyncio.shield(asyncio.gather(task, return_exceptions=True))
                except asyncio.CancelledError:
                    control.cancel()
            if not task.cancelled():
                task.exception()
            raise

    def cancel(self) -> None:
        with self._control_lock:
            controls = tuple(self._controls)
        for control in controls:
            control.cancel()


def select_backend(platform: str | None = None) -> SandboxBackend:
    current = platform or sys.platform
    try:
        if current.startswith("win"):
            from ragents.sandbox_windows import WindowsAppContainerBackend

            return WindowsAppContainerBackend()
        if current == "darwin":
            from ragents.sandbox_posix import MacOSSeatbeltBackend

            return MacOSSeatbeltBackend()
        if current.startswith("linux"):
            from ragents.sandbox_posix import LinuxBubblewrapBackend

            return LinuxBubblewrapBackend()
    except ImportError as error:
        raise SandboxUnavailable(
            f"{current} sandbox backend'i bu kurulumda yüklenemedi: {error}"
        ) from None
    raise SandboxUnavailable(f"Desteklenmeyen platform için sandbox backend yok: {current}")


def backend_status(platform: str | None = None) -> SandboxStatus:
    try:
        backend = select_backend(platform)
    except SandboxUnavailable as error:
        return SandboxStatus(
            backend="unsupported", available=False,
            capabilities=SandboxCapabilities(
                backend="unsupported", filesystem=False, network=False, process=False,
                resources=False, hard_cancel=False, read_isolation=False,
            ),
            reason=str(error),
        )
    available, reason = backend.availability()
    capabilities = backend.capabilities()
    return SandboxStatus(
        backend=backend.name, available=available, capabilities=capabilities,
        reason=reason, notes=capabilities.notes,
    )
