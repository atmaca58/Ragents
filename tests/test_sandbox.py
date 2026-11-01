import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import pytest
from pydantic import ValidationError

from ragents.cli import main
from ragents.errors import SandboxError, WorkspaceError
from ragents.sandbox import (
    Sandbox, SandboxPolicy, SandboxUnavailable, backend_status, sandbox_environment,
    select_backend, validate_argv,
)
from ragents.sandbox_posix import (
    LinuxBubblewrapBackend, MacOSSeatbeltBackend, seatbelt_profile,
)


def policy(tmp_path, **overrides) -> SandboxPolicy:
    root = tmp_path / "workspace"
    root.mkdir(exist_ok=True)
    return SandboxPolicy(workspace=root, **overrides)


def test_policy_rejects_relative_and_drive_root_workspace(tmp_path):
    with pytest.raises((ValidationError, WorkspaceError)):
        SandboxPolicy(workspace=Path("workspace"))
    with pytest.raises((ValidationError, WorkspaceError)):
        SandboxPolicy(workspace=Path(Path.cwd().anchor))


def test_policy_rejects_oversized_output_and_invalid_environment(tmp_path):
    with pytest.raises(ValidationError):
        policy(tmp_path, max_output_bytes=10_000_000)
    with pytest.raises(ValidationError):
        policy(tmp_path, env={"1BAD": "x"})
    with pytest.raises(ValidationError):
        policy(tmp_path, env={"SAFE": "x\x00y"})


def test_environment_allowlist_does_not_inherit_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    monkeypatch.setenv("RAGENTS_SANDBOX_SECRET", "secret-value")
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    environment = sandbox_environment(policy(tmp_path, env={"EXPLICIT": "yes"}),
                                      tmp_path / "temp", path="/usr/bin:/bin")
    assert "OPENAI_API_KEY" not in environment
    assert "RAGENTS_SANDBOX_SECRET" not in environment
    assert environment["EXPLICIT"] == "yes"
    assert environment["LANG"] == "tr_TR.UTF-8"
    assert environment["TMPDIR"] == str(tmp_path / "temp")
    assert environment["PYTHONNOUSERSITE"] == "1"


def test_argv_validation_rejects_empty_nul_and_oversized_values():
    with pytest.raises(SandboxError):
        validate_argv([])
    with pytest.raises(SandboxError):
        validate_argv(["python", "a\x00b"])
    with pytest.raises(SandboxError):
        validate_argv(["python", "x" * 40_000])


def test_platform_selection_returns_expected_backend_names():
    assert select_backend("win32").name == "windows-appcontainer"
    assert select_backend("darwin").name == "macos-seatbelt"
    assert select_backend("linux").name == "linux-bubblewrap"


def test_unknown_platform_is_explicitly_rejected():
    with pytest.raises(SandboxUnavailable):
        select_backend("aix")
    status = backend_status("aix")
    assert status.available is False
    assert status.backend == "unsupported"
    assert "aix" in (status.reason or "")


def test_linux_bubblewrap_command_enforces_network_and_write_isolation(tmp_path):
    backend = LinuxBubblewrapBackend(binary=Path("/usr/bin/bwrap"))
    root = tmp_path / "workspace"
    temp = tmp_path / "temp"
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    command = backend._command(["python", "-c", "print(1)"], policy(tmp_path), root, temp, environment)
    assert "--unshare-net" in command
    assert "--unshare-pid" in command
    assert "--die-with-parent" in command
    assert "--new-session" in command
    assert "--ro-bind" in command
    assert "--bind" in command
    assert "--clearenv" in command
    assert "--setenv" in command
    assert command[-4:] == ["--", "python", "-c", "print(1)"]

    writable = policy(tmp_path, writable=True)
    writable_command = backend._command(["true"], writable, root, temp, environment)
    assert "--bind" in writable_command
    assert writable_command.index(str(root)) < len(writable_command)

    (root / "src").mkdir(exist_ok=True)
    scoped = policy(tmp_path, writable_paths=("src",))
    scoped_command = backend._command(["true"], scoped, root, temp, environment)
    triples = [
        scoped_command[index:index + 3]
        for index in range(len(scoped_command) - 2)
    ]
    assert ["--bind", str(root / "src"), str(root / "src")] in triples
    assert ["--bind", str(root), str(root)] not in triples

    networked = policy(tmp_path, network=True)
    network_command = backend._command(["true"], networked, root, temp, environment)
    assert "--unshare-net" not in network_command


def test_macos_seatbelt_profile_denies_network_and_writes(tmp_path):
    root = tmp_path / "workspace"
    temp = tmp_path / "temp"
    profile = seatbelt_profile(policy(tmp_path), root, temp)
    assert "(deny network*)" in profile
    assert "(deny file-write*)" in profile
    assert "(allow file-write*" in profile
    assert str(root).replace("\\", "\\\\") not in profile
    assert str(temp).replace("\\", "\\\\") in profile

    writable = seatbelt_profile(policy(tmp_path, writable=True), root, temp)
    assert str(root).replace("\\", "\\\\") in writable
    (root / "src").mkdir(exist_ok=True)
    scoped = seatbelt_profile(policy(tmp_path, writable_paths=("src",)), root, temp)
    escaped_root = str(root).replace("\\", "\\\\")
    assert str(root / "src").replace("\\", "\\\\") in scoped
    assert f'(subpath "{escaped_root}")' not in scoped
    networked = seatbelt_profile(policy(tmp_path, network=True), root, temp)
    assert "(deny network*)" not in networked


