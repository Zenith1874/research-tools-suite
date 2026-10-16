@echo off
REM Wrapper for scripts/drain_llm_backlog.py, used by Task Scheduler.
REM
REM ASCII only, deliberately. cmd.exe reads batch files in the system ANSI
REM codepage (GBK here), so UTF-8 comments come back as mojibake and cmd then
REM tries to execute the garbage as a command.
REM
REM PYTHONIOENCODING is required, not cosmetic: under Task Scheduler the console
REM codepage is GBK, which cannot encode the Yen sign the script prints, and the
REM run dies on UnicodeEncodeError before the first article. It also keeps the
REM log readable as UTF-8 instead of mixed encodings.
set PYTHONIOENCODING=utf-8
cd /d D:\claude
"C:\Users\cui10\AppData\Local\Programs\Python\Python312\python.exe" -u scripts\drain_llm_backlog.py %* >> logs\drain_llm_backlog.log 2>&1
