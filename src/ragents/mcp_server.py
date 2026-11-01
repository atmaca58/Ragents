import asyncio
from collections.abc import Callable
from typing import Any
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from ragents.config import ProjectConfig
from ragents.storage import TaskStateError, TaskStore
from ragents.verification import VerificationPlan
from ragents.management import ManagementCatalog
from ragents.catalog import enqueue_agent_task
from ragents.programmatic import ProgrammaticJob
from ragents.schedules import ScheduleService, ScheduleTiming
from ragents.memory import MemoryService


READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)


async def safe_call(function: Callable, *args, **kwargs):
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    except TaskStateError as error:
        raise ToolError(str(error)) from None
    except Exception:
        raise ToolError("İşlem tamamlanamadı; görev kimliğini ve servis ayarlarını kontrol edin.") from None


def create_server(store: TaskStore, agents: dict[str, ProjectConfig], *, allow_execute: bool = False,
                  root: Path | None = None, allow_write: bool = False,
                  allow_manage: bool = False, remote_provider=None) -> MCPServer:
    catalog = ManagementCatalog(root, agents)
    auth_settings = None
    middleware = []
    if remote_provider is not None:
        from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
        from ragents.remote_oauth import SCOPES
        from ragents.mcp_authorization import ScopeMiddleware
        auth_settings = AuthSettings(issuer_url=remote_provider.issuer, resource_server_url=remote_provider.resource,
            validate_token_resource=True, required_scopes=["read"],
            client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=list(SCOPES), default_scopes=["read"]),
            revocation_options=RevocationOptions(enabled=True))
        middleware = [ScopeMiddleware(remote_provider)]
    server = MCPServer(
        auth=auth_settings, auth_server_provider=remote_provider, middleware=middleware,
        name="r-agents", instructions="R Agents V2. Görev kimliğiyle durumu ve sonucu sorgulayın. "
        "Görev gönderme yalnız açık çalıştırma izniyle kullanılabilir. Worker ayrı süreçte kuyruğu işler. "
        "list_agents ile kayıtlı bağlantıları öğrenin; submit_task connection_id model kaynağını seçer. "
        "Durumu aralıklı sorgulayın; başarılı runs kimliğiyle get_result çağırın.",
    )

    @server.tool(annotations=READ_ONLY)
    async def list_agents() -> dict[str, Any]:
        """Kalıcı katalog ve açık uyumluluk kayıtlarındaki ajanları keşfet."""
        return {"agents": await safe_call(catalog.list)}

    @server.tool(annotations=READ_ONLY)
    async def list_tasks(limit: int = 50) -> dict[str, Any]:
        """V2 görev kuyruğunu ve son durumları listele."""
        tasks = await safe_call(store.list, limit=limit)
        return {"tasks": [task.model_dump() for task in tasks]}

    @server.tool(annotations=READ_ONLY)
    async def get_task(task_id: str) -> dict[str, Any]:
        """Bir V2 görevinin durumunu, çalışma metadatasını ve artifact'larını oku."""
        task = await safe_call(store.get, task_id)
        runs = await safe_call(store.runs, task_id)
        artifacts = await safe_call(store.artifacts, task_id)
        verifications = await safe_call(store.verifications, task_id)
        dependencies = await safe_call(store.dependencies, task_id)
        blocked_by = await safe_call(store.blocked_by, task_id)
        return {
            "task": task.model_dump(), "runs": [run.model_dump() for run in runs],
            "dependencies": list(dependencies), "blocked_by": list(blocked_by),
            "ready": task.status == "queued" and task.enabled and task.archived_at is None and not blocked_by,
            "verifications": [record.model_dump() for record in verifications],
            "artifacts": [artifact.model_dump() for artifact in artifacts],
        }

    @server.tool(annotations=READ_ONLY)
    async def get_result(run_id: str) -> dict[str, Any]:
        """Tamamlanmış çalışmanın kayıtlı sonucunu oku."""
        result = await safe_call(store.result, run_id)
        if result is None:
            raise ToolError("Bu çalışma için kayıtlı sonuç yok.")
        verification = await safe_call(store.verification, run_id)
        run = await safe_call(store.run, run_id)
        return {
            "status": run.status, "error_code": run.error_code,
            "result": result.model_dump(),
            "verification": verification.model_dump() if verification else None,
        }

    if allow_execute:
        register_execution(server, store, catalog)
    if root is not None:
        from ragents.artifact_store import ArtifactStore
        @server.tool(annotations=READ_ONLY)
        async def read_artifact(artifact_id: str, offset: int = 0, max_bytes: int = 16000) -> dict[str, Any]:
            """Artifact kimliğiyle değişmez içeriği sayfalı oku; serbest dosya yolu almaz."""
            return await safe_call(ArtifactStore(root, store).read, artifact_id, offset=offset, max_bytes=max_bytes)
        register_schedule_tools(server, store, allow_execute=allow_execute)
        register_memory_tools(server, store, allow_write=allow_write)
        register_setup_tools(server, store, root, allow_manage=allow_manage)
        register_team_tools(server, store, root, allow_execute=allow_execute)
    return server


