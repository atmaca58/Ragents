import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell kurulum sözleşmesi")


def powershell(code):
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", code],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                          env={key: value for key, value in os.environ.items() if key.lower() != "psmodulepath"})


def helpers():
    script = Path("scripts/install.ps1").resolve()
    return f". '{script}' -FunctionsOnly; "


def test_online_installer_parses_as_downloaded_text_in_powershell_51():
    script = Path("scripts/install.ps1").resolve()
    code = ("$ErrorActionPreference='Stop'; "
            f"$text=[System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes('{script}')); "
            "& ([scriptblock]::Create($text)) -FunctionsOnly")
    result = powershell(code)
    assert result.returncode == 0, result.stderr


def test_online_installer_rejects_bad_hash_before_promoting_download(tmp_path):
    target = tmp_path / "download.zip"
    code = helpers() + (
        "function Invoke-WebRequest { param([switch]$UseBasicParsing, $Uri, $OutFile) "
        "[System.IO.File]::WriteAllText($OutFile, 'tampered') }; "
        f"try {{ Get-VerifiedDownload 'https://example.test/file' '{target}' '{'0' * 64}'; exit 5 }} "
        "catch { [Console]::Error.WriteLine($_.Exception.Message); if ($_.Exception.Message -match 'SHA-256') { exit 0 }; exit 6 }"
    )
    result = powershell(code)
    assert result.returncode == 0, result.stderr
    assert not target.exists()
    assert not target.with_suffix(".zip.partial").exists()


def test_online_installer_rejects_archive_traversal(tmp_path):
    archive, target = tmp_path / "bad.zip", tmp_path / "extracted"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "bad")
    code = helpers() + (f"try {{ Expand-VerifiedArchive '{archive}' '{target}'; exit 5 }} "
                        "catch { if ($_.Exception.Message -match 'dosya yolu') { exit 0 }; exit 6 }")
    result = powershell(code)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "escape.txt").exists()
    assert not target.exists()
