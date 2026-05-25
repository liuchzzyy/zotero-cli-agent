[CmdletBinding()]
param(
    [string]$Date = (Get-Date).ToString("yyyy-MM-dd"),
    [string]$RssRepoRoot = "E:\Desktop\CodingDaily\rss-cli-agent",
    [string]$ZoteroRepoRoot = "",
    [string]$Library = "user",
    [string]$Profile = "",
    [string]$RecentCutoffUtc = "",
    [int]$ProgressIntervalSeconds = 10
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

if ($ZoteroRepoRoot) {
    $ZoteroRepoRoot = (Resolve-Path $ZoteroRepoRoot).Path
}
else {
    $ZoteroRepoRoot = Get-RepoRoot
}

function Get-ImportProcesses {
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like "*scripts/import_rss_inbox_plan.py*" } |
        Select-Object ProcessId, Name, CommandLine
}

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Invoke-UvCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )
    Write-Host ("Running: uv " + ($Arguments -join " "))
    Push-Location $WorkingDirectory
    try {
        & uv @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed with exit code ${LASTEXITCODE}: uv $($Arguments -join ' ')"
        }
    }
    finally {
        Pop-Location
    }
}

function Start-UvProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )
    $uvCommand = Get-Command uv -CommandType Application | Select-Object -First 1
    if (-not $uvCommand) {
        throw "uv was not found in PATH."
    }
    Write-Host ("Starting: uv " + ($Arguments -join " "))
    return Start-Process -FilePath $uvCommand.Source -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -PassThru -WindowStyle Hidden
}

function Format-Duration {
    param(
        [Parameter(Mandatory = $true)]
        [TimeSpan]$Duration
    )
    if ($Duration.TotalHours -ge 1) {
        return "{0:00}:{1:00}:{2:00}" -f [int]$Duration.TotalHours, $Duration.Minutes, $Duration.Seconds
    }
    return "{0:00}:{1:00}" -f [int]$Duration.TotalMinutes, $Duration.Seconds
}

function Get-ProgressSnapshot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ImportSummaryPath,
        [Parameter(Mandatory = $true)]
        [int]$Total
    )
    if (-not (Test-Path -LiteralPath $ImportSummaryPath)) {
        return $null
    }
    $summary = Read-JsonFile -Path $ImportSummaryPath
    $createdNew = [int]($summary.created_new | ForEach-Object { $_ }) 
    $reusedExisting = [int]($summary.reused_existing | ForEach-Object { $_ })
    $alreadyRouted = [int]($summary.already_routed | ForEach-Object { $_ })
    $failed = [int]($summary.failed | ForEach-Object { $_ })
    $processed = $createdNew + $reusedExisting + $alreadyRouted + $failed
    $percent = 0.0
    if ($Total -gt 0) {
        $percent = [Math]::Min(100.0, [Math]::Round(($processed * 100.0) / $Total, 1))
    }
    [pscustomobject]@{
        Total = $Total
        Processed = $processed
        Percent = $percent
        CreatedNew = $createdNew
        ReusedExisting = $reusedExisting
        AlreadyRouted = $alreadyRouted
        Failed = $failed
    }
}

function Write-ProgressLine {
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Snapshot,
        [Parameter(Mandatory = $true)]
        [datetime]$StartTime
    )
    $elapsed = (Get-Date) - $StartTime
    $elapsedText = Format-Duration -Duration $elapsed
    $etaText = "--:--"
    if ($Snapshot.Processed -gt 0 -and $Snapshot.Total -gt $Snapshot.Processed) {
        $secondsPerItem = $elapsed.TotalSeconds / $Snapshot.Processed
        $remainingSeconds = [int][Math]::Round(($Snapshot.Total - $Snapshot.Processed) * $secondsPerItem)
        $etaText = Format-Duration -Duration ([TimeSpan]::FromSeconds($remainingSeconds))
    }
    Write-Host (
        "[{0}] {1}/{2} ({3}%) | new={4} reused={5} routed={6} failed={7} | elapsed={8} eta={9}" -f
        (Get-Date).ToString("HH:mm:ss"),
        $Snapshot.Processed,
        $Snapshot.Total,
        $Snapshot.Percent,
        $Snapshot.CreatedNew,
        $Snapshot.ReusedExisting,
        $Snapshot.AlreadyRouted,
        $Snapshot.Failed,
        $elapsedText,
        $etaText
    )
}