def register_team_tools(server, store, root, *, allow_execute):
    from ragents.teams import TeamService
    from ragents.teams_cli import load_team, list_teams
    teams = TeamService(root, store)

    @server.tool(annotations=READ_ONLY)
    async def get_teams() -> dict[str, Any]:
        """Yerelde onaylanmış sabit ekip akışlarını listele."""
        return {"teams": await safe_call(list_teams, root)}

    @server.tool(annotations=READ_ONLY)
    async def get_team_run(run_id: str) -> dict[str, Any]:
        """Parent durumunu, adımları ve ortak tüketimi oku."""
        record = await safe_call(teams.get, run_id)
        return {key: value for key, value in record.items() if key != "definitions"}

    if not allow_execute:
        return

    @server.tool(annotations=WRITE)
    async def start_team(team_id: str, key: str) -> dict[str, Any]:
        """Onaylı ekibi aynı worker kuyruğunda başlat; bu MCP çağrısı modeli çalıştırmaz."""
        spec = await safe_call(load_team, root, team_id)
        record = await safe_call(teams.start, spec, key=key)
        return {key: value for key, value in record.items() if key != "definitions"}

    @server.tool(annotations=WRITE)
    async def cancel_team(run_id: str) -> dict[str, Any]:
        """Ekip iptalini kalıcı kaydet ve tüm alt görevlere yay."""
        record = await safe_call(teams.cancel, run_id)
        return {key: value for key, value in record.items() if key != "definitions"}


def register_setup_tools(server, store, root, *, allow_manage):
    from ragents.setup_plans import SetupPlan, SetupPlanService
    plans = SetupPlanService(root, store)

    @server.tool(annotations=READ_ONLY)
    async def get_capabilities() -> dict[str, Any]:
        """Ürün yeteneklerini ve henüz tamamlanmayan kabul kapılarını oku."""
        return {"setup_plans": True, "local_approval_required": True,
                "ready_for_release": False, "remote_oauth": True, "remote_oauth_accepted": False,
                "permissions": {"manage": allow_manage},
                "missing": ["Windows kurucu kabulü", "Uzak OAuth kabulü", "Canlı 20x3 kabul"]}

    @server.tool(annotations=READ_ONLY)
    async def list_connections() -> dict[str, Any]:
        """Kayıtlı model bağlantılarını secret veya endpoint göstermeden listele."""
        connections = await safe_call(plans.connections)
        return {"connections": [{"id": identity, "provider": value.provider, "model": value.model}
                                for identity, value in connections.items()]}

    @server.tool(annotations=READ_ONLY)
    async def get_setup_schema() -> dict[str, Any]:
        """Ajan/ekip taslağının kapalı sürümlü JSON şemasını oku."""
        return SetupPlan.model_json_schema()

    if not allow_manage:
        return

    @server.tool(annotations=WRITE)
    async def propose_setup(plan: dict[str, Any]) -> dict[str, Any]:
        """Ajan kurulum taslağını doğrula ve yerel insan onayı iste; onay vermez."""
        try:
            parsed = SetupPlan.model_validate(plan)
        except ValidationError:
            raise ToolError("Kurulum taslağı geçersiz; sözleşme alanlarını kontrol edin.") from None
        request = await safe_call(plans.propose, parsed)
        return {"approval": request.model_dump(mode="json"), "next": "Terminalde ragents approvals show KIMLIK ve ragents approvals approve KIMLIK ile inceleyip onaylayın."}

    @server.tool(annotations=READ_ONLY)
    async def get_setup(approval_id: str) -> dict[str, Any]:
        """Kurulum önizlemesi ve gerçek yerel onayın durumunu oku."""
        request = await safe_call(plans.get, approval_id)
        return {"approval": request.model_dump(mode="json")}

    @server.tool(annotations=WRITE)
    async def apply_setup(approval_id: str) -> dict[str, Any]:
        """Yalnız daha önce yerelde onaylanmış işlemi idempotent uygula."""
        return await safe_call(plans.apply, approval_id)


