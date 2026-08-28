#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Root = "D:\AI\Factory",
    [switch]$SkipHerdr,
    [switch]$SkipOrca
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Require-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required. $Hint"
    }
}

function Ensure-Directory([string]$Path) {
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

Write-Step "Checking Windows prerequisites"
Require-Command "git" "Install Git for Windows, then rerun this script."

if (-not (Get-Command "pwsh" -ErrorAction SilentlyContinue)) {
    Write-Warning "PowerShell 7 (pwsh) is recommended but not required for bootstrap."
}

Write-Step "Creating factory directories"
@("repos", "worktrees", "state", "logs", "config") | ForEach-Object {
    Ensure-Directory (Join-Path $Root $_)
}

if (-not $SkipOrca) {
    if (-not (Get-Command "orca" -ErrorAction SilentlyContinue)) {
        Write-Step "Installing Orca from source"
        Require-Command "go" "Install Go, or install an Orca Windows release manually and place orca.exe on PATH."
        & go install github.com/orca-cli/orca/cmd/orca@latest

        $GoBin = & go env GOPATH
        $GoBin = Join-Path $GoBin "bin"
        if ($env:PATH -notlike "*$GoBin*") {
            $env:PATH = "$GoBin;$env:PATH"
            Write-Warning "Added $GoBin to PATH for this PowerShell session. Add it permanently if needed."
        }
    }

    Require-Command "orca" "Install Orca and ensure orca.exe is on PATH."
    $orcaVersion = (& orca version 2>&1) -join " "
    if ($LASTEXITCODE -ne 0) {
        throw "Installed Orca failed its version command: $orcaVersion"
    }
    Write-Host "Orca: $orcaVersion"
}

if (-not $SkipHerdr) {
    if (-not (Get-Command "herdr" -ErrorAction SilentlyContinue)) {
        Write-Step "Installing Herdr Windows preview"
        Invoke-RestMethod "https://herdr.dev/install.ps1" | Invoke-Expression
    }

    if (Get-Command "herdr" -ErrorAction SilentlyContinue) {
        Write-Host "Herdr: $(& herdr --version 2>$null)"
    } else {
        Write-Warning "Herdr install completed but herdr is not yet visible on PATH. Open a new terminal before starting it."
    }
}

Write-Step "Checking optional operator/developer CLIs"
foreach ($cmd in @("gh", "codex", "claude", "opencode")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        Write-Host "[ok] $cmd"
    } else {
        Write-Host "[optional/missing] $cmd"
    }
}

Write-Step "Bootstrap complete"
Write-Host "Factory root: $Root"
Write-Host "Next: run .\factory\scripts\windows\health.ps1 -Root `"$Root`""
