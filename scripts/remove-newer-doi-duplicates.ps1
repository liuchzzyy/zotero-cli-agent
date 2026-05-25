[CmdletBinding()]
param(
    [string]$ZoteroRepoRoot = $PSScriptRoot,
    [string]$Library = "user",
    [string]$Profile = "",
    [int]$BatchSize = 25,
    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Stage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host ("[{0}] {1}" -f (Get-Date).ToString("HH:mm:ss"), $Message)
}

function Get-PercentText {
    param(
        [int]$Completed,
        [int]$Total
    )

    if ($Total -le 0) {
        return "0.0"
    }

    return ([Math]::Round(($Completed * 100.0) / $Total, 1)).ToString("0.0")
}

function Invoke-UvJsonCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [int[]]$AllowedExitCodes = @(0)
    )

    Write-Host ("Running: uv " + ($Arguments -join " "))

    Push-Location $WorkingDirectory
    try {
        $output = & uv @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($exitCode -notin $AllowedExitCodes) {
        $rendered = ($output | Out-String).Trim()
        throw "Command failed with exit code ${exitCode}: uv $($Arguments -join ' ')`n$rendered"
    }

    $text = ($output | Out-String).Trim()
    if (-not $text) {
        throw "Command returned no output: uv $($Arguments -join ' ')"
    }

    return $text | ConvertFrom-Json
}

function Get-DateAddedValue {
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Item
    )

    $raw = [string]$Item.date_added
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return [datetime]::MaxValue
    }

    try {
        return [datetime]::Parse($raw, [System.Globalization.CultureInfo]::InvariantCulture)
    }
    catch {
        return [datetime]::MaxValue
    }
}

function Get-DuplicatePlan {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Groups
    )

    $plan = @()
    $total = $Groups.Count
    $index = 0

    Write-Stage ("Building keep/delete plan for {0} duplicate groups..." -f $total)

    foreach ($group in $Groups) {
        $index += 1
        $items = @($group.items)
        if ($items.Count -lt 2) {
            Write-Host ("  [plan {0}/{1} {2}%] skipped group with fewer than 2 items" -f $index, $total, (Get-PercentText -Completed $index -Total $total))
            continue
        }

        $ordered = $items |
            Sort-Object `
                @{ Expression = { Get-DateAddedValue -Item $_ } ; Ascending = $true }, `
                @{ Expression = { [string]$_.key } ; Ascending = $true }

        $keep = $ordered[0]
        $delete = @($ordered | Select-Object -Skip 1)

        $plan += [pscustomobject]@{
            Group      = [int]$group.group
            MatchType  = [string]$group.match_type
            Score      = [double]$group.score
            Doi        = [string]$keep.doi
            Keep       = $keep
            Delete     = $delete
        }

        Write-Host (
            "  [plan {0}/{1} {2}%] keep={3} delete={4} doi={5}" -f
            $index,
            $total,
            (Get-PercentText -Completed $index -Total $total),
            $keep.key,
            ((@($delete | ForEach-Object { $_.key }) -join ",")),
            $keep.doi
        )
    }

    return $plan
}

function Write-PlanSummary {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Plan
    )

    $deleteCount = (@($Plan | ForEach-Object { $_.Delete }).Count)

    Write-Host ""
    Write-Host ("Duplicate groups: {0}" -f $Plan.Count)
    Write-Host ("Items to delete:  {0}" -f $deleteCount)
    Write-Host ""

    foreach ($entry in $Plan) {
        Write-Host ("Group {0} | DOI {1}" -f $entry.Group, $entry.Doi)
        Write-Host ("  keep   {0} | added {1} | {2}" -f $entry.Keep.key, $entry.Keep.date_added, $entry.Keep.title)
        foreach ($item in $entry.Delete) {
            Write-Host ("  delete {0} | added {1} | {2}" -f $item.key, $item.date_added, $item.title)
        }
    }
}

