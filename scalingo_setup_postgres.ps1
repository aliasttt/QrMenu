param(
    [Parameter(Mandatory = $true)]
    [string]$AppName
)

Write-Host "=== QR Menu / Scalingo PostgreSQL setup ===" -ForegroundColor Cyan

function Ensure-ScalingoCli {
    if (Get-Command scalingo -ErrorAction SilentlyContinue) {
        Write-Host "Scalingo CLI already installed." -ForegroundColor Green
        return
    }

    Write-Host "Scalingo CLI not found. Installing..." -ForegroundColor Yellow
    try {
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
    } catch {
        Write-Warning "Could not change execution policy automatically. You may be prompted for confirmation."
    }

    Invoke-Expression (Invoke-WebRequest -UseBasicParsing "https://cli-dl.scalingo.com/install.ps1").Content

    if (-not (Get-Command scalingo -ErrorAction SilentlyContinue)) {
        Write-Error "Scalingo CLI is still not available after install. Please install it manually from https://doc.scalingo.com/cli."
        exit 1
    }
    Write-Host "Scalingo CLI installed." -ForegroundColor Green
}

function Ensure-ScalingoLogin {
    Write-Host "Checking Scalingo login..." -ForegroundColor Cyan
    $whoami = scalingo whoami 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $whoami) {
        Write-Host "You are not logged in. Opening interactive login..." -ForegroundColor Yellow
        scalingo login
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Scalingo login failed. Please run 'scalingo login' manually and then re-run this script."
            exit 1
        }
    } else {
        Write-Host "Already logged in as $whoami" -ForegroundColor Green
    }
}

function Ensure-PostgresAddon {
    param(
        [string]$AppName
    )

    Write-Host "Checking existing addons for app '$AppName'..." -ForegroundColor Cyan
    $addons = scalingo --app $AppName addons 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to list addons for app '$AppName'. Check the app name and your permissions."
        exit 1
    }

    if ($addons -match "postgresql") {
        Write-Host "PostgreSQL addon already exists for '$AppName'." -ForegroundColor Green
        return
    }

    Write-Host "No PostgreSQL addon found. Creating free PostgreSQL addon..." -ForegroundColor Yellow
    scalingo --app $AppName addons-add postgresql free
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create PostgreSQL addon. Please check your Scalingo account/plan."
        exit 1
    }
    Write-Host "PostgreSQL addon created." -ForegroundColor Green
}

function Ensure-DatabaseUrlEnv {
    param(
        [string]$AppName
    )

    Write-Host "Ensuring DATABASE_URL is set for '$AppName'..." -ForegroundColor Cyan
    $envLines = scalingo --app $AppName env
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to read environment variables for '$AppName'."
        exit 1
    }

    $dbLine = $envLines | Where-Object { $_ -match "^DATABASE_URL=" }
    if ($dbLine) {
        Write-Host "DATABASE_URL already set." -ForegroundColor Green
        return
    }

    $pgLine = $envLines | Where-Object { $_ -match "^SCALINGO_POSTGRESQL_URL=" }
    if (-not $pgLine) {
        Write-Error "SCALINGO_POSTGRESQL_URL not found. PostgreSQL addon may not be correctly provisioned."
        exit 1
    }

    $pgUrl = $pgLine -replace "^SCALINGO_POSTGRESQL_URL=", ""
    if (-not $pgUrl) {
        Write-Error "Could not parse SCALINGO_POSTGRESQL_URL."
        exit 1
    }

    Write-Host "Setting DATABASE_URL from SCALINGO_POSTGRESQL_URL..." -ForegroundColor Yellow
    scalingo --app $AppName env-set DATABASE_URL=$pgUrl
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to set DATABASE_URL."
        exit 1
    }
    Write-Host "DATABASE_URL set." -ForegroundColor Green
}

function Run-DjangoMigrations {
    param(
        [string]$AppName
    )

    Write-Host "Running Django migrations on Scalingo app '$AppName'..." -ForegroundColor Cyan
    scalingo --app $AppName run python manage.py migrate --noinput
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Migrations failed. Check Scalingo logs for details."
        exit 1
    }
    Write-Host "Migrations completed successfully." -ForegroundColor Green
}

function Restart-App {
    param(
        [string]$AppName
    )

    Write-Host "Restarting app '$AppName'..." -ForegroundColor Cyan
    scalingo --app $AppName restart
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "App restart command failed. You may need to restart from the Scalingo dashboard."
    } else
    {
        Write-Host "App restart triggered." -ForegroundColor Green
    }
}

Ensure-ScalingoCli
Ensure-ScalingoLogin
Ensure-PostgresAddon -AppName $AppName
Ensure-DatabaseUrlEnv -AppName $AppName
Run-DjangoMigrations -AppName $AppName
Restart-App -AppName $AppName

Write-Host "=== Done. Your app should now use PostgreSQL on Scalingo. ===" -ForegroundColor Cyan

