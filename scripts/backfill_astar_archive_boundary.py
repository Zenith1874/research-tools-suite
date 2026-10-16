#!/usr/bin/env python3
"""Complete the issue-year boundary: early-online records printed from 2010 onward.

The original run and its immutable pages remain unchanged. This supplemental
checkpoint uses the same frozen journal scope and recorded issue-year policy.
Publication dates before 2010 are retained, with explicit derived issue years.
"""

import argparse
import gzip
import json
import sqlite3
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.astar_history_service import HistoryRunner, parse_crossref, digest, utc_now, write_new_json


def run_boundary(run_dir):
    folder = run_dir / 'archive_boundary'
    folder.mkdir(parents=True, exist_ok=True)
    runner = HistoryRunner(run_dir)
    db = sqlite3.connect(folder / 'checkpoint.sqlite3', timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript('''
        CREATE TABLE IF NOT EXISTS units(journal_key TEXT PRIMARY KEY,title TEXT,status TEXT,
            cursor TEXT,page INTEGER,expected INTEGER,observed INTEGER,error TEXT,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS pages(journal_key TEXT,page INTEGER,path TEXT,sha256 TEXT,
            row_count INTEGER,PRIMARY KEY(journal_key,page));
        CREATE TABLE IF NOT EXISTS records(journal_key TEXT,doi TEXT,article_id INTEGER,disposition TEXT,
            PRIMARY KEY(journal_key,doi));
    ''')
    for key, journal in runner.journals.items():
        db.execute('INSERT OR IGNORE INTO units VALUES(?,?,?, ?,1,NULL,0,NULL,?)',
                   (key, journal['journal_title'], 'PENDING', '*', utc_now()))
    db.commit()
    if not (folder / 'scope.json').exists():
        write_new_json(folder / 'scope.json', {'created_at': utc_now(), 'source_scope': 'frozen existing journals',
            'archive_from': runner.manifest['from_date'], 'archive_until': runner.manifest['to_date'],
            'first_publication_until': '2009-12-31', 'source_field': 'Crossref published-print',
            'year_policy': 'human-confirmed journal issue year first', 'original_dates_retained': True,
            'script_sha256': digest(__file__)})
    session = requests.Session()
    session.headers['User-Agent'] = 'ResearchTools-HistoryAudit/1.0'
    try:
        for original in db.execute("SELECT * FROM units WHERE status!='COMPLETE' ORDER BY journal_key").fetchall():
            unit = dict(original)
            journal = runner.journals[unit['journal_key']]
            db.execute('UPDATE units SET status=?,error=NULL,updated_at=? WHERE journal_key=?',
                       ('RUNNING', utc_now(), unit['journal_key']))
            db.commit()
            try:
                while True:
                    rel = Path('raw') / unit['journal_key'] / ('page_%06d.json.gz' % unit['page'])
                    raw = folder / rel
                    if raw.exists():
                        with gzip.open(raw, 'rt', encoding='utf-8') as stream:
                            envelope = json.load(stream)
                    else:
                        issns = sorted(set(filter(None, (journal.get('issn_print'), journal.get('issn_online')))))
                        filters = ['issn:' + value for value in issns] + [
                            'from-print-pub-date:' + runner.manifest['from_date'],
                            'until-print-pub-date:' + runner.manifest['to_date'], 'until-pub-date:2009-12-31']
                        # Crossref cursor paging rejects publication-date sorts.
                        # The default cursor order matches the primary collector.
                        params = {'filter': ','.join(filters), 'rows': 1000, 'cursor': unit['cursor'] or '*'}
                        for attempt in range(4):
                            response = session.get('https://api.crossref.org/works', params=params, timeout=30)
                            if response.status_code not in (429, 500, 502, 503, 504):
                                response.raise_for_status()
                                break
                            delay = max(5, min(60, int(response.headers.get('Retry-After', 5 * (attempt + 1)))))
                            time.sleep(delay)
                        else:
                            raise RuntimeError('Crossref retry budget exhausted')
                        envelope = {'requested_at': utc_now(), 'provider': 'crossref_archive_boundary',
                                    'url': 'https://api.crossref.org/works', 'params': params,
                                    'status_code': response.status_code, 'data': response.json()}
                        raw.parent.mkdir(parents=True, exist_ok=True)
                        with raw.open('xb') as file_handle:
                            with gzip.GzipFile(fileobj=file_handle, mode='wb') as stream:
                                stream.write(json.dumps(envelope, ensure_ascii=False).encode('utf-8'))
                        time.sleep(1)
                    message = envelope['data']['message']
                    expected = int(message['total-results'])
                    if unit['expected'] is not None and unit['expected'] != expected:
                        raise ValueError('archive-boundary count changed during pagination')
                    items = message.get('items') or []
                    next_cursor = message.get('next-cursor')
                    if next_cursor == unit['cursor'] and len(items) == 1000:
                        raise ValueError('archive-boundary cursor repeated on a full page')
                    runner.main.execute('BEGIN IMMEDIATE')
                    outcomes = []
                    try:
                        for item in items:
                            article = parse_crossref(item, journal)
                            article['_archive_scope_admission'] = True
                            # Other live source workers may have added this DOI after our index snapshot.
                            doi = article.get('doi')
                            if doi:
                                existing = runner.main.execute('SELECT id FROM astar_articles WHERE doi=? ORDER BY is_duplicate,id LIMIT 1', (doi,)).fetchone()
                                if existing:
                                    runner.doi_index[doi] = existing[0]
                            aid, disposition = runner.ingest_article(article, journal)
                            outcomes.append((unit['journal_key'], doi, aid, disposition))
                        runner.main.commit()
                    except BaseException:
                        runner.main.rollback()
                        raise
                    observed = unit['observed'] + len(items)
                    exhausted = len(items) < 1000 or observed >= expected
                    if exhausted and observed != expected:
                        raise ValueError('archive-boundary observed count does not reconcile')
                    db.execute('INSERT OR IGNORE INTO pages VALUES(?,?,?,?,?)',
                               (unit['journal_key'], unit['page'], str(rel), digest(raw), len(items)))
                    db.executemany('INSERT OR REPLACE INTO records VALUES(?,?,?,?)', outcomes)
                    db.execute('UPDATE units SET status=?,cursor=?,page=?,expected=?,observed=?,error=NULL,updated_at=? WHERE journal_key=?',
                               ('COMPLETE' if exhausted else 'RUNNING', next_cursor, unit['page'] + 1,
                                expected, observed, utc_now(), unit['journal_key']))
                    db.commit()
                    unit.update(cursor=next_cursor, page=unit['page'] + 1, expected=expected, observed=observed)
                    if exhausted:
                        break
                print(json.dumps({'journal': journal['journal_title'], 'status': 'COMPLETE', 'source_records': observed}), flush=True)
            except Exception as exc:
                db.execute('UPDATE units SET status=?,error=?,updated_at=? WHERE journal_key=?',
                           ('FAILED', str(exc)[:600], utc_now(), unit['journal_key']))
                db.commit()
                print(json.dumps({'journal': journal['journal_title'], 'status': 'FAILED', 'error': str(exc)[:200]}), flush=True)
        result = {'finished_at': utc_now(), 'states': [list(row) for row in db.execute('SELECT status,COUNT(*) FROM units GROUP BY status')],
                  'source_records': db.execute('SELECT COUNT(*) FROM records').fetchone()[0]}
        write_new_json(folder / ('report_' + str(time.time_ns()) + '.json'), result)
        return result
    finally:
        session.close()
        db.close()
        runner.close()


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_boundary(args.run_dir.resolve()), indent=2))


if __name__ == '__main__':
    main()
