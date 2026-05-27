param(
    [string]$ReviewDir = "current-state-review",
    [string]$OutputDir = "",
    [string]$Profile = "",
    [ValidateSet("all", "collections", "items", "verify")]
    [string]$Phase = "all",
    [int]$BatchSize = 25,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$logRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "log"))

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
