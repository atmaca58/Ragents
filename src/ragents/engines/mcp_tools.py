from pydantic_ai import Tool

from ragents.mcp_client import RemoteTool, ToolGateway


def gateway_tools(gateway: ToolGateway | None) -> list[Tool]:
    if gateway is None:
        return []
    return [make_tool(gateway, remote) for remote in gateway.tools]


def make_tool(gateway: ToolGateway, remote: RemoteTool) -> Tool:
    async def invoke(**arguments):
        return await gateway.call(remote.model_name, arguments)

    return Tool.from_schema(invoke, name=remote.model_name, description=remote.description,
                            json_schema=remote.input_schema, sequential=True)
