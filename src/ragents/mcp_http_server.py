from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette


def management_app(server: MCPServer) -> Starlette:
    """Yerel/tünelli yönetim; SDK'nın Host/Origin korumasını açık tutar."""
    return server.streamable_http_app(
        host="127.0.0.1", stateless_http=True, json_response=True,
        max_request_body_size=256 * 1024,
    )
