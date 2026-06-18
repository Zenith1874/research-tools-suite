@echo off
echo 启动研究工具集成服务...
cd /d "%~dp0"
start "" "http://localhost:5001"
python server.py
pause
