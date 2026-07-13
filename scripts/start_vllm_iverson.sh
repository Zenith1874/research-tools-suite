#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/simurghnobackup/zcui/astar_interest_14b_stageA
VENV=/home/simurghnobackup/zcui/venvs/reddit_env
export HF_HOME=/home/simurghnobackup/zcui/hf_cache
export HUGGINGFACE_HUB_CACHE="$HF_HOME/hub"
export CUDA_VISIBLE_DEVICES=0
export CPATH="/home/simurghnobackup/zcui/uv-python/cpython-3.13.12-linux-x86_64-gnu/include/python3.13${CPATH:+:$CPATH}"
export TRITON_CACHE_DIR=/tmp/zcui_triton_cache
export TORCHINDUCTOR_CACHE_DIR=/tmp/zcui_torchinductor_cache
export VLLM_CACHE_ROOT=/tmp/zcui_vllm_cache

cd "$ROOT"
source "$VENV/bin/activate"

if [[ -f logs/vllm.pid ]] && kill -0 "$(cat logs/vllm.pid)" 2>/dev/null; then
    echo "vLLM already running with PID $(cat logs/vllm.pid)"
    exit 0
fi

nohup python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-14B-Instruct-AWQ \
    --served-model-name Qwen/Qwen2.5-14B-Instruct-AWQ \
    --quantization awq \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.90 \
    --host 127.0.0.1 \
    --port 8000 \
    > logs/vllm.log 2>&1 &

echo $! > logs/vllm.pid
echo "started vLLM PID $(cat logs/vllm.pid); log=$ROOT/logs/vllm.log"
