import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import json
import os
import sys
from typing import Any

from jsonschema.validators import validator_for
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
import httpx2

from ragents.config import MCPConnection, ProjectConfig, StdioMCP
from ragents.mcp_client import MCPAccessError, RemoteTool, ToolCatalog, ToolGateway, relevant


def environment_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MCPAccessError()
    return value


@asynccontextmanager
async def connect_mcp(spec: MCPConnection):
    async with AsyncExitStack() as stack:
        if isinstance(spec, StdioMCP):
            command = sys.executable if spec.command == "{python}" else spec.command
            params = StdioServerParameters(command=command, args=list(spec.args), cwd=spec.cwd,
                                          env={name: environment_value(name) for name in spec.env_vars})
            error_log = stack.enter_context(open(os.devnull, "w"))
            transport = stdio_client(params, errlog=error_log)
        else:
            headers = {"Authorization": "Bearer " + environment_value(spec.bearer_env)} if spec.bearer_env else {}
            http = await stack.enter_async_context(httpx2.AsyncClient(
                headers=headers, timeout=spec.timeout_seconds, follow_redirects=False,
            ))
            transport = streamable_http_client(str(spec.url), http_client=http)
        # Legacy negotiation avoids automatic HEADER_MISMATCH tool-call replay.
        client = Client(transport, mode="legacy", read_timeout_seconds=spec.timeout_seconds, cache=None)
        async with client:
            yield client


async def discover(client: Client, server: str) -> list[RemoteTool]:
    tools, seen = [], set()
    cursor = None
    for _ in range(100):
        page = await client.list_tools(cursor=cursor)
        tools.extend(RemoteTool(server, tool.name, tool.description or "", tool.input_schema) for tool in page.tools)
        if len(tools) > 1000:
            raise MCPAccessError()
        cursor = page.next_cursor
        if cursor is None:
            return tools
        if cursor in seen:
            raise MCPAccessError()
        seen.add(cursor)
    raise MCPAccessError()


def check_local_references(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("$ref", "$dynamicRef") and isinstance(child, str) and not child.startswith("#"):
                raise MCPAccessError()
            check_local_references(child)
    elif isinstance(value, list):
        for child in value:
            check_local_references(child)


@asynccontextmanager
async def open_gateway(config: ProjectConfig, prompt: str, *, connector=connect_mcp):
    captured = None
    async with AsyncExitStack() as stack:
        gateway = await prepare_gateway(config, prompt, stack, connector)
        try:
            yield gateway
        except BaseException as error:
            # SDK task-group çıkışı model hatasını ExceptionGroup içine sarmasın.
            captured = error
    if captured is not None:
        raise captured


async def prepare_gateway(config, prompt, stack, connector) -> ToolGateway:
    needed = dict.fromkeys(grant.server for grant in config.agent.mcp_tools if relevant(grant, prompt))
    if config.agent.tool_selection.max_tools == 0:
        needed = {}
    try:
        clients, catalog = {}, []
        for server in needed:
            spec = config.mcp_servers[server]
            async with asyncio.timeout(spec.timeout_seconds):
                clients[server] = await stack.enter_async_context(connector(spec))
                catalog.extend(await discover(clients[server], server))
        selected = ToolCatalog(catalog).select(config.agent, prompt) if needed else []
        validators = {}
        for tool in selected:
            check_local_references(tool.input_schema)
            kind = validator_for(tool.input_schema)
            kind.check_schema(tool.input_schema)
            validators[tool.model_name] = kind(tool.input_schema)

        async def invoke(tool: RemoteTool, arguments: dict[str, Any]) -> str:
            try:
                validators[tool.model_name].validate(arguments)
                spec = config.mcp_servers[tool.server]
                async with asyncio.timeout(spec.timeout_seconds):
                    result = await clients[tool.server].call_tool(tool.name, arguments)
                if result.is_error:
                    raise MCPAccessError()
                return bounded_output(result, config.agent.context.max_tool_output_chars)
            except Exception:
                raise MCPAccessError() from None

        return ToolGateway(selected, invoke)
    except MCPAccessError:
        raise
    except Exception:
        # Sunucu hataları/header'lar/araç argümanları kimlik bilgisi içerebilir.
        raise MCPAccessError() from None


def bounded_output(result, limit: int) -> str:
    if result.structured_content is not None:
        output = json.dumps(result.structured_content, ensure_ascii=False)
    else:
        output = "\n".join(part.text for part in result.content if part.type == "text")
    suffix = "\n[araç çıktısı kısaltıldı]"
    return output if len(output) <= limit else output[:limit - len(suffix)] + suffix
