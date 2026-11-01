"""Sandbox durum ve komut çalıştırma CLI'si."""

from __future__ import annotations

import argparse
from pathlib import Path

from ragents.errors import SandboxError
from ragents.sandbox import Sandbox, SandboxPolicy, backend_status


def add_sandbox_parser(commands) -> None:
    parser = commands.add_parser("sandbox", help="Platform sandbox backend'i ve izolasyonlu komutlar")
    actions = parser.add_subparsers(dest="sandbox_action", required=True)
    status = actions.add_parser("status", help="Seçili platform backend'ini ve yeteneklerini göster")
    status.add_argument("--platform", help="Tanılama için platform adı (varsayılan: çalışan platform)")
    run = actions.add_parser("run", help="Komutu dosya, ağ, süreç ve kaynak sınırları içinde çalıştır")
    run.add_argument("--workspace", type=Path, required=True, help="Sandbox'ın izinli çalışma dizini")
    run.add_argument("--timeout", type=float, default=30, help="Duvar saati süre sınırı (saniye)")
    run.add_argument("--allow-network", action="store_true", help="Ağ erişimine açıkça izin ver")
    run.add_argument("--writable", action="store_true", help="Workspace köküne yazmaya açıkça izin ver")
    run.add_argument("--writable-path", action="append", default=[],
                     help="Yalnız bu göreli dizine yazma izni ver; birden çok kez kullanılabilir")
    run.add_argument("--cwd", type=Path, help="Sandbox içinde çalışma dizini")
    run.add_argument("--max-memory-mb", type=int, default=1024, help="Süreç başına bellek sınırı")
    run.add_argument("--max-processes", type=int, default=8, help="Job Object süreç sayısı sınırı")
    run.add_argument("--max-output-bytes", type=int, default=65_536, help="stdout/stderr başına sınır")
    run.add_argument("argv", nargs=argparse.REMAINDER, help="-- ayırıcısından sonra çalıştırılacak komut")


def dispatch_sandbox(args: argparse.Namespace) -> dict:
    if args.sandbox_action == "status":
        platform = getattr(args, "platform", None)
        return {"sandbox": backend_status(platform).model_dump()}
    argv = list(args.argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise SandboxError("Sandbox için bir komut belirtin.")
    cwd = args.cwd
    if cwd is not None and not cwd.is_absolute():
        cwd = args.workspace / cwd
    policy = SandboxPolicy(
        workspace=args.workspace, writable=args.writable,
        writable_paths=tuple(args.writable_path), cwd=cwd,
        network=args.allow_network, timeout_seconds=args.timeout,
        max_memory_mb=args.max_memory_mb, max_processes=args.max_processes,
        max_output_bytes=args.max_output_bytes,
    )
    result = Sandbox(policy).run(argv)
    return {"sandbox": result.model_dump()}
