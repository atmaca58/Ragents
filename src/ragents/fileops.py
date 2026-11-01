"""Sandbox içinde çalışan sınırlı dosya yazma ve yama yardımcısı."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ragents.errors import WorkspaceError
from ragents.workspace import MAX_WRITE_BYTES, Workspace


MAX_REQUEST_BYTES = MAX_WRITE_BYTES * 4


def apply_operation(workspace: Workspace, request: dict) -> dict:
    operation = request.get("op")
    path = request.get("path")
    if not isinstance(path, str):
        raise WorkspaceError("Dosya işlemi için geçerli bir yol gerekir.")
    if operation == "write":
        content = request.get("content")
        if not isinstance(content, str):
            raise WorkspaceError("Yazma işlemi için metin içeriği gerekir.")
        return workspace.write_file(
            path, content, overwrite=bool(request.get("overwrite", False)),
        )
    if operation == "patch":
        old_text = request.get("old_text")
        new_text = request.get("new_text")
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            raise WorkspaceError("Yama işlemi için eski ve yeni metin gerekir.")
        return workspace.apply_patch(
            path, old_text, new_text,
            replace_all=bool(request.get("replace_all", False)),
            expected_sha256=request.get("expected_sha256"),
        )
    raise WorkspaceError("Bilinmeyen dosya işlemi.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sınırlı sandbox dosya işlemi")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--readable-path", action="append", default=[])
    parser.add_argument("--writable-path", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        payload = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(payload) > MAX_REQUEST_BYTES:
            raise WorkspaceError("Dosya işlemi isteği izin verilen boyutu aşıyor.")
        request = json.loads(payload.decode("utf-8"))
        if not isinstance(request, dict):
            raise WorkspaceError("Dosya işlemi isteği nesne olmalıdır.")
        workspace = Workspace(
            args.workspace, readable_paths=tuple(args.readable_path),
            writable_paths=tuple(args.writable_path),
        )
        result = apply_operation(workspace, request)
        response = {"ok": True, "result": result}
        status = 0
    except (WorkspaceError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        response = {"ok": False, "error": str(error)}
        status = 1
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    sys.stdout.flush()
    return status


if __name__ == "__main__":
    raise SystemExit(main())
