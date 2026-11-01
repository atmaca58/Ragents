"""Ürün kaldırma; istemcilerin yalnız ürüne ait MCP kayıtlarına dokunur."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from filelock import FileLock
import json5
import tomlkit

from ragents.auth import atomic_write
from ragents.client_connections import CLIENTS, client_config_path
from ragents.profile_paths import profile_root
from ragents.storage import TaskStateError


def remove_client(path, client, installation, expected=None):
    path = Path(path)
    if not path.exists():
        return False
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise TaskStateError("Bağlantılı istemci ayarı düzenlenemez.")
    with FileLock(str(path) + ".ragents.lock"):
        original = path.read_bytes()
        if len(original) > 4 * 1024 * 1024:
            raise TaskStateError("İstemci ayarı boyut sınırını aşıyor.")
        config = tomlkit.parse(original.decode("utf-8-sig")) if client == "codex" else json5.loads(original.decode("utf-8-sig"))
        key = "mcp_servers" if client == "codex" else "mcp" if client == "opencode" else "mcpServers"
        servers = config.get(key, {})
        entry = servers.get("r_agents")
        if entry is None:
            return False
        command = entry.get("command", "")
        executable = command[0] if isinstance(command, list) and command else command
        owned = isinstance(executable, str) and Path(executable).is_absolute() and Path(executable).resolve().is_relative_to(installation.resolve())
        if not owned or (expected is not None and entry != expected):
            raise TaskStateError("MCP kaydı değiştirilmiş veya başka kuruluma ait; korunarak kaldırma durduruldu.")
        del servers["r_agents"]
        content = tomlkit.dumps(config) if client == "codex" else json.dumps(config, ensure_ascii=False, indent=2)
        if path.read_bytes() != original:
            raise TaskStateError("İstemci ayarı değişti; yeniden deneyin.")
        atomic_write(path, content.encode("utf-8"))
        return True


def installed_root():
    executable = Path(sys.executable).resolve()
    # <installation>/versions/<version>/python/python.exe
    if executable.parent.name != "python" or executable.parents[2].name != "versions":
        raise TaskStateError("Kaynaktan geliştirme kurulumu silinmez; uninstall yalnız paketlenmiş Windows kurulumu içindir.")
    root = executable.parents[3]
    if not (root / "ragents.exe").is_file():
        raise TaskStateError("Ürün kurulum kökü doğrulanamadı.")
    if any(p.is_symlink() or p.is_junction() for p in (root, *root.parents)):
        raise TaskStateError("Bağlantılı kurulum kökü kaldırılamaz.")
    return root


def uninstall(args):
    if sys.platform != "win32":
        raise TaskStateError("Paket kaldırma bu sürümde yalnız Windows içindir.")
    installation = installed_root()
    root = profile_root(args.root)
    if root.resolve().is_relative_to(installation.resolve()):
        raise TaskStateError("Profil kurulum dizininin içinde; veriyi korumak için kaldırma durduruldu.")
    from ragents.terminal_setup import ask
    if not args.yes and ask("Uygulama, hizmet ve MCP kayıtları kaldırılsın mı? Profil korunur. e/h", "h") != "e":
        return {"removed": False}
    from ragents.windows_service import scheduler_command
    from ragents.installation import _stop_profile
    _stop_profile(root)
    if scheduler_command(root, "status"):
        scheduler_command(root, "uninstall")
    journal = root / "connections/client-registrations.json"
    records = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else []
    known = {item["path"] for item in records}
    for client in CLIENTS:
        if client == "chatgpt":
            continue
        path = client_config_path(client)
        if str(path) not in known:
            records.append({"client": client, "path": str(path)})
    removed = []
    for item in records:
        if remove_client(item["path"], item["client"], installation, item.get("entry")):
            removed.append(item["client"])
    journal.unlink(missing_ok=True)
    # Yardımcı başka dizinde çalışır; Python kapandıktan sonra uygulamayı siler.
    script = r'''
param([string]$Target, [int]$ParentId)
$ErrorActionPreference = 'Stop'
Wait-Process -Id $ParentId -ErrorAction SilentlyContinue
$resolved = [IO.Path]::GetFullPath($Target)
if (-not (Test-Path -LiteralPath (Join-Path $resolved 'ragents.exe'))) { throw 'Kurulum doğrulanamadı.' }
Get-ChildItem -LiteralPath $resolved -Recurse -Force | ForEach-Object {
    if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Bağlantılı dosya bulundu.' }
}
if ((Get-Item -LiteralPath $resolved).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Bağlantılı kök.' }
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$clean = ($userPath -split ';' | Where-Object { $_.TrimEnd('\') -ine $resolved.TrimEnd('\') }) -join ';'
[Environment]::SetEnvironmentVariable('Path', $clean, 'User')
$done = $false
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    try { Remove-Item -LiteralPath $resolved -Recurse -Force; $done = $true; break }
    catch { Start-Sleep -Milliseconds 500 }
}
if (-not $done) { throw 'Uygulama dosyaları kullanımda; kaldırma tamamlanamadı.' }
Write-Host 'R Agents kaldırıldı. Kullanıcı profili korundu. Bu terminali kapatabilirsiniz.'
Remove-Item -LiteralPath $PSCommandPath -Force
'''
    handle, filename = tempfile.mkstemp(prefix="ragents-uninstall-", suffix=".ps1")
    with os.fdopen(handle, "w", encoding="utf-8-sig") as stream:
        stream.write(script)
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    subprocess.Popen([str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", filename,
                      "-Target", str(installation), "-ParentId", str(os.getpid())],
                     cwd=tempfile.gettempdir(), close_fds=True)
    return {"removal_scheduled": True, "mcp_removed": removed, "profile_preserved": str(root),
            "next": "Yardımcının kaldırma sonucunu bekleyin. ChatGPT web bağlantısını hesap ayarlarından ayrıca kaldırın; kendi tüneliniz silinmez."}
