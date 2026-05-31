param(
    [string] $TaskName = "ChargeRateWidget Warehouse Backup"
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Unregistered scheduled task: $TaskName"
} else {
    Write-Output "Scheduled task not found: $TaskName"
}
