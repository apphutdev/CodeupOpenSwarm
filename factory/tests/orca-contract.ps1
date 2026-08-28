#requires -Version 7.0
[CmdletBinding()]
param(
    [string[]]$RequiredTools = @(
        "orca_create_run",
        "orca_create_pod",
        "orca_list_runs",
        "orca_stage",
        "orca_review",
        "orca_ship"
    ),
    [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Fail-Contract([string]$Message) {
    throw "ORCA CONTRACT BLOCKED: $Message"
}

$orca = Get-Command orca -ErrorAction SilentlyContinue
if (-not $orca) {
    Fail-Contract "orca is not installed or is not on PATH."
}

$versionOutput = & orca version 2>&1
if ($LASTEXITCODE -ne 0) {
    Fail-Contract "'orca version' failed: $($versionOutput -join ' ')"
}
Write-Host "Orca version check passed: $($versionOutput -join ' ')"

$process = [System.Diagnostics.Process]::new()
$process.StartInfo = [System.Diagnostics.ProcessStartInfo]@{
    FileName = $orca.Source
    Arguments = "mcp serve"
    UseShellExecute = $false
    RedirectStandardInput = $true
    RedirectStandardOutput = $true
    RedirectStandardError = $true
    CreateNoWindow = $true
}

try {
    if (-not $process.Start()) {
        Fail-Contract "could not start 'orca mcp serve'."
    }

    Start-Sleep -Milliseconds 300
    if ($process.HasExited) {
        $stderr = $process.StandardError.ReadToEnd().Trim()
        Fail-Contract "'orca mcp serve' exited with code $($process.ExitCode). $stderr"
    }

    function Invoke-McpRequest([int]$Id, [string]$Method, [hashtable]$Params) {
        $request = @{
            jsonrpc = "2.0"
            id = $Id
            method = $Method
            params = $Params
        } | ConvertTo-Json -Depth 10 -Compress

        $process.StandardInput.WriteLine($request)
        $process.StandardInput.Flush()

        $readTask = $process.StandardOutput.ReadLineAsync()
        if (-not $readTask.Wait([TimeSpan]::FromSeconds($TimeoutSeconds))) {
            Fail-Contract "timed out waiting for MCP response to '$Method'."
        }

        $line = $readTask.Result
        if ([string]::IsNullOrWhiteSpace($line)) {
            Fail-Contract "received an empty MCP response to '$Method'."
        }

        try {
            $response = $line | ConvertFrom-Json -Depth 20
        } catch {
            Fail-Contract "received invalid JSON from MCP for '$Method': $line"
        }

        if ($response.error) {
            Fail-Contract "MCP '$Method' returned error: $($response.error | ConvertTo-Json -Compress)"
        }
        return $response
    }

    $initialize = Invoke-McpRequest 1 "initialize" @{
        protocolVersion = "2025-06-18"
        capabilities = @{}
        clientInfo = @{
            name = "software-factory-contract-test"
            version = "1.0.0"
        }
    }

    if (-not $initialize.result.serverInfo) {
        Fail-Contract "initialize response did not contain serverInfo."
    }

    $notification = @{
        jsonrpc = "2.0"
        method = "notifications/initialized"
        params = @{}
    } | ConvertTo-Json -Depth 5 -Compress
    $process.StandardInput.WriteLine($notification)
    $process.StandardInput.Flush()

    $toolResponse = Invoke-McpRequest 2 "tools/list" @{}
    $availableTools = @($toolResponse.result.tools | ForEach-Object { $_.name })

    $missingTools = @($RequiredTools | Where-Object { $_ -notin $availableTools })
    if ($missingTools.Count -gt 0) {
        Fail-Contract "missing required MCP tools: $($missingTools -join ', '). Available: $($availableTools -join ', ')"
    }

    Write-Host "Orca MCP contract passed."
    Write-Host "Required tools: $($RequiredTools -join ', ')"
} finally {
    if (-not $process.HasExited) {
        $process.Kill($true)
        $process.WaitForExit()
    }
    $process.Dispose()
}
