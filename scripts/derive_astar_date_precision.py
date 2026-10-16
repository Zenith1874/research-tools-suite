#!/usr/bin/env python3
"""Derive views for dates demonstrably padded by historical ingestion.

Original article/source/classification rows are never updated. Only inserted
Crossref records with partial reported parts and the exact padded cached value
are eligible. Each correction retains its raw page/hash, DOI and source parts.
"""

import argparse
import gzip
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.astar_history_service import connect, digest, normalize_doi, utc_now, write_new_json
from services.astar_publication_precision_service import ensure_tables, has_table


def derive(run_dirs, output_root, apply=False):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = output_root / stamp
    folder.mkdir(parents=True, exist_ok=False)
    candidate_path = folder / 'candidates.sqlite3'
    candidates = sqlite3.connect(candidate_path, uri=True)
    candidates.row_factory = sqlite3.Row
    candidates.execute('''CREATE TABLE corrections(article_id INTEGER PRIMARY KEY,
        precision TEXT,publication_month TEXT,cached_date TEXT,source_year INTEGER,
        evidence_json TEXT,source_page TEXT,source_page_sha256 TEXT,derived_at TEXT)''')
    main_path = None
    pages_checked = 0
    for run in run_dirs:
        manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
        if main_path and main_path != manifest['db_path']:
            raise ValueError('runs must refer to the same article database')
        main_path = manifest['db_path']
        state = connect(run / 'checkpoint.sqlite3', readonly=True)
        try:
            unit_keys = [row[0] for row in state.execute("SELECT unit_key FROM units WHERE provider='crossref' AND status='COMPLETE'")]
            for key in unit_keys:
                inserted = {row[0]: row[1] for row in state.execute('''
                    SELECT source_id,article_id FROM records WHERE unit_key=?
                    AND disposition='INSERTED' AND date_precision IN ('year','month')
                    AND article_id IS NOT NULL''', (key,))}
                if not inserted:
                    continue
                for page in state.execute('SELECT path,sha256 FROM pages WHERE unit_key=? ORDER BY page', (key,)):
                    path = run / page['path']
                    if digest(path) != page['sha256']:
                        raise ValueError('raw page hash mismatch')
                    pages_checked += 1
                    with gzip.open(path, 'rt', encoding='utf-8') as stream:
                        envelope = json.load(stream)
                    for item in envelope['data']['message']['items']:
                        doi = normalize_doi(item.get('DOI'))
                        identifier = inserted.get(doi)
                        if not identifier:
                            continue
                        selected_field, parts = None, []
                        for field in ('published', 'published-online', 'published-print'):
                            values = (item.get(field) or {}).get('date-parts') or []
                            if values and values[0] and values[0][0] is not None:
                                selected_field, parts = field, values[0]
                                break
                        if len(parts) not in (1, 2):
                            continue
                        try:
                            cached = date(int(parts[0]), int(parts[1]) if len(parts) == 2 else 1, 1).isoformat()
                        except (TypeError, ValueError):
                            continue
                        precision = 'year' if len(parts) == 1 else 'month'
                        month = cached[:7] if precision == 'month' else None
                        evidence = {'doi': doi, 'reported_field': selected_field,
                                    'reported_date_parts': parts, 'historical_disposition': 'INSERTED',
                                    'historical_run': str(run), 'unit_key': key,
                                    'basis': 'own parser padded missing components; exact day is not established'}
                        candidates.execute('INSERT OR IGNORE INTO corrections VALUES(?,?,?,?,?,?,?,?,?)',
                            (identifier, precision, month, cached, int(parts[0]),
                             json.dumps(evidence, ensure_ascii=False), str(path), page['sha256'], utc_now()))
                candidates.commit()
        finally:
            state.close()
    candidates.execute('ATTACH DATABASE ? AS live_articles',
                       (Path(main_path).resolve().as_uri() + '?mode=ro',))
    eligible = '''SELECT c.* FROM corrections c JOIN live_articles.astar_articles a
        ON a.id=c.article_id WHERE a.publication_date=c.cached_date
        AND a.publication_year=c.source_year'''
    count = candidates.execute('SELECT COUNT(*) FROM (' + eligible + ')').fetchone()[0]
    by_precision = dict(candidates.execute('SELECT precision,COUNT(*) FROM (' + eligible + ') GROUP BY precision').fetchall())
    with (folder / 'corrections.jsonl').open('x', encoding='utf-8') as stream:
        for row in candidates.execute(eligible):
            stream.write(json.dumps(dict(row), ensure_ascii=False) + '\n')
    applied = 0
    if apply:
        main = connect(main_path)
        try:
            with (folder / 'previous_derived_rows.jsonl').open('x', encoding='utf-8') as stream:
                if has_table(main):
                    for row in main.execute('SELECT * FROM astar_publication_precision'):
                        stream.write(json.dumps(dict(row), ensure_ascii=False) + '\n')
            ensure_tables(main)
            main.executemany('''INSERT INTO astar_publication_precision VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(article_id) DO UPDATE SET precision=excluded.precision,
                publication_month=excluded.publication_month,cached_date=excluded.cached_date,
                source_year=excluded.source_year,evidence_json=excluded.evidence_json,
                source_page=excluded.source_page,source_page_sha256=excluded.source_page_sha256,
                derived_at=excluded.derived_at''', (tuple(row) for row in candidates.execute(eligible)))
            main.commit()
            applied = count
        except BaseException:
            main.rollback()
            raise
        finally:
            main.close()
    candidates.close()
    receipt = {'created_at': utc_now(), 'run_dirs': [str(run) for run in run_dirs],
               'corrected_views': count, 'by_precision': by_precision,
               'source_pages_hash_checked': pages_checked, 'applied': applied,
               'original_article_source_and_classification_rows_updated': False,
               'correction_directory': str(folder), 'script_sha256': digest(__file__)}
    write_new_json(folder / 'verification.json', receipt)
    return receipt


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, action='append', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(derive([run.resolve() for run in args.run_dir], args.output_dir.resolve(), args.apply), ensure_ascii=False, indent=2))
