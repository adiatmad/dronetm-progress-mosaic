Option Explicit
Dim shell, fso, root, ps1, powershell, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = fso.BuildPath(root, "update_and_run.ps1")
powershell = shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
If Not fso.FileExists(ps1) Then
  MsgBox "update_and_run.ps1 was not found beside this launcher.", vbCritical, "DroneTM Progress Mosaic"
  WScript.Quit 1
End If
If Not fso.FileExists(powershell) Then
  MsgBox "Windows PowerShell was not found at its standard Windows path.", vbCritical, "DroneTM Progress Mosaic"
  WScript.Quit 1
End If
command = """" & powershell & """ -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """"
shell.CurrentDirectory = root
shell.Run command, 1, False
