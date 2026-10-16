"""Fingerprints describe actual encoded document inputs, never reconstructed guesses."""

import hashlib
import json
from pathlib import Path

from services.astar_semantic_service import _doc_text

SCHEMA = 'sha256-doc-text-utf8-v1'


def input_fingerprint(title, abstract):
    import numpy as np
    return np.frombuffer(hashlib.sha256(_doc_text(title, abstract).encode('utf-8')).digest(), dtype=np.uint8)


def fingerprint_known(value):
    import numpy as np
    return bool(np.any(value))


def seed_input_matches(value, current):
    import numpy as np
    return value is not None and fingerprint_known(value) and bool(np.array_equal(value, current))


def forced_ids(path):
    if path is None:
        return set()
    rows = json.loads(Path(path).read_text(encoding='utf-8'))
    result = set()
    for row in rows:
        identifier = row.get('article_id') if isinstance(row, dict) else row
        if type(identifier) is not int or identifier <= 0:
            raise ValueError('Forced input-drift identifiers must be positive article IDs')
        result.add(identifier)
    return result
