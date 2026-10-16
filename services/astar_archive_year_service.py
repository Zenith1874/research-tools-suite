"""Derived journal archive years, with original publication metadata preserved."""

import json
import re
from datetime import datetime, timezone

POLICY_VERSION = 'journal-issue-year-first-v1'


def ensure_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS astar_article_archive_years (
        article_id INTEGER PRIMARY KEY, archive_year INTEGER NOT NULL,
        year_basis TEXT NOT NULL, source_name TEXT NOT NULL,
        source_reference TEXT NOT NULL, evidence_json TEXT NOT NULL,
        priority INTEGER NOT NULL, policy_version TEXT NOT NULL,
        derived_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_astar_archive_year ON astar_article_archive_years(archive_year,article_id)')


def has_table(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='astar_article_archive_years'").fetchone() is not None


def year_expression(conn, alias='a'):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', alias):
        raise ValueError('archive-year SQL alias must be an identifier')
    if not has_table(conn):
        return alias + '.publication_year'
    return ('COALESCE((SELECT ay.archive_year FROM astar_article_archive_years ay '
            'WHERE ay.article_id=' + alias + '.id),' + alias + '.publication_year)')


def put_year(conn, article_id, archive_year, basis, source_name, reference, evidence, priority=20):
    """Write derived evidence only; callers own the transaction."""
    if not isinstance(archive_year, int) or not 1000 <= archive_year <= 3000:
        raise ValueError('the source must provide a valid archive year')
    conn.execute('''INSERT INTO astar_article_archive_years
        (article_id,archive_year,year_basis,source_name,source_reference,evidence_json,priority,policy_version,derived_at)
        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(article_id) DO UPDATE SET
        archive_year=excluded.archive_year,year_basis=excluded.year_basis,source_name=excluded.source_name,
        source_reference=excluded.source_reference,evidence_json=excluded.evidence_json,
        priority=excluded.priority,policy_version=excluded.policy_version,derived_at=excluded.derived_at
        WHERE excluded.priority>=astar_article_archive_years.priority''',
        (article_id, archive_year, basis, source_name, reference, json.dumps(evidence, ensure_ascii=False),
         priority, POLICY_VERSION, datetime.now(timezone.utc).isoformat(timespec='seconds')))


def attach_years(conn, articles):
    """Add archive fields to returned dictionaries without changing their raw fields."""
    if not articles:
        return articles
    found = {}
    if has_table(conn):
        ids = [int(article['id']) for article in articles]
        for first in range(0, len(ids), 800):
            keys = ids[first:first + 800]
            for row in conn.execute('SELECT article_id,archive_year,year_basis FROM astar_article_archive_years '
                                    'WHERE article_id IN (%s)' % ','.join('?' for _ in keys), keys):
                found[int(row[0])] = (row[1], row[2])
    for article in articles:
        selected = found.get(int(article['id']))
        article['archive_year'] = selected[0] if selected else article.get('publication_year')
        article['archive_year_basis'] = selected[1] if selected else 'reported_publication_year_fallback'
    from services.astar_publication_precision_service import attach_precision
    attach_precision(conn, articles)
    return articles


def record_from_article(conn, article_id, article):
    year = article.get('_archive_issue_year')
    if not isinstance(year, int):
        return
    if not has_table(conn):
        ensure_tables(conn)
    put_year(conn, article_id, year, 'crossref_published_print_year',
             article.get('source_name') or 'Crossref', article.get('source_url') or article.get('doi') or '',
             article.get('_archive_year_evidence') or {'reported_print_year': year})
