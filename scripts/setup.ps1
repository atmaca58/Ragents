param([switch]$RunTests, [switch]$SkipConfigure, [string]$ProfileDirectory = "local-profile")

$ErrorActionPreference = "Stop"
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    if (-not (Test-Path -LiteralPath ".venv/Scripts/python.exe")) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Python sanal ortamı oluşturulamadı." }
    }
    & ./.venv/Scripts/python.exe -m pip install -r requirements-dev.lock -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { throw "Bağımlılıklar kurulamadı." }
    & ./.venv/Scripts/python.exe -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Bağımlılıklar uyumsuz." }
    if ($RunTests) {
        & ./.venv/Scripts/python.exe -m pytest
        if ($LASTEXITCODE -ne 0) { throw "Testler başarısız." }
    }
    if (-not $SkipConfigure) {
        & ./.venv/Scripts/python.exe -m ragents setup --directory $ProfileDirectory
        if ($LASTEXITCODE -ne 0) { throw "Ajan kurulumu tamamlanamadı. Mevcut ayarlar korunur; doctor ile kontrol edebilirsiniz." }
        Write-Host "Profil hazır. Worker'ı profilinizdeki start-worker.ps1 ile başlatın; MCP ayarını istemcinize ekleyin."
    }
    else {
        Write-Host "Bağımlılıklar hazır. Ajan oluşturma: .\.venv\Scripts\ragents.exe setup"
    }
}
finally {
    Pop-Location
}
