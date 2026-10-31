import asyncio
from pathlib import Path

import httpx2
from mcp.server.mcpserver import MCPServer

from ragents.config import ProjectConfig, load_config
from ragents.mcp_transport import open_gateway


def test_streamable_http_uses_explicit_bearer_env_and_real_protocol(monkeypatch):
    server = MCPServer("http-tools")

    @server.tool()
    def count(text: str) -> dict:
        return {"length": len(text)}

    app = server.streamable_http_app()
    original = httpx2.AsyncClient
    seen = []

    async def inspect(request):
        seen.append(request.headers.get("Authorization"))

    def http_client(**kwargs):
        return original(**kwargs, transport=httpx2.ASGITransport(app=app), event_hooks={"request": [inspect]})

    monkeypatch.setattr("ragents.mcp_transport.httpx2.AsyncClient", http_client)
    monkeypatch.setenv("RAGENTS_TEST_MCP_KEY", "test-only-token")
    data = load_config(Path("examples/ollama.yaml")).model_dump()
    data["mcp_servers"] = {"remote": {"transport": "streamable-http", "url": "http://127.0.0.1:8000/mcp",
                                      "bearer_env": "RAGENTS_TEST_MCP_KEY"}}
    data["agent"]["mcp_tools"] = [{"server": "remote", "name": "count", "always": True}]

    async def scenario():
        async with app.router.lifespan_context(app):
            async with open_gateway(ProjectConfig.model_validate(data), "say") as gateway:
                assert '3' in await gateway.call("remote__count", {"text": "abc"})

    asyncio.run(scenario())
    assert seen and all(header == "Bearer test-only-token" for header in seen)
