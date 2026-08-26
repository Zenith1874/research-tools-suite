#!/usr/bin/env python3
"""Backward-compatible wrapper for the dynamic project audit.

The filename remains for existing scripts and historical documentation; the
registry is no longer fixed at five projects.
"""

from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_projects import (  # noqa: E402,F401
    build_report,
    collect_matches,
    git_bytes,
    git_paths,
    iter_pattern_files,
    load_registry,
    main as _dynamic_main,
    relative_path,
    scan_high_confidence_secrets,
    validate_registry,
)


def main(argv=None):
    return _dynamic_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
