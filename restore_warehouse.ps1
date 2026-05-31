param(
    [string] $DatabaseUrl = $(if ($env:CHARGE_RATE_DATABASE_URL) { $env:CHARGE_RATE_DATABASE_URL } else { "postgresql://postgres:postgres@localhost:5432/charge_rate" }),
    [string] $BackupDir = $(Join-Path $env:LOCALAPPDATA "chargeRateWidget\warehouse_backups"),
    [string] $BackupPath,
    [string] $PgRestorePath,
    [switch] $Force
)

$ErrorActionPreference = "Stop"

function Resolve-PostgresTool {
    param(
        [string] $ToolName,
        [string] $ExplicitPath
    )

    if ($ExplicitPath) {
        if (-not (Test-Path -LiteralPath $ExplicitPath)) {
            throw "Postgres tool not found: $ExplicitPath"
        }
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }

    $command = Get-Command $ToolName -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $defaultPath = Join-Path "C:\Program Files\PostgreSQL\16\bin" $ToolName
    if (Test-Path -LiteralPath $defaultPath) {
        return $defaultPath
    }

    throw "$ToolName was not found. Add PostgreSQL bin to PATH or pass -PgRestorePath."
}

if (-not $Force) {
    throw "Restore is destructive. Re-run with -Force after confirming the target database is correct."
}

if (-not $BackupPath) {
    $latestPath = Join-Path $BackupDir "latest.txt"
    if (Test-Path -LiteralPath $latestPath) {
        $BackupPath = (Get-Content -LiteralPath $latestPath -Raw).Trim()
    } else {
        $latestBackup = Get-ChildItem -LiteralPath $BackupDir -Filter "charge_rate_warehouse_*.dump" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($latestBackup) {
            $BackupPath = $latestBackup.FullName
        }
    }
}

if (-not $BackupPath -or -not (Test-Path -LiteralPath $BackupPath)) {
    throw "Backup file not found. Pass -BackupPath or create a backup first."
}

$pgRestore = Resolve-PostgresTool -ToolName "pg_restore.exe" -ExplicitPath $PgRestorePath
$resolvedBackupPath = (Resolve-Path -LiteralPath $BackupPath).Path

& $pgRestore `
    --clean `
    --if-exists `
    --no-owner `
    --dbname=$DatabaseUrl `
    $resolvedBackupPath

if ($LASTEXITCODE -ne 0) {
    throw "pg_restore failed with exit code $LASTEXITCODE"
}

Write-Output "Restored warehouse backup: $resolvedBackupPath"
