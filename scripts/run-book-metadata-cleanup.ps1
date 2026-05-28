[CmdletBinding()]
param(
    [string]$OutputDir = "",
    [int]$BatchSize = 25,
    [int]$Limit = 0,
    [string]$Profile = "",
    [string]$AddTag = "workflow/metadata_cleaned",
    [string]$Providers = "open_library,library_of_congress",
    [string]$GoogleApiKey = "",
    [string]$GoogleOAuthClientSecret = "",
    [string]$GoogleOAuthTokenCache = "",
    [double]$TimeoutSeconds = 12.0,
    [double]$SleepSeconds = 0.4,
    [switch]$NoAddTag,
    [switch]$Apply,
    [switch]$Resume,
    [switch]$LocalNormalization
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
    return Join-Path $RepoRoot ("log\book-metadata-cleanup\{0}" -f $stamp)
}

function Write-RunMetadata {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RunOutputDir,
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $metadata = [ordered]@{
        started_at = (Get-Date).ToString("o")
        repo_root = $RepoRoot
        apply = [bool]$Apply
        resume = [bool]$Resume
        batch_size = [int]$BatchSize
        limit = [int]$Limit
        profile = $Profile
        add_tag = $AddTag
        providers = $Providers
        google_api_key_configured = [bool]$GoogleApiKey
        google_oauth_client_secret = $GoogleOAuthClientSecret
        google_oauth_token_cache = $GoogleOAuthTokenCache
        timeout_seconds = [double]$TimeoutSeconds
        sleep_seconds = [double]$SleepSeconds
        no_add_tag = [bool]$NoAddTag
        local_normalization = [bool]$LocalNormalization
    }
    $metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $RunOutputDir "run-metadata.json") -Encoding UTF8
}

if ($BatchSize -lt 1 -or $BatchSize -gt 50) {
    throw "BatchSize must be between 1 and 50 because Zotero API batch/update workflows should stay at or below 50."
}

$repoRoot = Get-RepoRoot
$runOutputDir = New-RunOutputDir -RepoRoot $repoRoot -RequestedOutputDir $OutputDir
New-Item -ItemType Directory -Force -Path $runOutputDir | Out-Null
$runOutputDir = (Resolve-Path -LiteralPath $runOutputDir).Path

Write-RunMetadata -RunOutputDir $runOutputDir -RepoRoot $repoRoot

$runLog = Join-Path $runOutputDir "run.out.log"
$commandFile = Join-Path $runOutputDir "run-command.txt"

$arguments = @(
    "run", "python", "-u", "scripts/book_metadata_cleanup.py",
    "--output-dir", $runOutputDir,
    "--batch-size", "$BatchSize",
    "--providers", $Providers,
    "--timeout", "$TimeoutSeconds",
    "--sleep-seconds", "$SleepSeconds"
)
if ($Limit -gt 0) {
    $arguments += @("--limit", "$Limit")
}
if ($Profile) {
    $arguments += @("--profile", $Profile)
}
if ($Apply) {
    $arguments += "--apply"
}
if ($Resume) {
    $arguments += "--resume"
}
if ($NoAddTag) {
    $arguments += "--no-add-tag"
}
elseif ($AddTag) {
    $arguments += @("--add-tag", $AddTag)
}
if ($GoogleApiKey) {
    $arguments += @("--google-api-key", $GoogleApiKey)
}
if ($GoogleOAuthClientSecret) {
    $arguments += @("--google-oauth-client-secret", $GoogleOAuthClientSecret)
}
if ($GoogleOAuthTokenCache) {
    $arguments += @("--google-oauth-token-cache", $GoogleOAuthTokenCache)
}
if ($LocalNormalization) {
    $arguments += "--local-normalization"
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
    throw "Book metadata cleanup failed with exit code $exitCode. See: $runLog"
}

Write-Host ("Done. Logs and outputs: {0}" -f $runOutputDir)
