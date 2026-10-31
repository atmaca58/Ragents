import asyncio
from pathlib import Path

from mcp import Client
from mcp.server.mcpserver import MCPServer

from ragents.config import ProjectConfig, load_config
import pytest


def mcp_config():
    data = load_config(Path("examples/ollama.yaml")).model_dump()
    data["mcp_servers"] = {"office": {"transport": "stdio", "command": "unused"}}
    data["agent"]["mcp_tools"] = [{"server": "office", "name": "search", "keywords": ["posta"]}]
    return ProjectConfig.model_validate(data)


def test_real_mcp_protocol_discovers_and_calls_only_selected_tool():
    from ragents.mcp_transport import open_gateway

    server = MCPServer("tools")
    calls = []

    @server.tool()
    def search(query: str) -> str:
        calls.append(query)
        return "Posta bulundu"

    @server.tool()
    def delete_everything() -> str:
        raise AssertionError("İzinsiz araç çalıştırılmamalı")

    async def scenario():
        async with open_gateway(mcp_config(), "posta ara", connector=lambda spec: Client(server)) as gateway:
            assert [tool.model_name for tool in gateway.tools] == ["office__search"]
            assert "Posta bulundu" in await gateway.call("office__search", {"query": "rapor"})

    asyncio.run(scenario())
    assert calls == ["rapor"]


def test_stdio_transport_runs_existing_pure_tool_without_llm():
    from ragents.mcp_transport import open_gateway
    from pathlib import Path
    import sys

    data = load_config(Path("examples/ollama-mcp.yaml")).model_dump()
    data["mcp_servers"]["local-tools"]["command"] = sys.executable
    config = ProjectConfig.model_validate(data)

    async def scenario():
        async with open_gateway(config, "kelime say") as gateway:
            result = await gateway.call("local-tools__text_stats", {"text": "merhaba dünya"})
            import json
            assert json.loads(result)["words"] == 2

    asyncio.run(scenario())


def test_model_error_is_not_misclassified_as_mcp_failure():
    from ragents.mcp_transport import open_gateway

    async def scenario():
        config = load_config(Path("examples/ollama.yaml"))
        with pytest.raises(ValueError, match="model failure"):
            async with open_gateway(config, "Görev"):
                raise ValueError("model failure")

    asyncio.run(scenario())
