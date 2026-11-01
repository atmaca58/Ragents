import json

from ragents.cli import main
from ragents.setup_plans import SetupPlanService, SetupPlan
from ragents.storage import TaskStore
from test_setup_plans import plan_data


def test_terminal_init_needs_no_yaml_or_frontend(tmp_path, capsys):
    assert main(["init", "--root", str(tmp_path), "--provider", "ollama", "--model", "test",
                 "--search", "disabled", "--no-login", "--non-interactive"]) == 0
    catalog = json.loads((tmp_path / "connections/catalog.json").read_text(encoding="utf-8"))
    assert catalog["primary"]["model"] == "test"
    assert not (tmp_path / "ragents.yaml").exists()
    assert "ragents connect" in capsys.readouterr().out


def test_catalog_connection_check_needs_no_yaml_or_model_call(tmp_path, capsys):
    assert main(["init", "--root", str(tmp_path), "--provider", "ollama", "--model", "test",
                 "--non-interactive"]) == 0
    capsys.readouterr()
    assert main(["connections", "--root", str(tmp_path), "test", "primary"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["credentials_ready"]
    assert report["model_requests"] == 0
    assert not report["remote_validated"]


def test_terminal_json_uses_utf8_when_windows_redirects_output(tmp_path, monkeypatch):
    import io
    import sys
    output = io.BytesIO()
    stream = io.TextIOWrapper(output, encoding="cp1254")
    monkeypatch.setattr(sys, "stdout", stream)
    assert main(["init", "--root", str(tmp_path), "--provider", "ollama", "--model", "test",
                 "--non-interactive"]) == 0
    stream.flush()
    report = json.loads(output.getvalue().decode("utf-8"))
    assert "→" in report["approval"]


def test_catalog_connection_check_missing_credentials_is_nonzero(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("RAGENTS_MISSING_TEST_KEY", raising=False)
    assert main(["init", "--root", str(tmp_path), "--provider", "openrouter", "--model", "test",
                 "--api-key-env", "RAGENTS_MISSING_TEST_KEY", "--non-interactive"]) == 0
    capsys.readouterr()
    assert main(["connections", "--root", str(tmp_path), "test", "primary"]) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "credentials_required"


def test_cli_approval_refuses_piped_input(tmp_path, capsys):
    service = SetupPlanService(tmp_path, TaskStore(tmp_path / "data/ragents.db"))
    request = service.propose(SetupPlan.model_validate(plan_data()))
    assert main(["approvals", "--root", str(tmp_path), "approve", request.id]) == 2
    assert service.get(request.id).status == "pending"
    assert "terminal" in capsys.readouterr().err.lower()


def test_terminal_approval_applies_only_the_seen_hash(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    service = SetupPlanService(tmp_path, TaskStore(tmp_path / "data/ragents.db"))
    request = service.propose(SetupPlan.model_validate(plan_data()))
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda: request.operation_hash[:12])
    assert main(["approvals", "--root", str(tmp_path), "approve", request.id]) == 0
    assert service.get(request.id).status == "applied"

def test_numbered_choice_retries_invalid_input(monkeypatch):
    from ragents.terminal_setup import choose
    monkeypatch.setattr("ragents.terminal_setup.require_terminal", lambda: None)
    answers = iter(["wrong", "9", "2"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    assert choose("Provider", [("a", "A"), ("b", "B")]) == "b"


def test_model_selection_uses_provider_catalog_without_generation(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from ragents.config import ConnectionSpec
    from ragents.terminal_setup import select_model
    calls = []
    class Client:
        def __init__(self, **kwargs):
            self.models = self
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def list(self):
            calls.append('models.list')
            return SimpleNamespace(data=[SimpleNamespace(id='local-model-b'), SimpleNamespace(id='local-model-a')])
    monkeypatch.setattr('openai.AsyncOpenAI', Client)
    monkeypatch.setattr('ragents.terminal_setup.require_terminal', lambda: None)
    monkeypatch.setattr('builtins.input', lambda: '2')
    connection = ConnectionSpec(provider='ollama', model='discovery')
    assert asyncio.run(select_model(connection, tmp_path)) == 'local-model-b'
    assert calls == ['models.list']
