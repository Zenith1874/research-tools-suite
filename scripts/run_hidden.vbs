' 隐藏窗口运行任意 bat/命令(供计划任务调用,避免弹出黑色控制台窗)。
' 用法: wscript.exe run_hidden.vbs "D:\claude\scripts\daily_update.bat"
' 防御:目标不存在或运行出错时静默退出,绝不弹对话框。
On Error Resume Next
If WScript.Arguments.Count < 1 Then WScript.Quit 0
Dim fso : Set fso = CreateObject("Scripting.FileSystemObject")
If Not fso.FileExists(WScript.Arguments(0)) Then WScript.Quit 0
Dim sh : Set sh = CreateObject("WScript.Shell")
sh.Run """" & WScript.Arguments(0) & """", 0, False
WScript.Quit 0
