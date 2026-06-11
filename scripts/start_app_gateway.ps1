# Start Hermes App Gateway on Windows.
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\start_app_gateway.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "[!] .venv not found. Create it first:" -ForegroundColor Yellow
    Write-Host "    py -3.11 -m venv .venv"
    Write-Host "    .\.venv\Scripts\python.exe -m pip install -e `".[web]`""
    exit 1
}

& $python -c "import yaml, dotenv" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing minimal Python deps (first run may take a minute)..." -ForegroundColor Cyan
    & $python -m ensurepip --upgrade 2>$null | Out-Null
    & $python -m pip install pyyaml python-dotenv uvicorn fastapi httpx pydantic python-multipart -q
}

$launcher = Join-Path $RepoRoot "scripts\run_app_gateway.py"
Write-Host "Starting: $python $launcher start" -ForegroundColor Cyan
Write-Host "Flutter Web (dev): http://127.0.0.1:8081  (plugins/app_gateway/flutter_app)" -ForegroundColor DarkGray
Write-Host "Phone gateway URL: http://YOUR_LAN_IP:8787  (run ipconfig, use WLAN IPv4)" -ForegroundColor DarkGray
Write-Host ""

& $python $launcher start @args
