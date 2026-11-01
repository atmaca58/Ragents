import json
from pathlib import Path
import tomllib

from ragents.client_connections import configure_client, mcp_command


def test_codex_registration_preserves_settings_and_is_idempotent(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('# my setting\nmodel = "my-model"\n[mcp_servers.other]\ncommand="other"\n', encoding="utf-8")
    original = path.read_bytes()
    result = configure_client("codex", tmp_path / "profile", config_path=path)
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    assert config["model"] == "my-model"
    assert config["mcp_servers"]["other"]["command"] == "other"
    assert "# my setting" in path.read_text(encoding="utf-8")
    assert Path(result["backup"]).read_bytes() == original
    assert config["mcp_servers"]["r_agents"]["args"] == mcp_command(tmp_path / "profile")[1:]
    assert not configure_client("codex", tmp_path / "profile", config_path=path)["changed"]


def test_opencode_jsonc_and_claude_keep_existing_servers(tmp_path):
    import json5
    for client in ("opencode", "claude", "claude-desktop"):
        path = tmp_path / f"{client}.json"
        key = "mcp" if client == "opencode" else "mcpServers"
        original = '// user comment\n' + json.dumps({"theme": "dark", key: {"existing": {"command": "other"}}})
        path.write_text(original, encoding="utf-8")
        result = configure_client(client, tmp_path / "profile", config_path=path)
        configured = json5.loads(path.read_text(encoding="utf-8"))
        assert configured["theme"] == "dark"
        assert configured[key]["existing"]["command"] == "other"
        assert "r_agents" in configured[key]
        assert Path(result["backup"]).read_text(encoding="utf-8") == original


def test_stdio_handshake_never_runs_a_model(tmp_path):
    import asyncio
    from ragents.client_connections import test_stdio_connection
    result = asyncio.run(test_stdio_connection(tmp_path))
    assert result["mcp_verified"]
    assert result["model_requests"] == 0


def test_chatgpt_preview_keeps_profile_and_permissions_without_writing(tmp_path, capsys):
    from ragents.cli import main
    root = tmp_path / "profile with spaces"
    assert main(["connect", "chatgpt", "--root", str(root), "--public-url", "https://mcp.example.test", "--show"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["serve_argv"] == ["ragents", "mcp", "serve", "--root", str(root.resolve()),
        "--transport", "streamable-http", "--public-url", "https://mcp.example.test",
        "--allow-manage", "--allow-write", "--allow-execute"]
    assert not root.exists()
    assert not report["connection_verified"]


def test_chatgpt_cannot_misreport_local_test_as_remote_acceptance(tmp_path, capsys):
    from ragents.cli import main
    assert main(["connect", "chatgpt", "--root", str(tmp_path), "--public-url", "https://mcp.example.test", "--test"]) == 2
    assert "gerçek" in capsys.readouterr().err.lower()


def test_chatgpt_background_preserves_selected_read_only_mode(tmp_path, capsys):
    from ragents.cli import main
    from ragents.windows_service import supervisor_commands
    for read_only in (True, False):
        root = tmp_path / str(read_only)
        args = ["connect", "chatgpt", "--root", str(root), "--public-url", "https://mcp.example.test"]
        assert main(args + (["--read-only"] if read_only else [])) == 0
        capsys.readouterr()
        command = supervisor_commands(root)[1]
        for flag in ("--allow-manage", "--allow-write", "--allow-execute"):
            assert (flag in command) is not read_only


def test_legacy_remote_settings_do_not_grant_background_writes(tmp_path):
    from ragents.windows_service import supervisor_commands
    (tmp_path / "connections").mkdir()
    (tmp_path / "connections/remote.json").write_text(json.dumps({"public_url": "https://mcp.example.test"}))
    command = supervisor_commands(tmp_path)[1]
    assert all(flag not in command for flag in ("--allow-manage", "--allow-write", "--allow-execute"))
