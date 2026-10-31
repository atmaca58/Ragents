import asyncio
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from ragents.config import ProjectConfig
from ragents.storage import TaskStateError, TaskStore


READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)


async def safe_call(function: Callable, *args, **kwargs):
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    except TaskStateError as error:
        raise ToolError(str(error)) from None
    except Exception:
        raise ToolError("İşlem tamamlanamadı; görev kimliğini ve servis ayarlarını kontrol edin.") from None


def create_server(store: TaskStore, agents: dict[str, ProjectConfig], *, allow_execute: bool = False) -> MCPServer:
    server = MCPServer(
        "r-agents", instructions="R Agents V2. Görev kimliğiyle durumu ve sonucu sorgulayın. "
        "Görev gönderme yalnız açık çalıştırma izniyle kullanılabilir. Worker ayrı süreçte kuyruğu işler. "
        "list_agents ile kayıtlı bağlantıları öğrenin; submit_task connection_id model kaynağını seçer. "
        "Durumu aralıklı sorgulayın; başarılı runs kimliğiyle get_result çağırın.",
    )

    @server.tool(annotations=READ_ONLY)
    async def list_agents() -> dict[str, Any]:
        """Sunucuya açıkça kaydedilmiş örnek ajanları listele."""
        return {"agents": [{"id": config.agent.id, "name": config.agent.name,
                            "connection": config.agent.connection,
                            "connections": [{"id": name, "provider": spec.provider, "model": spec.model}
                                            for name, spec in config.connections.items()]}
                           for config in agents.values()]}

    @server.tool(annotations=READ_ONLY)
    async def list_tasks(limit: int = 50) -> dict[str, Any]:
        """V2 görev kuyruğunu ve son durumları listele."""
        tasks = await safe_call(store.list, limit=limit)
        return {"tasks": [task.model_dump() for task in tasks]}

    @server.tool(annotations=READ_ONLY)
    async def get_task(task_id: str) -> dict[str, Any]:
        """Bir V2 görevinin durumunu ve çalışma metadatasını oku."""
        task = await safe_call(store.get, task_id)
        runs = await safe_call(store.runs, task_id)
        return {"task": task.model_dump(), "runs": [run.model_dump() for run in runs]}

    @server.tool(annotations=READ_ONLY)
    async def get_result(run_id: str) -> dict[str, Any]:
        """Tamamlanmış çalışmanın kayıtlı sonucunu oku."""
        result = await safe_call(store.result, run_id)
        if result is None:
            raise ToolError("Bu çalışma için kayıtlı sonuç yok.")
        return {"result": result.model_dump()}

    if allow_execute:
        register_execution(server, store, agents)
    return server


def register_execution(server: MCPServer, store: TaskStore, agents: dict[str, ProjectConfig]) -> None:
    @server.tool(annotations=WRITE)
    async def submit_task(agent_id: str, prompt: str, key: str, connection_id: str | None = None) -> dict[str, Any]:
        """İşi sıraya al; connection_id kayıtlı model kaynağını seçer. Tekrarlar için aynı key kullanın. Worker çağrı yapar."""
        config = agents.get(agent_id)
        if config is None:
            raise ToolError("Ajan kayıtlı değil; önce list_agents çağırın.")
        if not key.strip() or len(key) > 200:
            raise ToolError("Görev anahtarı 1–200 karakter olmalıdır.")
        if connection_id is not None and connection_id not in config.connections:
            raise ToolError("Seçilen bağlantı tanımlı değil; list_agents içindeki bağlantılardan seçin.")
        task = await safe_call(store.enqueue, config, prompt, connection_id, idempotency_key=key)
        return {"task": task.model_dump()}

    @server.tool(annotations=WRITE)
    async def cancel_task(task_id: str) -> dict[str, Any]:
        """Bekleyen görevi iptal et; çalışan göreve iptal isteği gönder."""
        task = await safe_call(store.request_cancel, task_id)
        return {"task": task.model_dump()}

    @server.tool(annotations=WRITE)
    async def retry_task(task_id: str) -> dict[str, Any]:
        """Başarısız/kesilmiş/iptal edilmiş görevi yeniden sıraya al; worker tekrar çağrı yapabilir."""
        task = await safe_call(store.retry, task_id)
        return {"task": task.model_dump()}
