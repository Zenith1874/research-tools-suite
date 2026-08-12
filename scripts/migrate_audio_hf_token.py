#!/usr/bin/env python3
"""Move one already-authorized Hugging Face token into a private runtime file.

The script is intentionally silent about token values. It scans only explicitly
provided notebook files, validates candidates with the Hugging Face API, and
writes the first valid token atomically with mode 0600.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


TOKEN_RE = re.compile(r'\bhf_[A-Za-z0-9]{20,}\b')


def candidate_tokens(paths: list[Path]) -> list[str]:
    candidates = []
    seen = set()
    for path in paths:
        if not path.is_file() or path.suffix.casefold() != '.ipynb':
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        for token in TOKEN_RE.findall(text):
            if token not in seen:
                seen.add(token)
                candidates.append(token)
    return candidates


def save_first_valid(paths: list[Path], destination: Path) -> tuple[int, int]:
    from huggingface_hub import HfApi

    candidates = candidate_tokens(paths)
    valid = None
    invalid = 0
    api = HfApi()
    for token in candidates:
        try:
            api.whoami(token=token)
        except Exception:
            invalid += 1
            continue
        valid = token
        break
    if valid is None:
        raise RuntimeError('no valid authorized Hugging Face token was found')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = destination.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        handle.write(valid + '\n')
    os.chmod(temporary, 0o600)
    os.replace(temporary, destination)
    os.chmod(destination, 0o600)
    return len(candidates), invalid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True)
    parser.add_argument('notebooks', nargs='+')
    args = parser.parse_args()
    count, invalid = save_first_valid(
        [Path(item).resolve() for item in args.notebooks], Path(args.destination).resolve())
    print(f'valid_token_saved=true candidates={count} invalid_before_valid={invalid}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
