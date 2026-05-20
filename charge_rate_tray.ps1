$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $repoRoot "logs"
$widgetScript = Join-Path $repoRoot "charge_rate_widget.py"
$overlayScript = Join-Path $repoRoot "charge_rate_overlay.py"
$icoIcon = Join-Path $repoRoot "icon.ico"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"
$script:monitorProcess = $null
$script:overlayProcess = $null

function Resolve-PythonRunner {
    if (Test-Path -LiteralPath $venvPython) {
        return (Resolve-Path -LiteralPath $venvPython).Path
    }

    $python = Get-Command "python" -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }

    if (Test-Path -LiteralPath $venvPythonw) {
        return (Resolve-Path -LiteralPath $venvPythonw).Path
    }

    return (Get-Command "pythonw" -ErrorAction Stop).Source
}

function Format-ArgumentList {
    param([string[]] $Arguments)

    return ($Arguments | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' }) -join " "
}

function Start-PythonScript {
    param(
        [string] $ScriptPath,
        [string[]] $Arguments = @()
    )

    $allArguments = @($ScriptPath) + $Arguments
    return Start-Process `
        -FilePath $pythonRunner `
        -ArgumentList (Format-ArgumentList -Arguments $allArguments) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -PassThru
}

function Get-ScriptProcesses {
    param([string] $ScriptPath)

    $resolvedPath = (Resolve-Path -LiteralPath $ScriptPath).Path
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.IndexOf($resolvedPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        }
}

function Test-ScriptRunning {
    param([string] $ScriptPath)

    return $null -ne (Get-ScriptProcesses -ScriptPath $ScriptPath | Select-Object -First 1)
}

function Stop-ScriptProcesses {
    param([string] $ScriptPath)

    Get-ScriptProcesses -ScriptPath $ScriptPath | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Start-Monitor {
    if (-not (Test-ScriptRunning -ScriptPath $widgetScript)) {
        $script:monitorProcess = Start-PythonScript `
            -ScriptPath $widgetScript `
            -Arguments @("--interval", "2", "--no-overlay")
    }
}

function Stop-Monitor {
    Stop-ScriptProcesses -ScriptPath $widgetScript
    $script:monitorProcess = $null
}

function Show-Overlay {
    if (-not (Test-ScriptRunning -ScriptPath $overlayScript)) {
        $script:overlayProcess = Start-PythonScript -ScriptPath $overlayScript
    }
}

function Hide-Overlay {
    Stop-ScriptProcesses -ScriptPath $overlayScript
    $script:overlayProcess = $null
}

function Toggle-Overlay {
    if (Test-ScriptRunning -ScriptPath $overlayScript) {
        Hide-Overlay
    } else {
        Show-Overlay
    }
    Update-MenuText
}

function Toggle-Monitor {
    if (Test-ScriptRunning -ScriptPath $widgetScript) {
        Stop-Monitor
    } else {
        Start-Monitor
    }
    Update-MenuText
}

function Update-MenuText {
    if (Test-ScriptRunning -ScriptPath $widgetScript) {
        $monitorItem.Text = "Stop Monitor"
    } else {
        $monitorItem.Text = "Start Monitor"
    }

    if (Test-ScriptRunning -ScriptPath $overlayScript) {
        $overlayItem.Text = "Hide Overlay"
    } else {
        $overlayItem.Text = "Show Overlay"
    }
}

$pythonRunner = Resolve-PythonRunner

$notifyIcon = New-Object System.Windows.Forms.NotifyIcon
$notifyIcon.Text = "Charge Rate Widget"
if (Test-Path -LiteralPath $icoIcon) {
    $notifyIcon.Icon = New-Object System.Drawing.Icon $icoIcon
} else {
    $notifyIcon.Icon = [System.Drawing.SystemIcons]::Information
}
$notifyIcon.Visible = $true

$contextMenu = New-Object System.Windows.Forms.ContextMenuStrip
$monitorItem = $contextMenu.Items.Add("Start Monitor")
$overlayItem = $contextMenu.Items.Add("Show Overlay")
[void] $contextMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
$openLogsItem = $contextMenu.Items.Add("Open Logs Folder")
[void] $contextMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
$exitItem = $contextMenu.Items.Add("Exit")

$monitorItem.Add_Click({ Toggle-Monitor })
$overlayItem.Add_Click({ Toggle-Overlay })
$openLogsItem.Add_Click({ Start-Process explorer.exe -ArgumentList (Format-ArgumentList -Arguments @($logDir)) })
$exitItem.Add_Click({
    Hide-Overlay
    Stop-Monitor
    $notifyIcon.Visible = $false
    $notifyIcon.Dispose()
    [System.Windows.Forms.Application]::Exit()
})
$contextMenu.Add_Opening({ Update-MenuText })
$notifyIcon.Add_DoubleClick({ Toggle-Overlay })
$notifyIcon.ContextMenuStrip = $contextMenu

Start-Monitor
Update-MenuText
$notifyIcon.ShowBalloonTip(
    2000,
    "Charge Rate Widget",
    "Monitoring started. Right-click for overlay controls.",
    [System.Windows.Forms.ToolTipIcon]::Info
)

[System.Windows.Forms.Application]::Run()
