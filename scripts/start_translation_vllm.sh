#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT=${TRANSLATION_DEPLOY_ROOT:-/home/simurghnobackup/zcui/paper_translation}
VENV=${TRANSLATION_VLLM_VENV:-/home/simurghnobackup/zcui/venvs/reddit_env}
MODEL=${TRANSLATION_MODEL:-Qwen/Qwen3-14B-AWQ}
PORT=${TRANSLATION_REMOTE_PORT:-8000}
GPU_INDEX=${TRANSLATION_GPU_INDEX:-0}
MAX_USED_MIB=${TRANSLATION_MAX_USED_MIB:-1024}
MAX_UTILIZATION=${TRANSLATION_MAX_UTILIZATION:-10}

mkdir -p "$DEPLOY_ROOT/logs"
used_util=$(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits -i "$GPU_INDEX" | tr -d ' ')
IFS=',' read -r used_mib utilization <<< "$used_util"
if [[ ${TRANSLATION_FORCE_START:-0} != 1 ]] && (( used_mib > MAX_USED_MIB || utilization > MAX_UTILIZATION )); then
    echo "Refusing to start: GPU $GPU_INDEX is busy (memory=${used_mib}MiB, utilization=${utilization}%)."
    exit 2
fi

pid_file="$DEPLOY_ROOT/logs/vllm.pid"
if [[ -f "$pid_file" ]]; then
    old_pid=$(<"$pid_file")
    if [[ "$old_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
        echo "Translation vLLM is already running with PID $old_pid."
        exit 0
    fi
fi

if [[ ! -x "$VENV/bin/python" ]]; then
    echo "vLLM environment not found: $VENV"
    exit 3
fi

export HF_HOME=${TRANSLATION_HF_HOME:-/home/simurghnobackup/zcui/.cache/huggingface}
export HUGGINGFACE_HUB_CACHE=${TRANSLATION_HUGGINGFACE_HUB_CACHE:-$HF_HOME/hub}
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-$GPU_INDEX}
export CPATH="/home/simurghnobackup/zcui/uv-python/cpython-3.13.12-linux-x86_64-gnu/include/python3.13${CPATH:+:$CPATH}"
export TRITON_CACHE_DIR=${TRITON_CACHE_DIR:-/tmp/zcui_translation_triton}
export TORCHINDUCTOR_CACHE_DIR=${TORCHINDUCTOR_CACHE_DIR:-/tmp/zcui_translation_torchinductor}
export VLLM_CACHE_ROOT=${VLLM_CACHE_ROOT:-/tmp/zcui_translation_vllm}

cd "$DEPLOY_ROOT"
nohup "$VENV/bin/python" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --served-model-name "$MODEL" \
    --quantization awq \
    --max-model-len 8192 \
    --max-num-seqs 4 \
    --gpu-memory-utilization 0.90 \
    --enable-prefix-caching \
    --host 127.0.0.1 \
    --port "$PORT" \
    > "$DEPLOY_ROOT/logs/vllm.log" 2>&1 &

new_pid=$!
printf '%s\n' "$new_pid" > "$pid_file"
echo "Started translation vLLM PID $new_pid; model=$MODEL; log=$DEPLOY_ROOT/logs/vllm.log"
