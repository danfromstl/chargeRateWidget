param(
    [string] $TaskName = "ChargeRateWidget Warehouse Backup",
    [int] $IntervalHours = 6,
    [int] $Keep = 28,
    [string] $DatabaseUrl = $(if ($env:CHARGE_RATE_DATABASE_URL) { $env:CHARGE_RATE_DATABASE_URL } else { "postgresql://postgres:postgres@localhost:5432/charge_rate" }),
    [string] $BackupDir = $(Join-Path $env:LOCALAPPDATA "chargeRateWidget\warehouse_backups")
)

$ErrorActionPreference = "Stop"

if ($IntervalHours -lt 1) {
    throw "IntervalHours must be at least 1."
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backupScript = Join-Path $repoRoot "backup_warehouse.ps1"
if (-not (Test-Path -LiteralPath $backupScript)) {
    throw "Backup script not found: $backupScript"
}

$actionArguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$backupScript`"",
    "-DatabaseUrl", "`"$DatabaseUrl`"",
    "-BackupDir", "`"$BackupDir`"",
    "-Keep", "$Keep"
) -join " "

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArguments
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Creates periodic pg_dump snapshots for the Charge Rate Widget warehouse." `
    -Force | Out-Null

Write-Output "Registered scheduled task: $TaskName"
Write-Output "Backup directory: $BackupDir"
