#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
runtime_state="$script_dir/../data/translation_runtime.json"
recorded_host=
if [[ -z ${TRANSLATION_HOST:-} && -f "$runtime_state" ]] && command -v python3 >/dev/null 2>&1; then
    recorded_host=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("host", ""))' "$runtime_state" 2>/dev/null || true)
fi
HOST=${TRANSLATION_HOST:-${recorded_host:-iverson.cs.nmsu.edu}}
LOCAL_PORT=${TRANSLATION_LOCAL_PORT:-18001}
REMOTE_PORT=${TRANSLATION_REMOTE_PORT:-8000}

ssh_args=()
identity_source=${TRANSLATION_SSH_IDENTITY:-}
ssh_config=${TRANSLATION_SSH_CONFIG:-}
known_hosts=${TRANSLATION_SSH_KNOWN_HOSTS:-}

if [[ -z "$identity_source" && ! -f ~/.ssh/id_ed25519 ]] && command -v powershell.exe >/dev/null 2>&1 \
        && command -v wslpath >/dev/null 2>&1; then
    windows_profile=$(powershell.exe -NoProfile -Command '[Environment]::GetFolderPath("UserProfile")' | tr -d '\r')
    windows_ssh_dir="$(wslpath -u "$windows_profile")/.ssh"
    [[ -f "$windows_ssh_dir/id_ed25519" ]] && identity_source="$windows_ssh_dir/id_ed25519"
    [[ -f "$windows_ssh_dir/config" ]] && ssh_config="$windows_ssh_dir/config"
    [[ -f "$windows_ssh_dir/known_hosts" ]] && known_hosts="$windows_ssh_dir/known_hosts"
fi

if [[ -n "$identity_source" ]]; then
    tunnel_key_dir=$(mktemp -d)
    trap 'unlink "$tunnel_key_dir/id_ed25519"; rmdir "$tunnel_key_dir"' EXIT
    install -m 600 "$identity_source" "$tunnel_key_dir/id_ed25519"
    ssh_args+=(-i "$tunnel_key_dir/id_ed25519" -o IdentitiesOnly=yes)
fi
[[ -n "$ssh_config" ]] && ssh_args+=(-F "$ssh_config")
if [[ -n "$known_hosts" ]]; then
    ssh_args+=(-o "UserKnownHostsFile=$known_hosts" -o StrictHostKeyChecking=yes)
fi

echo "Opening private tunnel 127.0.0.1:${LOCAL_PORT} -> ${HOST}:127.0.0.1:${REMOTE_PORT}"
echo "Keep this terminal open while translating; press Ctrl-C to close the tunnel."
ssh "${ssh_args[@]}" -N \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=60 \
    -o ServerAliveCountMax=3 \
    -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" \
    "$HOST"