function Invoke-DeleteBatches {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Keys,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string]$Library,
        [string]$Profile = "",
        [Parameter(Mandatory = $true)]
        [int]$BatchSize
    )

    $total = $Keys.Count
    if ($total -eq 0) {
        Write-Host "Nothing to delete."
        return
    }

    $batchIndex = 0
    $processed = 0
    $totalBatches = [Math]::Ceiling($total / [double]$BatchSize)

    Write-Stage ("Deleting {0} newer duplicate items in {1} batch(es)..." -f $total, $totalBatches)

    for ($offset = 0; $offset -lt $total; $offset += $BatchSize) {
        $count = [Math]::Min($BatchSize, $total - $offset)
        $chunk = $Keys[$offset..($offset + $count - 1)]
        $batchIndex += 1

        Write-Host ""
        Write-Host (
            "Deleting batch {0}/{1}: next {2} item(s) | current progress {3}/{4} ({5}%)" -f
            $batchIndex,
            $totalBatches,
            $count,
            $processed,
            $total,
            (Get-PercentText -Completed $processed -Total $total)
        )

        $arguments = @("run", "zot", "--json", "--library", $Library)
        if ($Profile) {
            $arguments += @("--profile", $Profile)
        }
        $arguments += @("delete", "--yes")
        $arguments += $chunk

        $result = Invoke-UvJsonCommand -Arguments $arguments -WorkingDirectory $WorkingDirectory
        $deleted = @()
        $failed = @()

        if ($result.ok -eq $true -and $null -ne $result.data -and $null -ne $result.data.deleted) {
            $deleted = @($result.data.deleted)
        }
        elseif ($result.ok -eq "partial" -and $null -ne $result.data) {
            $deleted = @($result.data.succeeded | ForEach-Object { $_.key })
            $failed = @($result.data.failed | ForEach-Object { $_.key })
        }
        elseif ($result.ok -eq $false) {
            $message = if ($null -ne $result.error.message) { [string]$result.error.message } else { "delete failed" }
            throw "Delete batch failed: $message"
        }
        else {
            throw "Unexpected delete response shape."
        }

        $processed += $deleted.Count
        Write-Host (
            "  batch result: deleted={0} failed={1} | overall {2}/{3} ({4}%)" -f
            $deleted.Count,
            $failed.Count,
            $processed,
            $total,
            (Get-PercentText -Completed $processed -Total $total)
        )
        if ($deleted.Count -gt 0) {
            Write-Host ("  deleted keys: {0}" -f ($deleted -join ", "))
        }
        if ($failed.Count -gt 0) {
            Write-Host ("  failed keys:  {0}" -f ($failed -join ", "))
            throw "Delete batch completed partially. Review failed keys above."
        }
    }
}

$duplicatesArgs = @("run", "zot", "--json", "--library", $Library)
if ($Profile) {
    $duplicatesArgs += @("--profile", $Profile)
}
$duplicatesArgs += @("duplicates", "--by", "doi")

Write-Stage "Querying DOI duplicates..."
$duplicates = Invoke-UvJsonCommand -Arguments $duplicatesArgs -WorkingDirectory $ZoteroRepoRoot -AllowedExitCodes @(0, 6)
$groups = @()

$hasDataProperty = $false
if ($null -ne $duplicates -and $null -ne $duplicates.PSObject.Properties["data"]) {
    $hasDataProperty = $true
}

if ($hasDataProperty) {
    $groups = @($duplicates.data)
}
else {
    $groups = @($duplicates)
}

Write-Stage ("DOI duplicate query finished. Groups found: {0}" -f $groups.Count)

if ($groups.Count -eq 0) {
    Write-Host "No DOI duplicates found."
    exit 0
}

$plan = Get-DuplicatePlan -Groups $groups
Write-PlanSummary -Plan $plan

$keysToDelete = @($plan | ForEach-Object { $_.Delete } | ForEach-Object { [string]$_.key })

if (-not $Apply) {
    Write-Host ""
    Write-Host "Dry run only. Re-run with -Apply to move the newer items to trash."
    exit 0
}

Invoke-DeleteBatches -Keys $keysToDelete -WorkingDirectory $ZoteroRepoRoot -Library $Library -Profile $Profile -BatchSize $BatchSize

Write-Host ""
Write-Host "Done. Deleted newer DOI-duplicate items by date_added."
