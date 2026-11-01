"""Uzak MCP'de her araç çağrısında dar kapsam ve güncel iptal kontrolü."""
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.shared.exceptions import MCPError


TOOL_SCOPES = {
    "list_agents": "read", "list_tasks": "read", "get_task": "read", "get_result": "read",
    "read_artifact": "read",
    "get_capabilities": "read", "get_setup_schema": "read", "list_connections": "read",
    "get_setup": "manage", "propose_setup": "manage", "apply_setup": "manage",
    "get_teams": "read", "get_team_run": "read", "start_team": "execute", "cancel_team": "execute",
    "submit_task": "execute", "cancel_task": "execute", "retry_task": "execute",
    "list_schedules": "read", "create_schedule": "execute", "set_schedule_enabled": "execute",
    "list_memory": "read", "propose_memory": "configure", "revise_memory": "configure", "archive_memory": "configure",
}


class ScopeMiddleware:
    def __init__(self, provider):
        self.provider = provider

    async def __call__(self, ctx, call_next):
        token = get_access_token()
        current = await self.provider.load_access_token(token.token) if token else None
        scope = "read"
        if ctx.method == "tools/call":
            scope = TOOL_SCOPES.get((ctx.params or {}).get("name"))
        if current is None or scope is None or scope not in current.scopes:
            raise MCPError(-32003, "Bu işlem için bağlantı yetkisi eksik veya iptal edilmiş.")
        return await call_next(ctx)
