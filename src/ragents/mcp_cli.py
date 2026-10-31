from pathlib import Path

from ragents.config import load_config
from ragents.mcp_server import create_server
from ragents.mcp_transport import open_gateway
from ragents.storage import TaskStateError, TaskStore


def add_mcp_parser(commands) -> None:
    parser = commands.add_parser("mcp", help="MCP araç bağlantıları ve V2 yönetim sunucusu")
    actions = parser.add_subparsers(dest="mcp_action", required=True)
    serve = actions.add_parser("serve", help="Stdio veya yerel HTTP yönetim MCP'sini başlat")
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--port", type=int, default=8765, help="HTTP loopback portu (1–65535)")
    serve.add_argument("--db", type=Path, default=Path("data/ragents.db"))
    serve.add_argument("--config", type=Path, action="append", default=[])
    serve.add_argument("--allow-execute", action="store_true", help="Kuyruğa görev gönderme/iptal/yeniden deneme izni")
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
    server = create_server(TaskStore(args.db), agents, allow_execute=args.allow_execute)
    if args.transport == "streamable-http":
        from ragents.mcp_http_server import management_app
        import uvicorn

        await uvicorn.Server(uvicorn.Config(management_app(server), host="127.0.0.1", port=args.port,
                                           access_log=False)).serve()
    else:
        await server.run_stdio_async()
    return None  # stdout yalnız MCP protokolüne aittir.
