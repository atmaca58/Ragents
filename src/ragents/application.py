import asyncio

from ragents.config import ProjectConfig
from ragents.contracts import RunRequest, RunResult
from ragents.providers import open_engine
from ragents.mcp_transport import open_gateway


async def run_task(
    config: ProjectConfig, prompt: str, connection_id: str | None = None,
) -> RunResult:
    selected = connection_id or config.agent.connection
    if selected not in config.connections:
        raise ValueError("Seçilen bağlantı tanımlı değil.")
    request = RunRequest(agent=config.agent, prompt=prompt)
    async with asyncio.timeout(config.agent.budget.timeout_seconds):
        async with open_gateway(config, prompt) as gateway:
            async with open_engine(config.connections[selected]) as engine:
                if gateway.tools:
                    return await engine.run(request, gateway=gateway)
                return await engine.run(request)