def test_macos_and_linux_backends_report_missing_binary(tmp_path):
    mac = MacOSSeatbeltBackend(binary=tmp_path / "missing-sandbox-exec")
    assert mac.availability()[0] is False
    with pytest.raises(SandboxUnavailable):
        Sandbox(policy(tmp_path), backend=mac).run(["true"])

    linux = LinuxBubblewrapBackend(binary=tmp_path / "missing-bwrap")
    assert linux.availability()[0] is False
    assert "bwrap" in linux._missing_message()


def test_cli_sandbox_status_returns_backend_capabilities(capsys):
    assert main(["sandbox", "status"]) == 0
    payload = capsys.readouterr().out
    assert '"sandbox"' in payload
    assert '"backend"' in payload


def test_cli_sandbox_run_requires_a_command(tmp_path, capsys):
    assert main(["sandbox", "run", "--workspace", str(tmp_path)]) == 2
    assert "komut" in capsys.readouterr().err


posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX sandbox testi")


@posix_only
def test_native_posix_sandbox_blocks_writes_and_network(tmp_path):
    backend = select_backend()
    available, reason = backend.availability()
    if not available:
        pytest.skip(reason or "POSIX sandbox backend kullanılamıyor.")
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(0.5)
    port = listener.getsockname()[1]
    script = f"""
from pathlib import Path
import socket
Path("inside.txt").write_text("inside", encoding="utf-8")
print("inside-ok")
try:
    Path({str(outside)!r}).write_text("outside", encoding="utf-8")
    print("outside-allowed")
except Exception as error:
    print("outside-denied", type(error).__name__)
connection = socket.socket()
connection.settimeout(1)
try:
    connection.connect(("127.0.0.1", {port}))
    print("network-allowed")
except Exception as error:
    print("network-denied", type(error).__name__)
"""
    try:
        result = Sandbox(
            SandboxPolicy(workspace=root, writable=True), backend=backend,
        ).run([sys.executable, "-c", script])
        assert result.exit_code == 0, result.stderr
        assert "inside-ok" in result.stdout
        assert "outside-denied" in result.stdout
        assert "outside-allowed" not in result.stdout
        assert "network-denied" in result.stdout
        assert "network-allowed" not in result.stdout
        assert not outside.exists()
        with pytest.raises((TimeoutError, OSError)):
            listener.accept()
    finally:
        listener.close()


windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer testi")


@pytest.fixture(scope="module")
def windows_backend():
    from ragents.sandbox_windows import WindowsAppContainerBackend

    backend = WindowsAppContainerBackend()
    available, reason = backend.availability()
    if not available:
        pytest.skip(reason or "Windows AppContainer kullanılamıyor.")
    return backend


def run_windows(tmp_path, backend, script: str, *, writable: bool = False,
               writable_paths: tuple[str, ...] = (), network: bool = False,
               timeout: float = 10, max_output_bytes: int = 65_536,
               input: bytes | None = None):
    root = tmp_path / "workspace"
    root.mkdir(exist_ok=True)
    sandbox = Sandbox(
        SandboxPolicy(
            workspace=root, writable=writable, writable_paths=writable_paths,
            network=network, timeout_seconds=timeout, max_output_bytes=max_output_bytes,
        ),
        backend=backend,
    )
    return sandbox.run([sys.executable, "-c", script], input=input)


@windows_only
def test_windows_appcontainer_blocks_writes_and_reads_outside_workspace(tmp_path, windows_backend):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    script = f"""
from pathlib import Path
Path("inside.txt").write_text("inside", encoding="utf-8")
print("inside-ok")
try:
    Path({str(outside)!r}).write_text("bad", encoding="utf-8")
    print("outside-write-allowed")
except Exception as error:
    print("outside-write-denied", type(error).__name__)
try:
    print("outside-read", Path({str(outside)!r}).read_text(encoding="utf-8"))
except Exception as error:
    print("outside-read-denied", type(error).__name__)
"""
    result = run_windows(tmp_path, windows_backend, script, writable=True)
    assert result.exit_code == 0, result.stderr
    assert "inside-ok" in result.stdout
    assert "outside-write-denied" in result.stdout
    assert "outside-write-allowed" not in result.stdout
    assert "outside-read-denied" in result.stdout
    assert (root / "inside.txt").read_text(encoding="utf-8") == "inside"
    assert outside.read_text(encoding="utf-8") == "outside"


