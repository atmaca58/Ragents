from typing import Protocol

from pydantic import Field

from ragents.config import AgentSpec, Spec
from ragents.mcp_client import ToolGateway


class ConversationTurn(Spec):
    prompt: str = Field(min_length=1, max_length=32000)
    output: str = Field(min_length=1, max_length=64000)


class RunRequest(Spec):
    agent: AgentSpec
    prompt: str = Field(min_length=1, max_length=32000, pattern=r"\S")
    history: tuple[ConversationTurn, ...] = Field(default=(), max_length=50)


class Usage(Spec):
    requests: int
    tool_calls: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: str | None = None


class ContextUsage(Spec):
    dropped_turns: int = 0
    trimmed_tool_results: int = 0
    peak_request_chars: int = 0


class ToolUsage(Spec):
    selected: int = 0
    schema_chars: int = 0


class RunResult(Spec):
    agent_id: str
    output: str
    usage: Usage
    context: ContextUsage = Field(default_factory=ContextUsage)
    tools: ToolUsage = Field(default_factory=ToolUsage)


class Engine(Protocol):
    async def run(self, request: RunRequest, *, gateway: ToolGateway | None = None) -> RunResult: ...
