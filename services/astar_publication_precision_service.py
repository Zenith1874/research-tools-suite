"""Evidence-backed views of calendar precision without altering cached dates.

Only dates proven to have been padded by our historical parser are masked.
Original article rows and immutable provider pages remain available for audit.
"""

import re


def has_table(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='astar_publication_precision'").fetchone() is not None


def ensure_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS astar_publication_precision (
        article_id INTEGER PRIMARY KEY, precision TEXT NOT NULL,
        publication_month TEXT, cached_date TEXT NOT NULL,
        source_year INTEGER NOT NULL, evidence_json TEXT NOT NULL,
        source_page TEXT NOT NULL, source_page_sha256 TEXT NOT NULL,
        derived_at TEXT NOT NULL)''')


def date_expression(conn, alias='a'):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', alias):
        raise ValueError('date SQL alias must be an identifier')
    if not has_table(conn):
        return alias + '.publication_date'
    return ('CASE WHEN EXISTS(SELECT 1 FROM astar_publication_precision pd '
            'WHERE pd.article_id=' + alias + '.id AND pd.cached_date=' + alias +
            '.publication_date) THEN NULL ELSE ' + alias + '.publication_date END')


def attach_precision(conn, articles):
    if not articles or not has_table(conn):
        return articles
    found = {}
    ids = [int(article['id']) for article in articles]
    for first in range(0, len(ids), 800):
        keys = ids[first:first + 800]
        for row in conn.execute('''SELECT article_id,precision,publication_month,cached_date
            FROM astar_publication_precision WHERE article_id IN (''' +
            ','.join('?' for _ in keys) + ')', keys):
            found[int(row[0])] = tuple(row[1:])
    for article in articles:
        selected = found.get(int(article['id']))
        if selected and article.get('publication_date') == selected[2]:
            article['cached_publication_date'] = article['publication_date']
            article['publication_date'] = None
            article['publication_date_precision'] = selected[0]
            article['publication_month'] = selected[1]
            article['publication_date_basis'] = 'reported source precision; padded calendar date retained in cache only'
    return articles
