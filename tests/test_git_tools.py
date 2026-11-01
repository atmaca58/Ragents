import asyncio
from types import SimpleNamespace
from pathlib import Path
import pytest

from ragents.git_tools import GitTools
from ragents.workspace import WorkspaceGrant
from ragents.errors import WorkspaceError


def test_git_rejects_command_capable_local_configuration(tmp_path):
    calls = []
    class Sandbox:
        def __init__(self, policy):
            assert policy.network is False
        async def run_async(self, argv):
            calls.append(argv)
            return SimpleNamespace(exit_code=0, stdout="filter.evil.clean\nsteal-secrets\0", stderr="", timed_out=False)
    tool = GitTools(WorkspaceGrant(root=tmp_path, writable_paths=(".",)),
                    executable=Path("C:/trusted/git.exe"), sandbox_factory=Sandbox)
    with pytest.raises(WorkspaceError, match="yapılandırma"):
        asyncio.run(tool.status())
    assert len(calls) == 1


def test_git_status_runs_in_native_sandbox(tmp_path):
    import sys
    import os
    import shutil
    import subprocess
    from ragents.git_tools import git_executable
    from ragents.sandbox import backend_status
    if not backend_status().available or shutil.which("git") is None:
        pytest.skip("Native sandbox veya Git yok")
    subprocess.run([str(git_executable()), "init", str(tmp_path)], check=True, capture_output=True,
                   env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"})
    (tmp_path / "report.txt").write_text("Evidence", encoding="utf-8")
    executable = git_executable()
    if sys.platform == "win32":
        # Kurucudaki kullanıcıya ait MinGit yerleşimini gerçek Git binary'siyle temsil et.
        source = next((executable.parent.parent / layout for layout in ("ucrt64/bin", "mingw64/bin")
                       if (executable.parent.parent / layout / "git.exe").is_file()), None)
        assert source is not None, "Windows Git çalışma zamanı dizini bulunamadı."
        target = tmp_path / "runtime/git/bin"
        target.mkdir(parents=True)
        for path in [source / "git.exe", *source.glob("*.dll")]:
            shutil.copy2(path, target / path.name)
        executable = target / "git.exe"
    result = asyncio.run(GitTools(WorkspaceGrant(root=tmp_path), executable=executable).status())
    assert "report.txt" in result["stdout"]
