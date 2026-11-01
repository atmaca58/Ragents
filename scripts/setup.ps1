param([switch]$RunTests, [switch]$SkipConfigure, [string]$ProfileDirectory = "")

$ErrorActionPreference = "Stop"
$setupArguments = @((Join-Path $PSScriptRoot "setup.py"))
if ($ProfileDirectory) { $setupArguments += @("--profile-directory", $ProfileDirectory) }
if ($RunTests) { $setupArguments += "--run-tests" }
if ($SkipConfigure) { $setupArguments += "--skip-configure" }
& python @setupArguments
if ($LASTEXITCODE -ne 0) { throw "R Agents kurulumu tamamlanamadı." }
