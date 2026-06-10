Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\user\Downloads\클로드코드폴더"
WshShell.Run """C:\Users\user\AppData\Local\Programs\Python\Python314\python.exe"" briefing.py", 1, False
Set WshShell = Nothing
