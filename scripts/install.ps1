param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\RAgents'),
    [string]$ProfileRoot = $(if ($env:RAGENTS_HOME) { $env:RAGENTS_HOME } else { Join-Path $env:LOCALAPPDATA 'RAgents\profiles\default' }),
    [switch]$SkipConfigure,
    [switch]$NoPath,
    [string]$AssetDirectory,
    [switch]$FunctionsOnly
)

$ErrorActionPreference = 'Stop'
$ReleaseTag = 'v0.2.0-dev.20261102.1'
$ReleaseBase = "https://github.com/atmaca58/Ragents/releases/download/$ReleaseTag"
$ManifestHash = 'e2b2b938fffcec5864e0083cc1d32aaa88e1f5dd328fc982e7a6bbace6866785'

function Assert-PlainPath([string]$Path) {
    $item = [System.IO.DirectoryInfo]::new([System.IO.Path]::GetFullPath($Path))
    while ($null -ne $item) {
        if ($item.Exists -and ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            throw 'Kurulum hedefi bağlantılı dizin içeremez.'
        }
        $item = $item.Parent
    }
}

function Get-VerifiedDownload([string]$Url, [string]$Destination, [string]$Sha256) {
    if ($Sha256 -notmatch '^[0-9a-f]{64}$' -or -not $Url.StartsWith('https://')) {
        throw 'İndirme tanımı geçersiz.'
    }
    $partial = $Destination + '.partial'
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $partial
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Sha256) {
        Remove-Item -LiteralPath $partial -Force
        throw 'İndirilen dosyanın SHA-256 doğrulaması başarısız; kurulum durdu.'
    }
    Move-Item -LiteralPath $partial -Destination $Destination
}

function Expand-VerifiedArchive([string]$Archive, [string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $root = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\') + '\'
    $zip = [System.IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($entry in $zip.Entries) {
            $target = [System.IO.Path]::GetFullPath((Join-Path $root $entry.FullName))
            if (-not $target.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase) -or
                (($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000 -or
                $entry.FullName -match '(^|[/\\])\.\.([/\\]|$)|:') {
                throw 'Arşiv güvenli olmayan dosya yolu veya bağlantı içeriyor.'
            }
        }
    } finally { $zip.Dispose() }
    Expand-Archive -LiteralPath $Archive -DestinationPath $Destination
}

function Invoke-CheckedPython([string]$Python, [string[]]$Arguments) {
    & $Python '-I' '-B' '-X' 'utf8' @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'R Agents kurulum adımı başarısız; mevcut profil korunuyor.' }
}

function Get-ReleaseAsset($Asset, [string]$Downloads) {
    if ($Asset.name -notmatch '^[a-zA-Z0-9_.-]+$') { throw 'Paket dosya adı geçersiz.' }
    $destination = Join-Path $Downloads $Asset.name
    if ($AssetDirectory) {
        Copy-Item -LiteralPath (Join-Path $AssetDirectory $Asset.name) -Destination $destination
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Asset.sha256) {
            throw 'Yerel geliştirme paketinin hash doğrulaması başarısız.'
        }
    } else {
        Get-VerifiedDownload "$ReleaseBase/$($Asset.name)" $destination $Asset.sha256
    }
    return $destination
}

