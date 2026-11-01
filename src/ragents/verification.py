"""Model beyanından bağımsız görev doğrulama kontrolleri."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Annotated, Any, Literal

from jsonschema import SchemaError
from jsonschema.validators import validator_for
from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

from ragents.config import Spec
from ragents.managed_browser import BrowserWorkflow, ManagedBrowser
from ragents.contracts import RunResult
from ragents.errors import SandboxError, WorkspaceError
from ragents.sandbox import Sandbox, SandboxPolicy
from ragents.tools import is_publish_command, validate_command_argv
from ragents.workspace import (
    MAX_HASH_BYTES, MAX_PATCH_FILE_BYTES, Workspace, WorkspaceGrant,
    normalize_relative_path,
)


MAX_PLAN_CHECKS = 32
MAX_SCHEMA_BYTES = 16_384
MAX_CHECK_MESSAGE_CHARS = 500
MAX_EVIDENCE_ITEMS = 16
MAX_EVIDENCE_VALUE_CHARS = 512
MAX_CONTAINS_CHARS = 4096
PLAYWRIGHT_STATS = ("expected", "unexpected", "flaky", "skipped")


class FileCheck(Spec):
    """Workspace içindeki bir dosyanın varlığını, boyutunu ve içeriğini doğrula."""

    type: Literal["file"] = "file"
    path: str = Field(min_length=1, max_length=512)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    min_bytes: int = Field(default=0, ge=0)
    max_bytes: int | None = Field(default=None, ge=0)
    contains: str | None = Field(default=None, min_length=1, max_length=MAX_CONTAINS_CHARS)

    @field_validator("path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        try:
            return normalize_relative_path(value)
        except WorkspaceError as error:
            raise ValueError(str(error)) from None

    @model_validator(mode="after")
    def validate_bounds(self) -> "FileCheck":
        if self.max_bytes is not None and self.max_bytes < self.min_bytes:
            raise ValueError("max_bytes min_bytes değerinden küçük olamaz.")
        return self


def _reject_remote_refs(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("$ref", "$dynamicRef") and (
                not isinstance(item, str) or not item.startswith("#")
            ):
                raise ValueError("JSON şeması yalnız yerel $ref kullanabilir.")
            _reject_remote_refs(item)
    elif isinstance(value, list):
        for item in value:
            _reject_remote_refs(item)


class StructuredOutputCheck(Spec):
    """Model çıktısını JSON olarak ayrıştırıp yerel JSON şemasıyla doğrula."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    type: Literal["structured_output"] = "structured_output"
    json_schema: dict[str, Any] = Field(
        validation_alias=AliasChoices("json_schema", "schema"),
    )

    @field_validator("json_schema")
    @classmethod
    def validate_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            raise ValueError("JSON şeması serileştirilebilir olmalıdır.") from None
        if len(serialized.encode("utf-8")) > MAX_SCHEMA_BYTES:
            raise ValueError("JSON şeması çok büyük.")
        _reject_remote_refs(value)
        try:
            validator_for(value).check_schema(value)
        except SchemaError as error:
            raise ValueError("JSON şeması geçersiz: " + error.message) from None
        return value


class CommandSpec(Spec):
    """Doğrulama komutunun ortak argv, dizin ve süre sınırları."""

    argv: tuple[str, ...] = Field(min_length=1, max_length=64)
    cwd: str = Field(default=".", min_length=1, max_length=512)
    timeout_seconds: float | None = Field(default=None, gt=0, le=3600)

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        try:
            command = validate_command_argv(list(value))
        except WorkspaceError as error:
            raise ValueError(str(error)) from None
        executable = command[0]
        if "/" in executable or "\\" in executable:
            raise ValueError("Doğrulama komutu yalnız çalıştırılabilir adıyla verilmelidir.")
        return tuple(command)

    @field_validator("cwd")
    @classmethod
    def normalize_cwd(cls, value: str) -> str:
        try:
            return normalize_relative_path(value)
        except WorkspaceError as error:
            raise ValueError(str(error)) from None


class CommandCheck(CommandSpec):
    """Sandbox içinde bir test/komut çalıştırıp çıkış kodunu ve metnini doğrula."""

    type: Literal["command"] = "command"
    expected_exit_code: int = Field(default=0, ge=0, le=255)
    stdout_contains: tuple[str, ...] = Field(default=(), max_length=16)
    stderr_contains: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("stdout_contains", "stderr_contains")
    @classmethod
    def validate_needles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not isinstance(item, str) or not item or len(item) > 512:
                raise ValueError("Doğrulama metni 1–512 karakter olmalıdır.")
        return tuple(dict.fromkeys(value))


class BrowserCheck(CommandSpec):
    """Playwright JSON raporunu oku; model metnindeki BROWSER PASS ifadesine güvenme."""

    type: Literal["browser"] = "browser"
    min_expected: int = Field(default=1, ge=1, le=100_000)


