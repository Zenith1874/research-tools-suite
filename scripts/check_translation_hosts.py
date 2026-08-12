#!/usr/bin/env python3
"""Read-only GPU probe for the research tools' allowed cluster hosts."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess

# 从无窗进程(pythonw server)里 spawn 控制台程序时防止弹窗;非 Windows 为 0 无副作用
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
import tempfile
from pathlib import Path


DEFAULT_HOSTS = (
    'iverson.cs.nmsu.edu',
    'keller.cs.nmsu.edu',
    'lovelace.cs.nmsu.edu',
    'newton.cs.nmsu.edu',
    'riemann.cs.nmsu.edu',
)


def _discover_windows_ssh() -> dict[str, str]:
    """Find the current Windows user's SSH files when running inside WSL."""
    if os.name != 'posix' or shutil.which('powershell.exe') is None or shutil.which('wslpath') is None:
        return {}
    try:
        completed = subprocess.run(
            ['powershell.exe', '-NoProfile', '-Command', '[Environment]::GetFolderPath("UserProfile")'],
            text=True, capture_output=True, timeout=8, check=True,
        )
        windows_profile = completed.stdout.strip().replace('\r', '')
        converted = subprocess.run(
            ['wslpath', '-u', windows_profile], text=True, capture_output=True,
            timeout=5, check=True,
        ).stdout.strip()
    except Exception:
        return {}
    ssh_dir = Path(converted) / '.ssh'
    candidates = {
        'identity': ssh_dir / 'id_ed25519',
        'ssh_config': ssh_dir / 'config',
        'known_hosts': ssh_dir / 'known_hosts',
    }
    return {key: str(path) for key, path in candidates.items() if path.is_file()}


def _ssh_base(args, temporary_identity: str | None) -> list[str]:
    command = ['ssh', '-o', 'BatchMode=yes', '-o', f'ConnectTimeout={args.timeout}']
    if args.ssh_config:
        command += ['-F', args.ssh_config]
    if temporary_identity:
        command += ['-i', temporary_identity, '-o', 'IdentitiesOnly=yes']
    if args.known_hosts:
        command += ['-o', f'UserKnownHostsFile={args.known_hosts}', '-o', 'StrictHostKeyChecking=yes']
    return command


def probe(host: str, command: list[str]) -> dict:
    remote = (
        "hostname; "
        "nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu "
        "--format=csv,noheader,nounits; "
        "df -Pk /home/simurghnobackup/zcui | tail -1"
    )
    try:
        completed = subprocess.run(
            command + [host, remote], text=True, capture_output=True, timeout=25,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return {'host': host, 'reachable': False, 'error': ['SSH probe timed out']}
    if completed.returncode:
        return {'host': host, 'reachable': False, 'error': completed.stderr.strip().splitlines()[-1:]}
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    hostname = lines[0] if lines else host
    gpu_rows = []
    disk = None
    for line in lines[1:]:
        fields = [field.strip() for field in line.split(',')]
        if len(fields) == 5 and fields[0].isdigit():
            try:
                gpu_rows.append({
                    'index': int(fields[0]), 'name': fields[1], 'memory_total_mib': int(fields[2]),
                    'memory_used_mib': int(fields[3]), 'utilization_percent': int(fields[4]),
                })
            except ValueError:
                continue
        elif len(line.split()) >= 6 and line.split()[1].isdigit():
            disk_fields = line.split()
            disk = {'available_kib': int(disk_fields[3]), 'used_percent': disk_fields[4]}
    return {'host': host, 'hostname': hostname, 'reachable': True, 'gpus': gpu_rows, 'disk': disk}


def choose_recommendation(rows: list[dict], max_used_mib: int, max_utilization: int) -> dict | None:
    """Annotate GPU rows with idle state and return the least-used eligible GPU."""
    candidates = []
    for row in rows:
        for gpu in row.get('gpus') or []:
            gpu['idle'] = (gpu['memory_used_mib'] <= max_used_mib and
                           gpu['utilization_percent'] <= max_utilization)
            if gpu['idle']:
                candidates.append((gpu['memory_used_mib'], gpu['utilization_percent'],
                                   row['host'], gpu['index']))
    candidates.sort()
    if not candidates:
        return None
    _, _, host, gpu_index = candidates[0]
    return {'host': host, 'gpu_index': gpu_index}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hosts', nargs='+', default=list(DEFAULT_HOSTS))
    parser.add_argument('--max-used-mib', type=int, default=1024)
    parser.add_argument('--max-utilization', type=int, default=10)
    parser.add_argument('--timeout', type=int, default=10)
    parser.add_argument('--ssh-config')
    parser.add_argument('--identity', help='Private key; copied to a mode-0600 temporary file for WSL/DrvFS compatibility')
    parser.add_argument('--known-hosts')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    if shutil.which('ssh') is None:
        parser.error('ssh executable not found')
    native_identity = Path.home() / '.ssh' / 'id_ed25519'
    if not args.identity and not native_identity.is_file():
        discovered = _discover_windows_ssh()
        args.identity = discovered.get('identity')
        args.ssh_config = args.ssh_config or discovered.get('ssh_config')
        args.known_hosts = args.known_hosts or discovered.get('known_hosts')
    # WSL can inherit a Windows TEMP path mounted with mode 0777. OpenSSH then
    # rejects the copied private key, so prefer the real POSIX /tmp directory.
    secure_temp_root = '/tmp' if os.name == 'posix' and Path('/tmp').is_dir() else None
    with tempfile.TemporaryDirectory(prefix='translation-host-probe-', dir=secure_temp_root) as temp_dir:
        temporary_identity = None
        if args.identity:
            source = Path(args.identity).expanduser()
            temporary_identity = str(Path(temp_dir) / 'identity')
            shutil.copyfile(source, temporary_identity)
            os.chmod(temporary_identity, 0o600)
        command = _ssh_base(args, temporary_identity)
        rows = [probe(host, command) for host in args.hosts]

    recommendation = choose_recommendation(rows, args.max_used_mib, args.max_utilization)
    payload = {
        'checked_hosts': rows,
        'thresholds': {'max_used_mib': args.max_used_mib, 'max_utilization': args.max_utilization},
        'recommendation': recommendation,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            if not row.get('reachable'):
                print(f"{row['host']}: unreachable")
                continue
            for gpu in row.get('gpus') or []:
                state = 'IDLE' if gpu['idle'] else 'BUSY'
                print(f"{row['host']} GPU {gpu['index']} {gpu['name']}: {state}; "
                      f"memory={gpu['memory_used_mib']}/{gpu['memory_total_mib']} MiB; "
                      f"util={gpu['utilization_percent']}%")
        print('recommendation:', recommendation or 'no idle GPU')
    return 0 if recommendation else 2


if __name__ == '__main__':
    raise SystemExit(main())
