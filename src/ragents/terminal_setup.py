"""Ürünün ana kurulum ve yerel insan onayı arayüzü: terminal."""
import argparse
import getpass
import json
from pathlib import Path
import sys
from typing import get_args

from ragents.auth import ChatGPTStore
from ragents.chatgpt_login import sign_in
from ragents.config import AgentSpec, ConnectionSpec, ProjectConfig
from ragents.connection_catalog import ConnectionCatalog
from ragents.connections import ProviderName, DEFAULT_KEY_ENVS
from ragents.profile_paths import profile_root, database_path
from ragents.search import SearchConnection, save_search_connection, search_connection
from ragents.secrets import SecretStore
from ragents.setup_plans import SetupPlanService
from ragents.storage import TaskStore, TaskStateError


def require_terminal():
    if not sys.stdin.isatty():
        raise TaskStateError("Bu işlem gerçek etkileşimli yerel terminal gerektirir; pipe veya MCP onayı kabul edilmez.")


def ask(label, default=""):
    require_terminal()
    print(label + (f" [{default}]" if default else "") + ": ", end="", file=sys.stderr, flush=True)
    try:
        return input().strip() or default
    except EOFError:
        raise TaskStateError("Terminal girdisi sona erdi; işlem uygulanmadı.") from None


def choose(label, options):
    print(label, file=sys.stderr)
    for index, (value, title) in enumerate(options, 1):
        print(f"  {index}. {title}", file=sys.stderr)
    while True:
        selected = ask("Seçim numarası", "1")
        if selected.isdecimal() and 1 <= int(selected) <= len(options):
            return options[int(selected) - 1][0]
        print("Listeden geçerli bir numara seçin.", file=sys.stderr)


async def select_model(connection, root):
    from openai import AsyncOpenAI
    from ragents.providers import resolve_connection
    try:
        if connection.provider == "chatgpt":
            from pydantic_ai.providers.openai_chatgpt import OpenAIChatGPTProvider
            provider = OpenAIChatGPTProvider(credential_source=ChatGPTStore(root=root))
            client = provider.client
        else:
            endpoint, key = resolve_connection(connection)
            client = AsyncOpenAI(base_url=endpoint, api_key=key, timeout=20, max_retries=0)
        async with client:
            page = await client.models.list()
            models = sorted({item.id for item in page.data})
        if not models:
            raise ValueError("empty")
    except Exception:
        raise TaskStateError("Sağlayıcıdan model listesi alınamadı. Bağlantı ve hesap erişimini kontrol edip kurulumu yeniden başlatın. Model tahmin edilmedi; profil oluşturulmadı.") from None
    return choose("Hesabın sunduğu modeller (listeleme üretim isteği göndermez):", [(name, name) for name in models])


def confirm_seen(value):
    require_terminal()
    print(json.dumps(value, ensure_ascii=False, indent=2), file=sys.stderr)
    expected = value["operation_hash"][:12]
    typed = ask(f"Görülen izinleri onaylamak için {expected} yazın")
    if typed != expected:
        raise TaskStateError("Yerel onay verilmedi; işlem uygulanmadı.")


