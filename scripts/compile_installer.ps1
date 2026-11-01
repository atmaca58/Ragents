param(
    [Parameter(Mandatory=$true)][string]$StageDirectory,
    [string]$ProductVersion = '0.2.0.dev5',
    [string]$ReleaseDirectory = 'dist'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$stage = (Resolve-Path -LiteralPath $StageDirectory).Path
$compiler = Join-Path $projectRoot '.installer-tools\inno\ISCC.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Inno derleyicisi bulunamadı.' }
New-Item -ItemType Directory -Path $ReleaseDirectory -Force | Out-Null
$release = (Resolve-Path -LiteralPath $ReleaseDirectory).Path
& $compiler '/Qp' ("/DStageDir=" + $stage) ("/DProductVersion=" + $ProductVersion) ("/DReleaseDir=" + $release) (Join-Path $projectRoot 'packaging\windows.iss')
if ($LASTEXITCODE -ne 0) { throw 'Windows kurucusu derlenemedi.' }
$installer = Join-Path $release ("R-Agents-" + $ProductVersion + '-windows-x64.exe')
$checksum = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText(($installer + '.sha256'), ($checksum + '  ' + [System.IO.Path]::GetFileName($installer) + "`n"), [System.Text.UTF8Encoding]::new($false))
Write-Output $installer
Write-Output ('SHA256 ' + $checksum)
