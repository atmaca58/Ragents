import argparse
from pathlib import Path
from typing import get_args

from ragents.catalog import (
    AgentProfile, AgentStatus, agent_payload, create_agent, list_agents,
    load_agent, transition_agent, update_agent,
)
from ragents.config import BuiltinToolName, ConnectionSpec, load_config
from ragents.connections import DEFAULT_KEY_ENVS, ProviderName
from ragents.storage import TaskStateError
from ragents.workspace import TaskPermissions
from ragents.profile_paths import profile_root


DEFAULT_INSTRUCTIONS = "Türkçe, kısa ve açık yanıt ver. Bilmediğini belirt."
TOOL_NAMES = get_args(BuiltinToolName)
STATUS_NAMES = get_args(AgentStatus)


def _add_permission_arguments(parser: argparse.ArgumentParser, *, update: bool) -> None:
    parser.add_argument("--readable-path", action="append", default=[],
                        help="Görevin okuyabileceği göreli dizin; boşsa tüm workspace")
    parser.add_argument("--writable-path", action="append", default=[],
                        help="Görevin yazabileceği göreli dizin")
    parser.add_argument("--allowed-command", action="append", default=[],
                        help="İzinli çalıştırılabilir adı")
    if update:
        parser.add_argument("--remove-readable-path", action="append", default=[])
        parser.add_argument("--remove-writable-path", action="append", default=[])
        parser.add_argument("--remove-command", action="append", default=[])
        parser.add_argument("--allow-network", action=argparse.BooleanOptionalAction,
                            default=None, help="Sandbox komutlarına ağ izni ver/kaldır")
        parser.add_argument("--allow-publish", action=argparse.BooleanOptionalAction,
                            default=None, help="Push/yayın komutlarına izin ver/kaldır")
        parser.add_argument("--command-timeout", type=float, default=None)
        parser.add_argument("--max-command-output", type=int, default=None)
    else:
        parser.add_argument("--allow-network", action=argparse.BooleanOptionalAction,
                            default=False, help="Sandbox komutlarına ağ izni ver")
        parser.add_argument("--allow-publish", action=argparse.BooleanOptionalAction,
                            default=False, help="Push/yayın komutlarına izin ver")
        parser.add_argument("--command-timeout", type=float, default=60)
        parser.add_argument("--max-command-output", type=int, default=65_536)


def _permissions_from_args(args: argparse.Namespace) -> TaskPermissions:
    return TaskPermissions(
        readable_paths=tuple(args.readable_path),
        writable_paths=tuple(args.writable_path),
        commands=tuple(args.allowed_command),
        allow_network=args.allow_network,
        allow_publish=args.allow_publish,
        command_timeout_seconds=args.command_timeout,
        max_output_bytes=args.max_command_output,
    )