if ($FunctionsOnly) { return }
if ([Environment]::OSVersion.Version.Build -lt 22000 -or
    [Environment]::GetEnvironmentVariable('PROCESSOR_ARCHITECTURE') -ne 'AMD64') {
    throw 'Bu kurulum Windows 11 x64 ve 64-bit PowerShell gerektirir.'
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$ProfileRoot = [System.IO.Path]::GetFullPath($ProfileRoot)
Assert-PlainPath $InstallRoot
Assert-PlainPath $ProfileRoot
$downloads = Join-Path ([System.IO.Path]::GetTempPath()) ('RAgents-install-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $downloads | Out-Null
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
$lock = [System.IO.File]::Open((Join-Path $InstallRoot '.bootstrap.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    Write-Host 'R Agents geliştirme sürümü kuruluyor. Gerçek hesap/istemci kabulü henüz tamamlanmadı.'
    $manifestFile = Get-ReleaseAsset ([pscustomobject]@{name='install-manifest.json';sha256=$ManifestHash}) $downloads
    $manifest = Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or $manifest.release_tag -ne $ReleaseTag -or
        $manifest.version -notmatch '^[0-9][a-zA-Z0-9.\-]{0,63}$') { throw 'Kurulum manifesti desteklenmiyor.' }
    $version = Join-Path $InstallRoot ('versions\' + $manifest.version)
    $python = Join-Path $version 'python\python.exe'
    if (Test-Path -LiteralPath $version) {
        if (-not (Test-Path -LiteralPath (Join-Path $version 'package-manifest.json'))) {
            throw "Önceki yarım kurulum var: $version. Bu dizini inceleyip başka ada taşıdıktan sonra yeniden deneyin."
        }
        Invoke-CheckedPython $python @('-c', 'from pathlib import Path; from ragents.distribution import verify_package; import sys; verify_package(Path(sys.argv[1]))', $version)
    } else {
        New-Item -ItemType Directory -Path $version | Out-Null
        Write-Host 'Sabit Python ve Git resmi kaynaklarından indiriliyor...'
        $pythonZip = Join-Path $downloads 'python.zip'
        Get-VerifiedDownload $manifest.python.url $pythonZip $manifest.python.sha256
        Expand-VerifiedArchive $pythonZip (Join-Path $version 'python')
        $gitZip = Join-Path $downloads 'git.zip'
        Get-VerifiedDownload $manifest.git.url $gitZip $manifest.git.sha256
        Expand-VerifiedArchive $gitZip (Join-Path $version 'git')
        Get-VerifiedDownload $manifest.pip.url (Join-Path $version 'python\pip.whl') $manifest.pip.sha256
        [System.IO.File]::WriteAllText((Join-Path $version 'python\python314._pth'), "python314.zip`n.`npip.whl`nLib/site-packages`nimport site`n")
        $wheel = Get-ReleaseAsset $manifest.wheel $downloads
        $constraints = Get-ReleaseAsset $manifest.constraints $downloads
        Write-Host 'Sabit bağımlılıklar ve uygulama kuruluyor...'
        Invoke-CheckedPython $python @('-m', 'pip', '--isolated', 'install', '--disable-pip-version-check',
            '--index-url', 'https://pypi.org/simple', '--only-binary=:all:', '--no-compile',
            '--constraint', $constraints, '--target', (Join-Path $version 'python\Lib\site-packages'), $wheel)
        $priorBrowserPath = $env:PLAYWRIGHT_BROWSERS_PATH
        try {
            $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $version 'browsers'
            Invoke-CheckedPython $python @('-m', 'playwright', 'install', 'chromium', '--only-shell')
        } finally { $env:PLAYWRIGHT_BROWSERS_PATH = $priorBrowserPath }
        Invoke-CheckedPython $python @('-c', 'from pathlib import Path; from ragents.distribution import write_package_manifest; import sys; write_package_manifest(Path(sys.argv[1]), sys.argv[2])', $version, $manifest.version)
    }
    Invoke-CheckedPython $python @('-m', 'ragents', 'installation', 'activate', '--root', $ProfileRoot,
        '--installation-root', $InstallRoot, '--version', $manifest.version)
    $launchers = Get-ReleaseAsset $manifest.launchers $downloads
    $launcherDirectory = Join-Path $downloads 'launchers'
    Expand-VerifiedArchive $launchers $launcherDirectory
    foreach ($name in @('ragents.exe', 'R-Agents.exe')) {
        $target = Join-Path $InstallRoot $name
        if (-not (Test-Path -LiteralPath $target)) { Copy-Item -LiteralPath (Join-Path $launcherDirectory $name) -Destination $target }
    }
    if (-not $NoPath) {
        $userPath = [string][Environment]::GetEnvironmentVariable('Path', 'User')
        if (@($userPath -split ';') -notcontains $InstallRoot) {
            [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $InstallRoot).TrimStart(';'), 'User')
        }
        if (@($env:Path -split ';') -notcontains $InstallRoot) { $env:Path += ';' + $InstallRoot }
    }
    Write-Host "Kurulum tamamlandı: $InstallRoot"
    if (-not $SkipConfigure -and -not (Test-Path -LiteralPath (Join-Path $ProfileRoot 'connections\catalog.json'))) {
        & (Join-Path $InstallRoot 'ragents.exe') init --root $ProfileRoot
        if ($LASTEXITCODE -ne 0) { throw 'Uygulama kuruldu; model ayarını daha sonra ragents init ile tamamlayın.' }
    }
    Write-Host 'MCP bağlantısı: ragents connect codex | ragents connect opencode | ragents connect claude'
} finally {
    $lock.Dispose()
    $cleanup = [System.IO.Path]::GetFullPath($downloads)
    $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if ($cleanup.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
        [System.IO.Path]::GetFileName($cleanup) -match '^RAgents-install-[a-f0-9]{32}$') {
        Remove-Item -LiteralPath $cleanup -Recurse -Force
    }
}
