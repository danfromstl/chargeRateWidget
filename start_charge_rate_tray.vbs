Set fileSystem = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fileSystem.GetParentFolderName(WScript.ScriptFullName)
trayScript = fileSystem.BuildPath(scriptDir, "charge_rate_tray.ps1")

command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Quote(trayScript)
shell.Run command, 0, False

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
