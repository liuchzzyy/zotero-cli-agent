param(
    [string]$ReviewDir = "current-state-review",
    [string]$OutputDir = "",
    [string]$Profile = "",
    [ValidateSet("all", "collections", "items", "verify")]
    [string]$Phase = "all",
    [int]$BatchSize = 25,
    [switch]$Apply,
    [switch]$HideProgressWatchCommands
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$logRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "log"))

function Write-ProgressWatchCommands([string]$ReviewDirValue) {
    $reviewRoot = if ([System.IO.Path]::IsPathRooted($ReviewDirValue)) {
        $ReviewDirValue
    }
    else {
        Join-Path $logRoot ("zotero-library-rebuild\{0}" -f $ReviewDirValue)
    }
    $resultsDir = Join-Path $reviewRoot "50_execution_results"
    Write-Host ""
    Write-Host "Progress watch from another PowerShell:" -ForegroundColor DarkGray
    Write-Host "  Keep this PowerShell visible; use these checks for live progress instead of waiting silently." -ForegroundColor DarkGray
    Write-Host '  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match ''apply-zotero-library-rebuild|apply_rebuild'' } | Select-Object ProcessId,Name,CommandLine'
    Write-Host ("  if (Test-Path -LiteralPath '{0}') {{ Get-ChildItem -LiteralPath '{0}' -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName,Length,LastWriteTime }}" -f $resultsDir)
    Write-Host ("  if (Test-Path -LiteralPath '{0}') {{ Get-Content -Raw -LiteralPath '{0}' }}" -f (Join-Path $resultsDir "verification_summary.md"))
}

Push-Location $repoRoot
try {
    $script = Join-Path $repoRoot "skill\zotero-library-rebuild\scripts\apply_rebuild.py"
    $argsList = @(
        "run", "python", $script,
        "--review-dir", $ReviewDir,
        "--phase", $Phase,
        "--batch-size", "$BatchSize"
    )

    if ($OutputDir -ne "") {
        $outputDirFull = [System.IO.Path]::GetFullPath($OutputDir)
        $separator = [System.IO.Path]::DirectorySeparatorChar.ToString()
        $isUnderLog = $outputDirFull.StartsWith($logRoot + $separator, [System.StringComparison]::OrdinalIgnoreCase)
        if (-not $isUnderLog) {
            throw "OutputDir must resolve under repository log directory: $logRoot"
        }
        $argsList += @("--output-dir", $outputDirFull)
    }
    if ($Profile -ne "") {
        $argsList += @("--profile", $Profile)
    }
    if ($Apply) {
        $argsList += "--apply"
        Write-Host "Applying Zotero rebuild through Zotero Web API..."
    }
    else {
        Write-Host "Dry-running Zotero rebuild apply script. No Zotero writes will be performed."
    }
    Write-Host "Run mode: direct PowerShell with visible output and progress checks"
    if (-not $HideProgressWatchCommands) {
        Write-ProgressWatchCommands -ReviewDirValue $ReviewDir
    }

    & uv @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "Apply script failed with exit code $LASTEXITCODE"
    }
}
catch {
    Write-Warning "Apply run failed. Inspect log\zotero-library-rebuild\current-state-review\50_execution_results."
    throw
}
finally {
    Pop-Location
}
