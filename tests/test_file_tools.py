import asyncio
import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from ragents.config import AgentSpec, Budget, load_config
from ragents.contracts import RunRequest, RunResult, Usage
from ragents.errors import WorkspaceError
from ragents.sandbox import backend_status
from ragents.storage import TaskStore
from ragents.task_service import TaskService
from ragents.tools import (
    build_tools, is_publish_command, validate_command_argv,
)
from ragents.workspace import ArtifactDraft, ArtifactLog, Workspace, WorkspaceGrant


def make_agent(*tools) -> AgentSpec:
    return AgentSpec(
        id="gelistirici", name="Geliştirici", instructions="Kısa yanıt ver.",
        connection="primary", tools=tools,
    )


def make_grant(tmp_path, **overrides) -> WorkspaceGrant:
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    values = {
        "root": root, "writable_paths": ("src",), "commands": ("python",),
        "command_timeout_seconds": 20,
    }
    values.update(overrides)
    return WorkspaceGrant(**values)


def tool_map(agent, grant, *, artifacts=None):
    return {
        tool.__name__: tool
        for tool in build_tools(agent, grant, artifacts=artifacts)
    }


def test_workspace_write_and_patch_enforce_writable_scope(tmp_path):
    grant = make_grant(tmp_path)
    workspace = Workspace(grant.root, writable_paths=grant.writable_paths)

    written = workspace.write_file("src/ornek.py", "print('ilk')\n")
    assert written["created"] is True
    assert written["path"] == "src/ornek.py"
    patched = workspace.apply_patch(
        "src/ornek.py", "print('ilk')", "print('yeni')",
        expected_sha256=written["sha256"],
    )
    assert patched["replacements"] == 1
    assert (grant.root / "src" / "ornek.py").read_text(encoding="utf-8") == "print('yeni')\n"

    with pytest.raises(WorkspaceError, match="yazılabilir"):
        workspace.write_file("docs/yetkisiz.txt", "veri")
    with pytest.raises(WorkspaceError, match="dışına"):
        workspace.write_file("../disari.txt", "veri")
    with pytest.raises(WorkspaceError, match="zaten var"):
        workspace.write_file("src/ornek.py", "ezme")
    with pytest.raises(WorkspaceError, match="eşleşmiyor"):
        workspace.apply_patch(
            "src/ornek.py", "print('yeni')", "x", expected_sha256="0" * 64,
        )


def test_read_scope_limits_read_tools_and_write_scope_must_be_inside(tmp_path):
    from ragents.workspace import TaskPermissions

    grant = make_grant(tmp_path, readable_paths=("src",))
    workspace = Workspace(
        grant.root, readable_paths=grant.readable_paths,
        writable_paths=grant.writable_paths,
    )
    (grant.root / "src" / "ok.txt").write_text("içerik", encoding="utf-8")
    (grant.root / "docs" / "gizli.txt").write_text("gizli", encoding="utf-8")
    assert workspace.read_file("src/ok.txt")["content"] == "içerik"
    with pytest.raises(WorkspaceError, match="okunabilir"):
        workspace.read_file("docs/gizli.txt")
    with pytest.raises(WorkspaceError, match="okunabilir"):
        workspace.search_text("gizli")
    with pytest.raises(ValidationError, match="okunabilir kapsam"):
        TaskPermissions(readable_paths=("src",), writable_paths=("docs",))


def test_workspace_patch_requires_unique_match_and_bounds_size(tmp_path):
    grant = make_grant(tmp_path)
    workspace = Workspace(grant.root, writable_paths=grant.writable_paths)
    workspace.write_file("src/tekrar.txt", "aynı\ndiğer\naynı\n")
    with pytest.raises(WorkspaceError, match="birden çok"):
        workspace.apply_patch("src/tekrar.txt", "aynı", "farklı")
    result = workspace.apply_patch("src/tekrar.txt", "aynı", "farklı", replace_all=True)
    assert result["replacements"] == 2
    with pytest.raises(WorkspaceError, match="bulamadı"):
        workspace.apply_patch("src/tekrar.txt", "yok", "x")


def test_write_and_command_tools_need_explicit_task_permissions(tmp_path):
    grant = make_grant(tmp_path, writable_paths=(), commands=())
    agent = make_agent("write_file", "run_command")

    with pytest.raises(ValidationError, match="yazılabilir dizin"):
        RunRequest(agent=make_agent("write_file"), prompt="Yaz", workspace=grant)
    with pytest.raises(ValidationError, match="komut listesi"):
        RunRequest(agent=make_agent("run_command"), prompt="Çalıştır", workspace=grant)
    with pytest.raises(WorkspaceError, match="yazılabilir"):
        build_tools(make_agent("write_file"), grant)
    with pytest.raises(WorkspaceError, match="komut listesi"):
        build_tools(make_agent("run_command"), grant)

    store = TaskStore(tmp_path / "tasks.db")
    config = load_config(Path("examples/ollama.yaml")).model_copy(
        update={"agent": agent},
    )
    with pytest.raises(ValidationError, match="yazılabilir dizin"):
        store.enqueue(config, "Görev", workspace=grant)


