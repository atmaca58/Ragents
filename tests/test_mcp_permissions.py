import asyncio
from pathlib import Path

from mcp import Client
from mcp.server.mcpserver import MCPServer
import pytest

from ragents.config import ProjectConfig, load_config
from ragents.mcp_client import MCPAccessError
from ragents.mcp_transport import open_gateway


@pytest.fixture
def tool_server():
    data = load_config(Path("examples/ollama.yaml")).model_dump()
    data["mcp_servers"] = {"office": {"transport": "stdio", "command": "unused"}}
    data["agent"]["mcp_tools"] = [{"server": "office", "name": "search", "keywords": ["posta"]}]
    data["agent"]["context"]["max_tool_output_chars"] = 64
    config = ProjectConfig.model_validate(data)
    server = MCPServer("permission-test")
    calls = []

    @server.tool()
    def search(query: str) -> str:
        calls.append(query)
        return "x" * 500

    return config, server, calls


def test_irrelevant_task_never_connects_to_configured_server(tool_server):
    config, _, _ = tool_server

    def denied(spec):
        raise AssertionError("İlgisiz sunucuya bağlantı açılmamalı")

    async def scenario():
        async with open_gateway(config, "şiir yaz", connector=denied) as gateway:
            assert gateway.tools == []

    asyncio.run(scenario())


def test_unknown_or_unselected_tool_is_denied_before_remote_call(tool_server):
    config, server, calls = tool_server

    async def scenario():
        async with open_gateway(config, "posta", connector=lambda spec: Client(server)) as gateway:
            with pytest.raises(MCPAccessError):
                await gateway.call("office__delete", {})

    asyncio.run(scenario())
    assert calls == []


def test_invalid_arguments_are_rejected_locally_without_echoing_values(tool_server):
    config, server, calls = tool_server

    async def scenario():
        async with open_gateway(config, "posta", connector=lambda spec: Client(server)) as gateway:
            with pytest.raises(MCPAccessError) as error:
                await gateway.call("office__search", {"query": {"secret": "hidden-value"}})
            assert "hidden-value" not in str(error.value)

    asyncio.run(scenario())
    assert calls == []


def test_large_remote_output_is_bounded_before_entering_model_context(tool_server):
    config, server, _ = tool_server

    async def scenario():
        async with open_gateway(config, "posta", connector=lambda spec: Client(server)) as gateway:
            output = await gateway.call("office__search", {"query": "rapor"})
            assert len(output) == 64
            assert "kısaltıldı" in output

    asyncio.run(scenario())
