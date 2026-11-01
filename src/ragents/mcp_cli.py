from pathlib import Path

from ragents.config import load_config
from ragents.mcp_server import create_server
from ragents.mcp_transport import open_gateway
from ragents.storage import TaskStateError, TaskStore
from ragents.profile_paths import database_path, profile_root


def add_mcp_parser(commands) -> None:
    parser = commands.add_parser("mcp", help="MCP araç bağlantıları ve V2 yönetim sunucusu")
    actions = parser.add_subparsers(dest="mcp_action", required=True)
    serve = actions.add_parser("serve", help="Stdio veya yerel HTTP yönetim MCP'sini başlat")
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--port", type=int, default=8765, help="HTTP loopback portu (1–65535)")
    serve.add_argument("--db", type=Path)
    serve.add_argument("--root", type=Path)
    serve.add_argument("--config", type=Path, action="append", default=[])
    serve.add_argument("--allow-execute", action="store_true", help="Kuyruğa görev gönderme/iptal/yeniden deneme izni")
    serve.add_argument("--allow-write", action="store_true", help="Hafıza adayı yazma; onay veya ücretli çalışma yetkisi vermez")
    serve.add_argument("--allow-manage", action="store_true", help="Kurulum taslağı önerme; yerel kullanıcı onayı ayrıca gerekir")
    serve.add_argument("--public-url", help="Yalnız OAuth korumalı uzak mod için HTTPS tünel kök adresi")
    tools = actions.add_parser("tools", help="Görev için seçilen izinli araçları keşfet; model/araç çağrısı yapma")
    tools.add_argument("--config", type=Path, required=True)
    tools.add_argument("--prompt", required=True)


async def dispatch_mcp(args) -> dict | None:
    if args.mcp_action == "tools":
        config = load_config(args.config)
        async with open_gateway(config, args.prompt) as gateway:
            return {"selected": [{"name": tool.model_name, "schema_chars": tool.schema_chars()}
                                 for tool in gateway.tools], "model_requests": 0}
    if not 1 <= args.port <= 65535:
        raise TaskStateError("HTTP portu 1–65535 arasında olmalıdır.")
    agents = {}
    for path in args.config:
        config = load_config(path)
        if config.agent.id in agents:
            raise TaskStateError("MCP sunucusuna aynı ajan kimliği iki kez kaydedilemez.")
        agents[config.agent.id] = config
    root = profile_root(getattr(args, "root", None))
    remote = None
    if getattr(args, "public_url", None):
        if args.transport != "streamable-http":
            raise TaskStateError("Uzak adres yalnız HTTP taşımasında kullanılabilir.")
        from ragents.remote_oauth import RemoteOAuthProvider
        from ragents.catalog import _write_atomic
        import json
        remote = RemoteOAuthProvider(root, args.public_url)
        _write_atomic(root / "connections/remote.json", json.dumps({"public_url": remote.issuer,
            "allow_manage": args.allow_manage, "allow_write": args.allow_write,
            "allow_execute": args.allow_execute}))
    server = create_server(TaskStore(database_path(root, args.db)), agents,
                           root=root, allow_execute=args.allow_execute,
                           allow_write=getattr(args, "allow_write", False),
                           allow_manage=getattr(args, "allow_manage", False), remote_provider=remote)
    if args.transport == "streamable-http":
        from ragents.mcp_http_server import management_app
        import uvicorn

        await uvicorn.Server(uvicorn.Config(management_app(server, remote_provider=remote), host="127.0.0.1", port=args.port,
                                           access_log=False, proxy_headers=False)).serve()
    else:
        await server.run_stdio_async()
    return None  # stdout yalnız MCP protokolüne aittir.
