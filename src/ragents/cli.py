import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from pydantic import ValidationError
import yaml

from ragents import __version__
from ragents.agents_cli import add_agents_parser, dispatch_agents
from ragents.catalog import enqueue_agent_task
from ragents.config import AgentSpec, load_config
from ragents.contracts import RunRequest
from ragents.engines.native import NativeEngine
from ragents.errors import (
    AuthError, ContextLimitError, InstructionError, ProviderAccessError, SandboxError,
    WorkspaceError,
)
from ragents.storage import TaskStateError, TaskStore
from ragents.task_cli import (
    add_task_parser, dispatch_tasks, execute_saved, resolve_database, resolve_root,
)
from ragents.worker_cli import add_worker_parser, dispatch_worker
from ragents.mcp_client import MCPAccessError
from ragents.mcp_cli import add_mcp_parser, dispatch_mcp
from ragents.setup_cli import add_setup_parser, dispatch_setup
from ragents.sandbox_cli import add_sandbox_parser, dispatch_sandbox
from ragents.schedule_cli import add_schedule_parser, dispatch_schedules
from ragents.profile_paths import profile_scope
from ragents.profile_cli import add_profile_parser, dispatch_profile
from ragents.memory_cli import add_memory_parser, dispatch_memory
from ragents.terminal_setup import add_terminal_parsers, dispatch_terminal
from ragents.teams_cli import add_teams_parser, dispatch_teams
from ragents.windows_service import add_service_parsers, dispatch_service
from ragents.installation import add_installation_parser, dispatch_installation
from ragents.client_connections import add_connect_parser, dispatch_connect


def main(argv: list[str] | None = None) -> int:
    # Windows yönlendirilmiş çıktıda ANSI kod sayfası seçebilir; MCP ve JSON UTF-8 ister.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = getattr(args, "directory", None) or getattr(args, "root", None)
        with profile_scope(root):
            payload = asyncio.run(dispatch(args))
    except (
        AuthError, ContextLimitError, InstructionError, TaskStateError,
        MCPAccessError, SandboxError, WorkspaceError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2
    except ProviderAccessError as error:
        print(str(error), file=sys.stderr)
        return 1
    except ValidationError as error:
        locations = [".".join(map(str, item["loc"])) for item in error.errors()]
        print("Geçersiz ayar veya görev alanı: " + ", ".join(locations), file=sys.stderr)
        return 2
    except TimeoutError:
        print("Görev süre sınırına ulaştı.", file=sys.stderr)
        return 1
    except (ValueError, OSError, yaml.YAMLError):
        print("Yapılandırmayı, dosya yolunu ve gerekli anahtar ortam değişkenini kontrol edin.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Çalışma iptal edildi.", file=sys.stderr)
        return 130
    except Exception:
        # Sağlayıcı hataları istek içeriği veya gizli bilgi içerebilir.
        print("Çalışma tamamlanamadı. Sağlayıcı erişimini, model desteğini ve kullanım sınırlarını kontrol edin.", file=sys.stderr)
        return 1
    if payload is not None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    report = payload.get("connection", payload) if payload is not None else {}
    checked = (args.command == "doctor" or (args.command == "setup" and args.verify)
               or (args.command == "connections" and args.connection_action == "test"))
    if checked and (not report["credentials_ready"] or "error_code" in report):
        return 1
    if payload is not None and "run_id" in payload and payload.get("status") in (
        "failed", "cancelled", "interrupted",
    ):
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ragents", description="R Agents native ajan çekirdeği")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    add_task_parser(commands)
    add_agents_parser(commands)
    add_worker_parser(commands)
    add_mcp_parser(commands)
    add_setup_parser(commands)
    add_sandbox_parser(commands)
    add_schedule_parser(commands)
    add_profile_parser(commands)
    add_memory_parser(commands)
    add_terminal_parsers(commands)
    add_teams_parser(commands)
    add_service_parsers(commands)
    add_installation_parser(commands)
    add_connect_parser(commands)
    auth = commands.add_parser("auth", help="ChatGPT hesabı için giriş, durum ve yerel çıkış")
    auth.add_argument("--root", type=Path)
    auth_actions = auth.add_subparsers(dest="auth_action", required=True)
    for action in ("login", "status", "logout"):
        action_parser = auth_actions.add_parser(action)
        action_parser.add_argument("provider", choices=["chatgpt"])
        action_parser.add_argument("--account", default="default", help="Yerel hesap etiketi")
    commands.add_parser("demo", help="Model/ağ gerektirmeyen açıkça işaretlenmiş simülasyon")
    check = commands.add_parser("check", help="Ayar şemasını yerelde doğrula; bağlantı testi yapmaz")
    check.add_argument("--config", type=Path, required=True, help="YAML ayar dosyası")
    run = commands.add_parser("run", help="Seçilen sağlayıcıya gerçek model isteği gönder")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path, help="YAML ayar dosyası")
    source.add_argument("--agent", help="Kalıcı ajan kataloğundaki kimlik")
    run.add_argument("--root", type=Path, default=None,
                     help="Ajan profillerinin kök dizini; veritabanı varsayılanını belirler")
    run.add_argument("--connection", help="Ajanı değiştirmeden başka tanımlı bağlantıyı kullan")
    run.add_argument("--skill", action="append", default=[],
                     help="Görev için seçilecek izinli skill; birden çok kez kullanılabilir")
    run.add_argument("--db", type=Path, default=None,
                     help="SQLite dosyası; verilmezse --root altında data/ragents.db")
    run.add_argument("--key", help="Aynı tamamlanmış görevi tekrar çağrı yapmadan al")
    run.add_argument("prompt", help="Görev metni")
    return parser