function Wait-ImportWithProgress {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)]
        [string]$ImportSummaryPath,
        [Parameter(Mandatory = $true)]
        [int]$Total,
        [Parameter(Mandatory = $true)]
        [int]$ProgressIntervalSeconds
    )
    $startTime = Get-Date
    $lastKey = ""
    $lastHeartbeat = Get-Date "2000-01-01"
    while (-not $Process.HasExited) {
        $snapshot = Get-ProgressSnapshot -ImportSummaryPath $ImportSummaryPath -Total $Total
        if ($null -ne $snapshot) {
            $key = "{0}|{1}|{2}|{3}|{4}" -f $snapshot.Processed, $snapshot.CreatedNew, $snapshot.ReusedExisting, $snapshot.AlreadyRouted, $snapshot.Failed
            $now = Get-Date
            if ($key -ne $lastKey -or ($now - $lastHeartbeat).TotalSeconds -ge ($ProgressIntervalSeconds * 3)) {
                Write-ProgressLine -Snapshot $snapshot -StartTime $startTime
                $lastKey = $key
                $lastHeartbeat = $now
            }
        }
        else {
            Write-Host ("[{0}] import starting..." -f (Get-Date).ToString("HH:mm:ss"))
        }
        Start-Sleep -Seconds $ProgressIntervalSeconds
        $Process.Refresh()
    }
    $Process.WaitForExit()
    $finalSnapshot = Get-ProgressSnapshot -ImportSummaryPath $ImportSummaryPath -Total $Total
    if ($null -ne $finalSnapshot) {
        Write-ProgressLine -Snapshot $finalSnapshot -StartTime $startTime
    }
    if ($Process.ExitCode -ne 0) {
        throw "Import process failed with exit code $($Process.ExitCode)"
    }
}

function Export-FailedDois {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FailedResultsPath,
        [Parameter(Mandatory = $true)]
        [string]$OutputTxtPath,
        [Parameter(Mandatory = $true)]
        [string]$Date
    )
    if (-not (Test-Path -LiteralPath $FailedResultsPath)) {
        return 0
    }
    $failedResults = Read-JsonFile -Path $FailedResultsPath
    if ($null -eq $failedResults) {
        return 0
    }
    $rows = @($failedResults)
    $failedCount = $rows.Count
    if ($failedCount -eq 0) {
        if (Test-Path -LiteralPath $OutputTxtPath) {
            Remove-Item -LiteralPath $OutputTxtPath -Force
        }
        Write-Host "No failed DOIs to export."
        return 0
    }

    $doiLines = foreach ($row in $rows) {
        if ($row.doi) {
            [string]$row.doi
        }
    }
    Set-Content -LiteralPath $OutputTxtPath -Value $doiLines -Encoding UTF8

    Write-Host ""
    Write-Host "Exported failed DOI file:"
    Write-Host ("  txt  : {0}" -f $OutputTxtPath)
    return $failedCount
}

$selectedJson = Join-Path $RssRepoRoot ("storage\daily\{0}.selected.json" -f $Date)
if (-not (Test-Path -LiteralPath $selectedJson)) {
    throw "Selected JSON not found: $selectedJson"
}

$runningImports = @(Get-ImportProcesses)
if ($runningImports.Count -gt 0) {
    $details = $runningImports | Format-Table -AutoSize | Out-String
    throw "Detected running import_rss_inbox_plan.py process(es). Stop them before rerunning.`n$details"
}

