import json
from contextlib import asynccontextmanager

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from ragents.cli import main
from ragents.engines.native import NativeEngine


def test_doctor_only_calls_model_with_live_flag(tmp_path, monkeypatch, capsys):
    profile = tmp_path / "profile"
    assert main(["setup", "--non-interactive", "--provider", "ollama", "--model", "test-model",
                 "--directory", str(profile)]) == 0
    capsys.readouterr()
    calls = []

    @asynccontextmanager
    async def engine(connection):
        calls.append(connection.model)
        yield NativeEngine(FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart("OK")])))

    monkeypatch.setattr("ragents.application.open_engine", engine)
    command = ["doctor", "--config", str(profile / "ragents.yaml")]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["remote_validated"] is False
    assert calls == []
    assert main([*command, "--live"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["remote_validated"] is True
    assert payload["model_requests"] == 1
    assert calls == ["test-model"]
    assert not (profile / "data").exists()


def test_missing_api_key_fails_doctor_without_sending_request(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("RAGENTS_TEST_KEY", raising=False)
    directory = tmp_path / "profile"
    assert main(["setup", "--non-interactive", "--provider", "opencode_go", "--model", "test-model",
                 "--api-key-env", "RAGENTS_TEST_KEY", "--directory", str(directory)]) == 0
    capsys.readouterr()
    assert main(["doctor", "--config", str(directory / "ragents.yaml"), "--live"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["api_key_env"] == "RAGENTS_TEST_KEY"
    assert report["error_code"] == "credentials_required"
    assert report["model_requests"] == 0


def test_failed_probe_is_safe_and_preserves_unknown_consumption(tmp_path, monkeypatch, capsys):
    from ragents.errors import ProviderAccessError

    @asynccontextmanager
    async def engine(connection):
        raise ProviderAccessError(401)
        yield

    monkeypatch.setattr("ragents.application.open_engine", engine)
    profile = tmp_path / "profile"
    assert main(["setup", "--non-interactive", "--provider", "ollama", "--model", "test-model",
                 "--directory", str(profile), "--verify"]) == 1
    report = json.loads(capsys.readouterr().out)["connection"]
    assert report["error_code"] == "provider_http_401"
    assert report["remote_validated"] is False
    assert report["model_requests"] is None
    assert (profile / "ragents.yaml").is_file()
