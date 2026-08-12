#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT=${TRANSLATION_DEPLOY_ROOT:-/home/simurghnobackup/zcui/paper_translation}
pid_file="$DEPLOY_ROOT/logs/vllm.pid"
if [[ ! -f "$pid_file" ]]; then
    echo "No translation vLLM PID file found."
    exit 0
fi
pid=$(<"$pid_file")
if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
    echo "Invalid PID file; refusing to signal any process."
    exit 2
fi
if ! kill -0 "$pid" 2>/dev/null; then
    echo "Translation vLLM is not running (stale PID $pid)."
    exit 0
fi
command_line=$(ps -p "$pid" -o args=)
if [[ "$command_line" != *vllm.entrypoints.openai.api_server* ]]; then
    echo "PID $pid is not the expected vLLM process; refusing to stop it."
    exit 3
fi
kill "$pid"
for _ in {1..30}; do
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "Stopped translation vLLM PID $pid."
        exit 0
    fi
    sleep 1
done
echo "vLLM did not stop within 30 seconds; manual review required."
exit 4