def register_execution(server: MCPServer, store: TaskStore, catalog: ManagementCatalog) -> None:
    @server.tool(annotations=WRITE)
    async def submit_task(
        agent_id: str, prompt: str, key: str, connection_id: str | None = None,
        verification: dict[str, Any] | None = None, title: str | None = None,
        description: str = "", priority: int = 0,
        depends_on: list[str] | None = None,
        programmatic: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """İşi sıraya al; connection_id model kaynağını, verification isteğe bağlı bağımsız kontrolleri seçer. Worker çağrı yapar."""
        config = await safe_call(catalog.resolve, agent_id)
        if not key.strip() or len(key) > 200:
            raise ToolError("Görev anahtarı 1–200 karakter olmalıdır.")
        if connection_id is not None and connection_id not in config.connections:
            raise ToolError("Seçilen bağlantı tanımlı değil; list_agents içindeki bağlantılardan seçin.")
        plan = None
        job = None
        if programmatic is not None:
            try:
                job = ProgrammaticJob.model_validate(programmatic)
            except ValidationError:
                raise ToolError("Programatik iş tanımı geçersiz.") from None
        if verification is not None:
            try:
                plan = VerificationPlan.model_validate(verification)
            except ValidationError:
                raise ToolError("Doğrulama planı geçersiz; checks listesini ve alanları kontrol edin.") from None
        in_catalog = await safe_call(catalog.contains, agent_id)
        if plan is not None and plan.requires_workspace and not in_catalog:
            raise ToolError(
                "Dosya/komut doğrulaması bu MCP bağlantısında workspace olmadığı için kullanılamaz."
            )
        metadata = {"idempotency_key": key, "verification": plan, "title": title,
                    "description": description, "priority": priority,
                    "dependencies": tuple(depends_on or ()), "programmatic": job,
                    "enabled": enabled}
        if in_catalog:
            task = await safe_call(enqueue_agent_task, store, catalog.root, agent_id,
                                   prompt, connection_id, **metadata)
        else:
            task = await safe_call(store.enqueue, config, prompt, connection_id, **metadata)
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


def register_schedule_tools(server: MCPServer, store: TaskStore, *, allow_execute: bool):
    service = ScheduleService(store)

    @server.tool(annotations=READ_ONLY)
    async def list_schedules() -> dict[str, Any]:
        """Kayıtlı zamanlı görevleri ve sonraki tetiklemeyi göster."""
        records = await safe_call(service.list)
        return {"schedules": [record.model_dump(mode="json") for record in records]}

    if not allow_execute:
        return

    @server.tool(annotations=WRITE)
    async def create_schedule(template_task_id: str, timing: dict[str, Any]) -> dict[str, Any]:
        """Devre dışı görevden kalıcı takvim oluştur; gelecekte model/araç çalıştırabilir."""
        try:
            spec = ScheduleTiming.model_validate(timing)
        except ValidationError:
            raise ToolError("Takvim zamanı/saat dilimi geçersiz.") from None
        record = await safe_call(service.create, template_task_id, spec)
        return {"schedule": record.model_dump(mode="json")}

    @server.tool(annotations=WRITE)
    async def set_schedule_enabled(schedule_id: str, enabled: bool, revision: int) -> dict[str, Any]:
        """Takvimi revizyon denetimiyle aç/kapat; açmak ücretli çalışma doğurabilir."""
        record = await safe_call(service.set_enabled, schedule_id, enabled, revision)
        return {"schedule": record.model_dump(mode="json")}


def register_memory_tools(server: MCPServer, store: TaskStore, *, allow_write: bool):
    service = MemoryService(store)

    @server.tool(annotations=READ_ONLY)
    async def list_memory(agent_id: str) -> dict[str, Any]:
        """Ajanın kaynaklı/onaylı/aday proje kayıtlarını oku."""
        entries = await safe_call(service.list, agent_id)
        return {"memory": [entry.model_dump() for entry in entries]}

    if not allow_write:
        return

    @server.tool(annotations=WRITE)
    async def propose_memory(agent_id: str, body: str, source_run_id: str, keywords: list[str]) -> dict[str, Any]:
        """Doğrulanmış kaynaktan hafıza adayı öner; insan onayı vermez."""
        entry = await safe_call(service.propose, agent_id, body, source_run_id, tuple(keywords))
        return {"memory": entry.model_dump(), "requires_local_approval": entry.status == "proposed"}

    @server.tool(annotations=WRITE)
    async def revise_memory(entry_id: str, revision: int, body: str) -> dict[str, Any]:
        """Aday metni revizyonla değiştir; varsa eski onayı kaldır."""
        entry = await safe_call(service.revise, entry_id, revision, body)
        return {"memory": entry.model_dump(), "requires_local_approval": True}

    @server.tool(annotations=WRITE)
    async def archive_memory(entry_id: str, revision: int) -> dict[str, Any]:
        """Proje kaydını sonraki bağlamlardan çıkar; revizyon geçmişini koru."""
        entry = await safe_call(service.archive, entry_id, revision)
        return {"memory": entry.model_dump()}