class ManagedBrowserCheck(Spec):
    type: Literal["managed_browser"] = "managed_browser"
    workflow: BrowserWorkflow

    @model_validator(mode="after")
    def requires_assertions(self):
        if not any(action.action in ("expect_text", "expect_visible") for action in self.workflow.actions):
            raise ValueError("Yönetilen tarayıcı doğrulaması en az bir gerçek kontrol gerektirir.")
        return self


VerificationCheck = Annotated[
    FileCheck | StructuredOutputCheck | CommandCheck | BrowserCheck | ManagedBrowserCheck,
    Field(discriminator="type"),
]


class VerificationPlan(Spec):
    """Görevle birlikte dondurulan bağımsız doğrulama kontrolleri."""

    checks: tuple[VerificationCheck, ...] = Field(min_length=1, max_length=MAX_PLAN_CHECKS)

    @property
    def requires_workspace(self) -> bool:
        return any(not isinstance(check, StructuredOutputCheck) for check in self.checks)


EvidenceValue = str | int | float | bool | None


class VerificationCheckResult(Spec):
    type: Literal["file", "structured_output", "command", "browser", "managed_browser"]
    status: Literal["passed", "failed", "error"]
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=MAX_CHECK_MESSAGE_CHARS)
    evidence: dict[str, EvidenceValue] = Field(default_factory=dict, max_length=MAX_EVIDENCE_ITEMS)


class VerificationRecord(Spec):
    run_id: str
    task_id: str
    status: Literal["passed", "failed", "error"]
    checks: tuple[VerificationCheckResult, ...]
    duration_ms: int = Field(default=0, ge=0)
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: str, limit: int = MAX_CHECK_MESSAGE_CHARS) -> str:
    text = " ".join(str(value).split())
    return text[:limit] if text else "Doğrulama tamamlanamadı."


def _evidence(values: dict[str, EvidenceValue]) -> dict[str, EvidenceValue]:
    clipped: dict[str, EvidenceValue] = {}
    for key, value in list(values.items())[:MAX_EVIDENCE_ITEMS]:
        if isinstance(value, str) and len(value) > MAX_EVIDENCE_VALUE_CHARS:
            value = value[:MAX_EVIDENCE_VALUE_CHARS]
        clipped[key] = value
    return clipped


def _check_result(
    kind: str, status: str, code: str, message: str,
    evidence: dict[str, EvidenceValue] | None = None,
) -> VerificationCheckResult:
    return VerificationCheckResult(
        type=kind, status=status, code=code, message=_clip(message),
        evidence=_evidence(evidence or {}),
    )


def _passed(kind: str, code: str, message: str, evidence: dict[str, EvidenceValue] | None = None):
    return _check_result(kind, "passed", code, message, evidence)


def _failed(kind: str, code: str, message: str, evidence: dict[str, EvidenceValue] | None = None):
    return _check_result(kind, "failed", code, message, evidence)