def sandbox_or_skip():
    status = backend_status()
    if not status.available:
        pytest.skip(status.reason or "Sandbox backend kullanılamıyor.")
    return status


def test_sandboxed_write_and_patch_record_final_artifact(tmp_path):
    sandbox_or_skip()
    grant = make_grant(tmp_path)
    artifacts = ArtifactLog()
    tools = tool_map(
        make_agent("write_file", "apply_patch"), grant, artifacts=artifacts,
    )

    written = asyncio.run(tools["write_file"]("src/uygulama.py", "değer = 1\n"))
    patched = asyncio.run(tools["apply_patch"](
        "src/uygulama.py", "değer = 1", "değer = 2",
    ))
    assert written["created"] is True
    assert patched["replacements"] == 1
    content = (grant.root / "src" / "uygulama.py").read_text(encoding="utf-8")
    assert content == "değer = 2\n"
    assert len(artifacts.drafts) == 1
    assert artifacts.drafts[0].path == "src/uygulama.py"
    assert artifacts.drafts[0].sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()

    with pytest.raises(WorkspaceError, match="tamamlanamadı"):
        asyncio.run(tools["write_file"]("docs/yetkisiz.txt", "veri"))
    with pytest.raises(WorkspaceError, match="tamamlanamadı"):
        asyncio.run(tools["write_file"]("../disari.txt", "veri"))


def test_run_command_allowlist_cwd_publish_and_output_limit(tmp_path):
    sandbox_or_skip()
    grant = make_grant(tmp_path, commands=("python", "git"), max_output_bytes=1024)
    tools = tool_map(
        make_agent("run_command"), grant,
    )

    result = asyncio.run(tools["run_command"](
        ["python", "-c", "print('sandbox-ok')"], cwd="src",
    ))
    assert result["exit_code"] == 0
    assert "sandbox-ok" in result["stdout"]
    assert result["writable"] is True
    assert result["network_allowed"] is False

    with pytest.raises(WorkspaceError, match="izinli değil"):
        asyncio.run(tools["run_command"](["cmd", "/c", "echo", "x"]))
    with pytest.raises(WorkspaceError, match="yayın"):
        asyncio.run(tools["run_command"](["git", "push"]))
    with pytest.raises(WorkspaceError, match="dışına"):
        asyncio.run(tools["run_command"](["python", "-c", "print(1)"], cwd="../"))

    loud = asyncio.run(tools["run_command"](
        ["python", "-c", "print('x' * 20000)"],
    ))
    assert loud["output_truncated"] is True
    assert len(loud["stdout"]) <= 1024


