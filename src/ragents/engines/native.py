import asyncio

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from ragents.contracts import RunRequest, RunResult, ToolUsage, Usage
from ragents.engines.context import ContextGuard
from ragents.engines.mcp_tools import gateway_tools
from ragents.mcp_client import ToolGateway
from ragents.tools import build_tools
from ragents.workspace import ArtifactLog


class NativeEngine:
    def __init__(self, model: Model, *, request_token_cap: bool = True):
        self.model = model
        self.request_token_cap = request_token_cap

    @classmethod
    def demo(cls) -> "NativeEngine":
        from pydantic_ai.models.test import TestModel

        return cls(TestModel(custom_output_text="R Agents native motor demosu. Bu yanıt simülasyondur."))

    async def run(self, request: RunRequest, *, gateway: ToolGateway | None = None) -> RunResult:
        budget = request.agent.budget
        schema_chars = sum(tool.schema_chars() for tool in gateway.tools) if gateway else 0
        context = ContextGuard(request, extra_chars=schema_chars)
        history = context.history(request)

        def model_settings(ctx: RunContext) -> dict:
            remaining = min(
                budget.output_tokens_limit - ctx.usage.output_tokens,
                budget.total_tokens_limit - ctx.usage.total_tokens,
            )
            if remaining <= 0:
                raise UsageLimitExceeded("Token bütçesi tükendi; yeni model isteği gönderilmedi.")
            return {"max_tokens": remaining} if self.request_token_cap else {}

        artifacts = ArtifactLog()
        agent = Agent(
            self.model,
            instructions=request.agent.instructions,
            retries=0,
            capabilities=[ProcessHistory(context.process)],
            tools=[
                *build_tools(request.agent, request.workspace, artifacts=artifacts),
                *gateway_tools(gateway),
            ],
            model_settings=model_settings,
        )
        async with asyncio.timeout(budget.timeout_seconds):
            result = await agent.run(
                request.prompt,
                message_history=history,
                usage_limits=UsageLimits(
                    request_limit=budget.request_limit,
                    tool_calls_limit=budget.tool_calls_limit,
                    output_tokens_limit=budget.output_tokens_limit,
                    input_tokens_limit=budget.input_tokens_limit,
                    total_tokens_limit=budget.total_tokens_limit,
                ),
            )
        usage = result.usage
        return RunResult(
            agent_id=request.agent.id,
            output=result.output,
            context=context.report(),
            tools=ToolUsage(selected=len(gateway.tools) if gateway else 0, schema_chars=schema_chars),
            artifacts=tuple(artifacts.drafts),
            usage=Usage(
                requests=usage.requests,
                tool_calls=usage.tool_calls,
                input_tokens=usage.input_tokens or None,
                output_tokens=usage.output_tokens or None,
            ),
        )
