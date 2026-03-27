#Requires -Version 5.1
<#
.SYNOPSIS
    Start dev-watch on Windows (native).

.DESCRIPTION
    Creates a Python virtual environment, installs dependencies, starts the Flask
    server on http://localhost:3999, and opens the dashboard in the default browser.

.PARAMETER Help
    Show this help message and exit.

.EXAMPLE
    .\start.ps1
    Start dev-watch and open the dashboard.

.EXAMPLE
    .\start.ps1 -Help
    Show usage information.
#>
param(
    [switch]$Help
)

if ($Help) {
    Write-Host "Usage: .\start.ps1 [options]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -Help    Show this help message"
    Write-Host ""
    Write-Host "The dashboard will open at http://localhost:3999"
    exit 0
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Check Python availability
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python is not installed or not in PATH. Install Python 3.8+ from https://python.org"
    exit 1
}

# Create venv if it doesn't exist
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create virtual environment."
        exit 1
    }
    & ".venv\Scripts\pip" install -q -r requirements.txt
    Write-Host "Dependencies installed."
}

# Stop any running dev-watch instances on port 3999
$existing = Get-NetTCPConnection -LocalPort 3999 -ErrorAction SilentlyContinue
if ($existing) {
    $existing | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

# Start server in background
$server = Start-Process `
    -FilePath ".venv\Scripts\python.exe" `
    -ArgumentList "-m", "src.server" `
    -PassThru `
    -WindowStyle Hidden

Write-Host "dev-watch starting (PID: $($server.Id))..."

# Wait for server to be ready
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        Invoke-WebRequest -Uri "http://localhost:3999/api/health" `
            -UseBasicParsing -TimeoutSec 1 | Out-Null
        $ready = $true
        break
    } catch {
        Start-Sleep -Milliseconds 300
    }
}

if ($ready) {
    Write-Host "dev-watch started at http://localhost:3999"
    Start-Process "http://localhost:3999"
} else {
    Write-Host "Server may still be starting. Try: http://localhost:3999"
}

Write-Host "Press Ctrl+C to stop"
try {
    $server.WaitForExit()
} catch {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}
