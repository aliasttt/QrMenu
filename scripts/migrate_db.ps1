# Migration: mywebsite PostgreSQL -> qrmenu PostgreSQL (data-only)
# Usage:
#   $env:DATABASE_URL_OLD = 'postgres://mywebsite_2040:PASSWORD@mywebsite-2040.postgresql.c.osc-fr1.scalingo-dbs.com:36348/mywebsite_2040?sslmode=prefer'
#   $env:DATABASE_URL_NEW = 'postgres://qrmenu_8822:PASSWORD@qrmenu-8822.postgresql.c.osc-fr1.scalingo-dbs.com:35045/qrmenu_8822?sslmode=prefer'
#   .\migrate_db.ps1

$ErrorActionPreference = "Stop"
$dumpFile = "backup.dump"

if (-not $env:DATABASE_URL_OLD -or -not $env:DATABASE_URL_NEW) {
    Write-Host "Set DATABASE_URL_OLD and DATABASE_URL_NEW first." -ForegroundColor Red
    Write-Host "Example:"
    Write-Host '  $env:DATABASE_URL_OLD = "postgres://user:pass@host:port/db?sslmode=prefer"'
    Write-Host '  $env:DATABASE_URL_NEW = "postgres://user:pass@host:port/db?sslmode=prefer"'
    exit 1
}

Write-Host "1. Dumping old database..." -ForegroundColor Cyan
& pg_dump $env:DATABASE_URL_OLD -Fc -f $dumpFile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "2. Restoring data-only to new database..." -ForegroundColor Cyan
& pg_restore --data-only --no-owner --no-acl -d $env:DATABASE_URL_NEW $dumpFile
$restoreExit = $LASTEXITCODE

if (Test-Path $dumpFile) { Remove-Item $dumpFile }

if ($restoreExit -ne 0) {
    Write-Host "Restore had warnings or errors (e.g. duplicate key). If tables already had data, truncate them and run only restore:" -ForegroundColor Yellow
    Write-Host "  pg_restore --data-only --no-owner --no-acl -d `"`$env:DATABASE_URL_NEW`" backup.dump" -ForegroundColor Gray
    exit $restoreExit
}

Write-Host "Done." -ForegroundColor Green
