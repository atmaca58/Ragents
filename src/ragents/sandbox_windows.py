"""Windows AppContainer + Job Object sandbox backend'i."""

from __future__ import annotations

from collections.abc import Sequence
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
import struct
from typing import Any

try:
    import msvcrt
except ImportError:  # Modül POSIX'te yalnız keşif/tanılama için içe aktarılabilir.
    msvcrt = None  # type: ignore[assignment]

from ragents.errors import SandboxError
from ragents.sandbox import (
    OutputCollector, SandboxCapabilities, SandboxControl, SandboxPolicy, SandboxResult,
    cleanup_temp_dir, create_temp_dir, resolve_executable, runtime_paths,
    sandbox_environment,
)


_CREATE_NO_WINDOW = 0x08000000
_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_STARTF_USESTDHANDLES = 0x00000100
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
_JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_SE_GROUP_ENABLED = 0x00000004


class _SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.c_void_p),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _configure_windows_api() -> tuple[Any, Any, Any]:
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
        ctypes.POINTER(_SID_AND_ATTRIBUTES), wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
    ]
    userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.c_void_p, ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    return userenv, advapi32, kernel32


class WindowsAppContainerBackend:
    """AppContainer ile okuma/yazma ve ağ, Job Object ile süreç/kaynak sınırı."""

    name = "windows-appcontainer"

    def __init__(self, profile_name: str = "RagentsToolSandbox"):
        self.profile_name = profile_name
        self._api: tuple[Any, Any, Any] | None = None
        self._sid = ctypes.c_void_p()
        self._sid_text: str | None = None
        self._grants: set[tuple[str, str]] = set()
        self._grant_lock = threading.Lock()

    def _windows_api(self) -> tuple[Any, Any, Any]:
        if os.name != "nt":
            raise SandboxError("Windows AppContainer backend'i yalnız Windows'ta kullanılabilir.")
        if self._api is None:
            self._api = _configure_windows_api()
        return self._api

    def availability(self) -> tuple[bool, str | None]:
        if os.name != "nt":
            return False, "Windows AppContainer backend'i yalnız Windows'ta kullanılabilir."
        try:
            self._windows_api()
        except OSError as error:
            return False, f"Windows AppContainer API'si yüklenemedi: {error}"
        return True, None

    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            backend=self.name, filesystem=True, network=True, process=True,
            resources=True, hard_cancel=True, read_isolation=True,
            notes=(
                "AppContainer SID'i için Python çalışma zamanına salt okunur ACL verilir.",
                "Yazma yalnız görevde izin verilen workspace yolları ve geçici dizinle sınırlıdır.",
                "Job Object bellek, süreç sayısı, CPU süresi ve süreç ağacı sınırlarını uygular.",
                "Ağ varsayılan olarak kapalıdır; internetClient yalnız açık izinle eklenir.",
                "Harici MCP stdio süreçleri bu backend'in kapsamında değildir.",
            ),
        )

    def _ensure_profile(self) -> tuple[Any, Any, Any, str]:
        userenv, advapi32, kernel32 = self._windows_api()
        if self._sid_text is not None:
            return userenv, advapi32, kernel32, self._sid_text
        hr = userenv.CreateAppContainerProfile(
            self.profile_name, self.profile_name, "R Agents tool sandbox", None, 0,
            ctypes.byref(self._sid),
        )
        if hr < 0 and (hr & 0xFFFFFFFF) != 0x800700B7:
            raise SandboxError(f"AppContainer profili oluşturulamadı (HRESULT {hr & 0xFFFFFFFF:08x}).")
        if hr < 0:
            hr = userenv.DeriveAppContainerSidFromAppContainerName(
                self.profile_name, ctypes.byref(self._sid),
            )
            if hr < 0:
                raise SandboxError(
                    f"AppContainer SID'i çözümlenemedi (HRESULT {hr & 0xFFFFFFFF:08x})."
                )
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(self._sid, ctypes.byref(text)):
            raise SandboxError("AppContainer SID'i metne çevrilemedi.")
        try:
            self._sid_text = text.value
        finally:
            kernel32.LocalFree(text)
        return userenv, advapi32, kernel32, self._sid_text

    def _grant(self, path: Path, permissions: str) -> None:
        if os.name != "nt":
            return
        canonical = path.resolve()
        if not canonical.exists():
            return
        _, _, kernel32, sid = self._ensure_profile()
        key = (str(canonical).casefold(), permissions)
        with self._grant_lock:
            if key in self._grants:
                return
            result = subprocess.run(
                ["icacls", str(canonical), "/grant", f"*{sid}:{permissions}"],
                capture_output=True, text=True, errors="replace", timeout=60,
                creationflags=_CREATE_NO_WINDOW,
            )
            if result.returncode != 0:
                raise SandboxError(
                    "Sandbox ACL izni verilemedi. Python kurulumunun kullanıcı tarafından "
                    "okunabilir olduğundan emin olun."
                )
            self._grants.add(key)

    def _grant_policy_paths(self, policy: SandboxPolicy, root: Path, temp: Path) -> None:
        writable = policy.checked_writable_paths()
        self._grant(root, "(OI)(CI)(M)" if root in writable else "(OI)(CI)(RX)")
        for path in writable:
            if path != root:
                self._grant(path, "(OI)(CI)(M)")
        self._grant(temp, "(OI)(CI)(M)")
        for path in (*runtime_paths(), *policy.runtime_roots):
            self._grant(path, "(OI)(CI)(RX)")

    def _windows_path(self) -> str:
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        paths = [
            Path(sys.executable).parent,
            Path(sys.prefix) / "Scripts",
            Path(sys.base_prefix) / "Scripts",
            Path(sys.base_prefix),
            system_root / "System32",
            system_root,
        ]
        return ";".join(str(path) for path in dict.fromkeys(paths) if path.exists())

    def _allowed_roots(self, root: Path, temp: Path) -> tuple[Path, ...]:
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
        return tuple(path.resolve() for path in (root, temp, *runtime_paths(), system_root))

    def _check_executable(self, executable: Path, root: Path, temp: Path, runtime_roots=()) -> None:
        target = executable.resolve()
        if target.suffix.lower() not in (".exe", ".com"):
            raise SandboxError(
                "Sandbox yalnız .exe/.com çalıştırılabilirlerini doğrudan başlatır; "
                "Python betikleri için 'python betik.py' kullanın."
            )
        if not any(target == base or base in target.parents for base in (*self._allowed_roots(root, temp), *runtime_roots)):
            raise SandboxError(
                "Sandbox çalıştırılabilir dosyası izinli Python, sistem veya workspace "
                "dizinlerinin dışında."
            )

    def _create_job(self, kernel32: Any, policy: SandboxPolicy) -> wintypes.HANDLE:
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise SandboxError("Sandbox Job Object oluşturulamadı.")
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | _JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | _JOB_OBJECT_LIMIT_JOB_MEMORY
            | _JOB_OBJECT_LIMIT_JOB_TIME
        )
        info.BasicLimitInformation.ActiveProcessLimit = policy.max_processes
        info.BasicLimitInformation.PerJobUserTimeLimit = max(
            1, int(policy.timeout_seconds * 10_000_000),
        )
        memory = policy.max_memory_mb * 1024 * 1024
        info.ProcessMemoryLimit = memory
        info.JobMemoryLimit = memory
        if not kernel32.SetInformationJobObject(
            job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info), ctypes.sizeof(info),
        ):
            kernel32.CloseHandle(job)
            raise SandboxError("Sandbox kaynak sınırları uygulanamadı.")
        return job

    def _handle_list(self, handles: Sequence[int]) -> tuple[Any, Any]:
        array = (wintypes.HANDLE * len(handles))(*(wintypes.HANDLE(handle) for handle in handles))
        return array, ctypes.cast(array, ctypes.c_void_p)

    def run(
        self, argv: Sequence[str], policy: SandboxPolicy, *,
        input: bytes | None = None, control: SandboxControl, extra_fds: tuple[int, ...] = (),
    ) -> SandboxResult:
        # Bir backend yeniden kullanılsa da OS yetkileri her yürütmeye aittir.
        execution = WindowsAppContainerBackend(f"RagentsRun-{uuid.uuid4().hex}")
        try:
            return execution._run_isolated(argv, policy, input=input, control=control, extra_fds=extra_fds)
        finally:
            execution._release_identity()

    def _release_identity(self) -> None:
        if self._sid_text is None:
            return
        userenv, advapi32, _, sid = self._ensure_profile()
        failed = False
        try:
            for path in {path for path, _ in self._grants}:
                if not Path(path).exists():
                    continue
                try:
                    result = subprocess.run(
                        ["icacls", path, "/remove:g", f"*{sid}"],
                        capture_output=True, timeout=60, creationflags=_CREATE_NO_WINDOW,
                    )
                    failed |= result.returncode != 0
                except (OSError, subprocess.TimeoutExpired):
                    failed = True
            userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
            userenv.DeleteAppContainerProfile.restype = ctypes.c_long
            failed |= userenv.DeleteAppContainerProfile(self.profile_name) < 0
        finally:
            advapi32.FreeSid.argtypes = [ctypes.c_void_p]
            advapi32.FreeSid.restype = ctypes.c_void_p
            advapi32.FreeSid(self._sid)
            self._sid = ctypes.c_void_p()
            self._sid_text = None
            self._grants.clear()
        if failed:
            raise SandboxError("Sandbox yürütme kimliğinin temizliği tamamlanamadı.")

    def _run_isolated(
        self, argv: Sequence[str], policy: SandboxPolicy, *,
        input: bytes | None = None, control: SandboxControl, extra_fds: tuple[int, ...] = (),
    ) -> SandboxResult:
        if control.cancelled.is_set():
            raise SandboxError("Sandbox komutu başlatılmadan iptal edildi.")
        available, reason = self.availability()
        if not available:
            raise SandboxError(reason or "Windows sandbox backend kullanılamıyor.")
        if msvcrt is None:
            raise SandboxError("Windows sandbox backend'i bu platformda kullanılamaz.")
        _, advapi32, kernel32, _ = self._ensure_profile()
        root = policy.checked_root()
        temp = create_temp_dir()
        # Win32 alt süreç ortamı lowbox TEMP yolunu LOCALAPPDATA altında yeniden üretir.
        (temp / "Packages" / self.profile_name.lower() / "AC" / "Temp").mkdir(parents=True)
        environment = sandbox_environment(policy, temp, path=self._windows_path())
        executable = resolve_executable(argv, path=environment["PATH"], cwd=root)
        self._check_executable(executable, root, temp, policy.runtime_roots)
        self._grant_policy_paths(policy, root, temp)
        command_line = subprocess.list2cmdline([str(executable), *argv[1:]])
        command_buffer = ctypes.create_unicode_buffer(command_line)
        environment_block = "\0".join(
            f"{name}={value}" for name, value in sorted(environment.items())
        ) + "\0\0"
        environment_buffer = ctypes.create_string_buffer(environment_block.encode("utf-16-le"))
        started = time.perf_counter()
        process_info = _PROCESS_INFORMATION()
        job = None
        attribute_buffer = None
        attributes_ready = False
        capability_sid = ctypes.c_void_p()
        capability_sid_allocated = False
        stdout_collector: OutputCollector | None = None
        stderr_collector: OutputCollector | None = None
        stdout_stream = stderr_stream = None
        reader_threads: list[threading.Thread] = []
        writer_thread: threading.Thread | None = None
        stdin_read = stdin_write = stdout_read = stdout_write = stderr_read = stderr_write = -1
        timed_out = False
        cancelled = False
        exit_code_value: int | None = None
        terminator = lambda: None
        try:
            if input is not None:
                stdin_read, stdin_write = os.pipe()
            stdout_read, stdout_write = os.pipe()
            stderr_read, stderr_write = os.pipe()
            if input is None:
                stdin_read = os.open(os.devnull, os.O_RDONLY)
            stdin_handle = msvcrt.get_osfhandle(stdin_read)
            stdout_write_handle = msvcrt.get_osfhandle(stdout_write)
            stderr_write_handle = msvcrt.get_osfhandle(stderr_write)
            for handle in (stdin_handle, stdout_write_handle, stderr_write_handle):
                if not kernel32.SetHandleInformation(handle, 1, 1):
                    raise SandboxError("Sandbox alt süreç tutamacı devredilebilir yapılamadı.")
            for read_fd in (stdout_read, stderr_read):
                kernel32.SetHandleInformation(msvcrt.get_osfhandle(read_fd), 1, 0)
            if input is not None:
                kernel32.SetHandleInformation(msvcrt.get_osfhandle(stdin_write), 1, 0)

            size = ctypes.c_size_t(0)
            if not kernel32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size)):
                if ctypes.get_last_error() != 122:  # ERROR_INSUFFICIENT_BUFFER
                    raise SandboxError("Sandbox süreç öznitelik listesi hazırlanamadı.")
            attribute_buffer = ctypes.create_string_buffer(size.value)
            if not kernel32.InitializeProcThreadAttributeList(
                attribute_buffer, 2, 0, ctypes.byref(size),
            ):
                raise SandboxError("Sandbox süreç öznitelik listesi başlatılamadı.")
            attributes_ready = True

            capabilities = None
            capability_array = None
            if policy.network:
                if not advapi32.ConvertStringSidToSidW(
                    "S-1-15-3-1", ctypes.byref(capability_sid),
                ):
                    raise SandboxError("Ağ yeteneği SID'i oluşturulamadı.")
                capability_sid_allocated = True
                capability_array = (_SID_AND_ATTRIBUTES * 1)(
                    _SID_AND_ATTRIBUTES(capability_sid, _SE_GROUP_ENABLED),
                )
                capabilities = _SECURITY_CAPABILITIES(
                    self._sid, ctypes.cast(capability_array, ctypes.c_void_p), 1, 0,
                )
            else:
                capabilities = _SECURITY_CAPABILITIES(self._sid, None, 0, 0)
            if not kernel32.UpdateProcThreadAttribute(
                attribute_buffer, 0, _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes.byref(capabilities), ctypes.sizeof(capabilities), None, None,
            ):
                raise SandboxError("AppContainer güvenlik yeteneği uygulanamadı.")

            if extra_fds not in ((), (3, 4)):
                raise SandboxError("Yalnız kayıtlı Chromium CDP boruları devredilebilir.")
            extra_handles = tuple(msvcrt.get_osfhandle(fd) for fd in extra_fds)
            for handle in extra_handles:
                if not kernel32.SetHandleInformation(handle, 1, 1):
                    raise SandboxError("Chromium borusu devredilebilir yapılamadı.")
            handle_values = (stdin_handle, stdout_write_handle, stderr_write_handle, *extra_handles)
            handles_array, handles_pointer = self._handle_list(handle_values)
            if not kernel32.UpdateProcThreadAttribute(
                attribute_buffer, 0, _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                handles_pointer, ctypes.sizeof(handles_array), None, None,
            ):
                raise SandboxError("Sandbox devredilecek tutamaç listesi uygulanamadı.")

            startup = _STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
            startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = wintypes.HANDLE(stdin_handle)
            startup.StartupInfo.hStdOutput = wintypes.HANDLE(stdout_write_handle)
            startup.StartupInfo.hStdError = wintypes.HANDLE(stderr_write_handle)
            if extra_handles:
                # Windows CRT stdio tablosu: count + flags[count] + HANDLE[count].
                packed = struct.pack("<I", len(handle_values)) + bytes([9] * len(handle_values))
                packed += struct.pack("<" + "Q" * len(handle_values), *handle_values)
                stdio_table = ctypes.create_string_buffer(packed)
                startup.StartupInfo.cbReserved2 = len(packed)
                startup.StartupInfo.lpReserved2 = ctypes.cast(stdio_table, ctypes.c_void_p)
            startup.lpAttributeList = ctypes.cast(attribute_buffer, ctypes.c_void_p)
            flags = (
                _EXTENDED_STARTUPINFO_PRESENT | _CREATE_SUSPENDED
                | _CREATE_UNICODE_ENVIRONMENT | _CREATE_NO_WINDOW
            )
            if not kernel32.CreateProcessW(
                str(executable), command_buffer, None, None, True, flags,
                ctypes.cast(environment_buffer, ctypes.c_void_p), str(policy.checked_cwd()),
                ctypes.byref(startup), ctypes.byref(process_info),
            ):
                raise SandboxError(
                    f"Sandbox alt süreci başlatılamadı (Windows hata {ctypes.get_last_error()})."
                )

            os.close(stdout_write)
            os.close(stderr_write)
            stdout_write = stderr_write = -1
            os.close(stdin_read)
            stdin_read = -1

            job = self._create_job(kernel32, policy)
            if not kernel32.AssignProcessToJobObject(job, process_info.hProcess):
                raise SandboxError("Sandbox alt süreci Job Object'e atanamadı.")
            def terminate() -> None:
                if job is not None:
                    kernel32.TerminateJobObject(job, 1)
                if process_info.hProcess:
                    kernel32.TerminateProcess(process_info.hProcess, 1)

            terminator = terminate
            control.register(terminate)
            with control.launching():
                if kernel32.ResumeThread(process_info.hThread) == 0xFFFFFFFF:
                    raise SandboxError("Sandbox alt süreci devam ettirilemedi.")

            def on_output_limit() -> None:
                terminate()

            if stdout_read is None or stderr_read is None:
                raise SandboxError("Sandbox çıktı boruları açılamadı.")
            stdout_stream = os.fdopen(stdout_read, "rb", buffering=0)
            stderr_stream = os.fdopen(stderr_read, "rb", buffering=0)
            stdout_read = stderr_read = -1
            stdout_collector = OutputCollector(policy.max_output_bytes, on_output_limit)
            stderr_collector = OutputCollector(policy.max_output_bytes, on_output_limit)
            for stream, collector in (
                (stdout_stream, stdout_collector), (stderr_stream, stderr_collector),
            ):
                thread = threading.Thread(target=collector.pump, args=(stream,), daemon=True)
                thread.start()
                reader_threads.append(thread)
            if input is not None and stdin_write >= 0:
                write_fd = stdin_write
                stdin_write = -1

                def write_input() -> None:
                    try:
                        os.write(write_fd, input)
                    except OSError:
                        pass
                    finally:
                        try:
                            os.close(write_fd)
                        except OSError:
                            pass

                writer_thread = threading.Thread(target=write_input, daemon=True)
                writer_thread.start()

            deadline = time.monotonic() + policy.timeout_seconds
            while True:
                if control.cancelled.is_set():
                    cancelled = True
                    terminate()
                    break
                remaining = max(0, int((deadline - time.monotonic()) * 1000))
                if remaining <= 0:
                    timed_out = True
                    terminate()
                    break
                result = kernel32.WaitForSingleObject(process_info.hProcess, min(100, remaining))
                if result == _WAIT_OBJECT_0:
                    break
                if result != _WAIT_TIMEOUT:
                    raise SandboxError("Sandbox alt süreci beklenirken Windows hatası oluştu.")
            if control.cancelled.is_set():
                cancelled = True
            # Ana süreç bitse bile arka planda kalan çocukları yaşatma.
            kernel32.TerminateJobObject(job, 1)
            kernel32.WaitForSingleObject(process_info.hProcess, 5000)
            code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(process_info.hProcess, ctypes.byref(code)):
                exit_code_value = code.value
        finally:
            control.unregister(terminator)
            if job is not None:
                kernel32.TerminateJobObject(job, 1)
            for thread in reader_threads:
                thread.join(timeout=5)
            if writer_thread is not None:
                writer_thread.join(timeout=5)
            for stream in (stdout_stream, stderr_stream):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            if process_info.hThread:
                kernel32.CloseHandle(process_info.hThread)
                process_info.hThread = None
            if job is not None:
                kernel32.CloseHandle(job)
                job = None
            if process_info.hProcess:
                kernel32.TerminateProcess(process_info.hProcess, 1)
                kernel32.CloseHandle(process_info.hProcess)
                process_info.hProcess = None
            for fd in (
                stdin_read, stdin_write, stdout_read, stdout_write, stderr_read, stderr_write,
            ):
                if fd is not None and fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            if attributes_ready and attribute_buffer is not None:
                kernel32.DeleteProcThreadAttributeList(attribute_buffer)
            if capability_sid_allocated:
                kernel32.LocalFree(capability_sid)
            cleanup_temp_dir(temp)

        if stdout_collector is None or stderr_collector is None:
            raise SandboxError("Sandbox çıktı okuyucuları hazırlanamadı.")
        return SandboxResult(
            backend=self.name, workspace=str(root), exit_code=exit_code_value,
            stdout=stdout_collector.text(), stderr=stderr_collector.text(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            timed_out=timed_out, cancelled=cancelled,
            output_truncated=stdout_collector.truncated or stderr_collector.truncated,
            network_allowed=policy.network,
            writable=bool(policy.checked_writable_paths()),
            writable_paths=tuple(str(path) for path in policy.checked_writable_paths()),
        )
