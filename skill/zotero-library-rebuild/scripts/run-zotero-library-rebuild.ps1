param(
    [string]$OutputDir = "",
    [string]$Profile = "",
    [int]$LibraryId = 1,
    [string]$DataDir = "",
    [int]$Limit = 0,
    [int]$TitleSampleSize = 200,
    [string]$ArchiveDate = "",
    [switch]$KeepOutput,
    [switch]$HideProgressWatchCommands
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$logRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "log"))
$runRoot = Join-Path $logRoot "zotero-library-rebuild"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

if ($OutputDir -eq "") {
    $outputDirCandidate = Join-Path $runRoot "dry-run-$timestamp"
}
elseif ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $outputDirCandidate = $OutputDir
}
elseif ($OutputDir -like "log\*" -or $OutputDir -like "log/*") {
    $outputDirCandidate = Join-Path $repoRoot $OutputDir
}
else {
    $outputDirCandidate = Join-Path $runRoot $OutputDir
}

$outputDirFull = [System.IO.Path]::GetFullPath($outputDirCandidate)
$separator = [System.IO.Path]::DirectorySeparatorChar.ToString()
$isUnderLog = $outputDirFull.Equals($logRoot, [System.StringComparison]::OrdinalIgnoreCase) -or `
    $outputDirFull.StartsWith($logRoot + $separator, [System.StringComparison]::OrdinalIgnoreCase)

if (-not $isUnderLog) {
    throw "OutputDir must resolve under repository log directory: $logRoot"
}

function Write-ProgressWatchCommands([string]$OutputDirFull) {
    Write-Host ""
    Write-Host "Progress watch from another PowerShell:" -ForegroundColor DarkGray
    Write-Host "  Keep this PowerShell visible; use these checks for live progress instead of waiting silently." -ForegroundColor DarkGray
    Write-Host '  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match ''run-zotero-library-rebuild|plan_rebuild'' } | Select-Object ProcessId,Name,CommandLine'
    Write-Host ("  if (Test-Path -LiteralPath '{0}') {{ Get-ChildItem -LiteralPath '{0}' -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName,Length,LastWriteTime }}" -f $OutputDirFull)
    Write-Host ("  if (Test-Path -LiteralPath '{0}') {{ Get-Content -Raw -LiteralPath '{0}' }}" -f (Join-Path $OutputDirFull "summary.md"))
}

Push-Location $repoRoot
try {
    $script = Join-Path $repoRoot "skill\zotero-library-rebuild\scripts\plan_rebuild.py"
    $argsList = @(
        "run", "python", $script,
        "--output-dir", $outputDirFull,
        "--library-id", "$LibraryId"
    )

    if ($Profile -ne "") {
        $argsList += @("--profile", $Profile)
    }
    if ($DataDir -ne "") {
        $argsList += @("--data-dir", $DataDir)
    }
    if ($Limit -gt 0) {
        $argsList += @("--limit", "$Limit")
    }
    if ($TitleSampleSize -gt 0) {
        $argsList += @("--title-sample-size", "$TitleSampleSize")
    }
    if ($ArchiveDate -ne "") {
        $argsList += @("--archive-date", $ArchiveDate)
    }

    Write-Host "Generating Zotero rebuild dry-run artifacts..."
    Write-Host "OutputDir: $outputDirFull"
    Write-Host "Run mode: direct PowerShell with visible output and progress checks"
    if (-not $HideProgressWatchCommands) {
        Write-ProgressWatchCommands -OutputDirFull $outputDirFull
    }
    & uv @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "Dry-run planner failed with exit code $LASTEXITCODE"
    }
    if ($KeepOutput) {
        Write-Host "Dry-run complete. Review plan and summary:"
        Write-Host (Join-Path $outputDirFull "plan.md")
        Write-Host (Join-Path $outputDirFull "summary.md")
    }
    else {
        if (Test-Path -LiteralPath $outputDirFull) {
            $safeDelete = $outputDirFull.StartsWith($logRoot + $separator, [System.StringComparison]::OrdinalIgnoreCase)
            if (-not $safeDelete) {
                throw "Refusing to clean output outside log directory: $outputDirFull"
            }
            Remove-Item -LiteralPath $outputDirFull -Recurse -Force
        }
        Write-Host "Dry-run complete. Intermediate files removed because the run succeeded."
        Write-Host "Use -KeepOutput when review artifacts should be retained."
    }
}
catch {
    Write-Warning "Run failed. Intermediate files are preserved for debugging: $outputDirFull"
    throw
}
finally {
    Pop-Location
}
