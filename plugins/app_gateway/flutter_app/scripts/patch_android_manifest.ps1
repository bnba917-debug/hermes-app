# Allow HTTP gateway on LAN during dev (cleartext).
$manifest = Join-Path $PSScriptRoot "..\android\app\src\main\AndroidManifest.xml"
if (-not (Test-Path $manifest)) {
    Write-Error "AndroidManifest not found. Run: flutter create . --project-name hermes_app"
    exit 1
}
$xml = Get-Content $manifest -Raw
if ($xml -match 'usesCleartextTraffic') {
    Write-Host "AndroidManifest already patched."
    exit 0
}
$xml = $xml -replace '<application\s', '<application android:usesCleartextTraffic="true" '
Set-Content -Path $manifest -Value $xml -Encoding UTF8
Write-Host "Patched: usesCleartextTraffic=true"