def add_terminal_parsers(commands):
    uninstall = commands.add_parser("uninstall", help="MCP kayıtlarını, hizmeti ve uygulamayı kaldır; kullanıcı profilini koru")
    uninstall.add_argument("--root", type=Path)
    uninstall.add_argument("--yes", action="store_true", help="Yerel kaldırma onayını önceden ver")
    init = commands.add_parser("init", help="Terminalden modeli/aramayı bağla ve kullanıcı profilini hazırla")
    init.add_argument("--root", type=Path)
    init.add_argument("--provider", choices=get_args(ProviderName))
    init.add_argument("--model")
    init.add_argument("--api-key-env")
    init.add_argument("--base-url")
    init.add_argument("--search", choices=["disabled", "tavily", "brave", "searxng"])
    init.add_argument("--search-endpoint")
    init.add_argument("--login", action=argparse.BooleanOptionalAction, default=None)
    init.add_argument("--background", action=argparse.BooleanOptionalAction, default=None)
    init.add_argument("--non-interactive", action="store_true")
    connections = commands.add_parser("connections", help="Model kaynakları; yönetici MCP istemcisinden bağımsız")
    connections.add_argument("--root", type=Path)
    actions = connections.add_subparsers(dest="connection_action", required=True)
    actions.add_parser("list")
    test = actions.add_parser("test", help="Kayıtlı model bağlantısını YAML olmadan denetle")
    test.add_argument("id")
    test.add_argument("--live", action="store_true", help="Araçsız tek gerçek model isteği gönder; kota tüketebilir")
    add = actions.add_parser("add")
    add.add_argument("id")
    add.add_argument("--provider", choices=get_args(ProviderName), required=True)
    add.add_argument("--model", required=True)
    add.add_argument("--base-url")
    add.add_argument("--api-key-env")
    add.add_argument("--store-key", action="store_true", help="Anahtarı görünmeyen terminal girdisiyle Windows kasasına kaydet")
    search = commands.add_parser("search", help="Web arama seçimi ve güvenli anahtar girişi")
    search.add_argument("--root", type=Path)
    search_actions = search.add_subparsers(dest="search_action", required=True)
    search_actions.add_parser("status")
    configure = search_actions.add_parser("configure")
    configure.add_argument("--provider", choices=["disabled", "tavily", "brave", "searxng"], required=True)
    configure.add_argument("--endpoint")
    configure.add_argument("--api-key-env")
    configure.add_argument("--store-key", action="store_true")
    approvals = commands.add_parser("approvals", help="MCP taslaklarını terminalde incele ve yalnız görülen işlemi onayla")
    approvals.add_argument("--root", type=Path)
    approval_actions = approvals.add_subparsers(dest="approval_action", required=True)
    approval_actions.add_parser("list")
    approval_actions.add_parser("connections", help="Uzak MCP bağlantı izin taleplerini listele")
    for name in ("show", "approve", "apply", "approve-connection"):
        action = approval_actions.add_parser(name)
        action.add_argument("id")


def store_key(reference):
    require_terminal()
    value = getpass.getpass("API anahtarı (ekranda görünmez): ")
    SecretStore().set(reference, value)
    return reference


async def initialize(args):
    root = profile_root(args.root)
    if not args.non_interactive:
        print("R Agents · terminal kurulumu\nModel kaynakları: " + ", ".join(get_args(ProviderName)), file=sys.stderr)
        args.provider = args.provider or choose("Model sağlayıcısı", [(name, name) for name in get_args(ProviderName)])
        args.search = args.search or choose("Web araması", [("disabled", "Şimdilik bağlama"), ("tavily", "Tavily — hesap/anahtar"), ("brave", "Brave — hesap/anahtar"), ("searxng", "SearXNG — instance adresi")])
    if not args.provider or (args.non_interactive and not args.model):
        raise TaskStateError("Model kaynağı ve model kimliği gereklidir.")
    catalog = ConnectionCatalog(root)
    if "primary" in catalog.read():
        raise TaskStateError("Profil zaten hazırlanmış; connections add veya connections list kullanın.")
    env_name = args.api_key_env or DEFAULT_KEY_ENVS.get(args.provider)
    secret_ref = None
    if not args.non_interactive and args.provider in DEFAULT_KEY_ENVS and not args.api_key_env:
        secret_ref, env_name = store_key("model-primary"), None
    if args.provider == "chatgpt":
        login = args.login if args.login is not None else not args.non_interactive and ask("Resmi ChatGPT girişi açılsın mı? e/h", "e") == "e"
        if login:
            await sign_in(ChatGPTStore(root=root))
    if not args.model:
        candidate = ConnectionSpec(provider=args.provider, model="discovery", base_url=args.base_url,
                                   api_key_env=env_name, secret_ref=secret_ref)
        args.model = await select_model(candidate, root)
    connection = ConnectionSpec(provider=args.provider, model=args.model, base_url=args.base_url,
                                api_key_env=env_name, secret_ref=secret_ref)
    search = SearchConnection(provider=args.search or "disabled",
        endpoint=args.search_endpoint or (ask("SearXNG HTTPS instance adresi") if args.search == "searxng" and not args.non_interactive else None))
    if search.provider in ("tavily", "brave") and not args.non_interactive:
        search = search.model_copy(update={"secret_ref": store_key("search-" + search.provider)})
    catalog.put("primary", connection)
    TaskStore(database_path(root))
    save_search_connection(root, search)
    background = args.background if args.background is not None else not args.non_interactive and ask("Oturum açılışında arka planı başlat? e/h", "e") == "e"
    if background:
        from ragents.windows_service import install_service, scheduler_command
        import asyncio
        await asyncio.to_thread(install_service, root)
        (root / "data/supervisor.stop").unlink(missing_ok=True)
        await asyncio.to_thread(scheduler_command, root, "start")
    if not args.non_interactive:
        print("\n✓ R Agents profil kurulumu tamamlandı.\n"
              f"Sağlayıcı: {args.provider} | Model: {args.model}\n"
              "Canlı model erişimi henüz doğrulanmadı.\n"
              "Sonraki adım: ragents connect codex (veya opencode / claude)\n"
              "Bağlantı kontrolü: ragents connections test primary", file=sys.stderr)
    return {"initialized": True, "profile": str(root), "model_connection": "primary", "background": bool(background),
            "next": "ragents connect codex | ragents connect opencode | ragents connect claude",
            "approval": "ragents approvals list → ragents approvals show KIMLIK → ragents approvals approve KIMLIK"}


