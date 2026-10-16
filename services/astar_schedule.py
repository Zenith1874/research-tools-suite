"""Keep metadata-update slots anchored when a job takes time or fails."""

import json
import math
from datetime import datetime, timedelta
from pathlib import Path


def apply_runtime_controls(profile_path, environment, now_local):
    """Load only reviewed research-scheduler controls after a service restart.

    Explicit process settings take precedence. A past calendar anchor rolls
    forward to the same daily time, avoiding a new startup-relative schedule.
    """
    profile_path = Path(profile_path)
    if not profile_path.exists():
        return {}
    profile = json.loads(profile_path.read_text(encoding='utf-8-sig'))
    allowed = {'schema_version', 'embedding_auto', 'daily_anchor_local', 'reason'}
    if not isinstance(profile, dict) or set(profile) - allowed:
        raise ValueError('Unsupported research runtime control fields')
    if type(profile.get('schema_version')) is not int or profile['schema_version'] != 1:
        raise ValueError('Unsupported research runtime control schema')
    if profile.get('embedding_auto') not in ('0', '1'):
        raise ValueError('embedding_auto must be the string 0 or 1')
    anchor = datetime.fromisoformat(profile['daily_anchor_local'])
    if anchor.tzinfo is not None or now_local.tzinfo is not None:
        raise ValueError('Calendar anchors must use the local naive clock')
    if anchor <= now_local:
        days = math.floor((now_local - anchor).total_seconds() / 86400) + 1
        anchor += timedelta(days=days)
    values = {'EMB_AUTO': profile['embedding_auto'],
              'ASTAR_NEXT_DUE_LOCAL': anchor.isoformat()}
    applied = {}
    # Validate the entire profile before mutating the supplied environment.
    for key, value in values.items():
        if key not in environment:
            environment[key] = value
            applied[key] = value
    return {'profile_path': str(profile_path), 'applied': applied}


def initial_delay(next_due_local, now_local, fallback_seconds=600):
    if not next_due_local:
        return max(0.0, float(fallback_seconds))
    due = datetime.fromisoformat(next_due_local)
    return max(0.0, (due - now_local).total_seconds())


def advance_slot(previous_slot, now, interval_seconds):
    if interval_seconds <= 0:
        raise ValueError("The update interval must be positive")
    next_slot = previous_slot + interval_seconds
    if next_slot <= now:
        next_slot += (math.floor((now - next_slot) / interval_seconds) + 1) * interval_seconds
    return next_slot, max(0.0, next_slot - now)
