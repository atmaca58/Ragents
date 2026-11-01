from typing import Protocol

from pydantic import Field, model_validator

from ragents.config import (
    AgentSpec, COMMAND_TOOL_NAMES, Spec, WORKSPACE_TOOL_NAMES, WRITE_TOOL_NAMES,
)
from ragents.mcp_client import ToolGateway
from ragents.workspace import ArtifactDraft, WorkspaceGrant


class ConversationTurn(Spec):
    prompt: str = Field(min_length=1, max_length=32000)
    output: str = Field(min_length=1, max_length=64000)


class RunRequest(Spec):
    agent: AgentSpec
    prompt: str = Field(min_length=1, max_length=32000, pattern=r"\S")
    history: tuple[ConversationTurn, ...] = Field(default=(), max_length=50)
    workspace: WorkspaceGrant | None = None

    @model_validator(mode="after")
    def validate_workspace(self) -> "RunRequest":
        tools = set(self.agent.tools)
        if self.workspace is None and WORKSPACE_TOOL_NAMES.intersection(tools):
            raise ValueError("Workspace araçları için workspace tanımlı olmalıdır.")
        if self.workspace is not None:
            if tools & WRITE_TOOL_NAMES and not self.workspace.writable_paths:
                raise ValueError("Dosya yazma araçları için yazılabilir dizin tanımlı olmalıdır.")
            if tools & COMMAND_TOOL_NAMES and not self.workspace.commands:
                raise ValueError("Komut aracı için izinli komut listesi tanımlı olmalıdır.")
        return self


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
    artifacts: tuple[ArtifactDraft, ...] = ()


class Engine(Protocol):
    async def run(self, request: RunRequest, *, gateway: ToolGateway | None = None) -> RunResult: ...
