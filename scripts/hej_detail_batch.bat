@echo off
REM HigherEdJobs 正文增量补齐（供 Windows 任务计划调用）
REM
REM 板子按信誉限额发详情页：一轮约 60-90 条后开始返挑战页，放慢间隔没用，
REM 恢复靠时间（按小时）。所以这是增量任务，不是一次性跑批——每次跑一批就停，
REM 反复跑即可：已读的跳过、被挑战的下次重试、正文比库里短的不覆盖。
REM
REM 采集必须用真实浏览器（headless 会被识别返空白页），所以用 --offscreen
REM 把窗口挪到屏幕外，定时跑不会打断你。
REM
REM 建议：一天 3-4 次，间隔至少 3 小时。间隔太密只会被拒，采不到东西。
REM
REM 注册计划任务（每天 03:00 / 09:00 / 15:00 / 21:00）：
REM   schtasks /create /tn "HEJ detail backlog" /tr "D:\claude\scripts\hej_detail_batch.bat" ^
REM            /sc daily /st 03:00 /ri 360 /du 24:00 /f
REM 取消：
REM   schtasks /delete /tn "HEJ detail backlog" /f

cd /d D:\claude
if not exist logs mkdir logs
echo ============ %DATE% %TIME% ============ >> logs\hej_detail_batch.log
python scripts\hej_detail_batch.py --size 60 --delay 2500 --offscreen >> logs\hej_detail_batch.log 2>&1
echo done %TIME% >> logs\hej_detail_batch.log
