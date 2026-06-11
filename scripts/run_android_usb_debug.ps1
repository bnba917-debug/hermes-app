# USB debug: Flutter run on connected Android phone.
# Usage (repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\run_android_usb_debug.ps1
#
# Phone: enable Developer options + USB debugging, allow PC when prompted.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$AppDir = Join-Path $RepoRoot "plugins\app_gateway\flutter_app"

$jdk = Get-Item "C:\Program Files\Microsoft\jdk-17*" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $jdk) {
    Write-Host "[!] JDK 17 not found. Run: winget install Microsoft.OpenJDK.17" -ForegroundColor Yellow
    exit 1
}
$env:JAVA_HOME = $jdk.FullName
$env:PATH = "$($env:JAVA_HOME)\bin;" + $env:PATH

$flutter = "C:\flutter\bin\flutter.bat"
if (-not (Test-Path $flutter)) {
    if (Get-Command flutter -ErrorAction SilentlyContinue) { $flutter = "flutter" }
    else {
        Write-Host "[!] Flutter not found (expected C:\flutter or PATH)." -ForegroundColor Yellow
        exit 1
    }
}
$env:PATH = "$(Split-Path $flutter -Parent);" + $env:PATH

$sdkRoot = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$sm = Join-Path $sdkRoot "cmdline-tools\latest\bin\sdkmanager.bat"
if (-not (Test-Path $sm)) {
    Write-Host "[!] Android SDK cmdline-tools missing. Run:" -ForegroundColor Yellow
    Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\install_android_sdk.ps1"
    exit 1
}
$env:ANDROID_HOME = $sdkRoot
$env:ANDROID_SDK_ROOT = $sdkRoot
$env:PATH = "$sdkRoot\platform-tools;$sdkRoot\cmdline-tools\latest\bin;" + $env:PATH

$needPkgs = @()
if (-not (Test-Path "$sdkRoot\platform-tools\adb.exe")) { $needPkgs += "platform-tools" }
if (-not (Test-Path "$sdkRoot\platforms\android-35")) { $needPkgs += "platforms;android-35" }
if (-not (Test-Path "$sdkRoot\build-tools\35.0.0")) { $needPkgs += "build-tools;35.0.0" }

if ($needPkgs.Count -gt 0) {
    Write-Host "Installing Android packages: $($needPkgs -join ', ') (first run: 5-15 min)..." -ForegroundColor Cyan
    foreach ($pkg in $needPkgs) {
        & $sm $pkg --sdk_root=$sdkRoot
    }
    1..30 | ForEach-Object { "y" } | & $sm --licenses --sdk_root=$sdkRoot 2>&1 | Out-Null
}

& $flutter config --android-sdk $sdkRoot | Out-Null

Write-Host ""
Write-Host "=== ADB devices ===" -ForegroundColor Cyan
& "$sdkRoot\platform-tools\adb.exe" devices -l
Write-Host ""

$lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' -and $_.InterfaceAlias -notmatch 'vEthernet|WSL|Loopback' } |
    Select-Object -First 1).IPAddress
if ($lanIp) {
    Write-Host "Gateway URL on phone login screen: http://${lanIp}:8787" -ForegroundColor Green
    Write-Host "Dev SMS code: 111111" -ForegroundColor DarkGray
} else {
    Write-Host "Could not detect LAN IP. Run ipconfig and use WLAN IPv4." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Start gateway in another terminal:" -ForegroundColor Cyan
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\start_app_gateway.ps1"
Write-Host "Press Enter to run flutter (Ctrl+C to quit)..." -ForegroundColor Cyan
Read-Host

Set-Location $AppDir
if (-not (Test-Path "android")) {
    & $flutter create . --project-name hermes_app
}
& $flutter pub get
$patch = Join-Path $AppDir "scripts\patch_android_manifest.ps1"
if (Test-Path $patch) { & $patch }

& $flutter devices
if ($lanIp) {
    & $flutter run -d android --dart-define=HERMES_DEV_GATEWAY=http://${lanIp}:8787
} else {
    & $flutter run -d android
}
