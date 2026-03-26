# Remote Claws - start server
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $root

try {
    if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
        Write-Host "Creating venv..." -ForegroundColor Yellow
        python -m venv .venv
        .venv\Scripts\Activate.ps1
        pip install -e .
        playwright install chromium
    } else {
        .venv\Scripts\Activate.ps1
    }

    if (-not (Test-Path ".remote-claws-auth.json")) {
        Write-Host "No auth token found - running setup..." -ForegroundColor Yellow
        remote-claws-setup
    }

    Write-Host ""
    Write-Host "Starting Remote Claws..." -ForegroundColor Green
    remote-claws
} finally {
    Pop-Location
}
