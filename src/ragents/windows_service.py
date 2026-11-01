"""Kullanıcı oturumunda Task Scheduler kaydı ve sınırlı arka plan supervisor."""
import asyncio
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from xml.etree import ElementTree as ET

from filelock import FileLock, Timeout

from ragents.auth import atomic_write
from ragents.profile_paths import profile_root
from ragents.storage import TaskStateError


def task_name(root: Path):
    identity = hashlib.sha256(os.path.normcase(str(root.resolve())).encode()).hexdigest()[:16]
    return "RAgents-" + identity


def scheduler_xml(root: Path, executable: Path, user: str):
    namespace = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", namespace)
    def element(parent, name, text=None):
        child = ET.SubElement(parent, f"{{{namespace}}}{name}")
        child.text = text
        return child
    task = ET.Element(f"{{{namespace}}}Task", version="1.4")
    triggers = element(task, "Triggers")
    trigger = element(triggers, "LogonTrigger")
    element(trigger, "Enabled", "true")
    element(trigger, "UserId", user)
    principal = element(element(task, "Principals"), "Principal")
    principal.set("id", "Owner")
    element(principal, "UserId", user)
    element(principal, "LogonType", "InteractiveToken")
    element(principal, "RunLevel", "LeastPrivilege")
    settings = element(task, "Settings")
    element(settings, "MultipleInstancesPolicy", "IgnoreNew")
    element(settings, "DisallowStartIfOnBatteries", "false")
    element(settings, "StopIfGoingOnBatteries", "false")
    element(settings, "AllowHardTerminate", "true")
    element(settings, "StartWhenAvailable", "true")
    element(settings, "Enabled", "true")
    element(settings, "Hidden", "true")
    element(settings, "ExecutionTimeLimit", "PT0S")
    restart = element(settings, "RestartOnFailure")
    element(restart, "Interval", "PT1M")
    element(restart, "Count", "3")
    actions = element(task, "Actions")
    actions.set("Context", "Owner")
    execute = element(actions, "Exec")
    element(execute, "Command", str(executable))
    element(execute, "Arguments", subprocess.list2cmdline(["-m", "ragents", "supervise", "--root", str(root.resolve())]))
    element(execute, "WorkingDirectory", str(executable.parent))
    return ET.tostring(task, encoding="unicode")


def scheduler_command(root, action):
    if sys.platform != "win32":
        raise TaskStateError("Arka plan hizmeti bu sürümde yalnız Windows'ta desteklenir.")
    executable = Path(os.environ["SystemRoot"]) / "System32/schtasks.exe"
    arguments = {"start": ["/Run"], "stop": ["/End"], "uninstall": ["/Delete", "/F"], "status": ["/Query", "/XML"]}
    result = subprocess.run([str(executable), *arguments[action], "/TN", task_name(root)],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
    if result.returncode and action != "status":
        raise TaskStateError("Windows zamanlanmış görev işlemi tamamlanamadı.")
    return result.returncode == 0


def install_service(root):
    root = profile_root(root)
    if sys.platform != "win32":
        raise TaskStateError("Kurulum yalnız Windows'ta desteklenir.")
    python = Path(sys.executable).with_name("pythonw.exe")
    if not python.is_file():
        raise TaskStateError("Ürünle gelen pythonw.exe bulunamadı.")
    user = os.environ.get("USERDOMAIN", "") + "\\" + getpass.getuser()
    directory = root / "data"
    directory.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=directory, suffix=".xml")
    try:
        with os.fdopen(handle, "w", encoding="utf-16") as stream:
            stream.write(scheduler_xml(root, python, user.lstrip("\\")))
        executable = Path(os.environ["SystemRoot"]) / "System32/schtasks.exe"
        result = subprocess.run([str(executable), "/Create", "/TN", task_name(root), "/XML", name, "/F"],
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
        if result.returncode:
            raise TaskStateError("Windows oturum açılışı görevi kaydedilemedi.")
    finally:
        Path(name).unlink(missing_ok=True)
    return {"installed": True, "task_name": task_name(root), "started": False}


class WindowsChild:
    """Çocuk başlatılmadan Job Object'e bağlanır; parent ölünce ağaç kapanır."""
    def __init__(self, argv):
        import ctypes
        from ctypes import wintypes
        from ragents.sandbox_windows import (_configure_windows_api, _JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
                                              _STARTUPINFOW, _PROCESS_INFORMATION)
        self.ctypes = ctypes
        _, _, self.kernel = _configure_windows_api()
        self.job = self.kernel.CreateJobObjectW(None, None)
        self.process = _PROCESS_INFORMATION()
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000
        try:
            if not self.job or not self.kernel.SetInformationJobObject(self.job, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise TaskStateError("Supervisor süreç grubu oluşturulamadı.")
            startup = _STARTUPINFOW()
            startup.cb = ctypes.sizeof(startup)
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            if not self.kernel.CreateProcessW(argv[0], command, None, None, False, 0x4 | 0x08000000,
                                              None, str(Path(argv[0]).parent), ctypes.byref(startup), ctypes.byref(self.process)):
                raise TaskStateError("Arka plan süreci başlatılamadı.")
            if not self.kernel.AssignProcessToJobObject(self.job, self.process.hProcess):
                raise TaskStateError("Arka plan süreci Job Object'e bağlanamadı.")
            if self.kernel.ResumeThread(self.process.hThread) == 0xFFFFFFFF:
                raise TaskStateError("Arka plan süreci devam ettirilemedi.")
            self.kernel.CloseHandle(self.process.hThread)
            self.process.hThread = None
        except BaseException:
            self.close()
            raise

    def poll(self):
        from ctypes import wintypes
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.process.hProcess, self.ctypes.byref(code)):
            raise TaskStateError("Arka plan süreç durumu okunamadı.")
        return None if code.value == 259 else code.value

    def close(self):
        if self.process.hProcess:
            self.kernel.TerminateProcess(self.process.hProcess, 1)
        if self.job:
            self.kernel.CloseHandle(self.job)
            self.job = None
        for name in ("hProcess", "hThread"):
            handle = getattr(self.process, name)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self.process, name, None)