def add_agents_parser(commands) -> None:
    parser = commands.add_parser("agents", help="Kalıcı ajan kataloğu ve yaşam döngüsü")
    parser.add_argument("--root", type=Path, default=None,
                        help="Ajan profillerinin kök dizini")
    actions = parser.add_subparsers(dest="agent_action", required=True)

    create = actions.add_parser("create", help="Yeni kalıcı ajan profili oluştur")
    create.add_argument("--id", help="Sabit ajan kimliği")
    create.add_argument("--name", help="Görünen ad")
    create.add_argument("--from-config", type=Path,
                        help="Mevcut ragents.yaml bağlantı/talimatlarını içe aktar")
    create.add_argument("--connection", help="Varsayılan bağlantı adı")
    create.add_argument("--provider", choices=get_args(ProviderName))
    create.add_argument("--model")
    create.add_argument("--api-key-env", help="Anahtarın ortam değişkeni adı (değeri değil)")
    create.add_argument("--base-url", help="Ollama gibi uyumlu API adresi")
    create.add_argument("--oauth-account")
    create.add_argument("--tool", action="append", choices=TOOL_NAMES, default=[],
                        help="İzin verilen yerleşik araç; birden çok kez kullanılabilir")
    _add_permission_arguments(create, update=False)
    create.add_argument("--workspace", help="Mevcut çalışma alanı dizini; verilmezse varsayılan oluşturulur")
    text = create.add_mutually_exclusive_group()
    text.add_argument("--instructions", help="Başlangıç talimat metni")
    text.add_argument("--instructions-file", type=Path)
    project = create.add_mutually_exclusive_group()
    project.add_argument("--project", help="Proje bilgisi metni")
    project.add_argument("--project-file", type=Path)
    rules = create.add_mutually_exclusive_group()
    rules.add_argument("--rules", help="Kalıcı kural metni")
    rules.add_argument("--rules-file", type=Path)

    listing = actions.add_parser("list", help="Ajanları listele")
    listing.add_argument("--all", action="store_true", help="Arşivlenenleri de göster")
    listing.add_argument("--status", choices=STATUS_NAMES)

    show = actions.add_parser("show", help="Ajan profilini ve revizyonunu göster")
    show.add_argument("agent_id")

    update = actions.add_parser("update", help="Ajan profilini güncelle")
    update.add_argument("agent_id")
    update.add_argument("--name")
    update.add_argument("--connection")
    update.add_argument("--provider", choices=get_args(ProviderName))
    update.add_argument("--model")
    update.add_argument("--api-key-env", help="Anahtarın ortam değişkeni adı (değeri değil)")
    update.add_argument("--base-url")
    update.add_argument("--oauth-account")
    update.add_argument("--add-tool", action="append", choices=TOOL_NAMES, default=[])
    update.add_argument("--remove-tool", action="append", choices=TOOL_NAMES, default=[])
    _add_permission_arguments(update, update=True)
    update.add_argument("--add-skill", action="append", default=[],
                        help="İzinli skill kataloğuna ekle; SKILL.md önceden oluşturulmalı")
    update.add_argument("--remove-skill", action="append", default=[])
    update.add_argument("--add-default-skill", action="append", default=[],
                        help="Görev seçim yapmazsa yüklenecek skill")
    update.add_argument("--remove-default-skill", action="append", default=[])
    update.add_argument("--clear-default-skills", action="store_true")
    workspace = update.add_mutually_exclusive_group()
    workspace.add_argument("--workspace", help="Mevcut çalışma alanı dizini")
    workspace.add_argument("--default-workspace", action="store_true",
                           help="Varsayılan workspaces/<ajan-id> dizinini kullan")
    text = update.add_mutually_exclusive_group()
    text.add_argument("--instructions")
    text.add_argument("--instructions-file", type=Path)
    project = update.add_mutually_exclusive_group()
    project.add_argument("--project", help="Boş metin proje bilgisini kaldırır")
    project.add_argument("--project-file", type=Path)
    rules = update.add_mutually_exclusive_group()
    rules.add_argument("--rules", help="Boş metin kuralları kaldırır")
    rules.add_argument("--rules-file", type=Path)
    update.add_argument("--if-revision", help="Yalnız bu revizyonla eşleşirse güncelle")

    for name, help_text in (
        ("disable", "Ajanı yeni görevlere kapat"),
        ("enable", "Devre dışı ajanı yeniden aç"),
        ("archive", "Ajanı arşivle; görev geçmişini silme"),
        ("restore", "Arşivlenen ajanı devre dışı olarak geri getir"),
    ):
        action = actions.add_parser(name, help=help_text)
        action.add_argument("agent_id")


def _read_text(value: str | None, path: Path | None, label: str) -> str | None:
    if path is None:
        return value
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise TaskStateError(f"{label} dosyası UTF-8 metin olmalıdır.") from None
    except OSError:
        raise TaskStateError(f"{label} dosyası okunamadı: {path}") from None


def _create_profile(args: argparse.Namespace) -> tuple[AgentProfile, str, str | None]:
    instructions = _read_text(args.instructions, args.instructions_file, "Talimat")
    rules = _read_text(args.rules, args.rules_file, "Kural")
    provider_flags = (args.provider, args.model, args.api_key_env, args.base_url, args.oauth_account)
    if args.from_config is not None:
        if any(value is not None for value in provider_flags):
            raise TaskStateError(
                "--from-config ile --provider/--model/--api-key-env/--base-url/--oauth-account birlikte kullanılamaz."
            )
        config = load_config(args.from_config)
        agent_id = args.id or config.agent.id
        name = args.name or config.agent.name
        connection = args.connection or config.agent.connection
        if connection not in config.connections:
            raise TaskStateError("Seçilen bağlantı içe aktarılan ayarda tanımlı değil.")
        tools = tuple(args.tool) if args.tool else config.agent.tools
        profile = AgentProfile(
            schema_version=3, id=agent_id, name=name, connection=connection,
            connections=config.connections, mcp_servers=config.mcp_servers,
            mcp_tools=config.agent.mcp_tools, tool_selection=config.agent.tool_selection,
            tools=tools, permissions=_permissions_from_args(args),
            budget=config.agent.budget, context=config.agent.context,
        )
        return profile, instructions if instructions is not None else config.agent.instructions, rules

    missing = [flag for flag, value in (
        ("--id", args.id), ("--name", args.name), ("--provider", args.provider), ("--model", args.model),
    ) if value is None]
    if missing:
        raise TaskStateError("Yeni ajan için zorunlu alanlar eksik: " + ", ".join(missing))
    connection_name = args.connection or "primary"
    connection = ConnectionSpec(
        provider=args.provider, model=args.model,
        api_key_env=args.api_key_env or DEFAULT_KEY_ENVS.get(args.provider),
        base_url=args.base_url, oauth_account=args.oauth_account,
    )
    profile = AgentProfile(
        schema_version=3, id=args.id, name=args.name, connection=connection_name,
        connections={connection_name: connection}, tools=tuple(args.tool),
        permissions=_permissions_from_args(args),
    )
    return profile, instructions if instructions is not None else DEFAULT_INSTRUCTIONS, rules


