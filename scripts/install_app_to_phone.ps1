# Build and install Hermes Flutter app to USB-connected phone (debug).
# Prerequisite: gateway already on :8787 OR start it in another terminal first.
#
# Usage (repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\install_app_to_phone.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$AppDir = Join-Path $RepoRoot "plugins\app_gateway\flutter_app"

$env:PATH = "C:\flutter\bin;$env:LOCALAPPDATA\Android\Sdk\platform-tools;C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot\bin;" + $env:PATH
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
$env:JAVA_HOME = "C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot"

Write-Host "=== Step 1: phone (adb) ===" -ForegroundColor Cyan
$adb = "$env:ANDROID_HOME\platform-tools\adb.exe"
& $adb devices -l
$serial = (& $adb devices | Select-String "device$" | Where-Object { $_ -notmatch "List of" } | ForEach-Object { ($_ -split '\s+')[0] } | Select-Object -First 1)
if (-not $serial) {
    Write-Host "[!] No phone in 'device' state. Enable USB debugging and allow this PC." -ForegroundColor Red
    exit 1
}
Write-Host "Using device: $serial" -ForegroundColor Green

Write-Host ""
Write-Host "=== Step 2: gateway (8787) ===" -ForegroundColor Cyan
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8787/health" -UseBasicParsing -TimeoutSec 3
    Write-Host "Gateway OK (HTTP $($r.StatusCode))" -ForegroundColor Green
} catch {
    Write-Host "[!] Gateway not reachable on 127.0.0.1:8787" -ForegroundColor Red
    Write-Host "    Start it first: powershell -File scripts\start_app_gateway.ps1"
    exit 1
}

$lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -match '^192\.168\.' } |
    Select-Object -First 1).IPAddress
if (-not $lanIp) { $lanIp = "192.168.0.1" }
$gateway = "http://${lanIp}:8787"
Write-Host "Phone login URL: $gateway  (SMS code: 111111)" -ForegroundColor Green

Write-Host ""
Write-Host "=== Step 3: Android SDK (Flutter 3.44 needs API 36) ===" -ForegroundColor Cyan
$sm = "$env:ANDROID_HOME\cmdline-tools\latest\bin\sdkmanager.bat"
if (-not (Test-Path "$env:ANDROID_HOME\platforms\android-36")) {
    Write-Host "Installing platforms;android-36 (one-time)..."
    & $sm "platforms;android-36" --sdk_root=$env:ANDROID_HOME
}

Write-Host ""
Write-Host "=== Step 4: flutter run (first time 10-30 min, installs APK) ===" -ForegroundColor Cyan
Write-Host "Do NOT close this window until you see the app on the phone." -ForegroundColor Yellow
Set-Location $AppDir
& flutter pub get
& flutter run -d $serial --dart-define=HERMES_DEV_GATEWAY=$gateway
