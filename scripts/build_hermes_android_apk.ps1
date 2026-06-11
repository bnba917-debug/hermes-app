# Build Hermes Flutter app release APK.
# Requires: Flutter SDK 3.22+, Android SDK (Android Studio or cmdline-tools), JDK 17+
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\build_hermes_android_apk.ps1
# Output:
#   plugins\app_gateway\flutter_app\build\app\outputs\flutter-apk\app-release.apk

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$AppDir = Join-Path $RepoRoot "plugins\app_gateway\flutter_app"

function Get-FlutterExe {
    if (Get-Command flutter -ErrorAction SilentlyContinue) {
        return "flutter"
    }
    $candidates = @(
        "$env:LOCALAPPDATA\flutter\bin\flutter.bat",
        "C:\flutter\bin\flutter.bat",
        "D:\flutter\bin\flutter.bat",
        "$env:USERPROFILE\flutter\bin\flutter.bat",
        "$env:USERPROFILE\develop\flutter\bin\flutter.bat"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

$flutter = Get-FlutterExe
if (-not $flutter) {
    $autoFlutter = "C:\flutter"
    if ((Get-Command git -ErrorAction SilentlyContinue) -and -not (Test-Path "$autoFlutter\bin\flutter.bat")) {
        Write-Host "Cloning Flutter stable to $autoFlutter (one-time, ~1GB)..." -ForegroundColor Cyan
        git clone https://github.com/flutter/flutter.git -b stable --depth 1 $autoFlutter
    }
    if (Test-Path "$autoFlutter\bin\flutter.bat") {
        $env:PATH = "$autoFlutter\bin;" + $env:PATH
        $flutter = "$autoFlutter\bin\flutter.bat"
    }
}
if (-not $flutter) {
    Write-Host @"

[!] 未检测到 Flutter。请先安装：

  1. 下载: https://docs.flutter.dev/get-started/install/windows
  2. 解压到 C:\flutter ，把 C:\flutter\bin 加入 PATH
  3. 运行: flutter doctor
  4. 安装 Android Studio，在 SDK Manager 里装 Android SDK + Platform Tools
  5. 重新执行本脚本

  或安装 Git 后重跑本脚本（会自动 clone 到 C:\flutter）

"@ -ForegroundColor Yellow
    exit 1
}

Write-Host "Using Flutter: $flutter" -ForegroundColor Cyan
& $flutter --version
& $flutter doctor

Set-Location $AppDir

if (-not (Test-Path "android")) {
    Write-Host "Creating Android/iOS/Web project files..." -ForegroundColor Cyan
    & $flutter create . --project-name hermes_app
}

Write-Host "Resolving dependencies..." -ForegroundColor Cyan
& $flutter pub get

$patchScript = Join-Path $AppDir "scripts\patch_android_manifest.ps1"
if (Test-Path $patchScript) {
    & $patchScript
}

Write-Host "Building release APK (may take several minutes)..." -ForegroundColor Cyan
& $flutter build apk --release

$apk = Join-Path $AppDir "build\app\outputs\flutter-apk\app-release.apk"
if (Test-Path $apk) {
    $dest = Join-Path $RepoRoot "dist\hermes-app-release.apk"
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    Copy-Item $apk $dest -Force
    Write-Host ""
    Write-Host "APK build OK:" -ForegroundColor Green
    Write-Host "  $apk"
    Write-Host "  $dest"
    Write-Host ""
    Write-Host "Install on phone: adb install -r `"$dest`"" -ForegroundColor Cyan
} else {
    Write-Error "APK not found after build. Check flutter build output above."
}
