#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Root = "D:\AI\Factory"
)

$ErrorActionPreference = "Continue"

$checks = @()

function Add-Check([string]$Name, [bool]$Ok, [string]$Detail) {
    $script:checks += [pscustomobject]@{
        Name = $Name
        Status = if ($Ok) { "PASS" } else { "FAIL" }
        Detail = $Detail
    }
}

foreach ($cmd in @("git", "orca")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    Add-Check $cmd ([bool]$found) (if ($found) { $found.Source } else { "Not on PATH" })
}

$herdr = Get-Command "herdr" -ErrorAction SilentlyContinue
Add-Check "herdr" ([bool]$herdr) (if ($herdr) { $herdr.Source } else { "Optional control plane is not on PATH" })

foreach ($dir in @("repos", "worktrees", "state", "logs", "config")) {
    $path = Join-Path $Root $dir
    Add-Check "dir:$dir" (Test-Path $path) $path
}

$gitVersion = $null
if (Get-Command git -ErrorAction SilentlyContinue) {
    $gitVersion = (& git --version) -join " "
}
if ($gitVersion) { Add-Check "git-version" $true $gitVersion }

$orcaVersion = $null
if (Get-Command orca -ErrorAction SilentlyContinue) {
    try { $orcaVersion = (& orca --version 2>&1) -join " " } catch { $orcaVersion = $_.Exception.Message }
}
if ($orcaVersion) { Add-Check "orca-version" $true $orcaVersion }

$checks | Format-Table -AutoSize

$requiredFailures = $checks | Where-Object { $_.Status -eq "FAIL" -and $_.Name -ne "herdr" }
if ($requiredFailures) {
    Write-Error "Factory health check failed. Fix required checks before starting V1."
    exit 1
}

Write-Host "`nRequired V1 health checks passed." -ForegroundColor Green
if (-not $herdr) {
    Write-Warning "Herdr is unavailable; Orca can still run headlessly."
}
