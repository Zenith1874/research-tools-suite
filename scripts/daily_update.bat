@echo off
REM A* 研究雷达每日增量更新（供 Windows 任务计划调用，不依赖 server.py 是否在运行）
REM 抓最近 14 天，去重；日志追加到 logs\daily_update.log
cd /d D:\claude
if not exist logs mkdir logs
echo ============ %DATE% %TIME% ============ >> logs\daily_update.log
REM 如需 OpenAlex/Crossref polite pool，取消下一行注释并填你的邮箱
REM set ASTAR_MAILTO=you@example.com
python scripts\update_abdc_astar.py --mode daily_incremental --days 14 >> logs\daily_update.log 2>&1
echo done %TIME% >> logs\daily_update.log
