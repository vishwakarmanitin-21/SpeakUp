Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.Run """" & WshShell.CurrentDirectory & "\.venv\Scripts\pythonw.exe"" -m src.main", 0, False
