# Install minimal Android SDK for Flutter APK builds (no Android Studio).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install_android_sdk.ps1

$ErrorActionPreference = "Stop"

$sdkRoot = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$cmdlineZip = Join-Path $env:TEMP "commandlinetools-win.zip"
$cmdlineUrl = "https://dl.google.com/android/repository/commandlinetools-win-13114758_latest.zip"

$jdkCandidates = @(
    "C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot",
    "C:\Program Files\Microsoft\jdk-17*",
    "C:\Program Files\Eclipse Adoptium\jdk-17*"
)
$javaHome = $null
foreach ($c in $jdkCandidates) {
    $resolved = Get-Item $c -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($resolved) { $javaHome = $resolved.FullName; break }
}
if (-not $javaHome) {
    Write-Error "JDK 17 not found. Run: winget install Microsoft.OpenJDK.17"
}
$env:JAVA_HOME = $javaHome
$env:PATH = "$javaHome\bin;" + $env:PATH

New-Item -ItemType Directory -Force -Path $sdkRoot | Out-Null

if (-not (Test-Path (Join-Path $sdkRoot "cmdline-tools\latest\bin\sdkmanager.bat"))) {
    Write-Host "Downloading Android command-line tools..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $cmdlineUrl -OutFile $cmdlineZip -UseBasicParsing
    $extractDir = Join-Path $env:TEMP "android-cmdline-extract"
    if (Test-Path $extractDir) { Remove-Item $extractDir -Recurse -Force }
    Expand-Archive -Path $cmdlineZip -DestinationPath $extractDir -Force
    $latestDir = Join-Path $sdkRoot "cmdline-tools\latest"
    New-Item -ItemType Directory -Force -Path $latestDir | Out-Null
    $inner = Join-Path $extractDir "cmdline-tools"
    if (Test-Path $inner) {
        Copy-Item -Path (Join-Path $inner "*") -Destination $latestDir -Recurse -Force
    } else {
        Copy-Item -Path (Join-Path $extractDir "*") -Destination $latestDir -Recurse -Force
    }
    Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $cmdlineZip -Force -ErrorAction SilentlyContinue
}

$sdkmanager = Join-Path $sdkRoot "cmdline-tools\latest\bin\sdkmanager.bat"
if (-not (Test-Path $sdkmanager)) {
    Write-Error "sdkmanager not found at $sdkmanager"
}

$env:ANDROID_HOME = $sdkRoot
$env:ANDROID_SDK_ROOT = $sdkRoot
$env:PATH = "$sdkRoot\platform-tools;$sdkRoot\cmdline-tools\latest\bin;" + $env:PATH

Write-Host "Installing SDK packages (platform-tools, platform 35, build-tools 35)..." -ForegroundColor Cyan
$packages = @(
    "platform-tools",
    "platforms;android-35",
    "build-tools;35.0.0"
)
foreach ($pkg in $packages) {
    Write-Host "  -> $pkg"
    & $sdkmanager $pkg --sdk_root=$sdkRoot 2>&1 | ForEach-Object { Write-Host $_ }
}

Write-Host "Accepting SDK licenses..." -ForegroundColor Cyan
1..50 | ForEach-Object { "y" } | & $sdkmanager --licenses --sdk_root=$sdkRoot 2>&1 | Out-Null

# Persist for current user
[Environment]::SetEnvironmentVariable("ANDROID_HOME", $sdkRoot, "User")
[Environment]::SetEnvironmentVariable("ANDROID_SDK_ROOT", $sdkRoot, "User")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$additions = @(
    "$sdkRoot\platform-tools",
    "$sdkRoot\cmdline-tools\latest\bin"
)
foreach ($a in $additions) {
    if ($userPath -notlike "*$a*") { $userPath = "$a;$userPath" }
}
[Environment]::SetEnvironmentVariable("Path", $userPath, "User")

Write-Host ""
Write-Host "Android SDK ready: $sdkRoot" -ForegroundColor Green
Write-Host "JAVA_HOME=$javaHome"