@windows_only
def test_windows_appcontainer_limits_writes_to_granted_subdirectory(tmp_path, windows_backend):
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    script = """
from pathlib import Path
for relative in ("src/izinli.txt", "docs/yetkisiz.txt", "kok.txt"):
    try:
        Path(relative).write_text("veri", encoding="utf-8")
        print(relative, "written")
    except Exception as error:
        print(relative, "denied", type(error).__name__)
"""
    result = run_windows(tmp_path, windows_backend, script, writable_paths=("src",))
    assert result.exit_code == 0, result.stderr
    assert "src/izinli.txt written" in result.stdout
    assert "docs/yetkisiz.txt denied" in result.stdout
    assert "kok.txt denied" in result.stdout
    assert (root / "src" / "izinli.txt").read_text(encoding="utf-8") == "veri"
    assert not (root / "docs" / "yetkisiz.txt").exists()
    assert not (root / "kok.txt").exists()
    assert result.writable is True
    assert result.writable_paths == (str((root / "src").resolve()),)


@windows_only
def test_windows_appcontainer_blocks_network(tmp_path, windows_backend):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(0.5)
    port = listener.getsockname()[1]
    try:
        script = f"""
import socket
connection = socket.socket()
connection.settimeout(1)
try:
    connection.connect(("127.0.0.1", {port}))
    print("network-allowed")
except Exception as error:
    print("network-denied", type(error).__name__)
"""
        result = run_windows(tmp_path, windows_backend, script)
        assert result.exit_code == 0, result.stderr
        assert "network-denied" in result.stdout
        assert "network-allowed" not in result.stdout
        with pytest.raises(TimeoutError):
            listener.accept()
    finally:
        listener.close()


@windows_only
def test_windows_appcontainer_timeout_kills_descendants(tmp_path, windows_backend):
    marker = tmp_path / "workspace" / "grandchild.txt"
    script = f"""
import subprocess
import sys
import time
subprocess.Popen([sys.executable, "-c",
    "import time; time.sleep(2); open({str(marker)!r}, 'w').write('alive')"])
print("spawned", flush=True)
time.sleep(10)
"""
    result = run_windows(tmp_path, windows_backend, script, timeout=1.0, writable=True)
    assert result.timed_out is True
    assert "spawned" in result.stdout
    time.sleep(2.5)
    assert not marker.exists()


@windows_only
def test_windows_appcontainer_limits_child_processes(tmp_path, windows_backend):
    script = """
import subprocess
import sys
try:
    subprocess.Popen([sys.executable, "-c", "print('child')"])
    print("child-allowed")
except OSError as error:
    print("child-denied", type(error).__name__)
"""
    root = tmp_path / "workspace"
    root.mkdir()
    base_python = Path(sys.base_prefix) / "python.exe"
    result = Sandbox(
        SandboxPolicy(workspace=root, writable=True, max_processes=1),
        backend=windows_backend,
    ).run([str(base_python), "-c", script])
    assert result.exit_code == 0, result.stderr
    assert "child-denied" in result.stdout
    assert "child-allowed" not in result.stdout


@windows_only
def test_windows_appcontainer_limits_output_and_does_not_leak_secrets(
    tmp_path, windows_backend, monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    script = """
import os
print("secret", os.environ.get("OPENAI_API_KEY", "absent"))
print("x" * 100000)
"""
    result = run_windows(tmp_path, windows_backend, script, max_output_bytes=1024)
    assert "secret absent" in result.stdout
    assert result.output_truncated is True
    assert len(result.stdout) <= 1024


@windows_only
def test_windows_appcontainer_stdin_and_hard_cancel(tmp_path, windows_backend):
    root = tmp_path / "workspace"
    root.mkdir()
    sandbox = Sandbox(SandboxPolicy(workspace=root, writable=True), backend=windows_backend)
    echoed = sandbox.run([sys.executable, "-c", "import sys; print(sys.stdin.read())"],
                         input=b"merhaba")
    assert echoed.exit_code == 0
    assert "merhaba" in echoed.stdout

    started = root / "started.txt"
    script = f"""
from pathlib import Path
import time
Path("started.txt").write_text("started", encoding="utf-8")
time.sleep(10)
"""
    result_box = {}

    def execute() -> None:
        result_box["result"] = sandbox.run([sys.executable, "-c", script])

    thread = threading.Thread(target=execute)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started.exists()
        sandbox.cancel()
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert result_box["result"].cancelled is True
    finally:
        sandbox.cancel()
        thread.join(timeout=5)


@windows_only
def test_windows_cli_runs_scoped_writable_command(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    assert main([
        "sandbox", "run", "--workspace", str(workspace), "--writable-path", "src",
        "--cwd", "src", "--", sys.executable, "-c",
        "open('cli.txt', 'w').write('cli'); print('cli-ok')",
    ]) == 0
    output = capsys.readouterr().out
    assert "cli-ok" in output
    assert '"writable": true' in output
    assert (workspace / "src" / "cli.txt").read_text(encoding="utf-8") == "cli"
    assert not (workspace / "cli.txt").exists()


@windows_only
def test_windows_cli_runs_isolated_command(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert main([
        "sandbox", "run", "--workspace", str(workspace), "--writable",
        "--", sys.executable, "-c", "print('sandbox-ok')",
    ]) == 0
    output = capsys.readouterr().out
    assert "sandbox-ok" in output
    assert '"timed_out": false' in output
