import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError
from pydantic_ai.models.test import TestModel
import pytest

from ragents import application
from ragents.cli import main
from ragents.config import load_config
from ragents.contracts import RunResult, Usage
from ragents.engines.native import NativeEngine
from ragents.sandbox import SandboxResult
from ragents.storage import TaskStore
from ragents.task_service import TaskService
from ragents.verification import (
    BrowserCheck, CommandCheck, FileCheck, StructuredOutputCheck, VerificationPlan, Verifier,
)
from ragents.workspace import Workspace, WorkspaceGrant


def make_workspace(tmp_path):
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    grant = WorkspaceGrant(root=root, writable_paths=("src",), commands=("python",))
    workspace = Workspace(root, writable_paths=grant.writable_paths)
    return workspace, grant


def run_result(output: str = "Tamam") -> RunResult:
    return RunResult(agent_id="ajan", output=output, usage=Usage(requests=1, tool_calls=0))


def plan(*checks) -> VerificationPlan:
    return VerificationPlan(checks=checks)


def run_verifier(
    checks, result=None, workspace=None, grant=None, factory=None,
):
    verifier = Verifier(workspace, grant, sandbox_factory=factory) if factory else Verifier(workspace, grant)
    return asyncio.run(verifier.run(
        plan(*checks), result or run_result(), run_id="run", task_id="task",
    ))


class FakeSandbox:
    def __init__(self, outcome, calls, policies):
        self.outcome = outcome
        self.calls = calls
        self.policies = policies

    async def run_async(self, argv, *, input=None):
        self.calls.append(list(argv))
        return self.outcome


class FakeFactory:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []
        self.policies = []

    def __call__(self, policy):
        self.policies.append(policy)
        return FakeSandbox(self.outcome, self.calls, self.policies)


def sandbox_outcome(
    root: Path, *, exit_code: int = 0, stdout: str = "", stderr: str = "",
    timed_out: bool = False, cancelled: bool = False, truncated: bool = False,
) -> SandboxResult:
    return SandboxResult(
        backend="fake", workspace=str(root), exit_code=exit_code,
        stdout=stdout, stderr=stderr, duration_ms=3,
        timed_out=timed_out, cancelled=cancelled, output_truncated=truncated,
    )


def test_file_check_validates_existence_size_hash_and_text(tmp_path):
    workspace, grant = make_workspace(tmp_path)
    content = "sonuç: başarılı\n"
    target = grant.root / "src" / "rapor.txt"
    target.write_text(content, encoding="utf-8", newline="")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    check = FileCheck(
        path="src/rapor.txt", sha256=digest,
        min_bytes=len(content.encode("utf-8")), max_bytes=100, contains="başarılı",
    )
    record = run_verifier([check], workspace=workspace, grant=grant)
    assert record.status == "passed"
    assert record.checks[0].evidence["sha256"] == digest
    assert record.checks[0].evidence["size_bytes"] == len(content.encode("utf-8"))

    missing = run_verifier([FileCheck(path="src/yok.txt")], workspace=workspace, grant=grant)
    assert missing.checks[0].code == "file_missing"

    wrong_hash = run_verifier(
        [FileCheck(path="src/rapor.txt", sha256="0" * 64)],
        workspace=workspace, grant=grant,
    )
    assert wrong_hash.checks[0].code == "file_hash_mismatch"

    too_small = run_verifier(
        [FileCheck(path="src/rapor.txt", min_bytes=10_000)],
        workspace=workspace, grant=grant,
    )
    assert too_small.checks[0].code == "file_too_small"

    missing_text = run_verifier(
        [FileCheck(path="src/rapor.txt", contains="başarısız")],
        workspace=workspace, grant=grant,
    )
    assert missing_text.checks[0].code == "file_content_missing"


def test_file_check_rejects_unsafe_paths_at_plan_validation(tmp_path):
    with pytest.raises(ValidationError, match="dışına"):
        FileCheck(path="../gizli.txt")
    with pytest.raises(ValidationError, match="göreli"):
        FileCheck(path=str(tmp_path / "gizli.txt"))
    with pytest.raises(ValidationError, match="max_bytes"):
        FileCheck(path="src/x.txt", min_bytes=10, max_bytes=5)


def test_structured_output_check_parses_json_and_applies_schema():
    schema = {
        "type": "object",
        "required": ["summary", "count"],
        "properties": {"summary": {"type": "string"}, "count": {"type": "integer"}},
        "additionalProperties": False,
    }
    check = StructuredOutputCheck(schema=schema)
    record = run_verifier([check], result=run_result('{"summary":"ok","count":2}'))
    assert record.status == "passed"

    invalid_json = run_verifier([check], result=run_result("BROWSER PASS"))
    assert invalid_json.checks[0].code == "output_not_json"

    mismatch = run_verifier([check], result=run_result('{"summary":"ok"}'))
    assert mismatch.checks[0].code == "schema_mismatch"
    assert mismatch.checks[0].evidence["path"] == "$"

    nan = run_verifier([check], result=run_result('{"summary":"ok","count":NaN}'))
    assert nan.checks[0].code == "output_not_json"

    with pytest.raises(ValidationError, match="yerel \\$ref"):
        StructuredOutputCheck(schema={"type": "object", "$ref": "https://example.com/schema.json"})
    with pytest.raises(ValidationError, match="şeması geçersiz"):
        StructuredOutputCheck(schema={"type": "nonsense"})