def _error(kind: str, code: str, message: str, evidence: dict[str, EvidenceValue] | None = None):
    return _check_result(kind, "error", code, message, evidence)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"JSON sabiti kullanılamaz: {value}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Verifier:
    """Doğrulama planını çalıştırır; komutları platform sandbox'ında yürütür."""

    def __init__(
        self, workspace: Workspace | None, grant: WorkspaceGrant | None, *,
        sandbox_factory: Callable[[SandboxPolicy], Sandbox] = Sandbox,
    ) -> None:
        self.workspace = workspace
        self.grant = grant
        self.sandbox_factory = sandbox_factory

    async def run(
        self, plan: VerificationPlan, result: RunResult, *, run_id: str, task_id: str,
    ) -> VerificationRecord:
        started = time.perf_counter()
        checks: list[VerificationCheckResult] = []
        for check in plan.checks:
            checks.append(await self._run_check(check, result))
        if any(check.status == "failed" for check in checks):
            status = "failed"
        elif any(check.status == "error" for check in checks):
            status = "error"
        else:
            status = "passed"
        return VerificationRecord(
            run_id=run_id, task_id=task_id, status=status, checks=tuple(checks),
            duration_ms=int((time.perf_counter() - started) * 1000), created_at=_now(),
        )

    async def _run_check(
        self, check: VerificationCheck, result: RunResult,
    ) -> VerificationCheckResult:
        try:
            if isinstance(check, FileCheck):
                return await self._file_check(check)
            if isinstance(check, StructuredOutputCheck):
                return self._structured_output_check(check, result)
            if isinstance(check, BrowserCheck):
                return await self._command_check(check, browser=True)
            if isinstance(check, ManagedBrowserCheck):
                if self.grant is None:
                    return _error(check.type, "workspace_missing", "Tarayıcı doğrulaması workspace izni gerektirir.")
                evidence = await ManagedBrowser(self.grant).run(check.workflow)
                stats = evidence["stats"]
                if stats["expected"] > 0 and all(stats[key] == 0 for key in ("unexpected", "skipped", "flaky")):
                    return _passed(check.type, "browser_ok", "Bağımsız Playwright kontrolleri geçti.", stats)
                return _failed(check.type, "browser_failed", "Bağımsız Playwright kontrolleri geçmedi.", stats)
            return await self._command_check(check, browser=False)
        except (WorkspaceError, SandboxError, OSError) as error:
            return _error(check.type, "check_unavailable", str(error))
        except Exception:
            return _error(check.type, "check_failed", "Doğrulama kontrolü beklenmeyen bir hata verdi.")

    async def _file_check(self, check: FileCheck) -> VerificationCheckResult:
        if self.workspace is None:
            return _error("file", "workspace_missing", "Dosya doğrulaması için workspace tanımlı değil.")

        def inspect() -> tuple[str, int | None, str | None]:
            target = self.workspace.checked_path(check.path, must_exist=False, access=None)
            if not target.exists():
                return "missing", None, None
            if not target.is_file():
                return "not_file", None, None
            size = target.stat().st_size
            if size < check.min_bytes:
                return "too_small", size, None
            if check.max_bytes is not None and size > check.max_bytes:
                return "too_large", size, None
            digest = None
            if check.sha256 is not None:
                if size > MAX_HASH_BYTES:
                    return "too_large_hash", size, None
                digest = _sha256_file(target)
                if digest != check.sha256:
                    return "hash_mismatch", size, digest
            if check.contains is not None:
                if size > MAX_PATCH_FILE_BYTES:
                    return "too_large_inspect", size, digest
                try:
                    text = target.read_bytes().decode("utf-8")
                except UnicodeDecodeError:
                    return "not_utf8", size, digest
                if check.contains not in text:
                    return "content_missing", size, digest
            return "passed", size, digest

        code, size, digest = await asyncio.to_thread(inspect)
        evidence: dict[str, EvidenceValue] = {"path": check.path}
        if size is not None:
            evidence["size_bytes"] = size
        if digest is not None:
            evidence["sha256"] = digest
        if code == "passed":
            return _passed("file", "file_ok", f"Dosya doğrulandı: {check.path}.", evidence)
        if code == "missing":
            return _failed("file", "file_missing", f"Dosya bulunamadı: {check.path}.", evidence)
        if code == "not_file":
            return _failed("file", "file_not_file", f"Yol bir dosya değil: {check.path}.", evidence)
        if code == "too_small":
            return _failed(
                "file", "file_too_small",
                f"Dosya en az {check.min_bytes} bayt olmalı; {size} bayt bulundu.", evidence,
            )
        if code == "too_large":
            return _failed(
                "file", "file_too_large",
                f"Dosya en fazla {check.max_bytes} bayt olmalı; {size} bayt bulundu.", evidence,
            )
        if code == "hash_mismatch":
            return _failed(
                "file", "file_hash_mismatch",
                f"Dosyanın SHA-256 değeri beklenenle eşleşmiyor: {check.path}.", evidence,
            )
        if code == "content_missing":
            return _failed(
                "file", "file_content_missing",
                f"Dosyada beklenen metin bulunamadı: {check.path}.", evidence,
            )
        if code == "not_utf8":
            return _error("file", "file_not_utf8", "Doğrulama dosyası UTF-8 metin değil.", evidence)
        if code == "too_large_hash":
            return _error(
                "file", "file_too_large_to_hash",
                f"Dosya SHA-256 için çok büyük (sınır {MAX_HASH_BYTES} bayt).", evidence,
            )
        return _error(
            "file", "file_too_large_to_inspect",
            f"Dosya içerik doğrulaması için çok büyük (sınır {MAX_PATCH_FILE_BYTES} bayt).",
            evidence,
        )

    def _structured_output_check(
        self, check: StructuredOutputCheck, result: RunResult,
    ) -> VerificationCheckResult:
        try:
            payload = json.loads(result.output, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError, RecursionError):
            return _failed(
                "structured_output", "output_not_json",
                "Model çıktısı geçerli JSON değil.", {"output_chars": len(result.output)},
            )
        validator = validator_for(check.json_schema)(check.json_schema)
        errors = sorted(
            validator.iter_errors(payload),
            key=lambda error: (tuple(str(item) for item in error.absolute_path), error.message),
        )
        if errors:
            first = errors[0]
            path = "/".join(str(item) for item in first.absolute_path) or "$"
            return _failed(
                "structured_output", "schema_mismatch",
                f"Çıktı JSON şemasıyla eşleşmiyor: {path}.",
                {"error_count": len(errors), "path": path, "output_chars": len(result.output)},
            )
        return _passed(
            "structured_output", "schema_valid",
            "Model çıktısı JSON şemasıyla eşleşiyor.", {"output_chars": len(result.output)},
        )

    async def _command_check(
        self, check: CommandCheck | BrowserCheck, *, browser: bool,
    ) -> VerificationCheckResult:
        if self.workspace is None or self.grant is None:
            return _error(check.type, "workspace_missing", "Komut doğrulaması için workspace tanımlı değil.")
        if is_publish_command(list(check.argv)) and not self.grant.allow_publish:
            return _failed(
                check.type, "publish_denied",
                "Doğrulama komutu dış sisteme yayınlama/push etkisi taşıyor; görevde yayın izni yok.",
            )
        directory = self.workspace.checked_directory(check.cwd, access=None)
        timeout = min(
            self.grant.command_timeout_seconds,
            check.timeout_seconds if check.timeout_seconds is not None
            else self.grant.command_timeout_seconds,
        )
        policy = SandboxPolicy(
            workspace=self.workspace.root, writable_paths=self.grant.writable_paths,
            cwd=directory, network=self.grant.allow_network, timeout_seconds=timeout,
            max_output_bytes=self.grant.max_output_bytes,
        )
        outcome = await self.sandbox_factory(policy).run_async(list(check.argv))
        evidence: dict[str, EvidenceValue] = {
            "backend": outcome.backend, "exit_code": outcome.exit_code,
            "duration_ms": outcome.duration_ms,
            "stdout_chars": len(outcome.stdout), "stderr_chars": len(outcome.stderr),
            "stdout_sha256": _text_digest(outcome.stdout),
            "stderr_sha256": _text_digest(outcome.stderr),
        }
        if outcome.cancelled:
            return _error(check.type, "command_cancelled", "Doğrulama komutu iptal edildi.", evidence)
        if outcome.timed_out:
            return _failed(check.type, "command_timeout", "Doğrulama komutu zaman aşımına uğradı.", evidence)
        if outcome.output_truncated:
            return _error(
                check.type, "output_truncated",
                "Doğrulama komutu çıktısı sınıra ulaştı; sonuç güvenilir değil.", evidence,
            )
        expected = 0 if browser else check.expected_exit_code
        if outcome.exit_code != expected:
            return _failed(
                check.type, "command_exit_code",
                f"Doğrulama komutu beklenen çıkış kodundan farklı bitti "
                f"(çıkış {outcome.exit_code}, beklenen {expected}).", evidence,
            )
        if browser:
            return self._browser_report(outcome.stdout, evidence, check.min_expected)
        missing_stdout = [item for item in check.stdout_contains if item not in outcome.stdout]
        if missing_stdout:
            return _failed(
                check.type, "stdout_missing",
                f"Doğrulama komutu çıktısında beklenen metin yok: {missing_stdout[0]}.", evidence,
            )
        missing_stderr = [item for item in check.stderr_contains if item not in outcome.stderr]
        if missing_stderr:
            return _failed(
                check.type, "stderr_missing",
                f"Doğrulama komutu hata çıktısında beklenen metin yok: {missing_stderr[0]}.", evidence,
            )
        return _passed(
            check.type, "command_ok", "Doğrulama komutu beklenen sonucu verdi.", evidence,
        )

    def _browser_report(
        self, stdout: str, evidence: dict[str, EvidenceValue], min_expected: int,
    ) -> VerificationCheckResult:
        try:
            payload = json.loads(stdout, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError, RecursionError):
            return _failed(
                "browser", "browser_output_not_json",
                "Tarayıcı doğrulama komutu geçerli Playwright JSON raporu üretmedi.", evidence,
            )
        stats = payload.get("stats") if isinstance(payload, dict) else None
        if not isinstance(stats, dict):
            return _failed(
                "browser", "browser_stats_missing",
                "Playwright raporunda stats alanı yok.", evidence,
            )
        values: dict[str, int] = {}
        for key in PLAYWRIGHT_STATS:
            value = stats.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return _failed(
                    "browser", "browser_stats_invalid",
                    f"Playwright raporunda geçersiz istatistik: {key}.", evidence,
                )
            values[key] = value
            evidence[key] = value
        if values["expected"] < min_expected:
            return _failed(
                "browser", "browser_no_expected",
                f"Playwright en az {min_expected} beklenen test raporlamalı; "
                f"{values['expected']} bulundu.", evidence,
            )
        if values["unexpected"] or values["flaky"] or values["skipped"]:
            return _failed(
                "browser", "browser_not_clean",
                "Playwright raporunda başarısız, flaky veya atlanan test var.", evidence,
            )
        return _passed(
            "browser", "browser_passed",
            f"Playwright: {values['expected']} beklenen test geçti; "
            "başarısız, flaky veya atlanan yok.", evidence,
        )
