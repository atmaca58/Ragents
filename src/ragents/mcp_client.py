from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
import json
import re
from typing import Any

from ragents.config import AgentSpec, MCPGrant


class MCPAccessError(RuntimeError):
    def __init__(self):
        super().__init__("MCP bağlantısı veya araç çağrısı tamamlanamadı; izinleri ve sunucuyu kontrol edin.")


@dataclass(frozen=True)
class RemoteTool:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def model_name(self) -> str:
        return f"{self.server}__{self.name}"

    def schema_chars(self) -> int:
        return len(json.dumps({"name": self.model_name, "description": self.description,
                               "parameters": self.input_schema}, ensure_ascii=False))


def relevant(grant: MCPGrant, prompt: str) -> bool:
    words = set(re.findall(r"\w+", prompt.casefold()))
    return grant.always or any(set(re.findall(r"\w+", keyword.casefold())) <= words
                               for keyword in grant.keywords if keyword.strip())


class ToolCatalog:
    def __init__(self, tools: list[RemoteTool]):
        self.tools = {(tool.server, tool.name): tool for tool in tools}
        if len(self.tools) != len(tools):
            raise MCPAccessError()

    def select(self, agent: AgentSpec, prompt: str) -> list[RemoteTool]:
        policy = agent.tool_selection
        selected, size = [], 0
        for grant in agent.mcp_tools:
            if not relevant(grant, prompt):
                continue
            tool = self.tools.get((grant.server, grant.name))
            if tool is None:
                raise MCPAccessError()
            tool = replace(tool, description=tool.description[:policy.max_description_chars])
            chars = tool.schema_chars()
            if len(selected) >= policy.max_tools or size + chars > policy.max_schema_chars:
                continue
            selected.append(tool)
            size += chars
        return selected


@dataclass
class ToolGateway:
    tools: list[RemoteTool]
    invoke: Callable[[RemoteTool, dict[str, Any]], Awaitable[str]]

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        tool = next((tool for tool in self.tools if tool.model_name == name), None)
        if tool is None:
            raise MCPAccessError()
        return await self.invoke(tool, arguments)