def test_command_check_runs_in_sandbox_and_checks_exit_code_and_text(tmp_path):
    workspace, grant = make_workspace(tmp_path)
    factory = FakeFactory(sandbox_outcome(grant.root, stdout="12 test geçti\n"))
    check = CommandCheck(
        argv=("python", "-m", "pytest", "-q"), cwd="src",
        stdout_contains=("12 test geçti",),
    )
    record = run_verifier([check], workspace=workspace, grant=grant, factory=factory)
    assert record.status == "passed"
    assert factory.calls == [["python", "-m", "pytest", "-q"]]
    assert factory.policies[0].cwd == (grant.root / "src").resolve()
    assert factory.policies[0].writable_paths == ("src",)
    assert record.checks[0].evidence["exit_code"] == 0

    failed_exit = FakeFactory(sandbox_outcome(grant.root, exit_code=1, stderr="hata"))
    failed = run_verifier([check], workspace=workspace, grant=grant, factory=failed_exit)
    assert failed.checks[0].code == "command_exit_code"

    missing_text = FakeFactory(sandbox_outcome(grant.root, stdout="başka çıktı"))
    missing = run_verifier([check], workspace=workspace, grant=grant, factory=missing_text)
    assert missing.checks[0].code == "stdout_missing"

    timeout = FakeFactory(sandbox_outcome(grant.root, timed_out=True))
    timed = run_verifier([check], workspace=workspace, grant=grant, factory=timeout)
    assert timed.checks[0].code == "command_timeout"

    truncated = FakeFactory(sandbox_outcome(grant.root, truncated=True))
    cut = run_verifier([check], workspace=workspace, grant=grant, factory=truncated)
    assert cut.checks[0].status == "error"
    assert cut.checks[0].code == "output_truncated"


def test_command_check_rejects_publish_without_permission(tmp_path):
    workspace, grant = make_workspace(tmp_path)
    factory = FakeFactory(sandbox_outcome(grant.root))
    check = CommandCheck(argv=("git", "push"))
    record = run_verifier([check], workspace=workspace, grant=grant, factory=factory)
    assert record.status == "failed"
    assert record.checks[0].code == "publish_denied"
    assert factory.calls == []

    allowed = WorkspaceGrant(
        root=grant.root, writable_paths=("src",), commands=("git",), allow_publish=True,
    )
    passed = run_verifier([check], workspace=workspace, grant=allowed, factory=factory)
    assert passed.status == "passed"


def test_browser_check_uses_playwright_report_not_model_text(tmp_path):
    workspace, grant = make_workspace(tmp_path)
    check = BrowserCheck(argv=("npx", "playwright", "test", "--reporter=json"))
    claim = run_result("BROWSER PASS")

    empty = FakeFactory(sandbox_outcome(
        grant.root, stdout=json.dumps({"stats": {
            "expected": 0, "unexpected": 0, "flaky": 0, "skipped": 0,
        }}),
    ))
    record = run_verifier([check], result=claim, workspace=workspace, grant=grant, factory=empty)
    assert record.status == "failed"
    assert record.checks[0].code == "browser_no_expected"

    dirty = FakeFactory(sandbox_outcome(
        grant.root, stdout=json.dumps({"stats": {
            "expected": 3, "unexpected": 1, "flaky": 0, "skipped": 0,
        }}),
    ))
    dirty_record = run_verifier(
        [check], result=claim, workspace=workspace, grant=grant, factory=dirty,
    )
    assert dirty_record.checks[0].code == "browser_not_clean"

    clean = FakeFactory(sandbox_outcome(
        grant.root, stdout=json.dumps({"stats": {
            "expected": 3, "unexpected": 0, "flaky": 0, "skipped": 0,
        }}),
    ))
    passed = run_verifier([check], result=claim, workspace=workspace, grant=grant, factory=clean)
    assert passed.status == "passed"
    assert passed.checks[0].evidence["expected"] == 3

    text_only = FakeFactory(sandbox_outcome(grant.root, stdout="BROWSER PASS"))
    text_record = run_verifier(
        [check], result=claim, workspace=workspace, grant=grant, factory=text_only,
    )
    assert text_record.checks[0].code == "browser_output_not_json"


