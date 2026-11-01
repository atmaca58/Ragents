"""Sabit Git alt komutları; kabuk, hook, filtre ve ağ çalıştırılmaz."""
from pathlib import Path
import re
import shutil
import sys

from ragents.errors import WorkspaceError
from ragents.sandbox import Sandbox, SandboxPolicy
from ragents.workspace import Workspace


SAFE_CONFIG = frozenset({"core.repositoryformatversion", "core.filemode", "core.bare", "core.logallrefupdates",
    "core.ignorecase", "core.precomposeunicode", "core.symlinks", "core.longpaths", "user.name", "user.email",
    "extensions.objectformat", "init.defaultbranch"})


def git_executable():
    bundled = Path(sys.executable).parent.parent / "git/cmd/git.exe"
    if bundled.is_file():
        return bundled
    found = shutil.which("git")
    if found is None:
        raise WorkspaceError("Git çalışma zamanı bulunamadı; ürün kurulumunu kontrol edin.")
    return Path(found).resolve()


class GitTools:
    def __init__(self, grant, *, executable=None, sandbox_factory=Sandbox):
        self.grant, self.factory = grant, sandbox_factory
        self.workspace = Workspace(grant.root, grant.protected_paths, readable_paths=grant.readable_paths,
                                   writable_paths=grant.writable_paths)
        self.executable = executable or git_executable()

    async def _run(self, arguments, *, write=False):
        if write and "." not in self.grant.writable_paths:
            raise WorkspaceError("Git yazma işlemi kök ve .git için açık yazma izni gerektirir.")
        null = "NUL" if sys.platform == "win32" else "/dev/null"
        environment = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": null, "GIT_TERMINAL_PROMPT": "0",
                       "GIT_OPTIONAL_LOCKS": "0", "GIT_ATTR_NOSYSTEM": "1"}
        policy = SandboxPolicy(workspace=self.workspace.root, writable_paths=self.grant.writable_paths if write else (),
            network=False, timeout_seconds=self.grant.command_timeout_seconds, max_output_bytes=self.grant.max_output_bytes,
            env=environment, env_allowlist=tuple(environment),
            runtime_roots=(self.executable.parent.parent,) if self.executable.is_file() else ())
        argv = [str(self.executable), "--no-pager", "-c", f"core.hooksPath={null}", "-c", "core.fsmonitor=false",
                "-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false", *arguments]
        result = await self.factory(policy).run_async(argv)
        if result.exit_code != 0 or result.timed_out:
            raise WorkspaceError("Git işlemi başarısız; repository, izin veya çalışma zamanını kontrol edin.")
        return {"stdout": result.stdout, "exit_code": result.exit_code}

    async def _check(self):
        result = await self._run(["config", "--local", "--no-includes", "--null", "--list"])
        for entry in result["stdout"].split("\0"):
            if not entry:
                continue
            key = entry.split("\n", 1)[0].lower()
            safe_remote = key.startswith("remote.") and key.rsplit(".", 1)[-1] in ("url", "fetch", "pushurl")
            safe_branch = key.startswith("branch.") and key.rsplit(".", 1)[-1] in ("remote", "merge")
            if key not in SAFE_CONFIG and not safe_remote and not safe_branch:
                raise WorkspaceError("Komut veya desteklenmeyen davranış içeren Git yapılandırması reddedildi.")

    async def status(self):
        await self._check()
        return await self._run(["status", "--porcelain=v1", "--untracked-files=normal"])

    async def diff(self):
        await self._check()
        return await self._run(["diff", "--no-ext-diff", "--no-textconv", "--"])

    async def branch(self, name):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
            raise WorkspaceError("Branch adı yalnız harf, rakam, tire ve alt çizgi içermelidir.")
        await self._check()
        return await self._run(["branch", "--", name], write=True)

    async def worktree(self, name, commit):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", name) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", commit):
            raise WorkspaceError("Worktree adı veya tam commit hash'i geçersiz.")
        await self._check()
        path = self.workspace._target(f".ragents-worktrees/{name}", must_exist=False, access="write")
        return await self._run(["worktree", "add", "--detach", str(path), commit], write=True)

    async def commit(self, message, paths):
        if not message.strip() or len(message) > 2000 or not 1 <= len(paths) <= 32:
            raise WorkspaceError("Commit mesajı veya dosya listesi geçersiz.")
        checked = []
        for value in paths:
            path = self.workspace._target(value, access="write")
            if not path.is_file() or ".git" in path.relative_to(self.workspace.root).parts:
                raise WorkspaceError("Commit yalnız açıkça seçilmiş normal dosyaları alabilir.")
            checked.append(path.relative_to(self.workspace.root).as_posix())
        await self._check()
        await self._run(["add", "--", *checked], write=True)
        result = await self._run(["-c", "user.name=R Agents", "-c", "user.email=local@ragents.invalid",
            "commit", "--no-verify", "--no-gpg-sign", "--message", message, "--only", "--", *checked], write=True)
        result["commit"] = (await self._run(["rev-parse", "HEAD"]))["stdout"].strip()
        return result


def git_tool_handlers(grant, *, sandbox_factory=Sandbox):
    tools = GitTools(grant, sandbox_factory=sandbox_factory)
    async def git_status() -> dict:
        """Git durumunu sandbox içinde oku."""
        return await tools.status()
    async def git_diff() -> dict:
        """Harici diff veya textconv çalıştırmadan değişiklikleri oku."""
        return await tools.diff()
    async def git_branch(name: str) -> dict:
        """İzinli repository içinde yeni branch oluştur."""
        return await tools.branch(name)
    async def git_worktree(name: str, commit: str) -> dict:
        """Tam commit kimliğinden workspace içinde bağımsız worktree oluştur."""
        return await tools.worktree(name, commit)
    async def git_commit(message: str, paths: list[str]) -> dict:
        """Yalnız seçilen dosyaları commit et; push yapmaz."""
        return await tools.commit(message, paths)
    return {function.__name__: function for function in (git_status, git_diff, git_branch, git_worktree, git_commit)}
