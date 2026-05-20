param(
    [ValidateSet("tray", "all_icons")]
    [string] $Mode = "tray"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath("Desktop")
$widgetScript = Join-Path $repoRoot "charge_rate_widget.py"
$overlayScript = Join-Path $repoRoot "charge_rate_overlay.py"
$trayLauncher = Join-Path $repoRoot "start_charge_rate_tray.vbs"
$pngIcon = Join-Path $repoRoot "icon.png"
$icoIcon = Join-Path $repoRoot "icon.ico"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"

Add-Type -AssemblyName System.Drawing

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
        [string] $Arguments,
        [string] $IconPath
    )

    $shell = New-Object -ComObject WScript.Shell
    $shortcutPath = Join-Path $desktop "$Name.lnk"
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $repoRoot
    $shortcut.Description = $Name
    if ($IconPath -and (Test-Path -LiteralPath $IconPath)) {
        $shortcut.IconLocation = "$IconPath,0"
    }
    $shortcut.Save()
    Write-Host "Created $shortcutPath"
}

function Remove-LegacyShortcuts {
    $legacyShortcut = Join-Path $desktop "Charge Rate Tray.lnk"
    if (Test-Path -LiteralPath $legacyShortcut) {
        Remove-Item -LiteralPath $legacyShortcut -Force
        Write-Host "Removed $legacyShortcut"
    }
}

function Write-UInt16 {
    param(
        [System.IO.BinaryWriter] $Writer,
        [int] $Value
    )

    $Writer.Write([uint16] $Value)
}

function Write-UInt32 {
    param(
        [System.IO.BinaryWriter] $Writer,
        [long] $Value
    )

    $Writer.Write([uint32] $Value)
}

function Convert-PngToIco {
    param(
        [string] $PngPath,
        [string] $IcoPath
    )

    if (-not (Test-Path -LiteralPath $PngPath)) {
        return $null
    }

    if ((Test-Path -LiteralPath $IcoPath) -and
        ((Get-Item -LiteralPath $IcoPath).LastWriteTime -ge (Get-Item -LiteralPath $PngPath).LastWriteTime)) {
        return $IcoPath
    }

    $sourceImage = [System.Drawing.Image]::FromFile($PngPath)
    $bitmap = $null
    $graphics = $null
    $pngStream = New-Object System.IO.MemoryStream
    $icoStream = $null
    $writer = $null

    try {
        $size = [Math]::Min(256, [Math]::Max($sourceImage.Width, $sourceImage.Height))
        $bitmap = New-Object System.Drawing.Bitmap $size, $size
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

        $scale = [Math]::Min($size / $sourceImage.Width, $size / $sourceImage.Height)
        $drawWidth = [int] [Math]::Round($sourceImage.Width * $scale)
        $drawHeight = [int] [Math]::Round($sourceImage.Height * $scale)
        $drawX = [int] [Math]::Round(($size - $drawWidth) / 2)
        $drawY = [int] [Math]::Round(($size - $drawHeight) / 2)
        $graphics.DrawImage($sourceImage, $drawX, $drawY, $drawWidth, $drawHeight)
        $bitmap.Save($pngStream, [System.Drawing.Imaging.ImageFormat]::Png)

        $pngBytes = $pngStream.ToArray()
        $icoStream = [System.IO.File]::Create($IcoPath)
        $writer = New-Object System.IO.BinaryWriter $icoStream

        Write-UInt16 -Writer $writer -Value 0
        Write-UInt16 -Writer $writer -Value 1
        Write-UInt16 -Writer $writer -Value 1
        $iconSize = if ($size -ge 256) { 0 } else { $size }
        $writer.Write([byte] $iconSize)
        $writer.Write([byte] $iconSize)
        $writer.Write([byte] 0)
        $writer.Write([byte] 0)
        Write-UInt16 -Writer $writer -Value 1
        Write-UInt16 -Writer $writer -Value 32
        Write-UInt32 -Writer $writer -Value $pngBytes.Length
        Write-UInt32 -Writer $writer -Value 22
        $writer.Write($pngBytes)
        Write-Host "Created $IcoPath"
        return $IcoPath
    } finally {
        if ($writer) { $writer.Dispose() }
        if ($icoStream) { $icoStream.Dispose() }
        if ($pngStream) { $pngStream.Dispose() }
        if ($graphics) { $graphics.Dispose() }
        if ($bitmap) { $bitmap.Dispose() }
        if ($sourceImage) { $sourceImage.Dispose() }
    }
}

$iconPath = Convert-PngToIco -PngPath $pngIcon -IcoPath $icoIcon
$python = Resolve-Python -VenvPath $venvPython -CommandName "python"
$pythonw = Resolve-Python -VenvPath $venvPythonw -CommandName "pythonw"
$wscript = (Get-Command wscript.exe -ErrorAction Stop).Source

Remove-LegacyShortcuts

if ($Mode -eq "all_icons") {
    New-ChargeRateShortcut `
        -Name "Charge Rate Widget" `
        -TargetPath $python `
        -Arguments "`"$widgetScript`" --interval 2" `
        -IconPath $iconPath

    New-ChargeRateShortcut `
        -Name "Charge Rate Widget (Hidden Overlay)" `
        -TargetPath $python `
        -Arguments "`"$widgetScript`" --interval 2 --no-overlay" `
        -IconPath $iconPath

    New-ChargeRateShortcut `
        -Name "Show Charge Rate Overlay" `
        -TargetPath $pythonw `
        -Arguments "`"$overlayScript`"" `
        -IconPath $iconPath
}

New-ChargeRateShortcut `
    -Name "Charge Rate Tray Widget" `
    -TargetPath $wscript `
    -Arguments "`"$trayLauncher`"" `
    -IconPath $iconPath
