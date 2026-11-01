"""MCP'nin önerdiği, yalnız yerelde onaylanan sürümlü kurulum işlemleri."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Literal
import uuid
import os
import yaml

from filelock import FileLock
from pydantic import Field, model_validator

from ragents.catalog import AgentProfile, create_agent, _catalog_lock, _assert_workspace_isolated, workspace_bindings
from ragents.config import Budget, BuiltinToolName, ConnectionSpec, Spec
from ragents.storage import TaskStateError, TaskStore
from ragents.workspace import TaskPermissions, resolve_agent_workspace
from ragents.profile_paths import protected_profile_paths
from ragents.errors import WorkspaceError
from ragents.operation_hash import digest
from ragents.teams import TeamSpec


class ConnectionRef(Spec):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")


class ToolGrant(Spec):
    tools: tuple[BuiltinToolName, ...] = ()
    permissions: TaskPermissions = Field(default_factory=TaskPermissions)


class AgentDraft(Spec):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    instructions: str = Field(min_length=1, max_length=12000)
    connection: ConnectionRef
    workspace: str | None = None
    shared_workspace_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    grants: ToolGrant = Field(default_factory=ToolGrant)
    budget: Budget = Field(default_factory=Budget)


class SetupPlan(Spec):
    schema_version: Literal[1]
    connections: dict[str, ConnectionSpec] = Field(default_factory=dict, max_length=32)
    agents: tuple[AgentDraft, ...] = Field(default=(), max_length=20)
    teams: tuple[TeamSpec, ...] = Field(default=(), max_length=20)
    shared_workspaces: dict[str, str] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def unique_agents(self):
        if len({agent.id for agent in self.agents}) != len(self.agents):
            raise ValueError("Ajan kimlikleri tekrarlanamaz.")
        if not self.agents and not self.teams:
            raise ValueError("En az bir ajan veya ekip gereklidir.")
        if len({team.id for team in self.teams}) != len(self.teams):
            raise ValueError("Ekip kimlikleri tekrarlanamaz.")
        for identity in self.connections:
            ConnectionRef(id=identity)
        return self


class ApprovalRequest(Spec):
    schema_version: Literal[1] = 1
    id: str
    operation_hash: str
    profile_revision: str
    expires_at: str
    status: Literal["pending", "approved", "applying", "applied"]
    plan: SetupPlan
    result: dict | None = None
    affected_agents: tuple[str, ...] = ()


class SetupPlanService:
    def __init__(self, root: Path, store: TaskStore):
        self.root = root.resolve()
        self.store = store

    def revision(self) -> str:
        documents = {}
        for name in ("agents", "connections", "teams"):
            base = self.root / name
            if not base.exists():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_symlink() or path.is_junction():
                    raise TaskStateError("Profil bağlantılı dosya içeremez.")
                if path.is_file() and not path.name.startswith("."):
                    documents[path.relative_to(self.root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest(documents)

    def connections(self) -> dict[str, ConnectionSpec]:
        from ragents.connection_catalog import ConnectionCatalog
        return ConnectionCatalog(self.root).read()

    def propose(self, plan: SetupPlan) -> ApprovalRequest:
        normalized = []
        workspaces = []
        bindings = workspace_bindings(self.root) | plan.shared_workspaces
        for identity, value in plan.shared_workspaces.items():
            ConnectionRef(id=identity)
            resolved = resolve_agent_workspace(self.root, identity, value, protected_paths=protected_profile_paths(self.root), require_exists=True)
            if identity in workspace_bindings(self.root) and Path(workspace_bindings(self.root)[identity]).resolve() != resolved:
                raise TaskStateError("Mevcut ortak workspace kaydı bu taslakla değiştirilemez.")
            bindings[identity] = str(resolved)
        for agent in plan.agents:
            try:
                value = agent.workspace
                if agent.shared_workspace_id:
                    if agent.shared_workspace_id not in bindings:
                        raise TaskStateError("Ortak workspace taslakta veya katalogda bulunamadı.")
                    binding = bindings[agent.shared_workspace_id]
                    if value and Path(value).resolve() != Path(binding).resolve():
                        raise TaskStateError("Ortak workspace ile açık yol farklı.")
                    value = binding
                workspace = resolve_agent_workspace(self.root, agent.id, value,
                    protected_paths=protected_profile_paths(self.root), require_exists=value is not None)
                _assert_workspace_isolated(self.root, agent.id, workspace, agent.shared_workspace_id)
            except WorkspaceError as error:
                raise TaskStateError(str(error)) from None
            for other, shared_id in workspaces:
                if workspace == other and shared_id and shared_id == agent.shared_workspace_id:
                    continue
                if workspace == other or workspace.is_relative_to(other) or other.is_relative_to(workspace):
                    raise TaskStateError("Taslak workspace yolları çakışıyor.")
            workspaces.append((workspace, agent.shared_workspace_id))
            normalized.append(agent.model_copy(update={"workspace": str(workspace)}))
        plan = plan.model_copy(update={"agents": tuple(normalized), "shared_workspaces": {
            identity: bindings[identity] for identity in plan.shared_workspaces}})
        connections = self.connections() | plan.connections
        if any(agent.connection.id not in connections for agent in plan.agents):
            raise TaskStateError("Ajanın model bağlantısı katalogda bulunamadı.")
        if any((self.root / "agents" / agent.id).exists() for agent in plan.agents):
            raise TaskStateError("Bu ajan kimliği zaten kullanılıyor.")
        known_agents = {agent.id for agent in plan.agents}
        for team in plan.teams:
            if (self.root / "teams" / f"{team.id}.json").exists():
                raise TaskStateError("Ekip kimliği zaten kullanılıyor.")
            if any(step.agent_id not in known_agents and not (self.root / "agents" / step.agent_id).is_dir()
                   for step in team.steps):
                raise TaskStateError("Ekip üyesi katalogda veya taslakta yok.")
        from ragents.catalog import list_agents
        affected = tuple(agent.id for agent in list_agents(self.root, include_archived=True)
                         if agent.valid and agent.connection in plan.connections)
        request = ApprovalRequest(id=uuid.uuid4().hex, operation_hash=digest(plan.model_dump(mode="json")),
                                  profile_revision=self.revision(),
                                  expires_at=(datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                                  status="pending", plan=plan, affected_agents=affected)
        with self.store.connect() as db:
            db.execute("INSERT INTO setup_requests VALUES (?,?)", (request.id, request.model_dump_json()))
        return request

    def get(self, identity: str) -> ApprovalRequest:
        with self.store.connect() as db:
            row = db.execute("SELECT record_json FROM setup_requests WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise TaskStateError("Kurulum talebi bulunamadı.")
        return ApprovalRequest.model_validate_json(row[0])

    def _save(self, request: ApprovalRequest) -> None:
        with self.store.connect() as db:
            db.execute("UPDATE setup_requests SET record_json=? WHERE id=?", (request.model_dump_json(), request.id))

    def _check_current(self, request: ApprovalRequest) -> None:
        if datetime.fromisoformat(request.expires_at) <= datetime.now(timezone.utc):
            raise TaskStateError("Yerel onayın süresi doldu; yeni taslak oluşturun.")
        if self.revision() != request.profile_revision:
            raise TaskStateError("Profil değişti; yeni önizleme ve onay gerekiyor.")

    def approve_local(self, identity: str, operation_hash: str) -> ApprovalRequest:
        with FileLock(self.root / "data/setup.lock"):
            request = self.get(identity)
            if request.status != "pending" or request.operation_hash != operation_hash:
                raise TaskStateError("Görülen işlem ile onay eşleşmiyor.")
            self._check_current(request)
            request = request.model_copy(update={"status": "approved"})
            self._save(request)
            return request

    def apply(self, identity: str) -> dict:
        with FileLock(self.root / "data/setup.lock"):
            if (self.root / "locks/maintenance.flag").exists():
                raise TaskStateError("Profil bakım modunda; kurulum uygulaması geçici olarak kapalı.")
            request = self.get(identity)
            if request.status == "applied":
                self._mark_applied(request)
                return request.result
            if request.status not in ("approved", "applying"):
                raise TaskStateError("Önce yerel kullanıcı onayı gerekiyor.")
            if request.status == "approved":
                self._check_current(request)
                self._stage(request)
                request = request.model_copy(update={"status": "applying"})
                self._save(request)
            self._promote(request)
            result = {"agents": [agent.id for agent in request.plan.agents],
                      "teams": [team.id for team in request.plan.teams], "operation_hash": request.operation_hash}
            self._save(request.model_copy(update={"status": "applied", "result": result}))
            self._mark_applied(request)
            return result

    def _mark_applied(self, request):
        from ragents.auth import atomic_write
        atomic_write(self.root / "approvals" / request.id / "operation.applied", request.operation_hash.encode())

    def _stage(self, request: ApprovalRequest) -> None:
        stage = self.root / "approvals" / request.id
        connections = self.connections() | request.plan.connections
        connection_dir = stage / "connections"
        connection_dir.mkdir(parents=True, exist_ok=True)
        bindings = workspace_bindings(self.root) | request.plan.shared_workspaces
        (connection_dir / "workspaces.json").write_text(json.dumps(bindings), encoding="utf-8")
        for agent in request.plan.agents:
            profile = AgentProfile(schema_version=3, id=agent.id, name=agent.name,
                                   status="disabled", setup_request_id=request.id,
                                   connection_catalog=True,
                                   shared_workspace_id=agent.shared_workspace_id,
                                   connection=agent.connection.id, connections=connections,
                                   workspace=agent.workspace or str(self.root / "workspaces" / agent.id),
                                   tools=agent.grants.tools, permissions=agent.grants.permissions,
                                   budget=agent.budget)
            Path(profile.workspace).mkdir(parents=True, exist_ok=True)
            create_agent(stage, profile, agent.instructions)
        connection_dir = stage / "connections"
        connection_dir.mkdir(parents=True, exist_ok=True)
        (connection_dir / "catalog.json").write_text(json.dumps(
            {key: value.model_dump(mode="json") for key, value in connections.items()},
            ensure_ascii=False), encoding="utf-8")
        for team in request.plan.teams:
            directory = stage / "teams"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{team.id}.json").write_text(team.model_dump_json(), encoding="utf-8")
            (directory / f"{team.id}.approval").write_text(request.id, encoding="utf-8")

    def _promote(self, request: ApprovalRequest) -> None:
        stage = self.root / "approvals" / request.id
        agents = self.root / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        with _catalog_lock(agents):
            if (self.root / "locks/maintenance.flag").exists():
                raise TaskStateError("Profil bakım modunda; kurulum uygulaması geçici olarak kapalı.")
            for agent in request.plan.agents:
                source, target = stage / "agents" / agent.id, agents / agent.id
                if source.exists() and target.exists():
                    raise TaskStateError("Ajan kimliği uygulama sırasında değişti.")
                if source.exists():
                    os.replace(source, target)
            for agent in request.plan.agents:
                path = agents / agent.id / "agent.yaml"
                profile = AgentProfile.model_validate(yaml.safe_load(path.read_bytes()))
                if profile.setup_request_id != request.id:
                    raise TaskStateError("Uygulanan ajan başka bir kurulum talebine ait.")
                from ragents.catalog import _write_atomic, _profile_yaml
                _write_atomic(path, _profile_yaml(profile.model_copy(update={"status": "active"})))
            connection_dir = self.root / "connections"
            connection_dir.mkdir(parents=True, exist_ok=True)
            source = stage / "connections/catalog.json"
            if source.exists():
                os.replace(source, connection_dir / "catalog.json")
            source = stage / "connections/workspaces.json"
            if source.exists():
                os.replace(source, connection_dir / "workspaces.json")
            for team in request.plan.teams:
                directory = self.root / "teams"
                directory.mkdir(parents=True, exist_ok=True)
                gate = stage / "teams" / f"{team.id}.approval"
                if gate.exists():
                    os.replace(gate, directory / gate.name)
                source = stage / "teams" / f"{team.id}.json"
                target = directory / source.name
                if source.exists() and target.exists():
                    raise TaskStateError("Ekip kimliği uygulama sırasında değişti.")
                if source.exists():
                    os.replace(source, target)
