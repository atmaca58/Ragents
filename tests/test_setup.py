import json

from ragents.cli import main
from ragents.config import load_config
import pytest


def test_setup_creates_custom_agent_and_matching_service_clients(tmp_path, capsys):
    import tomllib

    directory = tmp_path / "my agents 🧪"
    assert main(["setup", "--non-interactive", "--provider", "ollama", "--model", "local-model",
                 "--agent-id", "analist", "--name", "Analist", "--instructions", "Kısa rapor hazırla.",
                 "--directory", str(directory)]) == 0
    payload = json.loads(capsys.readouterr().out)
    config = load_config(directory / "ragents.yaml")
    assert config.agent.id == "analist"
    assert config.agent.instructions == "Kısa rapor hazırla."
    assert config.connections[config.agent.connection].model == "local-model"
    assert config.agent.tools == config.agent.mcp_tools == ()
    assert payload["connection"]["remote_validated"] is False
    assert payload["connection"]["credentials_ready"] is True
    client = json.loads((directory / "mcp-client.json").read_text(encoding="utf-8"))["mcpServers"]["r-agents"]
    codex = tomllib.loads((directory / "codex-mcp.toml").read_text(encoding="utf-8"))["mcp_servers"]["r_agents"]
    assert client["args"] == codex["args"]
    assert str(directory / "ragents.yaml") in client["args"]
    assert "--allow-execute" in client["args"]
    assert payload["worker_argv"][-1] == str(directory / "data" / "ragents.db")
    assert not (directory / "data").exists()


def test_setup_rejects_credentials_in_endpoint_before_writing_profile(tmp_path, capsys):
    directory = tmp_path / "invalid"
    assert main(["setup", "--non-interactive", "--provider", "ollama", "--model", "local-model",
                 "--base-url", "http://user:private-pass@localhost:11434/v1", "--directory", str(directory)]) == 2
    captured = capsys.readouterr()
    assert "private-pass" not in captured.out + captured.err
    assert not directory.exists()


@pytest.mark.parametrize("provider,env_name", [
    ("openrouter", "OPENROUTER_API_KEY"),
    ("opencode_go", "OPENCODE_GO_API_KEY"),
    ("opencode_zen", "OPENCODE_ZEN_API_KEY"),
])
def test_hosted_provider_uses_env_reference_without_saving_secret(provider, env_name, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(env_name, "private-test-key")
    directory = tmp_path / "profile"
    assert main(["setup", "--non-interactive", "--provider", provider, "--model", "chosen-model",
                 "--directory", str(directory)]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["connection"]["credentials_ready"] is True
    assert load_config(directory / "ragents.yaml").connections["primary"].api_key_env == env_name
    assert "private-test-key" not in output.out + output.err
    assert all("private-test-key" not in path.read_text(encoding="utf-8") for path in directory.iterdir())


def test_interactive_setup_collects_customization_without_calling_model(tmp_path, monkeypatch, capsys):
    answers = iter(["ollama", "my-model", "ekip", "Ekip Asistanı", "Özet hazırla.", "", "h"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    directory = tmp_path / "guided"
    assert main(["setup", "--directory", str(directory)]) == 0
    captured = capsys.readouterr()
    config = load_config(directory / "ragents.yaml")
    assert config.agent.name == "Ekip Asistanı"
    assert config.agent.id == "ekip"
    assert config.agent.instructions == "Özet hazırla."
    assert json.loads(captured.out)["connection"]["model_requests"] == 0
    assert "Sağlayıcı" in captured.err


def test_setup_verify_uses_single_probe_and_keeps_generated_config(tmp_path, monkeypatch, capsys):
    from contextlib import asynccontextmanager
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel
    from ragents.engines.native import NativeEngine

    requests = []

    def respond(messages, info):
        requests.append(info)
        assert info.function_tools == []
        return ModelResponse(parts=[TextPart("OK")])

    @asynccontextmanager
    async def engine(connection):
        yield NativeEngine(FunctionModel(respond))

    monkeypatch.setattr("ragents.application.open_engine", engine)
    directory = tmp_path / "verified"
    assert main(["setup", "--non-interactive", "--provider", "ollama", "--model", "test-model",
                 "--directory", str(directory), "--verify"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["connection"]["remote_validated"] is True
    assert len(requests) == 1
    assert load_config(directory / "ragents.yaml").agent.budget.output_tokens_limit == 512


def test_chatgpt_setup_can_use_existing_login_flow(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RAGENTS_HOME", str(tmp_path / "auth"))
    signed_in = []

    async def login(store):
        signed_in.append(store.account)
        return {"signed_in": True}

    async def status(store):
        return {"signed_in": bool(signed_in), "plan_usage_granted": bool(signed_in)}

    monkeypatch.setattr("ragents.chatgpt_login.sign_in", login)
    monkeypatch.setattr("ragents.diagnostics.auth_status", status)
    directory = tmp_path / "chatgpt"
    assert main(["setup", "--non-interactive", "--provider", "chatgpt", "--model", "gpt-6-luna",
                 "--oauth-account", "work", "--login", "--directory", str(directory)]) == 0
    assert signed_in == ["work"]
    report = json.loads(capsys.readouterr().out)["connection"]
    assert report["credentials_ready"] is True
    assert report["remote_validated"] is False


def test_profile_includes_worker_launcher_without_starting_any_process(tmp_path, capsys):
    directory = tmp_path / "profile"
    assert main(["setup", "--non-interactive", "--provider", "ollama", "--model", "my-model",
                 "--directory", str(directory)]) == 0
    payload = json.loads(capsys.readouterr().out)
    launcher = (directory / "start-worker.ps1").read_text(encoding="utf-8")
    assert str(directory / "data" / "ragents.db") in launcher
    assert "worker" in launcher
    assert payload["started"] is False
    assert not (directory / "data").exists()


def test_setup_preserves_existing_profile_on_repeat(tmp_path, capsys):
    directory = tmp_path / "profile"
    command = ["setup", "--non-interactive", "--provider", "ollama", "--model", "first-model",
               "--directory", str(directory)]
    assert main(command) == 0
    original = {path.name: path.read_bytes() for path in directory.iterdir()}
    capsys.readouterr()
    assert main(command) == 2
    assert "üzerine yazılmaz" in capsys.readouterr().err
    assert original == {path.name: path.read_bytes() for path in directory.iterdir()}


def test_chatgpt_without_login_creates_profile_with_clear_local_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RAGENTS_HOME", str(tmp_path / "auth"))
    directory = tmp_path / "profile"
    assert main(["setup", "--non-interactive", "--provider", "chatgpt", "--model", "gpt-6-luna",
                 "--directory", str(directory)]) == 0
    report = json.loads(capsys.readouterr().out)["connection"]
    assert report["error_code"] == "credentials_required"
    assert report["credentials_ready"] is False
    assert report["model_requests"] == 0
    assert report["auth_argv"] == ["auth", "login", "chatgpt", "--account", "default"]
