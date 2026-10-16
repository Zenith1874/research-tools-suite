#!/usr/bin/env python3
"""Validate the official bulletin, archive inputs, and audit a scoped sync."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.china_demography_service import (  # noqa: E402
    BULLETIN_UPDATES_PATH, DATA_PATH, read_demography_rows, update_china_demography,
)
from services.china_macro_dashboard_service import build_china_macro_payload  # noqa: E402
from services.housing_structural_driver_service import load_national_structural_drivers  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs' / 'china_demography')
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error('Database must already exist; do not create an empty production database.')

    import requests
    from pypdf import PdfReader

    captured_at = datetime.now().astimezone()
    out = args.output_dir / captured_at.strftime('%Y%m%d-%H%M%S-%f')
    out.mkdir(parents=True, exist_ok=False)
    updates, _ = read_demography_rows(BULLETIN_UPDATES_PATH)
    source_url = updates[0]['source_url']
    if any(row['source_url'] != source_url for row in updates):
        raise ValueError('This scoped audit expects one official bulletin source.')
    response = requests.get(source_url, timeout=25)
    response.raise_for_status()
    if not response.content.startswith(b'%PDF'):
        raise ValueError('The official source did not return a PDF; no sync performed.')
    reader = PdfReader(io.BytesIO(response.content))
    pages = [re.sub(r'\s+', '', page.extract_text() or '') for page in reader.pages]
    labels = {
        'CN_MARRIAGES': '办理结婚登记',
        'CN_DIVORCES_AGREEMENT': '民政部门登记离婚',
        'CN_DIVORCES_COURT': '法院判决、调解离婚',
        'CN_DIVORCES_TOTAL_OFFICIAL': '依法办理离婚手续',
    }
    checked_pages = {}
    for row in updates:
        needle = f"{labels[row['indicator_code']]}{row['value']:.1f}万对"
        matches = [i + 1 for i, page in enumerate(pages) if needle in page]
        if not matches:
            raise ValueError(f'Official PDF does not confirm {needle}; no sync performed.')
        checked_pages[row['indicator_code']] = matches
    (out / 'official-bulletin.pdf').write_bytes(response.content)

    def observations():
        with sqlite3.connect(args.db) as conn:
            conn.row_factory = sqlite3.Row
            count = conn.execute('SELECT COUNT(*) FROM china_macro_observations').fetchone()[0]
            rows = [dict(row) for row in conn.execute(
                "SELECT * FROM china_macro_observations WHERE period='2025' "
                "AND indicator_code IN ('CN_MARRIAGES','CN_DIVORCES_AGREEMENT',"
                "'CN_DIVORCES_COURT','CN_DIVORCES_TOTAL_OFFICIAL') ORDER BY indicator_code")]
            check = conn.execute('PRAGMA quick_check').fetchone()[0]
        return {'rows': rows, 'table_rows': count, 'quick_check': check}

    before = observations()
    if before['quick_check'] != 'ok':
        raise RuntimeError('Database integrity check failed; no sync performed.')
    # Preserve the before image before making any scoped production changes.
    (out / 'before.json').write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
    first = update_china_demography(str(args.db))
    second = update_china_demography(str(args.db))
    after = observations()
    if after['quick_check'] != 'ok' or second['records_changed'] != 0:
        raise RuntimeError('Post-sync integrity/idempotency check failed.')
    payload = build_china_macro_payload(str(args.db))
    selected = {
        code: [row for row in payload['series'].get(code, []) if row['period'] == '2025']
        for code in ('CN_MARRIAGES', 'CN_DIVORCES_AGREEMENT', 'CN_DIVORCES_COURT',
                     'CN_DIVORCES_TOTAL_OFFICIAL', 'CN_DIVORCES_TOTAL_DERIVED',
                     'CN_DIVORCES_TOTAL', 'CN_DIVORCE_MARRIAGE_RATIO_DERIVED')
    }
    audit = {
        'captured_at': captured_at.isoformat(), 'python': sys.version,
        'database_path': str(args.db.resolve()), 'source_url': source_url,
        'source_sha256': hashlib.sha256(response.content).hexdigest(),
        'source_bytes': len(response.content), 'source_pdf_pages_checked': checked_pages,
        'input_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (DATA_PATH, BULLETIN_UPDATES_PATH)},
        'first_sync': first, 'idempotent_sync': second, 'before': before, 'after': after,
        'dashboard_2025': selected,
        'housing_marriage_anchor': load_national_structural_drivers()['national_marriages'][-1],
    }
    (out / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output_dir': str(out.resolve()), 'records_changed': first['records_changed'],
                      'idempotent_changes': second['records_changed'],
                      'quick_check': after['quick_check'], 'dashboard_2025': selected},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
