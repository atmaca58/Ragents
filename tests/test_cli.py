import json

from ragents.cli import main


def test_demo_runs_without_credentials_and_labels_simulation(capsys):
    assert main(["demo"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["simulation"] is True
    assert payload["result"]["agent_id"] == "ornek-ajan"
    assert payload["result"]["usage"]["requests"] == 1


def test_check_rejects_secret_without_echoing_it(tmp_path, capsys):
    config = tmp_path / "invalid.yaml"
    config.write_text("schema_version: 2\napi_key: super-secret-value\n", encoding="utf-8")
    assert main(["check", "--config", str(config)]) == 2
    captured = capsys.readouterr()
    assert "super-secret-value" not in captured.err + captured.out
    assert "Geçersiz" in captured.err


def test_auth_status_without_saved_session_is_local_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RAGENTS_HOME", str(tmp_path))
    assert main(["auth", "status", "chatgpt"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["signed_in"] is False
    assert payload["remote_validated"] is False