def supervisor_commands(root):
    commands = [[sys.executable, "-m", "ragents", "worker", "--root", str(root)]]
    remote = root / "connections/remote.json"
    if remote.is_file():
        settings = json.loads(remote.read_text(encoding="utf-8"))
        command = [sys.executable, "-m", "ragents", "mcp", "serve", "--root", str(root),
                   "--transport", "streamable-http", "--public-url", settings["public_url"]]
        for grant in ("allow_manage", "allow_write", "allow_execute"):
            if settings.get(grant) is True:
                command.append("--" + grant.replace("_", "-"))
        commands.append(command)
    return commands


async def supervise(root):
    if sys.platform != "win32":
        raise TaskStateError("Supervisor yalnız Windows'ta desteklenir.")
    root = profile_root(root)
    directory = root / "data"
    directory.mkdir(parents=True, exist_ok=True)
    stop = directory / "supervisor.stop"
    state = directory / "supervisor.json"
    lock = FileLock(directory / "supervisor.lock", timeout=0)
    children = []
    try:
        lock.acquire()
    except Timeout:
        raise TaskStateError("Bu profilin supervisor süreci zaten çalışıyor.") from None
    try:
        failures = 0
        while not stop.exists() and failures < 3:
            for command in supervisor_commands(root):
                children.append(WindowsChild(command))
            atomic_write(state, json.dumps({"status": "running", "failures": failures, "pid": os.getpid()}).encode())
            while not stop.exists() and all(child.poll() is None for child in children):
                await asyncio.sleep(0.25)
            for child in children:
                child.close()
            children = []
            if not stop.exists():
                failures += 1
                await asyncio.sleep(min(failures, 3))
        status = "failed" if failures >= 3 else "stopped"
        atomic_write(state, json.dumps({"status": status, "failures": failures}).encode())
        return {"supervisor": status}
    finally:
        for child in children:
            child.close()
        lock.release()


def add_service_parsers(commands):
    service = commands.add_parser("service", help="Windows arka plan supervisor kaydı ve kontrolü")
    service.add_argument("--root", type=Path)
    service.add_argument("action", choices=["install", "start", "stop", "status", "uninstall"])
    supervisor = commands.add_parser("supervise", help="Task Scheduler arka plan giriş noktası")
    supervisor.add_argument("--root", type=Path)


async def dispatch_service(args):
    root = profile_root(args.root)
    if args.command == "supervise":
        return await supervise(root)
    if args.action == "install":
        return await asyncio.to_thread(install_service, root)
    stop = root / "data/supervisor.stop"
    if args.action in ("stop", "uninstall"):
        stop.parent.mkdir(parents=True, exist_ok=True)
        stop.touch()
        await asyncio.sleep(0.5)
    if args.action == "start":
        stop.unlink(missing_ok=True)
    success = await asyncio.to_thread(scheduler_command, root, args.action)
    return {"action": args.action, "registered": success, "profile": str(root)}
