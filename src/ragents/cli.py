import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from pydantic import ValidationError
import yaml

from ragents import __version__
from ragents.config import AgentSpec, load_config
from ragents.contracts import RunRequest
from ragents.engines.native import NativeEngine
from ragents.errors import AuthError, ContextLimitError, ProviderAccessError
from ragents.storage import TaskStateError, TaskStore
from ragents.task_cli import add_task_parser, dispatch_tasks, execute_saved
from ragents.worker_cli import add_worker_parser, dispatch_worker
from ragents.mcp_client import MCPAccessError
from ragents.mcp_cli import add_mcp_parser, dispatch_mcp
from ragents.setup_cli import add_setup_parser, dispatch_setup


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = asyncio.run(dispatch(args))
    except (AuthError, ContextLimitError, TaskStateError, MCPAccessError) as error:
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
    checked = args.command == "doctor" or (args.command == "setup" and args.verify)
    if checked and (not report["credentials_ready"] or "error_code" in report):
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ragents", description="R Agents native ajan çekirdeği")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    add_task_parser(commands)
    add_worker_parser(commands)
    add_mcp_parser(commands)
    add_setup_parser(commands)
    auth = commands.add_parser("auth", help="ChatGPT hesabı için giriş, durum ve yerel çıkış")
    auth_actions = auth.add_subparsers(dest="auth_action", required=True)
    for action in ("login", "status", "logout"):
        action_parser = auth_actions.add_parser(action)
        action_parser.add_argument("provider", choices=["chatgpt"])
        action_parser.add_argument("--account", default="default", help="Yerel hesap etiketi")
    commands.add_parser("demo", help="Model/ağ gerektirmeyen açıkça işaretlenmiş simülasyon")
    check = commands.add_parser("check", help="Ayar şemasını yerelde doğrula; bağlantı testi yapmaz")
    check.add_argument("--config", type=Path, required=True, help="YAML ayar dosyası")
    run = commands.add_parser("run", help="Seçilen sağlayıcıya gerçek model isteği gönder")
    run.add_argument("--config", type=Path, required=True, help="YAML ayar dosyası")
    run.add_argument("--connection", help="Ajanı değiştirmeden başka tanımlı bağlantıyı kullan")
    run.add_argument("--db", type=Path, default=Path("data/ragents.db"), help="V2 SQLite dosyası")
    run.add_argument("--key", help="Aynı tamamlanmış görevi tekrar çağrı yapmadan al")
    run.add_argument("prompt", help="Görev metni")
    return parser


async def dispatch(args: argparse.Namespace) -> dict:
    if args.command == "doctor":
        from ragents.diagnostics import inspect_connection
        return await inspect_connection(load_config(args.config), args.connection, live=args.live)
    if args.command == "setup":
        return await dispatch_setup(args)
    if args.command == "mcp":
        return await dispatch_mcp(args)
    if args.command == "worker":
        return await dispatch_worker(args)
    if args.command == "tasks":
        return await dispatch_tasks(args)
    if args.command == "auth":
        from ragents.auth import ChatGPTStore
        from ragents.chatgpt_login import auth_status, sign_in, sign_out

        store = ChatGPTStore(args.account)
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
    config = load_config(args.config)
    if args.command == "check":
        return {"valid": True, "agent_id": config.agent.id, "connections": list(config.connections)}
    store = TaskStore(args.db)
    task = store.enqueue(config, args.prompt, args.connection, idempotency_key=args.key)
    return await execute_saved(store, task.id)
