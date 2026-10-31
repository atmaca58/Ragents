"""Yerel MCP denemesi; mevcut saf aracı yeniden kullanır, modele erişmez."""
from mcp.server.mcpserver import MCPServer

from ragents.tools import text_stats


server = MCPServer("r-agents-example-tools")
server.tool()(text_stats)

if __name__ == "__main__":
    server.run(transport="stdio")
