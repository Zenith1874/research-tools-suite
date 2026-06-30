@echo off
REM 服务器看门狗：手动启动监控(连续 health 失败自动重启 server.py)。
REM 直接双击或命令行运行；Ctrl+C 停止。开机自启见 watchdog.py 末尾说明。
cd /d "%~dp0\.."
python "%~dp0watchdog.py" --start-if-down %*
