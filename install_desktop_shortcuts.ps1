$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath("Desktop")
$widgetScript = Join-Path $repoRoot "charge_rate_widget.py"
$overlayScript = Join-Path $repoRoot "charge_rate_overlay.py"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"

function Resolve-Python {
    param(
        [string] $VenvPath,
        [string] $CommandName
    )

    if (Test-Path -LiteralPath $VenvPath) {
        return (Resolve-Path -LiteralPath $VenvPath).Path
    }

    $command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    return (Get-Command python -ErrorAction Stop).Source
}

function New-ChargeRateShortcut {
    param(
        [string] $Name,
        [string] $TargetPath,
        [string] $Arguments
    )

    $shell = New-Object -ComObject WScript.Shell
    $shortcutPath = Join-Path $desktop "$Name.lnk"
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $repoRoot
    $shortcut.Description = $Name
    $shortcut.Save()
    Write-Host "Created $shortcutPath"
}

$python = Resolve-Python -VenvPath $venvPython -CommandName "python"
$pythonw = Resolve-Python -VenvPath $venvPythonw -CommandName "pythonw"

New-ChargeRateShortcut `
    -Name "Charge Rate Widget" `
    -TargetPath $python `
    -Arguments "`"$widgetScript`" --interval 2"

New-ChargeRateShortcut `
    -Name "Charge Rate Widget (Hidden Overlay)" `
    -TargetPath $python `
    -Arguments "`"$widgetScript`" --interval 2 --no-overlay"

New-ChargeRateShortcut `
    -Name "Show Charge Rate Overlay" `
    -TargetPath $pythonw `
    -Arguments "`"$overlayScript`""
