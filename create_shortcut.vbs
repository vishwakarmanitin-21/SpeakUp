Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

strDesktop = WshShell.SpecialFolders("Desktop")
strProjectDir = fso.GetParentFolderName(WScript.ScriptFullName)

Set oShortcut = WshShell.CreateShortcut(strDesktop & "\SpeakUp.lnk")
oShortcut.TargetPath = strProjectDir & "\SpeakUp.vbs"
oShortcut.WorkingDirectory = strProjectDir
oShortcut.Description = "SpeakUp - Voice AI Assistant"
oShortcut.IconLocation = "shell32.dll,169"
oShortcut.Save

WScript.Echo "Shortcut created on Desktop!"
