from pathlib import Path
import pytest

from ragents.cli import build_parser
from ragents.task_cli import resolve_database


def test_default_commands_share_user_profile_and_explicit_root_wins(tmp_path, monkeypatch):
    from ragents.profile_paths import profile_root
    from ragents.auth import auth_root

    monkeypatch.delenv("RAGENTS_HOME", raising=False)
    monkeypatch.setattr("ragents.profile_paths.sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    expected = (tmp_path / "RAgents" / "profiles" / "default").resolve()
    assert profile_root() == auth_root() == expected
    parser = build_parser()
    for command in (["tasks", "list"], ["worker", "--once"], ["mcp", "serve"]):
        assert resolve_database(parser.parse_args(command)) == expected / "data" / "ragents.db"
    override = tmp_path / "custom"
    monkeypatch.setenv("RAGENTS_HOME", str(override))
    assert profile_root() == override
    assert profile_root(tmp_path / "explicit") == tmp_path / "explicit"
    assert not expected.exists()


def test_explicit_root_also_scopes_model_credentials(tmp_path, monkeypatch, capsys):
    from contextlib import asynccontextmanager
    from pydantic_ai.models.test import TestModel
    from ragents import application
    from ragents.auth import auth_root
    from ragents.cli import main
    from ragents.engines.native import NativeEngine

    seen = []

    @asynccontextmanager
    async def engine(_connection):
        seen.append(auth_root())
        yield NativeEngine(TestModel(custom_output_text="ok"))

    monkeypatch.setattr(application, "open_engine", engine)
    assert main(["run", "--root", str(tmp_path), "--config", "examples/ollama.yaml", "Test"]) == 0
    assert seen == [tmp_path]
    capsys.readouterr()


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_experimental_platform_profile_uses_xdg_data_root(tmp_path, monkeypatch, platform):
    from ragents.profile_paths import profile_root

    monkeypatch.delenv("RAGENTS_HOME", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("ragents.profile_paths.sys.platform", platform)
    assert profile_root() == tmp_path / "RAgents" / "profiles" / "default"
