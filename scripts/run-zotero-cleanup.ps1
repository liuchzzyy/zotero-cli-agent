[CmdletBinding()]
param(
    [string]$RulesPath = "",
    [string]$OutputDir = "",
    [int]$BatchSize = 50,
    [string]$Profile = "",
    [switch]$Apply,
    [switch]$Resume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

function Resolve-InRepoPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return $Path
    }
    return Join-Path $RepoRoot $Path
}

function New-RunOutputDir {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [string]$RequestedOutputDir
    )

    if ($RequestedOutputDir) {
        return Resolve-InRepoPath -RepoRoot $RepoRoot -Path $RequestedOutputDir
    }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    return Join-Path $RepoRoot ("logs\zotero-cleanup\{0}" -f $stamp)
}

function Write-RunMetadata {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RunOutputDir,
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$RulesPath
    )

    $metadata = [ordered]@{
        started_at = (Get-Date).ToString("o")
        repo_root = $RepoRoot
        rules_path = $RulesPath
        apply = [bool]$Apply
        resume = [bool]$Resume
        batch_size = [int]$BatchSize
        profile = $Profile
    }
    $metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $RunOutputDir "run-metadata.json") -Encoding UTF8
}

$repoRoot = Get-RepoRoot
if (-not $RulesPath) {
    $RulesPath = Join-Path $repoRoot "scripts\zotero-cleanup-rules.json"
}
else {
    $RulesPath = Resolve-InRepoPath -RepoRoot $repoRoot -Path $RulesPath
}

if (-not (Test-Path -LiteralPath $RulesPath)) {
    throw "Rules file not found: $RulesPath"
}

if ($BatchSize -lt 1 -or $BatchSize -gt 50) {
    throw "BatchSize must be between 1 and 50 because Zotero accepts at most 50 items per batch."
}

$runOutputDir = New-RunOutputDir -RepoRoot $repoRoot -RequestedOutputDir $OutputDir
New-Item -ItemType Directory -Force -Path $runOutputDir | Out-Null
$runOutputDir = (Resolve-Path -LiteralPath $runOutputDir).Path

Write-RunMetadata -RunOutputDir $runOutputDir -RepoRoot $repoRoot -RulesPath $RulesPath

$runLog = Join-Path $runOutputDir "run.out.log"
$commandFile = Join-Path $runOutputDir "run-command.txt"

$arguments = @(
    "run", "python", "-u", "scripts/zotero_cleanup.py",
    "--rules", $RulesPath,
    "--output-dir", $runOutputDir,
    "--batch-size", "$BatchSize"
)
if ($Apply) {
    $arguments += "--apply"
}
if ($Resume) {
    $arguments += "--resume"
}
if ($Profile) {
    $arguments += @("--profile", $Profile)
}

("uv " + ($arguments -join " ")) | Set-Content -LiteralPath $commandFile -Encoding UTF8
Write-Host ("Run output dir: {0}" -f $runOutputDir)
Write-Host ("Running: uv {0}" -f ($arguments -join " "))

Push-Location $repoRoot
try {
    & uv @arguments 2>&1 | Tee-Object -FilePath $runLog
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    throw "Zotero cleanup failed with exit code $exitCode. See: $runLog"
}

Write-Host ("Done. Logs and outputs: {0}" -f $runOutputDir)
