@echo off
REM 每周把全量数据库快照发布到 GitHub Release "data-latest"（供任务计划调用）
cd /d D:\claude
if not exist logs mkdir logs
echo ============ %DATE% %TIME% ============ >> logs\snapshot.log
python scripts\publish_snapshot.py >> logs\snapshot.log 2>&1
