#!/usr/bin/env python3
"""Safely start or stop the paper-translation vLLM on an eligible cluster host."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .check_translation_hosts import (
        DEFAULT_HOSTS, _discover_windows_ssh, _ssh_base, choose_recommendation, probe,
    )
else:
    from check_translation_hosts import (  # type: ignore
        DEFAULT_HOSTS, _discover_windows_ssh, _ssh_base, choose_recommendation, probe,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = REPO_ROOT / 'data' / 'translation_runtime.json'
DEPLOY_ROOT = '/home/simurghnobackup/zcui/paper_translation'
DEFAULT_TRANSLATION_HOST = 'iverson.cs.nmsu.edu'


def _complete_ssh_options(args) -> None:
    native_identity = Path.home() / '.ssh' / 'id_ed25519'
    if not args.identity and not native_identity.is_file():
        discovered = _discover_windows_ssh()
        args.identity = discovered.get('identity')
        args.ssh_config = args.ssh_config or discovered.get('ssh_config')
        args.known_hosts = args.known_hosts or discovered.get('known_hosts')


@contextmanager
def secure_ssh_command(args):
    """Yield SSH arguments with any DrvFS private key copied to POSIX mode 0600."""
    _complete_ssh_options(args)
    secure_temp_root = '/tmp' if os.name == 'posix' and Path('/tmp').is_dir() else None
    with tempfile.TemporaryDirectory(prefix='translation-vllm-', dir=secure_temp_root) as temp_dir:
        temporary_identity = None
        if args.identity:
            source = Path(args.identity).expanduser()
            temporary_identity = str(Path(temp_dir) / 'identity')
            shutil.copyfile(source, temporary_identity)
            os.chmod(temporary_identity, 0o600)
        yield _ssh_base(args, temporary_identity)


def save_runtime_state(host: str, gpu_index: int) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'host': host,
        'gpu_index': gpu_index,
        'deploy_root': DEPLOY_ROOT,
        'started_at_utc': datetime.now(timezone.utc).isoformat(),
    }
    temporary = STATE_PATH.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, STATE_PATH)


def load_runtime_state() -> dict:
    if not STATE_PATH.is_file():
        return {}
    try:
        payload = json.loads(STATE_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def run_remote(command: list[str], host: str, remote_command: str) -> int:
    completed = subprocess.run(command + [host, remote_command], text=True)
    return completed.returncode


def select_host(args, command: list[str]) -> tuple[str, int]:
    hosts = list(DEFAULT_HOSTS) if args.host == 'auto' else [args.host]
    rows = [probe(host, command) for host in hosts]
    recommendation = choose_recommendation(rows, args.max_used_mib, args.max_utilization)
    for row in rows:
        if not row.get('reachable'):
            print(f"{row['host']}: unreachable")
            continue
        for gpu in row.get('gpus') or []:
            state = 'IDLE' if gpu['idle'] else 'BUSY'
            print(f"{row['host']} GPU {gpu['index']}: {state}; "
                  f"memory={gpu['memory_used_mib']}/{gpu['memory_total_mib']} MiB; "
                  f"util={gpu['utilization_percent']}%")
    if args.gpu_index is not None:
        if args.host == 'auto':
            raise RuntimeError('--gpu-index requires an explicit --host')
        requested = next((gpu for row in rows if row.get('reachable')
                          for gpu in row.get('gpus') or []
                          if row['host'] == args.host and gpu['index'] == args.gpu_index), None)
        if not requested or not requested['idle']:
            raise RuntimeError(f'{args.host} GPU {args.gpu_index} is not eligible or was not found')
        return args.host, args.gpu_index
    if not recommendation:
        raise RuntimeError('no eligible idle GPU; nothing was started')
    return recommendation['host'], recommendation['gpu_index']


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'stop'))
    parser.add_argument(
        '--host', default=None,
        help='Cluster FQDN; start defaults to recorded host, then iverson. Use "auto" explicitly for multi-host selection.',
    )
    parser.add_argument('--gpu-index', type=int)
    parser.add_argument('--max-used-mib', type=int, default=1024)
    parser.add_argument('--max-utilization', type=int, default=10)
    parser.add_argument('--timeout', type=int, default=10)
    parser.add_argument('--ssh-config')
    parser.add_argument('--identity')
    parser.add_argument('--known-hosts')
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if shutil.which('ssh') is None:
        raise SystemExit('ssh executable not found')
    state = load_runtime_state()
    if args.action == 'start':
        args.host = args.host or state.get('host') or DEFAULT_TRANSLATION_HOST
    else:
        args.host = args.host or state.get('host')
        if not args.host:
            raise SystemExit('no recorded translation host; pass --host explicitly')

    with secure_ssh_command(args) as command:
        if args.action == 'start':
            try:
                host, gpu_index = select_host(args, command)
            except RuntimeError as exc:
                print(f'Not started: {exc}')
                return 2
            print(f'Selected {host} GPU {gpu_index}.')
            remote = (f'TRANSLATION_GPU_INDEX={gpu_index} '
                      f'{DEPLOY_ROOT}/start_translation_vllm.sh')
            status = run_remote(command, host, remote)
            if status == 0:
                save_runtime_state(host, gpu_index)
                print('Model start requested. Open the tunnel with: scripts/start_translation_tunnel.sh')
            return status

        status = run_remote(command, args.host, f'{DEPLOY_ROOT}/stop_translation_vllm.sh')
        if status == 0 and STATE_PATH.is_file():
            STATE_PATH.unlink()
        return status


if __name__ == '__main__':
    raise SystemExit(main())