async def dispatch(args: argparse.Namespace) -> dict:
    if args.command == "connect":
        return await dispatch_connect(args)
    if args.command == "installation":
        return await asyncio.to_thread(dispatch_installation, args)
    if args.command in ("service", "supervise"):
        return await dispatch_service(args)
    if args.command == "teams":
        return dispatch_teams(args)
    if args.command in ("init", "connections", "search", "approvals"):
        return await dispatch_terminal(args)
    if args.command == "memory":
        return dispatch_memory(args)
    if args.command == "profile":
        return dispatch_profile(args)
    if args.command == "schedules":
        return dispatch_schedules(args)
    if args.command == "doctor":
        from ragents.diagnostics import inspect_connection
        return await inspect_connection(load_config(args.config), args.connection, live=args.live)
    if args.command == "setup":
        return await dispatch_setup(args)
    if args.command == "sandbox":
        return dispatch_sandbox(args)
    if args.command == "mcp":
        return await dispatch_mcp(args)
    if args.command == "worker":
        return await dispatch_worker(args)
    if args.command == "tasks":
        return await dispatch_tasks(args)
    if args.command == "agents":
        return dispatch_agents(args)
    if args.command == "auth":
        from ragents.auth import ChatGPTStore
        from ragents.chatgpt_login import auth_status, sign_in, sign_out

        store = ChatGPTStore(args.account, root=resolve_root(args))
        if args.auth_action == "login":
            print("Tarayıcıda R Agents için giriş ve plan kullanma iznini tamamlayın.", file=sys.stderr)
            return await sign_in(store)
        if args.auth_action == "logout":
            return sign_out(store)
        return await auth_status(store)
    if args.command == "demo":
        agent = AgentSpec(
            id="ornek-ajan", name="Örnek Ajan", instructions="Türkçe yanıt ver.", connection="demo",
        )
        result = await NativeEngine.demo().run(RunRequest(agent=agent, prompt="Kendini tanıt"))
        return {"simulation": True, "result": result.model_dump()}
    if args.command == "check":
        config = load_config(args.config)
        return {"valid": True, "agent_id": config.agent.id, "connections": list(config.connections)}
    if args.command == "run" and args.agent is None and args.skill:
        raise TaskStateError("--skill yalnız --agent ile kullanılabilir.")
    store = TaskStore(resolve_database(args))
    if args.command == "run" and args.agent is not None:
        root = resolve_root(args)
        if root is None:
            raise TaskStateError("Ajan profil kökü belirlenemedi.")
        task = enqueue_agent_task(
            store, root, args.agent, args.prompt, args.connection,
            skills=tuple(args.skill), idempotency_key=args.key,
        )
    else:
        config = load_config(args.config)
        task = store.enqueue(config, args.prompt, args.connection, idempotency_key=args.key)
    return await execute_saved(store, task.id)
