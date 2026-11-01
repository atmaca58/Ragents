"""Codex/OpenCode/Claude için terminalden geri alınabilir MCP kaydı."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from filelock import FileLock
import json5
import tomlkit

from ragents.auth import atomic_write
from ragents.profile_paths import profile_root
from ragents.storage import TaskStateError


CLIENTS = ("codex", "opencode", "claude", "claude-desktop", "chatgpt")


def mcp_command(root, *, read_only=False):
    python = Path(sys.executable).absolute()
    launcher = python.parents[3] / "ragents.exe" if len(python.parents) > 3 else None
    prefix = [str(launcher)] if launcher is not None and launcher.is_file() else [str(python), "-I", "-m", "ragents"]
    argv = [*prefix, "mcp", "serve", "--root", str(profile_root(root))]
    if not read_only:
        argv += ["--allow-manage", "--allow-write", "--allow-execute"]
    return argv


def client_config_path(client):
    home = Path.home()
    if client == "codex":
        return Path(os.environ.get("CODEX_HOME", str(home / ".codex"))) / "config.toml"
    if client == "claude":
        return home / ".claude.json"
    if client == "claude-desktop":
        return Path(os.environ.get("APPDATA", str(home / "AppData/Roaming"))) / "Claude/claude_desktop_config.json"
    if client == "opencode":
        explicit = os.environ.get("OPENCODE_CONFIG")
        if explicit:
            return Path(explicit)
        directory = home / ".config/opencode"
        candidates = [path for path in (directory / "opencode.json", directory / "opencode.jsonc") if path.exists()]
        if len(candidates) > 1:
            raise TaskStateError("Birden fazla OpenCode ayarı bulundu; --config ile hedefi seçin.")
        return candidates[0] if candidates else directory / "opencode.json"
    raise TaskStateError("Bu istemci için yerel ayar dosyası yok; HTTPS bağlantısı kullanın.")


def configure_client(client, root, *, config_path=None, read_only=False, replace=False, preview=False):
    if client not in CLIENTS or client == "chatgpt":
        raise TaskStateError("Yerel MCP istemcisi desteklenmiyor.")
    path = Path(config_path or client_config_path(client)).expanduser().absolute()
    if any(item.is_symlink() or item.is_junction() for item in (path, *path.parents)):
        raise TaskStateError("İstemci ayarı bağlantılı dosya olamaz.")
    argv = mcp_command(root, read_only=read_only)
    if client == "opencode":
        entry = {"type": "local", "command": argv, "enabled": True}
        key = "mcp"
    else:
        entry = {"command": argv[0], "args": argv[1:]}
        if client == "claude":
            entry["type"] = "stdio"
        key = "mcp_servers" if client == "codex" else "mcpServers"
    if preview:
        return {"client": client, "config": str(path), "entry": entry, "changed": False, "preview": True}
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(path.with_name(path.name + ".ragents.lock")):
        original = path.read_bytes() if path.exists() else None
        if original is not None and len(original) > 4 * 1024 * 1024:
            raise TaskStateError("İstemci ayarı güvenli düzenleme sınırını aşıyor.")
        try:
            config = (tomlkit.parse(original.decode("utf-8-sig")) if client == "codex" else
                      json5.loads(original.decode("utf-8-sig"))) if original else (tomlkit.document() if client == "codex" else {})
            servers = config.setdefault(key, {})
            existing = servers.get("r_agents")
        except (ValueError, TypeError, AttributeError):
            raise TaskStateError("İstemci ayarı okunamadı; dosyaya değişiklik yapılmadı.") from None
        if existing == entry:
            remember_client(root, client, path, entry)
            return {"client": client, "config": str(path), "changed": False, "registered": True}
        if existing is not None and not replace:
            raise TaskStateError("r_agents kaydı farklı; önizlemeyi inceleyip --replace ile yeniden deneyin.")
        servers["r_agents"] = entry
        content = tomlkit.dumps(config) if client == "codex" else json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False)
        if (path.read_bytes() if path.exists() else None) != original:
            raise TaskStateError("İstemci ayarı işlem sırasında değişti; yeniden önizleyin.")
        backup = None
        if original is not None:
            backup = path.with_name(path.name + ".ragents-backup-" + uuid.uuid4().hex)
            shutil.copy2(path, backup)
        atomic_write(path, content.encode("utf-8"))
        remember_client(root, client, path, entry)
        return {"client": client, "config": str(path), "backup": str(backup) if backup else None,
                "changed": True, "registered": True, "connection_verified": False,
                "next": "İstemciyi yeniden açın; istemcinin zorunlu MCP güven/bağlantı onayını tamamlayın."}


async def test_stdio_connection(root):
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client
    argv = mcp_command(root)
    with open(os.devnull, "w") as error_log:
        transport = stdio_client(StdioServerParameters(command=argv[0], args=argv[1:]), errlog=error_log)
        async with asyncio.timeout(30), Client(transport, mode="legacy", cache=None) as client:
            tools = await client.list_tools()
            capabilities = await client.call_tool("get_capabilities", {})
            if capabilities.is_error or "get_setup_schema" not in {tool.name for tool in tools.tools}:
                raise TaskStateError("MCP yetenek kontrolü geçmedi.")
            return {"mcp_verified": True, "tools": len(tools.tools), "model_requests": 0}


def add_connect_parser(commands):
    parser = commands.add_parser("connect", help="Codex, OpenCode, Claude veya ChatGPT'ye MCP bağlantısını hazırla")
    parser.add_argument("client", choices=CLIENTS)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--config", type=Path, help="İstemci ayarının açık hedef yolu")
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--show", action="store_true", help="Değişiklik yapmadan bağlantı kaydını göster")
    parser.add_argument("--test", action="store_true", help="Yerel stdio MCP el sıkışmasını model çağrısı olmadan doğrula")
    parser.add_argument("--public-url", help="ChatGPT web için kullanıcının HTTPS tünel kökü")


async def dispatch_connect(args):
    root = profile_root(args.root)
    if args.client == "chatgpt":
        if args.test:
            raise TaskStateError("ChatGPT kabulü gerçek istemcide OAuth bağlantısı gerektirir; --test yalnız yerel stdio içindir.")
        if args.config:
            raise TaskStateError("ChatGPT web için yerel --config kullanılmaz; --public-url seçin.")
        if not args.public_url:
            raise TaskStateError("ChatGPT web bağlantısı için --public-url HTTPS_TUNEL_KOKU gereklidir.")
        from ragents.remote_oauth import RemoteOAuthProvider
        provider = RemoteOAuthProvider(root, args.public_url)
        if not args.show:
            atomic_write(root / "connections/remote.json", json.dumps({"public_url": provider.issuer,
                "allow_manage": not args.read_only, "allow_write": not args.read_only,
                "allow_execute": not args.read_only}).encode())
        serve = ["ragents", "mcp", "serve", "--root", str(root), "--transport", "streamable-http",
                 "--public-url", provider.issuer]
        if not args.read_only:
            serve += ["--allow-manage", "--allow-write", "--allow-execute"]
        import shlex
        return {"client": "chatgpt", "mcp_url": provider.resource, "oauth_required": True, "connection_verified": False,
                "next": "ChatGPT'nin MCP/app bağlantı alanına bu URL'yi ekleyin. Bağlantı talebini ragents approvals connections ile inceleyip terminalden onaylayın.",
                "serve_argv": serve, "serve": subprocess.list2cmdline(serve) if os.name == "nt" else shlex.join(serve)}
    result = configure_client(args.client, root, config_path=args.config, read_only=args.read_only,
                              replace=args.replace, preview=args.show)
    if args.test:
        result["server_test"] = await test_stdio_connection(root)
    return result


def remember_client(root, client, path, entry):
    journal = profile_root(root) / "connections/client-registrations.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(journal) + ".lock"):
        records = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else []
        records = [item for item in records if item["path"] != str(path)]
        records.append({"client": client, "path": str(path), "entry": entry})
        atomic_write(journal, json.dumps(records, ensure_ascii=False).encode("utf-8"))