def test_verification_plan_validation_and_command_argv_rules():
    with pytest.raises(ValidationError):
        VerificationPlan(checks=())
    with pytest.raises(ValidationError, match="çalıştırılabilir adı"):
        CommandCheck(argv=("C:\\Python\\python.exe",))
    with pytest.raises(ValidationError):
        CommandCheck(argv=())
    with pytest.raises(ValidationError):
        CommandCheck(argv=("python", "a\x00b"))
    with pytest.raises(ValidationError):
        CommandCheck(argv=("python",), cwd="../src")


def test_model_claim_does_not_make_missing_file_successful(tmp_path):
    workspace, grant = make_workspace(tmp_path)
    store = TaskStore(tmp_path / "tasks.db")
    config = load_config(Path("examples/ollama.yaml"))
    verification = plan(FileCheck(path="src/rapor.txt", contains="sonuç"))
    task = store.enqueue(config, "Raporu yaz", workspace=grant, verification=verification)

    async def runner(config, prompt, connection_id, workspace):
        return run_result("Görev tamamlandı; dosya hazır.")

    run = asyncio.run(TaskService(store, runner=runner).execute(task.id))
    assert run.status == "failed"
    assert store.get(task.id).status == "failed"
    assert store.result(run.id).output == "Görev tamamlandı; dosya hazır."
    record = store.verification(run.id)
    assert record.status == "failed"
    assert record.checks[0].code == "file_missing"
    assert store.run(run.id).error_code == "verification_failed"


def test_successful_verification_is_persisted_and_listed(tmp_path):
    workspace, grant = make_workspace(tmp_path)
    store = TaskStore(tmp_path / "tasks.db")
    config = load_config(Path("examples/ollama.yaml"))
    verification = plan(FileCheck(path="src/rapor.txt", contains="sonuç"))
    task = store.enqueue(config, "Raporu yaz", workspace=grant, verification=verification)

    async def runner(config, prompt, connection_id, workspace):
        (grant.root / "src" / "rapor.txt").write_text("sonuç\n", encoding="utf-8")
        return run_result()

    run = asyncio.run(TaskService(store, runner=runner).execute(task.id))
    assert run.status == "succeeded"
    record = store.verification(run.id)
    assert record.status == "passed"
    assert store.verifications(task.id) == [record]


def test_structured_output_verification_needs_no_workspace(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    config = load_config(Path("examples/ollama.yaml"))
    verification = plan(StructuredOutputCheck(schema={
        "type": "object", "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }))
    task = store.enqueue(config, "JSON üret", verification=verification)

    async def runner(config, prompt, connection_id, workspace):
        return run_result('{"ok": true}')

    run = asyncio.run(TaskService(store, runner=runner).execute(task.id))
    assert run.status == "succeeded"
    assert store.verification(run.id).status == "passed"


def test_verification_error_is_distinct_from_failed_check(tmp_path):
    workspace, grant = make_workspace(tmp_path)
    (grant.root / "src" / "binary.bin").write_bytes(b"\xff\xfe")
    store = TaskStore(tmp_path / "tasks.db")
    config = load_config(Path("examples/ollama.yaml"))
    verification = plan(FileCheck(path="src/binary.bin", contains="metin"))
    task = store.enqueue(config, "İkili dosyayı doğrula", workspace=grant, verification=verification)

    async def runner(config, prompt, connection_id, workspace):
        return run_result()

    run = asyncio.run(TaskService(store, runner=runner).execute(task.id))
    assert run.status == "failed"
    assert store.run(run.id).error_code == "verification_error"
    assert store.verification(run.id).checks[0].status == "error"


def test_cli_freezes_verification_plan_and_reports_evidence(tmp_path, capsys, monkeypatch):
    plan_path = tmp_path / "dogrulama.yaml"
    plan_path.write_text(
        "checks:\n"
        "  - type: structured_output\n"
        "    schema:\n"
        "      type: object\n"
        "      required: [summary]\n"
        "      properties:\n"
        "        summary: {type: string}\n",
        encoding="utf-8",
    )
    db = tmp_path / "ragents.db"
    base = ["tasks", "--db", str(db)]
    assert main([
        *base, "add", "--config", "examples/chatgpt-luna.yaml",
        "--verify-plan", str(plan_path), "JSON üret",
    ]) == 0
    task = json.loads(capsys.readouterr().out)["task"]

    assert main([*base, "show", task["id"]]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["verification_plan"]["checks"][0]["type"] == "structured_output"
    assert shown["verifications"] == []

    @asynccontextmanager
    async def open_test_engine(connection):
        yield NativeEngine(TestModel(custom_output_text='{"summary":"ok"}'))

    monkeypatch.setattr(application, "open_engine", open_test_engine)
    assert main([*base, "run", task["id"]]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verification"]["status"] == "passed"
    assert payload["verification"]["checks"][0]["type"] == "structured_output"