def dispatch_agents(args: argparse.Namespace) -> dict:
    args.root = profile_root(args.root)
    root = args.root
    if args.agent_action == "create":
        profile, instructions, rules = _create_profile(args)
        project = _read_text(args.project, args.project_file, "Proje bilgisi")
        record = create_agent(
            root, profile, instructions, project=project, rules=rules,
            workspace=args.workspace,
        )
        return {"agent": agent_payload(record), "directory": str(record.directory)}
    if args.agent_action == "list":
        summaries = list_agents(root, include_archived=args.all, status=args.status)
        return {"root": str(root), "agents": [summary.model_dump() for summary in summaries]}
    if args.agent_action == "show":
        return {"agent": agent_payload(load_agent(root, args.agent_id))}
    if args.agent_action == "update":
        instructions = _read_text(args.instructions, args.instructions_file, "Talimat")
        project = _read_text(args.project, args.project_file, "Proje bilgisi")
        update_project = args.project is not None or args.project_file is not None
        update_rules = args.rules is not None or args.rules_file is not None
        rules = _read_text(args.rules, args.rules_file, "Kural")
        connection_spec = None
        connection_flags = (args.provider, args.model, args.api_key_env, args.base_url, args.oauth_account)
        if any(value is not None for value in connection_flags):
            if args.provider is None or args.model is None:
                raise TaskStateError("Bağlantı güncellemek için --provider ve --model birlikte gerekir.")
            connection_spec = ConnectionSpec(
                provider=args.provider, model=args.model,
                api_key_env=args.api_key_env or DEFAULT_KEY_ENVS.get(args.provider),
                base_url=args.base_url, oauth_account=args.oauth_account,
            )
        record = update_agent(
            root, args.agent_id, name=args.name, connection=args.connection,
            add_tools=tuple(args.add_tool), remove_tools=tuple(args.remove_tool),
            add_readable_paths=tuple(args.readable_path),
            remove_readable_paths=tuple(args.remove_readable_path),
            add_writable_paths=tuple(args.writable_path),
            remove_writable_paths=tuple(args.remove_writable_path),
            add_commands=tuple(args.allowed_command), remove_commands=tuple(args.remove_command),
            allow_network=args.allow_network, allow_publish=args.allow_publish,
            command_timeout_seconds=args.command_timeout,
            max_output_bytes=args.max_command_output,
            connection_spec=connection_spec, instructions=instructions,
            project=project, update_project=update_project, rules=rules,
            update_rules=update_rules, add_skills=tuple(args.add_skill),
            remove_skills=tuple(args.remove_skill),
            add_default_skills=tuple(args.add_default_skill),
            remove_default_skills=tuple(args.remove_default_skill),
            clear_default_skills=args.clear_default_skills,
            workspace=args.workspace,
            update_workspace=args.workspace is not None,
            use_default_workspace=args.default_workspace,
            expected_revision=args.if_revision,
        )
        return {"agent": agent_payload(record)}
    if args.agent_action in ("disable", "enable", "archive", "restore"):
        return {"agent": agent_payload(transition_agent(root, args.agent_id, args.agent_action))}
    raise TaskStateError("Bilinmeyen ajan işlemi.")


__all__ = ["add_agents_parser", "dispatch_agents", "TOOL_NAMES", "STATUS_NAMES"]

