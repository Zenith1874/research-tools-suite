#!/usr/bin/env python3
"""Deploy and verify the offline audio worker on the shared nobackup volume."""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

if __package__:
    from .check_translation_hosts import _discover_windows_ssh, _ssh_base
else:
    from check_translation_hosts import _discover_windows_ssh, _ssh_base  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = '/home/simurghnobackup/zcui/audio_transcription'
REMOTE_PYTHON = '/home/simurghnobackup/zcui/venvs/reddit_env/bin/python'
REMOTE_VENDOR = f'{REMOTE_ROOT}/vendor-20260721'
ASR_MODEL = ('/home/simurghnobackup/zcui/.cache/huggingface/hub/'
             'models--Systran--faster-whisper-medium/snapshots/'
             '08e178d48790749d25932bbc082711ddcfdfbc4f')
DIARIZATION_MODEL = ('/home/simurghnobackup/zcui/.cache/huggingface/hub/'
                     'models--pyannote--speaker-diarization-community-1/snapshots/'
                     '3533c8cf8e369892e6b79ff1bf80f7b0286a54ee')


@contextmanager
def transport(timeout: int):
    args = SimpleNamespace(timeout=timeout, ssh_config=None, identity=None, known_hosts=None)
    native_identity = Path.home() / '.ssh' / 'id_ed25519'
    if not native_identity.is_file():
        discovered = _discover_windows_ssh()
        args.identity = discovered.get('identity')
        args.ssh_config = discovered.get('ssh_config')
        args.known_hosts = discovered.get('known_hosts')
    secure_temp_root = '/tmp' if os.name == 'posix' and Path('/tmp').is_dir() else None
    with tempfile.TemporaryDirectory(prefix='audio-deploy-ssh-', dir=secure_temp_root) as temp_dir:
        temporary_identity = None
        if args.identity:
            temporary_identity = str(Path(temp_dir) / 'identity')
            shutil.copyfile(Path(args.identity), temporary_identity)
            os.chmod(temporary_identity, 0o600)
        ssh = _ssh_base(args, temporary_identity)
        ssh[0] = shutil.which('ssh') or 'ssh'
        scp = [shutil.which('scp') or 'scp', *ssh[1:]]
        yield ssh, scp


def checked(command: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    completed = subprocess.run(command, text=True, timeout=timeout)
    if completed.returncode:
        raise RuntimeError(f'command failed with exit code {completed.returncode}')
    return completed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='keller.cs.nmsu.edu')
    parser.add_argument('--timeout', type=int, default=10)
    parser.add_argument('--install-dependencies', action='store_true')
    parser.add_argument('--migrate-key', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    if not shutil.which('ssh') or not shutil.which('scp'):
        raise SystemExit('ssh/scp executable not found')
    worker = REPO_ROOT / 'scripts' / 'audio_transcription_worker.py'
    migrator = REPO_ROOT / 'scripts' / 'migrate_audio_hf_token.py'
    constraints = REPO_ROOT / 'scripts' / 'audio_transcription_constraints.txt'
    with transport(args.timeout) as (ssh, scp):
        if not args.check_only:
            checked(ssh + [args.host,
                f'install -d -m 700 {REMOTE_ROOT} {REMOTE_ROOT}/bin '
                f'{REMOTE_VENDOR} {REMOTE_ROOT}/jobs {REMOTE_ROOT}/.secrets'])
            checked(scp + [str(worker), f'{args.host}:{REMOTE_ROOT}/bin/audio_transcription_worker.py'])
            checked(scp + [str(migrator), f'{args.host}:{REMOTE_ROOT}/bin/migrate_audio_hf_token.py'])
            checked(scp + [str(constraints), f'{args.host}:{REMOTE_ROOT}/constraints.txt'])
            checked(ssh + [args.host,
                f'chmod 700 {REMOTE_ROOT}/bin/audio_transcription_worker.py '
                f'{REMOTE_ROOT}/bin/migrate_audio_hf_token.py'])
        if args.install_dependencies:
            checked(ssh + [args.host,
                f'{REMOTE_PYTHON} -m pip install --upgrade --target {REMOTE_VENDOR} '
                f'--constraint {REMOTE_ROOT}/constraints.txt faster-whisper==1.2.1'], timeout=1800)
        if args.migrate_key:
            notebooks = [
                '/home/simurghnobackup/zcui/transfer/2025/2026 Spring.ipynb',
                '/home/simurghnobackup/zcui/transfer/2025/Complete Workflow.ipynb',
                '/home/simurghnobackup/zcui/transfer/2025/Transcription.ipynb',
            ]
            remote = [
                REMOTE_PYTHON, f'{REMOTE_ROOT}/bin/migrate_audio_hf_token.py',
                '--destination', f'{REMOTE_ROOT}/.secrets/hf_token', *notebooks,
            ]
            checked(ssh + [args.host, ' '.join(shlex.quote(item) for item in remote)], timeout=180)
        check = (
            'set -eu; '
            f'test -s {ASR_MODEL}/model.bin; '
            f'test -s {DIARIZATION_MODEL}/config.yaml; '
            f'test -s {REMOTE_ROOT}/bin/audio_transcription_worker.py; '
            f'PYTHONPATH={REMOTE_VENDOR} {REMOTE_PYTHON} -c '
            "\"import faster_whisper, pyannote.audio; print('imports=ok')\"; "
            f'if test -f {REMOTE_ROOT}/.secrets/hf_token; then '
            f"printf 'hf_token_mode='; stat -c %a {REMOTE_ROOT}/.secrets/hf_token; "
            "else echo 'hf_token_mode=missing'; fi"
        )
        checked(ssh + [args.host, check], timeout=120)
    print(f'deployment_check=ok host={args.host} remote_root={REMOTE_ROOT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