def test_native_engine_exposes_write_patch_and_command_tools(tmp_path):
    sandbox_or_skip()
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel

    from ragents.engines.native import NativeEngine

    grant = make_grant(tmp_path)
    agent = make_agent("write_file", "apply_patch", "run_command").model_copy(
        update={"budget": Budget(tool_calls_limit=4, request_limit=5)},
    )

    def respond(messages, info):
        returns = [
            part for message in messages for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not returns:
            assert [tool.name for tool in info.function_tools] == [
                "write_file", "apply_patch", "run_command",
            ]
            return ModelResponse(parts=[ToolCallPart(
                "write_file", {"path": "src/uygulama.py", "content": "değer = 1\n"},
            )])
        if len(returns) == 1:
            return ModelResponse(parts=[ToolCallPart(
                "apply_patch",
                {"path": "src/uygulama.py", "old_text": "değer = 1", "new_text": "değer = 3"},
            )])
        if len(returns) == 2:
            return ModelResponse(parts=[ToolCallPart("run_command", {
                "argv": ["python", "-c", "print(open('src/uygulama.py').read().strip())"],
            })])
        assert "değer = 3" in returns[-1].content["stdout"]
        return ModelResponse(parts=[TextPart("Tamam.")])

    result = asyncio.run(NativeEngine(FunctionModel(respond)).run(
        RunRequest(agent=agent, prompt="Dosyayı düzenle ve sına", workspace=grant),
    ))
    assert result.output == "Tamam."
    assert result.usage.tool_calls == 3
    content = (grant.root / "src" / "uygulama.py").read_text(encoding="utf-8")
    assert content == "değer = 3\n"
    assert [draft.path for draft in result.artifacts] == ["src/uygulama.py"]
    assert result.artifacts[0].sha256 == hashlib.sha256(content.encode()).hexdigest()


def test_command_validation_and_publish_classification():
    with pytest.raises(WorkspaceError):
        validate_command_argv([])
    with pytest.raises(WorkspaceError):
        validate_command_argv(["python", "a\x00b"])
    with pytest.raises(WorkspaceError):
        validate_command_argv(["python", "x" * 9000])

    assert is_publish_command(["git", "-C", "repo", "push"])
    assert is_publish_command(["npm", "publish"])
    assert is_publish_command(["gh", "pr", "create"])
    assert is_publish_command(["docker", "push", "image"])
    assert is_publish_command(["twine", "upload", "dist/*"])
    assert not is_publish_command(["git", "status"])
    assert not is_publish_command(["python", "-m", "pytest"])
    assert not is_publish_command(["gh", "pr", "view"])


def test_task_service_records_file_tool_artifacts_explicitly(tmp_path):
    grant = make_grant(tmp_path)
    store = TaskStore(tmp_path / "tasks.db")
    config = load_config(Path("examples/ollama.yaml"))
    task = store.enqueue(config, "Görev", workspace=grant)

    async def runner(config, prompt, connection, grant):
        content = "üretilen içerik"
        path = grant.root / "src" / "uretim.txt"
        path.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return RunResult(
            agent_id=config.agent.id, output="Tamam",
            usage=Usage(requests=1, tool_calls=1),
            artifacts=(ArtifactDraft("src/uretim.txt", len(content.encode()), digest),),
        )

    asyncio.run(TaskService(store, runner=runner).execute(task.id))
    artifacts = store.artifacts(task.id)
    assert [artifact.path for artifact in artifacts] == ["src/uretim.txt"]
    assert artifacts[0].producer == "file_tool"
    assert artifacts[0].sha256 == hashlib.sha256("üretilen içerik".encode()).hexdigest()


def test_agent_task_snapshots_permissions_and_allows_task_override(tmp_path):
    from ragents.catalog import create_agent, enqueue_agent_task
    from ragents.workspace import TaskPermissions

    root = tmp_path / "profile"
    workspace = tmp_path / "proje"
    (workspace / "src").mkdir(parents=True)
    (workspace / "docs").mkdir()
    from ragents.catalog import AgentProfile

    agent = AgentProfile(
        schema_version=3, id="gelistirici", name="Geliştirici",
        connection="local",
        connections={"local": load_config(Path("examples/ollama.yaml")).connections["local"]},
        tools=("write_file", "run_command"),
        permissions=TaskPermissions(
            writable_paths=("src",), commands=("python",),
        ),
    )
    create_agent(root, agent, "Talimat", workspace=str(workspace))
    store = TaskStore(tmp_path / "tasks.db")
    task = enqueue_agent_task(store, root, "gelistirici", "Görev")
    grant = store.definition(task.id).workspace
    assert grant is not None
    assert grant.writable_paths == ("src",)
    assert grant.commands == ("python",)
    assert grant.allow_network is False

    overridden = enqueue_agent_task(
        store, root, "gelistirici", "İkinci görev",
        writable_paths=("docs",), commands=("pytest",),
    )
    second = store.definition(overridden.id).workspace
    assert second is not None
    assert second.writable_paths == ("docs",)
    assert second.commands == ("pytest",)


def test_cli_update_merges_permission_changes(tmp_path, capsys):
    import json
    from ragents.cli import main

    root = tmp_path / "profile"
    workspace = tmp_path / "proje"
    (workspace / "src").mkdir(parents=True)
    (workspace / "docs").mkdir()
    base = ["agents", "--root", str(root)]
    assert main([
        *base, "create", "--id", "gelistirici", "--name", "Geliştirici",
        "--provider", "ollama", "--model", "test-model",
        "--tool", "write_file", "--tool", "run_command",
        "--writable-path", "src", "--allowed-command", "python",
        "--workspace", str(workspace),
    ]) == 0
    capsys.readouterr()
    assert main([
        *base, "update", "gelistirici", "--writable-path", "docs",
        "--allowed-command", "pytest", "--allow-network", "--allow-publish",
    ]) == 0
    permissions = json.loads(capsys.readouterr().out)["agent"]["permissions"]
    assert permissions["writable_paths"] == ["src", "docs"]
    assert permissions["commands"] == ["python", "pytest"]
    assert permissions["allow_network"] is True
    assert permissions["allow_publish"] is True


def test_cli_lists_permission_fields_for_agent(tmp_path, capsys):
    import json
    from ragents.cli import main

    root = tmp_path / "profile"
    workspace = tmp_path / "proje"
    (workspace / "src").mkdir(parents=True)
    assert main([
        "agents", "--root", str(root), "create", "--id", "gelistirici",
        "--name", "Geliştirici", "--provider", "ollama", "--model", "test-model",
        "--tool", "write_file", "--tool", "run_command",
        "--writable-path", "src", "--allowed-command", "python",
        "--workspace", str(workspace),
    ]) == 0
    created = json.loads(capsys.readouterr().out)
    permissions = created["agent"]["permissions"]
    assert permissions["writable_paths"] == ["src"]
    assert permissions["commands"] == ["python"]
    assert permissions["allow_publish"] is False
