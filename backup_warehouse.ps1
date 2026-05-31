param(
    [string] $DatabaseUrl = $(if ($env:CHARGE_RATE_DATABASE_URL) { $env:CHARGE_RATE_DATABASE_URL } else { "postgresql://postgres:postgres@localhost:5432/charge_rate" }),
    [string] $BackupDir = $(Join-Path $env:LOCALAPPDATA "chargeRateWidget\warehouse_backups"),
    [int] $Keep = 28,
    [string] $PgDumpPath
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

    throw "$ToolName was not found. Add PostgreSQL bin to PATH or pass -PgDumpPath."
}

function Redact-DatabaseUrl {
    param([string] $Url)

    return [regex]::Replace($Url, "://([^:/@]+):([^@]+)@", '://$1:***@')
}

$pgDump = Resolve-PostgresTool -ToolName "pg_dump.exe" -ExplicitPath $PgDumpPath
$backupDirItem = New-Item -ItemType Directory -Force -Path $BackupDir
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupPath = Join-Path $backupDirItem.FullName "charge_rate_warehouse_$timestamp.dump"
$manifestPath = "$backupPath.json"
$latestPath = Join-Path $backupDirItem.FullName "latest.txt"

& $pgDump `
    --format=custom `
    --compress=9 `
    --file=$backupPath `
    $DatabaseUrl

if ($LASTEXITCODE -ne 0) {
    throw "pg_dump failed with exit code $LASTEXITCODE"
}

$backupItem = Get-Item -LiteralPath $backupPath
$manifest = [ordered] @{
    created_at = (Get-Date).ToString("o")
    backup_path = $backupItem.FullName
    database_url = (Redact-DatabaseUrl -Url $DatabaseUrl)
    format = "pg_dump custom"
    pg_dump = $pgDump
    size_bytes = $backupItem.Length
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Set-Content -LiteralPath $latestPath -Value $backupItem.FullName -Encoding UTF8

if ($Keep -gt 0) {
    $oldBackups = Get-ChildItem -LiteralPath $backupDirItem.FullName -Filter "charge_rate_warehouse_*.dump" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $Keep

    foreach ($oldBackup in $oldBackups) {
        Remove-Item -LiteralPath $oldBackup.FullName -Force
        $oldManifest = "$($oldBackup.FullName).json"
        if (Test-Path -LiteralPath $oldManifest) {
            Remove-Item -LiteralPath $oldManifest -Force
        }
    }
}

Write-Output "Wrote warehouse backup: $($backupItem.FullName)"