$tmpRoot = Join-Path $ZoteroRepoRoot "tmp"
$planDir = Join-Path $tmpRoot ("rss_inbox_plan_{0}" -f $Date)
$importDir = Join-Path $tmpRoot ("rss_inbox_import_{0}" -f $Date)
$routePlan = Join-Path $planDir "route_plan.json"
$cleanSummaryPath = Join-Path $planDir "summary.json"
$importSummaryPath = Join-Path $importDir "import_summary.json"
$failedResultsPath = Join-Path $importDir "failed_results.json"
$failedTxtPath = Join-Path $ZoteroRepoRoot ("rss_failed_dois_{0}.txt" -f $Date)
$completed = $false
$failedCount = 0

try {
    if (Test-Path -LiteralPath $tmpRoot) {
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $tmpRoot | Out-Null

    Write-Host ("Selected JSON: {0}" -f $selectedJson)

    $cleanArgs = @(
        "run", "python", "scripts/clean_rss_selected_for_inbox.py",
        "--selected-json", $selectedJson,
        "--output-dir", $planDir
    )
    Invoke-UvCommand -Arguments $cleanArgs -WorkingDirectory $ZoteroRepoRoot

    if (-not (Test-Path -LiteralPath $routePlan)) {
        throw "route_plan.json was not created: $routePlan"
    }

    $cleanSummary = Read-JsonFile -Path $cleanSummaryPath
    $totalToImport = [int]$cleanSummary.new_dois

    Write-Host ""
    Write-Host "Clean summary:"
    Write-Host ("  total_selected_rows      : {0}" -f $cleanSummary.total_selected_rows)
    Write-Host ("  unique_selected_dois     : {0}" -f $cleanSummary.unique_selected_dois)
    Write-Host ("  already_in_library       : {0}" -f $cleanSummary.already_in_library)
    Write-Host ("  new_dois                 : {0}" -f $cleanSummary.new_dois)
    Write-Host ("  author_routed_new_dois   : {0}" -f $cleanSummary.author_routed_new_dois)

    $importArgs = @(
        "run", "python", "scripts/import_rss_inbox_plan.py",
        "--route-plan", $routePlan,
        "--output-dir", $importDir,
        "--library", $Library,
        "--apply"
    )
    if ($Profile) {
        $importArgs += @("--profile", $Profile)
    }
    if ($RecentCutoffUtc) {
        $importArgs += @("--recent-cutoff-utc", $RecentCutoffUtc)
    }

    Write-Host ""
    Write-Host ("Import progress will update every {0}s." -f $ProgressIntervalSeconds)
    $importProcess = Start-UvProcess -Arguments $importArgs -WorkingDirectory $ZoteroRepoRoot
    Wait-ImportWithProgress -Process $importProcess -ImportSummaryPath $importSummaryPath -Total $totalToImport -ProgressIntervalSeconds $ProgressIntervalSeconds

    $importSummary = Read-JsonFile -Path $importSummaryPath

    Write-Host ""
    Write-Host "Import summary:"
    Write-Host ("  created_new              : {0}" -f $importSummary.created_new)
    Write-Host ("  reused_existing          : {0}" -f $importSummary.reused_existing)
    Write-Host ("  already_routed           : {0}" -f $importSummary.already_routed)
    Write-Host ("  collection_repairs       : {0}" -f $importSummary.collection_repairs)
    Write-Host ("  failed                   : {0}" -f $importSummary.failed)

    $failedCount = Export-FailedDois -FailedResultsPath $failedResultsPath -OutputTxtPath $failedTxtPath -Date $Date
    if ([int]$importSummary.failed -gt 0) {
        throw "Import finished with $($importSummary.failed) failures. Review: $failedResultsPath"
    }

    $completed = $true
}
finally {
    if (-not $failedCount) {
        $failedCount = Export-FailedDois -FailedResultsPath $failedResultsPath -OutputTxtPath $failedTxtPath -Date $Date
    }
    if ($completed -and (Test-Path -LiteralPath $tmpRoot)) {
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force
        Write-Host ""
        Write-Host "Removed tmp directory: $tmpRoot"
    }
}
