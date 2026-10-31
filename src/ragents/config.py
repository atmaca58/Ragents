from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from ragents.connections import FIXED_ENDPOINTS, ProviderName, WireAPI


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Budget(Spec):
    request_limit: int = Field(default=4, ge=1, le=100)
    tool_calls_limit: int = Field(default=2, ge=0, le=100)
    output_tokens_limit: int = Field(default=1024, ge=1, le=32768)
    input_tokens_limit: int = Field(default=16384, ge=1, le=2000000)
    total_tokens_limit: int = Field(default=18432, ge=1, le=2100000)
    timeout_seconds: float = Field(default=60, gt=0, le=3600)


class ContextPolicy(Spec):
    max_request_chars: int = Field(default=24000, ge=256, le=200000)
    max_history_turns: int = Field(default=4, ge=0, le=50)
    max_tool_output_chars: int = Field(default=2000, ge=64, le=32000)


class StdioMCP(Spec):
    transport: Literal["stdio"]
    command: str = Field(min_length=1)
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    env_vars: tuple[str, ...] = ()
    timeout_seconds: float = Field(default=20, gt=0, le=300)


class HttpMCP(Spec):
    transport: Literal["streamable-http"]
    url: HttpUrl
    bearer_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    timeout_seconds: float = Field(default=20, gt=0, le=300)

    @model_validator(mode="after")
    def validate_url(self) -> "HttpMCP":
        if self.url.username or self.url.password or self.url.query or self.url.fragment:
            raise ValueError("MCP URL kimlik bilgisi, sorgu veya fragment içeremez.")
        if self.url.scheme != "https" and self.url.host not in ("localhost", "127.0.0.1", "[::1]"):
            raise ValueError("Uzak MCP bağlantısı HTTPS kullanmalıdır.")
        return self


MCPConnection = Annotated[StdioMCP | HttpMCP, Field(discriminator="transport")]


class MCPGrant(Spec):
    server: str = Field(pattern=r"^[a-z][a-z0-9-]{0,19}$")
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    keywords: tuple[str, ...] = Field(default=(), max_length=30)
    always: bool = False


class ToolSelection(Spec):
    max_tools: int = Field(default=4, ge=0, le=32)
    max_schema_chars: int = Field(default=8000, ge=256, le=64000)
    max_description_chars: int = Field(default=600, ge=0, le=4000)


class ConnectionSpec(Spec):
    provider: ProviderName
    model: str = Field(min_length=1, max_length=200, pattern=r"^\S+$")
    base_url: HttpUrl | None = None
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    api: WireAPI | None = None
    oauth_account: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")

    @model_validator(mode="after")
    def validate_endpoint(self) -> "ConnectionSpec":
        if self.provider in FIXED_ENDPOINTS and self.base_url is not None:
            raise ValueError("OpenRouter/Go/Zen/ChatGPT için özel base_url desteklenmiyor.")
        if self.provider == "chatgpt":
            if self.api_key_env is not None or self.api not in (None, "responses"):
                raise ValueError("ChatGPT yalnız OAuth ve Responses API ile kullanılabilir.")
        elif self.oauth_account is not None:
            raise ValueError("oauth_account yalnız ChatGPT için kullanılabilir.")
        return self

    @property
    def wire_api(self) -> WireAPI:
        return self.api or ("responses" if self.provider == "chatgpt" else "chat_completions")


class AgentSpec(Spec):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    instructions: str = Field(min_length=1, max_length=16000)
    connection: str = Field(min_length=1)
    tools: tuple[Literal["text_stats"], ...] = ()
    budget: Budget = Field(default_factory=Budget)
    context: ContextPolicy = Field(default_factory=ContextPolicy)
    mcp_tools: tuple[MCPGrant, ...] = ()
    tool_selection: ToolSelection = Field(default_factory=ToolSelection)


class ProjectConfig(Spec):
    schema_version: Literal[2]
    connections: dict[str, ConnectionSpec] = Field(min_length=1)
    agent: AgentSpec
    mcp_servers: dict[str, MCPConnection] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_connection(self) -> "ProjectConfig":
        if self.agent.connection not in self.connections:
            raise ValueError("Ajanın bağlantısı connections içinde tanımlanmalıdır.")
        names = [(grant.server, grant.name) for grant in self.agent.mcp_tools]
        if len(set(names)) != len(names):
            raise ValueError("MCP araç izni tekrar edemez.")
        if any(grant.server not in self.mcp_servers for grant in self.agent.mcp_tools):
            raise ValueError("MCP araç sunucusu mcp_servers içinde tanımlanmalıdır.")
        return self


def load_config(path: Path) -> ProjectConfig:
    return ProjectConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
