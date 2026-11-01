"""Kalıcı ajan kataloğu: profil dosyaları, yaşam döngüsü ve görev snapshot'ı."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Literal

from filelock import FileLock, Timeout
from pydantic import Field, ValidationError, model_validator
import yaml

from ragents.auth import auth_root
from ragents.config import (
    MAX_INSTRUCTION_CHARS, AgentSpec, Budget, BuiltinToolName, ConnectionSpec,
    ContextPolicy, MCPConnection, MCPGrant, ProjectConfig, Spec, ToolSelection,
)
from ragents.errors import InstructionError, WorkspaceError
from ragents.instructions import (
    PROFILE_FILE, PROJECT_FILE, RULES_FILE, SKILL_FILE, CompiledInstructions,
    InstructionPolicy, InstructionSnapshot, SkillId, compile_instructions,
    compile_texts, load_skill, read_text_file,
)
from ragents.storage import TaskSnapshot, TaskStateError, TaskStore
from ragents.programmatic import ProgrammaticJob
from ragents.profile_paths import protected_profile_paths
from ragents.verification import VerificationPlan
from ragents.workspace import (
    TaskPermissions, Workspace, WorkspaceGrant, resolve_agent_workspace,
)


AgentStatus = Literal["active", "disabled", "archived"]
AGENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
AGENT_FILE = "agent.yaml"


class AgentProfile(Spec):
    """Bir ajanın kalıcı, kendi kendine yeterli profili."""

    schema_version: Literal[3]
    id: str = Field(pattern=AGENT_ID_PATTERN.pattern)
    name: str = Field(min_length=1, max_length=100)
    status: AgentStatus = "active"
    connection: str = Field(min_length=1)
    connection_catalog: bool = False
    connections: dict[str, ConnectionSpec] = Field(min_length=1)
    mcp_servers: dict[str, MCPConnection] = Field(default_factory=dict)
    mcp_tools: tuple[MCPGrant, ...] = ()
    tool_selection: ToolSelection = Field(default_factory=ToolSelection)
    tools: tuple[BuiltinToolName, ...] = ()
    permissions: TaskPermissions = Field(default_factory=TaskPermissions)
    workspace: str | None = Field(default=None, min_length=1, max_length=1024)
    shared_workspace_id: str | None = Field(default=None, pattern=AGENT_ID_PATTERN.pattern)
    setup_request_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    skills: tuple[SkillId, ...] = Field(default=(), max_length=32)
    default_skills: tuple[SkillId, ...] = Field(default=(), max_length=32)
    budget: Budget = Field(default_factory=Budget)
    context: ContextPolicy = Field(default_factory=ContextPolicy)

    @model_validator(mode="after")
    def validate_references(self) -> "AgentProfile":
        if self.connection not in self.connections:
            raise ValueError("Ajanın bağlantısı connections içinde tanımlı olmalıdır.")
        names = [(grant.server, grant.name) for grant in self.mcp_tools]
        if len(set(names)) != len(names):
            raise ValueError("MCP araç izni tekrar edemez.")
        if any(grant.server not in self.mcp_servers for grant in self.mcp_tools):
            raise ValueError("MCP araç sunucusu mcp_servers içinde tanımlı olmalıdır.")
        if len(set(self.skills)) != len(self.skills):
            raise ValueError("Skill kataloğunda aynı kimlik tekrar edemez.")
        if len(set(self.default_skills)) != len(self.default_skills):
            raise ValueError("Varsayılan skill listesinde aynı kimlik tekrar edemez.")
        if any(skill not in self.skills for skill in self.default_skills):
            raise ValueError("Varsayılan skill izinli katalogda tanımlı olmalıdır.")
        return self


class InstructionDocument(Spec):
    name: str
    sha256: str
    chars: int


class AgentSummary(Spec):
    id: str
    name: str | None = None
    status: AgentStatus | None = None
    revision: str | None = None
    connection: str | None = None
    tools: tuple[str, ...] = ()
    workspace: str | None = None
    workspace_ready: bool = False
    valid: bool = True
    error: str | None = None


@dataclass(frozen=True)
class AgentRecord:
    directory: Path
    profile: AgentProfile
    instructions: str
    default_instruction: InstructionSnapshot
    raw_instructions: str
    raw_project: str | None
    raw_rules: str | None
    documents: tuple[InstructionDocument, ...]
    workspace: Path
    revision: str


def agents_root(root: Path) -> Path:
    return Path(root).expanduser().resolve() / "agents"


def workspace_protected_paths(root: Path) -> tuple[Path, ...]:
    return tuple(dict.fromkeys((*protected_profile_paths(root), *protected_profile_paths(auth_root()))))


def workspace_bindings(root: Path) -> dict[str, str]:
    path = root / "connections/workspaces.json"
    if not path.is_file():
        return {}
    from pydantic import TypeAdapter
    bindings = TypeAdapter(dict[str, str]).validate_json(path.read_bytes())
    if any(not AGENT_ID_PATTERN.fullmatch(identity) or not Path(value).is_absolute() for identity, value in bindings.items()):
        raise TaskStateError("Ortak workspace kataloğu geçersiz.")
    return bindings


def _workspace(root: Path, profile: AgentProfile, *, require_exists: bool = False) -> Path:
    resolved = resolve_agent_workspace(
        root, profile.id, profile.workspace,
        protected_paths=workspace_protected_paths(root),
        require_exists=require_exists,
    )
    if profile.shared_workspace_id:
        binding = workspace_bindings(root).get(profile.shared_workspace_id)
        if binding is None or Path(binding).resolve() != resolved:
            raise TaskStateError("Ortak workspace kayıtlı ve onaylı kökle eşleşmiyor.")
    return resolved


def _assert_workspace_isolated(root: Path, agent_id: str, workspace: Path, shared_workspace_id=None) -> None:
    agents = agents_root(root)
    if not agents.is_dir():
        return
    for entry in sorted(agents.iterdir(), key=lambda item: item.name):
        if entry.name == agent_id or not entry.is_dir() or entry.name.startswith((".", "_")):
            continue
        try:
            other_record = _load_agent(root, entry.name)
            other = other_record.workspace
        except (TaskStateError, InstructionError, WorkspaceError, OSError):
            continue
        if (workspace == other or workspace.is_relative_to(other)
                or other.is_relative_to(workspace)):
            if workspace == other and shared_workspace_id and other_record.profile.shared_workspace_id == shared_workspace_id:
                continue
            raise TaskStateError("Workspace başka ajanın çalışma alanıyla çakışamaz.")


def _catalog_lock(agents: Path) -> FileLock:
    return FileLock(str(agents / ".catalog.lock"), timeout=5)


def _lock_acquire(lock: FileLock) -> None:
    try:
        lock.acquire()
        if (Path(lock.lock_file).parent.parent / "locks/maintenance.flag").exists():
            lock.release()
            raise TaskStateError("Profil bakım modunda; ajan yapılandırması geçici olarak kapalı.")
    except Timeout:
        raise TaskStateError("Ajan kataloğu başka bir işlemde kullanılıyor; kısa süre sonra yeniden deneyin.") from None


def _is_link(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return path.is_symlink() or (checker is not None and checker())


def _ensure_inside(base: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        raise TaskStateError("Ajan profili katalog dizininin dışına çıkamaz.") from None


def _validation_message(error: ValidationError) -> str:
    item = error.errors()[0]
    location = ".".join(str(part) for part in item["loc"])
    return f"{location}: {item['msg']}" if location else item["msg"]


def _revision(profile: AgentProfile, documents: tuple[InstructionDocument, ...]) -> str:
    payload = {
        "profile": profile.model_dump(mode="json", exclude={"status"}),
        "documents": [[document.name, document.sha256] for document in documents],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def instruction_policy(profile: AgentProfile) -> InstructionPolicy:
    return InstructionPolicy(
        max_chars=profile.context.max_instruction_chars,
        allowed_skills=profile.skills,
        default_skills=profile.default_skills,
    )


def _document(name: str, text: str) -> InstructionDocument:
    return InstructionDocument(
        name=name, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), chars=len(text),
    )


def _profile_documents(
    directory: Path, profile: AgentProfile, instructions: str,
    project: str | None, rules: str | None,
) -> tuple[InstructionDocument, ...]:
    documents = [_document(PROFILE_FILE, instructions)]
    if project and project.strip():
        documents.append(_document(PROJECT_FILE, project))
    if rules and rules.strip():
        documents.append(_document(RULES_FILE, rules))
    for skill_id in profile.skills:
        skill = load_skill(directory, skill_id)
        documents.append(InstructionDocument(
            name=f"skills/{skill_id}/{SKILL_FILE}",
            sha256=skill.source_sha256, chars=skill.source_chars,
        ))
    return tuple(documents)


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _profile_yaml(profile: AgentProfile) -> str:
    return yaml.safe_dump(profile.model_dump(mode="json"), allow_unicode=True, sort_keys=False)


def _load_agent(root: Path, agent_id: str) -> AgentRecord:
    if not AGENT_ID_PATTERN.fullmatch(agent_id):
        raise TaskStateError("Geçersiz ajan kimliği; küçük harf, rakam ve tire kullanın.")
    agents = agents_root(root)
    directory = agents / agent_id
    if not agents.is_dir():
        raise TaskStateError("Ajan kataloğu bulunamadı; önce agents create ile ajan oluşturun.")
    if _is_link(directory):
        raise TaskStateError("Ajan dizini sembolik bağlantı olamaz.")
    if not directory.is_dir():
        raise TaskStateError(f"Ajan bulunamadı: {agent_id}")
    _ensure_inside(agents, directory)
    path = directory / AGENT_FILE
    if not path.is_file() or _is_link(path):
        raise TaskStateError(f"Ajan profilinde {AGENT_FILE} dosyası yok.")
    _ensure_inside(directory, path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        raise TaskStateError("Ajan profili okunamadı; YAML biçimini kontrol edin.") from None
    if not isinstance(data, dict):
        raise TaskStateError("Ajan profili bir YAML nesnesi olmalıdır.")
    try:
        profile = AgentProfile.model_validate(data)
    except ValidationError as error:
        raise TaskStateError("Ajan profili geçersiz: " + _validation_message(error)) from None
    if profile.id != agent_id:
        raise TaskStateError("Ajan kimliği ile profil dizini eşleşmiyor.")
    if profile.status == "active" and profile.setup_request_id and not (
            root / "approvals" / profile.setup_request_id / "operation.applied").is_file():
        raise TaskStateError("Ajan kurulumu tamamlanmadı; onaylanmış kurulumu yeniden uygulayın.")
    raw_instructions = read_text_file(
        directory, PROFILE_FILE, required=True, label="Ajan talimatı",
    )
    if raw_instructions is None:
        raise TaskStateError(f"Ajan profilinde {PROFILE_FILE} dosyası yok.")
    raw_project = read_text_file(
        directory, PROJECT_FILE, required=False, label="Proje bilgisi",
    )
    raw_rules = read_text_file(
        directory, RULES_FILE, required=False, label="Kalıcı kurallar",
    )
    policy = instruction_policy(profile)
    compiled = compile_instructions(directory, policy)
    documents = _profile_documents(directory, profile, raw_instructions, raw_project, raw_rules)
    workspace = _workspace(root, profile)
    return AgentRecord(
        directory=directory, profile=profile, instructions=compiled.text,
        default_instruction=compiled.snapshot, raw_instructions=raw_instructions,
        raw_project=raw_project, raw_rules=raw_rules, documents=documents,
        workspace=workspace, revision=_revision(profile, documents),
    )


def load_agent(root: Path, agent_id: str) -> AgentRecord:
    agents = agents_root(root)
    if not agents.is_dir():
        return _load_agent(root, agent_id)
    lock = _catalog_lock(agents)
    _lock_acquire(lock)
    try:
        return _load_agent(root, agent_id)
    finally:
        lock.release()


def list_agents(
    root: Path, *, include_archived: bool = False, status: AgentStatus | None = None,
) -> list[AgentSummary]:
    agents = agents_root(root)
    if not agents.is_dir():
        return []
    lock = _catalog_lock(agents)
    _lock_acquire(lock)
    try:
        summaries: list[AgentSummary] = []
        for entry in sorted(agents.iterdir(), key=lambda item: item.name):
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue
            try:
                record = _load_agent(root, entry.name)
            except (TaskStateError, InstructionError, WorkspaceError, OSError) as error:
                summaries.append(AgentSummary(id=entry.name, valid=False, error=str(error)))
                continue
            profile = record.profile
            if status is not None and profile.status != status:
                continue
            if status is None and not include_archived and profile.status == "archived":
                continue
            summaries.append(AgentSummary(
                id=profile.id, name=profile.name, status=profile.status,
                revision=record.revision, connection=profile.connection,
                tools=profile.tools, workspace=str(record.workspace),
                workspace_ready=record.workspace.is_dir(), valid=True,
            ))
        return summaries
    finally:
        lock.release()


def create_agent(
    root: Path, profile: AgentProfile, instructions: str, *,
    project: str | None = None, rules: str | None = None, workspace: str | None = None,
) -> AgentRecord:
    agents = agents_root(root)
    agents.mkdir(parents=True, exist_ok=True, mode=0o700)
    if workspace is not None:
        if profile.workspace is not None and profile.workspace != workspace:
            raise TaskStateError("Profil ile --workspace aynı anda farklı değerler veremez.")
        profile = profile.model_copy(update={"workspace": workspace})
    workspace_value = profile.workspace or f"workspaces/{profile.id}"
    workspace_path = resolve_agent_workspace(
        root, profile.id, workspace_value,
        protected_paths=workspace_protected_paths(root),
        require_exists=profile.workspace is not None,
    )
    profile = profile.model_copy(update={"workspace": workspace_value})
    _workspace(root, profile)
    compile_texts(instruction_policy(profile), instructions, project, rules, {})
    lock = _catalog_lock(agents)
    _lock_acquire(lock)
    try:
        directory = agents / profile.id
        if directory.exists():
            raise TaskStateError(f"Bu kimlikte bir ajan zaten var: {profile.id}")
        _assert_workspace_isolated(root, profile.id, workspace_path, profile.shared_workspace_id)
        workspace_created = not workspace_path.exists()
        if workspace_created:
            workspace_path.mkdir(parents=True, mode=0o700)
        try:
            directory.mkdir(mode=0o700)
        except BaseException:
            if workspace_created:
                shutil.rmtree(workspace_path, ignore_errors=True)
            raise
        try:
            _write_atomic(directory / AGENT_FILE, _profile_yaml(profile))
            _write_atomic(directory / PROFILE_FILE, instructions.strip() + "\n")
            if project and project.strip():
                _write_atomic(directory / PROJECT_FILE, project.strip() + "\n")
            if rules and rules.strip():
                _write_atomic(directory / RULES_FILE, rules.strip() + "\n")
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            if workspace_created:
                shutil.rmtree(workspace_path, ignore_errors=True)
            raise
        return _load_agent(root, profile.id)
    finally:
        lock.release()


def update_agent(
    root: Path, agent_id: str, *,
    name: str | None = None,
    connection: str | None = None,
    tools: tuple[str, ...] | None = None,
    add_tools: tuple[str, ...] = (),
    remove_tools: tuple[str, ...] = (),
    permissions: TaskPermissions | None = None,
    add_readable_paths: tuple[str, ...] = (),
    remove_readable_paths: tuple[str, ...] = (),
    add_writable_paths: tuple[str, ...] = (),
    remove_writable_paths: tuple[str, ...] = (),
    add_commands: tuple[str, ...] = (),
    remove_commands: tuple[str, ...] = (),
    allow_network: bool | None = None,
    allow_publish: bool | None = None,
    command_timeout_seconds: float | None = None,
    max_output_bytes: int | None = None,
    connection_spec: ConnectionSpec | None = None,
    instructions: str | None = None,
    project: str | None = None,
    update_project: bool = False,
    rules: str | None = None,
    update_rules: bool = False,
    add_skills: tuple[str, ...] = (),
    remove_skills: tuple[str, ...] = (),
    add_default_skills: tuple[str, ...] = (),
    remove_default_skills: tuple[str, ...] = (),
    clear_default_skills: bool = False,
    workspace: str | None = None,
    update_workspace: bool = False,
    use_default_workspace: bool = False,
    expected_revision: str | None = None,
) -> AgentRecord:
    agents = agents_root(root)
    if not agents.is_dir():
        raise TaskStateError("Ajan kataloğu bulunamadı; önce agents create ile ajan oluşturun.")
    lock = _catalog_lock(agents)
    _lock_acquire(lock)
    try:
        current = _load_agent(root, agent_id)
        if expected_revision is not None and current.revision != expected_revision:
            raise TaskStateError("Ajan profili bu sırada değişti; --if-revision değerini yenileyin.")
        data: dict[str, Any] = current.profile.model_dump(mode="json")
        if name is not None:
            data["name"] = name
        if connection is not None:
            data["connection"] = connection
        if connection_spec is not None:
            target = connection or current.profile.connection
            connections = {
                name: spec.model_dump(mode="json")
                for name, spec in current.profile.connections.items()
            }
            connections[target] = connection_spec.model_dump(mode="json")
            data["connections"] = connections
            if connection is not None:
                data["connection"] = target
        if tools is not None or add_tools or remove_tools:
            selected = list(tools if tools is not None else current.profile.tools)
            selected.extend(tool for tool in add_tools if tool not in selected)
            selected = [tool for tool in selected if tool not in set(remove_tools)]
            data["tools"] = selected
        permission_changed = any((
            permissions is not None, add_readable_paths, remove_readable_paths,
            add_writable_paths, remove_writable_paths, add_commands, remove_commands,
            allow_network is not None, allow_publish is not None,
            command_timeout_seconds is not None, max_output_bytes is not None,
        ))
        if permission_changed:
            source = permissions or current.profile.permissions
            permission_data = source.model_dump(mode="json")
            for key, additions, removals in (
                ("readable_paths", add_readable_paths, remove_readable_paths),
                ("writable_paths", add_writable_paths, remove_writable_paths),
                ("commands", add_commands, remove_commands),
            ):
                selected = list(permission_data[key])
                selected.extend(item for item in additions if item not in selected)
                selected = [item for item in selected if item not in set(removals)]
                permission_data[key] = selected
            if allow_network is not None:
                permission_data["allow_network"] = allow_network
            if allow_publish is not None:
                permission_data["allow_publish"] = allow_publish
            if command_timeout_seconds is not None:
                permission_data["command_timeout_seconds"] = command_timeout_seconds
            if max_output_bytes is not None:
                permission_data["max_output_bytes"] = max_output_bytes
            data["permissions"] = permission_data
        skills = list(current.profile.skills)
        skills.extend(skill for skill in add_skills if skill not in skills)
        skills = [skill for skill in skills if skill not in set(remove_skills)]
        data["skills"] = skills
        defaults = [] if clear_default_skills else list(current.profile.default_skills)
        defaults = [
            skill for skill in defaults
            if skill not in set(remove_skills) and skill not in set(remove_default_skills)
        ]
        defaults.extend(skill for skill in add_default_skills if skill not in defaults)
        data["default_skills"] = defaults
        new_workspace: Path | None = None
        workspace_created = False
        if update_workspace and use_default_workspace:
            raise TaskStateError("--workspace ve --default-workspace birlikte kullanılamaz.")
        if update_workspace or use_default_workspace:
            workspace_value = (
                f"workspaces/{agent_id}" if use_default_workspace else workspace
            )
            if not workspace_value:
                raise TaskStateError("Workspace yolu boş olamaz.")
            new_workspace = resolve_agent_workspace(
                root, agent_id, workspace_value,
                protected_paths=workspace_protected_paths(root),
                require_exists=not use_default_workspace,
            )
            _assert_workspace_isolated(root, agent_id, new_workspace, current.profile.shared_workspace_id)
            data["workspace"] = workspace_value
        try:
            profile = AgentProfile.model_validate(data)
            _workspace(root, profile)
        except ValidationError as error:
            raise TaskStateError("Ajan profili geçersiz: " + _validation_message(error)) from None
        skill_documents = {
            skill: load_skill(current.directory, skill) for skill in profile.skills
        }
        new_instructions = current.raw_instructions if instructions is None else instructions
        new_project = project if update_project else current.raw_project
        new_rules = rules if update_rules else current.raw_rules
        compile_texts(
            instruction_policy(profile), new_instructions, new_project,
            new_rules, skill_documents,
        )
        if use_default_workspace and new_workspace is not None and not new_workspace.exists():
            new_workspace.mkdir(parents=True, mode=0o700)
            workspace_created = True
        directory = current.directory
        try:
            if instructions is not None:
                _write_atomic(directory / PROFILE_FILE, instructions.strip() + "\n")
            if update_project:
                path = directory / PROJECT_FILE
                if new_project and new_project.strip():
                    _write_atomic(path, new_project.strip() + "\n")
                elif path.exists():
                    path.unlink()
            if update_rules:
                path = directory / RULES_FILE
                if new_rules and new_rules.strip():
                    _write_atomic(path, new_rules.strip() + "\n")
                elif path.exists():
                    path.unlink()
            if profile != current.profile:
                _write_atomic(directory / AGENT_FILE, _profile_yaml(profile))
        except BaseException:
            if workspace_created and new_workspace is not None:
                shutil.rmtree(new_workspace, ignore_errors=True)
            raise
        return _load_agent(root, agent_id)
    finally:
        lock.release()


def _write_status(current: AgentRecord, status: AgentStatus) -> AgentRecord:
    data: dict[str, Any] = current.profile.model_dump(mode="json")
    data["status"] = status
    try:
        profile = AgentProfile.model_validate(data)
    except ValidationError as error:
        raise TaskStateError("Ajan profili geçersiz: " + _validation_message(error)) from None
    _write_atomic(current.directory / AGENT_FILE, _profile_yaml(profile))
    return AgentRecord(
        directory=current.directory, profile=profile, instructions=current.instructions,
        default_instruction=current.default_instruction,
        raw_instructions=current.raw_instructions, raw_project=current.raw_project,
        raw_rules=current.raw_rules, documents=current.documents,
        workspace=current.workspace, revision=_revision(profile, current.documents),
    )


def set_status(root: Path, agent_id: str, status: AgentStatus) -> AgentRecord:
    agents = agents_root(root)
    if not agents.is_dir():
        raise TaskStateError("Ajan kataloğu bulunamadı; önce agents create ile ajan oluşturun.")
    lock = _catalog_lock(agents)
    _lock_acquire(lock)
    try:
        current = _load_agent(root, agent_id)
        if current.profile.status == status:
            return current
        return _write_status(current, status)
    finally:
        lock.release()


def transition_agent(
    root: Path, agent_id: str,
    action: Literal["disable", "enable", "archive", "restore"],
) -> AgentRecord:
    agents = agents_root(root)
    if not agents.is_dir():
        raise TaskStateError("Ajan kataloğu bulunamadı; önce agents create ile ajan oluşturun.")
    lock = _catalog_lock(agents)
    _lock_acquire(lock)
    try:
        current = _load_agent(root, agent_id)
        status = current.profile.status
        if action in ("disable", "enable") and status == "archived":
            raise TaskStateError("Arşivlenmiş ajanı önce restore edin.")
        if action == "restore" and status != "archived":
            raise TaskStateError("Yalnız arşivlenmiş ajan geri getirilebilir.")
        target: AgentStatus = {
            "disable": "disabled", "enable": "active",
            "archive": "archived", "restore": "disabled",
        }[action]
        if status == target:
            return current
        return _write_status(current, target)
    finally:
        lock.release()


def project_config(
    record: AgentRecord, compiled: CompiledInstructions | None = None,
) -> ProjectConfig:
    profile = record.profile
    connections = profile.connections
    if profile.connection_catalog:
        from ragents.connection_catalog import ConnectionCatalog
        connections = ConnectionCatalog(record.directory.parent.parent).read()
    instructions = compiled.text if compiled is not None else record.instructions
    if len(instructions) > MAX_INSTRUCTION_CHARS:
        raise TaskStateError(
            f"Ajan talimatı çok uzun: {len(instructions)} karakter; "
            f"en fazla {MAX_INSTRUCTION_CHARS} olabilir."
        )
    agent = AgentSpec(
        id=profile.id, name=profile.name, instructions=instructions,
        connection=profile.connection, tools=profile.tools, budget=profile.budget,
        context=profile.context, mcp_tools=profile.mcp_tools,
        tool_selection=profile.tool_selection,
    )
    try:
        return ProjectConfig(
            schema_version=2, connections=connections, agent=agent,
            mcp_servers=profile.mcp_servers,
        )
    except ValidationError as error:
        raise TaskStateError("Ajan profili geçersiz: " + _validation_message(error)) from None


def enqueue_agent_task(
    store: TaskStore, root: Path, agent_id: str, prompt: str,
    connection: str | None = None, *, skills: tuple[str, ...] = (),
    idempotency_key: str | None = None,
    writable_paths: tuple[str, ...] | None = None,
    commands: tuple[str, ...] | None = None,
    allow_network: bool | None = None,
    allow_publish: bool | None = None,
    verification: VerificationPlan | None = None,
    title: str | None = None,
    description: str = "",
    priority: int = 0,
    enabled: bool = True,
    dependencies: tuple[str, ...] = (),
    programmatic: ProgrammaticJob | None = None,
) -> TaskSnapshot:
    record = load_agent(root, agent_id)
    if record.profile.status != "active":
        label = {"disabled": "devre dışı", "archived": "arşivlenmiş"}.get(
            record.profile.status, record.profile.status,
        )
        raise TaskStateError(f"Ajan '{agent_id}' {label} durumunda; yeni görev alamaz.")
    from ragents.memory import MemoryService
    memories = MemoryService(store).select(agent_id, prompt)
    compiled = compile_instructions(record.directory, instruction_policy(record.profile), skills,
                                    prompt=prompt, memories=memories)
    permission_data = record.profile.permissions.model_dump(mode="json")
    if writable_paths is not None:
        permission_data["writable_paths"] = list(writable_paths)
    if commands is not None:
        permission_data["commands"] = list(commands)
    if allow_network is not None:
        permission_data["allow_network"] = allow_network
    if allow_publish is not None:
        permission_data["allow_publish"] = allow_publish
    try:
        permissions = TaskPermissions.model_validate(permission_data)
    except ValidationError as error:
        raise TaskStateError("Görev izinleri geçersiz: " + _validation_message(error)) from None
    grant = WorkspaceGrant(
        root=record.workspace,
        protected_paths=workspace_protected_paths(root),
        **permissions.model_dump(),
    )
    Workspace(
        grant.root, grant.protected_paths,
        readable_paths=grant.readable_paths, writable_paths=grant.writable_paths,
    )
    _assert_workspace_isolated(root, agent_id, record.workspace, record.profile.shared_workspace_id)
    return store.enqueue(
        project_config(record, compiled), prompt, connection,
        idempotency_key=idempotency_key, instruction=compiled.snapshot,
        workspace=grant, verification=verification,
        title=title, description=description, priority=priority,
        enabled=enabled, dependencies=dependencies,
        programmatic=programmatic,
    )


def agent_payload(record: AgentRecord) -> dict[str, Any]:
    profile = record.profile
    return {
        "id": profile.id,
        "name": profile.name,
        "status": profile.status,
        "revision": record.revision,
        "connection": profile.connection,
        "connections": sorted(profile.connections),
        "mcp_servers": sorted(profile.mcp_servers),
        "tools": list(profile.tools),
        "permissions": profile.permissions.model_dump(mode="json"),
        "workspace": str(record.workspace),
        "workspace_ready": record.workspace.is_dir(),
        "skills": list(profile.skills),
        "default_skills": list(profile.default_skills),
        "instructions": {
            "chars": len(record.instructions),
            "revision": record.default_instruction.revision,
            "documents": [document.model_dump() for document in record.documents],
            "sources": [source.model_dump() for source in record.default_instruction.sources],
        },
        "directory": str(record.directory),
    }
