#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Root = "D:\AI\Factory",
    [switch]$Headless
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$healthScript = Join-Path $PSScriptRoot "health.ps1"
& $healthScript -Root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$env:SOFTWARE_FACTORY_ROOT = $Root
$env:SOFTWARE_FACTORY_CONFIG = (Resolve-Path (Join-Path $PSScriptRoot "..\..\config\factory.yaml")).Path

Write-Host "Factory root: $env:SOFTWARE_FACTORY_ROOT"
Write-Host "Factory config: $env:SOFTWARE_FACTORY_CONFIG"

if ($Headless) {
    Write-Host "Starting Orca MCP server in headless mode..." -ForegroundColor Cyan
    & orca mcp serve
    exit $LASTEXITCODE
}

if (Get-Command herdr -ErrorAction SilentlyContinue) {
    Write-Host "Starting Herdr control plane..." -ForegroundColor Cyan
    Write-Host "Inside Herdr, start the Commander harness with Orca configured as MCP: orca mcp serve"
    & herdr
    exit $LASTEXITCODE
}

Write-Warning "Herdr is unavailable. Falling back to headless Orca MCP server."
& orca mcp serve
