# Run DB migration using Scalingo db-tunnel (required when DB is not reachable directly)
# Starts two tunnels, runs migrate_db_auto.py, then stops tunnels.

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$PortOld = 10000
$PortNew = 10001

Write-Host "Starting db-tunnel for mywebsite on port $PortOld..."
$tunnelOld = Start-Process -FilePath "scalingo" -ArgumentList "--app","mywebsite","db-tunnel","SCALINGO_POSTGRESQL_URL","-p",$PortOld -PassThru -NoNewWindow
Start-Sleep -Seconds 2
Write-Host "Starting db-tunnel for qrmenu on port $PortNew..."
$tunnelNew = Start-Process -FilePath "scalingo" -ArgumentList "--app","qrmenu","db-tunnel","SCALINGO_POSTGRESQL_URL","-p",$PortNew -PassThru -NoNewWindow
Write-Host "Waiting for tunnels to be ready..."
Start-Sleep -Seconds 8

try {
    $env:TUNNEL_OLD_PORT = $PortOld
    $env:TUNNEL_NEW_PORT = $PortNew
    python scripts/migrate_db_auto.py
    $code = $LASTEXITCODE
} finally {
    Write-Host "Stopping tunnels..."
    if ($tunnelOld -and !$tunnelOld.HasExited) { Stop-Process -Id $tunnelOld.Id -Force -ErrorAction SilentlyContinue }
    if ($tunnelNew -and !$tunnelNew.HasExited) { Stop-Process -Id $tunnelNew.Id -Force -ErrorAction SilentlyContinue }
}

exit $code