def dispatch_approvals(args):
    root = profile_root(args.root)
    if args.approval_action in ("approve", "approve-connection"):
        require_terminal()
    if args.approval_action in ("connections", "approve-connection"):
        from ragents.remote_oauth import RemoteOAuthProvider
        path = root / "connections/remote.json"
        if not path.is_file():
            raise TaskStateError("Uzak MCP henüz yapılandırılmadı.")
        provider = RemoteOAuthProvider(root, json.loads(path.read_text(encoding="utf-8"))["public_url"])
        pending = provider.pending()
        if args.approval_action == "connections":
            return {"connections": pending}
        request = next((item for item in pending if item["id"] == args.id), None)
        if request is None:
            raise TaskStateError("Bekleyen bağlantı onayı bulunamadı.")
        confirm_seen(request)
        provider.approve_local(args.id, request["operation_hash"])
        return {"approved": True, "id": args.id}
    plans = SetupPlanService(root, TaskStore(database_path(root)))
    if args.approval_action == "list":
        with plans.store.connect() as db:
            rows = db.execute("SELECT record_json FROM setup_requests ORDER BY rowid DESC LIMIT 100").fetchall()
        return {"approvals": [json.loads(row[0]) for row in rows]}
    request = plans.get(args.id)
    if args.approval_action == "apply":
        return plans.apply(args.id)
    if args.approval_action == "show":
        return request.model_dump(mode="json")
    confirm_seen(request.model_dump(mode="json"))
    plans.approve_local(args.id, request.operation_hash)
    return plans.apply(args.id)


async def dispatch_terminal(args):
    root = profile_root(args.root)
    if args.command == "init":
        return await initialize(args)
    if args.command == "approvals":
        return dispatch_approvals(args)
    if args.command == "connections":
        catalog = ConnectionCatalog(root)
        if args.connection_action == "list":
            return {"connections": [{"id": key, "provider": value.provider, "model": value.model}
                                    for key, value in catalog.read().items()]}
        if args.connection_action == "test":
            from ragents.diagnostics import inspect_connection
            config = ProjectConfig(schema_version=2, connections=catalog.read(),
                agent=AgentSpec(id="connection-check", name="Bağlantı kontrolü",
                                instructions="Yalnız OK yaz.", connection=args.id))
            report = await inspect_connection(config, args.id, live=args.live)
            if "auth_argv" in report:
                report["auth_argv"] = ["auth", "--root", str(root), *report["auth_argv"][1:]]
            return report
        reference = store_key("model-" + args.id) if args.store_key else None
        return catalog.put(args.id, ConnectionSpec(provider=args.provider, model=args.model, base_url=args.base_url,
            api_key_env=args.api_key_env, secret_ref=reference))
    if args.search_action == "status":
        return search_connection(root).model_dump(mode="json")
    reference = store_key("search-" + args.provider) if args.store_key else None
    connection = SearchConnection(provider=args.provider, endpoint=args.endpoint,
                                  api_key_env=args.api_key_env, secret_ref=reference)
    save_search_connection(root, connection)
    return {"saved": True, "provider": connection.provider, "paid_fallback": False}
