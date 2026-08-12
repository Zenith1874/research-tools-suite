#!/usr/bin/env python3
"""Submit one synthetic/local audio file and print metadata-only job progress."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.audio_transcription_service import (  # noqa: E402
    AudioTranscriptionManager,
    RemoteAudioRunner,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio_file')
    parser.add_argument('--translate', action='store_true')
    parser.add_argument('--num-speakers', type=int)
    parser.add_argument('--target-language', default='Simplified Chinese')
    parser.add_argument('--host', help='Explicit transcription host; avoids cross-shell environment ambiguity')
    args = parser.parse_args()
    source = Path(args.audio_file).resolve()
    if not source.is_file():
        parser.error('audio file does not exist')
    runner_factory = (
        (lambda: RemoteAudioRunner(hosts=[args.host])) if args.host else None
    )
    manager = AudioTranscriptionManager(
        REPO_ROOT / 'data' / 'audio_jobs', runner_factory=runner_factory)
    options = {
        'translate': args.translate,
        'num_speakers': args.num_speakers,
        'target_language': args.target_language,
    }
    with source.open('rb') as handle:
        job = manager.create_job_from_stream(
            source.name, handle, source.stat().st_size, options, start=True)
    job_id = job['job_id']
    print(f'job_id={job_id}', flush=True)
    last = None
    while True:
        current = manager.get_job(job_id)
        marker = (
            current.get('status'), current.get('stage'),
            (current.get('progress') or {}).get('percent'),
        )
        if marker != last:
            print(json.dumps({
                'status': marker[0], 'stage': marker[1], 'percent': marker[2],
            }, ensure_ascii=False), flush=True)
            last = marker
        if current.get('status') not in {'queued', 'running'}:
            print(json.dumps({
                'final_status': current.get('status'),
                'error': current.get('error'),
                'audit': current.get('audit'),
                'runtime': current.get('runtime'),
                'outputs': sorted((current.get('outputs') or {}).keys()),
            }, ensure_ascii=False), flush=True)
            return 0 if current.get('status') == 'completed' else 1
        time.sleep(2)


if __name__ == '__main__':
    raise SystemExit(main())
