param(
    [string]$ReviewDir = "current-state-review",
    [string]$OutputDir = "",
    [string]$Profile = "",
    [ValidateSet("all", "collections", "items", "verify")]
    [string]$Phase = "all",
    [int]$BatchSize = 25,
    [switch]$Apply,
    [switch]$HideProgressWatchCommands,
    [switch]$RunInCurrentWindow
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$commonScript = Join-Path $repoRoot "tools\zotero-workflow-common.ps1"
. $commonScript

if (-not $RunInCurrentWindow) {
    Start-WorkflowInNewWindow -ScriptPath $PSCommandPath -WorkingDirectory $repoRoot -BoundParameters $PSBoundParameters -DisplayName "Zotero Library Rebuild Apply"
    return
}

$logRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "log"))

function Resolve-ReviewRoot([string]$ReviewDirValue) {
    if ([System.IO.Path]::IsPathRooted($ReviewDirValue)) {
        return [System.IO.Path]::GetFullPath($ReviewDirValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $logRoot ("zotero-library-rebuild\{0}" -f $ReviewDirValue)))
}

function Write-ProgressWatchCommands([string]$ReviewRoot) {
    $resultsDir = Join-Path $reviewRoot "50_execution_results"
    Write-Host ""
    Write-Host "Optional progress checks from another PowerShell:" -ForegroundColor DarkGray
    Write-Host "  Primary progress is this window plus run.log/progress.jsonl; use these checks only for diagnosis." -ForegroundColor DarkGray
    Write-Host '  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match ''apply-zotero-library-rebuild|apply_rebuild'' } | Select-Object ProcessId,Name,CommandLine'
    Write-Host ("  if (Test-Path -LiteralPath '{0}') {{ Get-ChildItem -LiteralPath '{0}' -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName,Length,LastWriteTime }}" -f $resultsDir)
    Write-Host ("  if (Test-Path -LiteralPath '{0}') {{ Get-Content -Raw -LiteralPath '{0}' }}" -f (Join-Path $resultsDir "verification_summary.md"))
}

$reviewRoot = Resolve-ReviewRoot -ReviewDirValue $ReviewDir
$runLogDir = Join-Path $reviewRoot "50_execution_results"
Start-WorkflowRunLog -RunDirectory $runLogDir -WorkflowName "zotero-library-rebuild-apply" -RepoRoot $repoRoot

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
    if (-not $HideProgressWatchCommands) {
        Write-ProgressWatchCommands -ReviewRoot $reviewRoot
    }

    & uv @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "Apply script failed with exit code $LASTEXITCODE"
    }
    Complete-WorkflowRunLog -Status "completed"
}
catch {
    Write-Warning "Apply run failed. Inspect log\zotero-library-rebuild\current-state-review\50_execution_results."
    throw
}
finally {
    Pop-Location
}
