"""Ürün regresyonlarının gerçek üretim kodunu kullandığını mutasyonla sınar."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile


TARGETS = (
    ("test_release_regressions.py", "config.py", "ConnectionSpec", "validate_endpoint", "connection_rejects"),
    ("test_release_regressions.py", "workspace.py", "Workspace", "read_file", "read_file_pages"),
    ("test_release_regressions.py", "task_cli.py", None, "execute_saved", "cli_returns_failure"),
    ("test_release_regressions.py", "task_service.py", "TaskService", "invoke", "cancel_during_snapshot"),
    ("test_sandbox_lifecycle.py", "sandbox.py", "Sandbox", "_run", "cancel_during_backend"),
    ("test_sandbox_lifecycle.py", "sandbox_windows.py", "WindowsAppContainerBackend", "run", "reused_windows_backend"),
    ("test_sandbox_lifecycle.py", "sandbox_posix.py", None, "terminate_process_group", "posix_cleanup"),
    ("test_execution_resources.py", "execution_locks.py", None, "resource_keys", "serialize_shared"),
    ("test_profile_paths.py", "profile_paths.py", None, "profile_root", "default_commands"),
    ("test_backups.py", "backups.py", None, "backup_database", "captures_wal"),
    ("test_schedules.py", "schedules.py", "ScheduleService", "tick", "survives_restart"),
    ("test_mcp_catalog.py", "management.py", "ManagementCatalog", "resolve", "discovers_catalog"),
    ("test_programmatic.py", "programmatic.py", None, "run_programmatic", "registered_programmatic"),
    ("test_skill_relevance.py", "instructions.py", None, "compile_instructions", "only_relevant"),
    ("test_memory.py", "memory.py", "MemoryService", "select", "requires_verified"),
    ("test_terminal_setup.py", "terminal_setup.py", None, "initialize", "init_needs_no_yaml"),
    ("test_client_connections.py", "client_connections.py", None, "configure_client", "codex_registration"),
    ("test_client_connections.py", "client_connections.py", None, "dispatch_connect", "chatgpt_preview"),
    ("test_client_connections.py", "windows_service.py", None, "supervisor_commands", "background_preserves"),
    ("test_terminal_setup.py", "cli.py", None, "main", "uses_utf8"),
)


def check_static(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {alias.asname or alias.name for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("ragents")
               for alias in node.names}
    declarations = {node.name for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    if not imports or imports.intersection(declarations):
        raise RuntimeError(f"Üretim import/gölgeleme kontrolü başarısız: {path.name}")


def check_mutation(root: Path, target):
    test, source, owner, symbol, selection = target
    check_static(root / "tests" / test)
    path = root / "src" / "ragents" / source
    original = path.read_bytes()
    text = original.decode("utf-8")
    tree = ast.parse(text)
    scope = tree.body if owner is None else next(
        node.body for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    function = next(node for node in scope
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol)
    lines = text.splitlines(keepends=True)
    stub = " " * function.body[0].col_offset + "return None\n"
    mutated = "".join(lines[:function.body[0].lineno - 1] + [stub] + lines[function.end_lineno:])
    compile(mutated, str(path), "exec")
    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    with tempfile.TemporaryDirectory(prefix="ragents-provenance-") as directory:
        try:
            path.write_text(mutated, encoding="utf-8")
            result = subprocess.run([
                sys.executable, "-m", "pytest", f"tests/{test}", "-k", selection,
                "-q", "-o", "addopts=", "--basetemp", str(Path(directory) / "pytest"),
            ], cwd=root, env=environment, capture_output=True, encoding="utf-8", errors="replace", timeout=45)
        finally:
            path.write_bytes(original)
            if path.read_bytes() != original:
                raise RuntimeError(f"Üretim kaynağı geri yüklenemedi: {path.name}")
    if result.returncode != 1 or "failed" not in result.stdout.lower():
        raise RuntimeError(f"Mutasyon kanıtlanamadı: {source}:{symbol}: {result.stdout[-1500:]}")
    print(f"PASS: {source}:{symbol}; static+mutation; byte restore", flush=True)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    for target in TARGETS:
        check_mutation(root, target)
    print(f"TEST PROVENANCE REPORT: {len(TARGETS)} targets; 0 findings; exit 0")
