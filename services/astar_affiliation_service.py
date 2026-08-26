# -*- coding: utf-8 -*-
"""Institution layer for the A* article corpus.

``_parse_openalex_work`` kept only author display names, so the 136k A* articles
carry no affiliation at all.  Everything needed to recover it is already stored:
99.6% of the rows have an ``openalex_id``, and OpenAlex returns authorships for
up to 50 ids per request.

This module owns the affiliation grain only.  It does not rank schools and does
not invent a research tier: it records which institution published which A*
article, with the OpenAlex/ROR identity that supports the claim, and leaves the
interpretation to the caller.
"""

from datetime import datetime, timezone
import logging
import time

import requests

LOG = logging.getLogger(__name__)

OPENALEX_WORKS = 'https://api.openalex.org/works'
MAILTO = 'zither1874@gmail.com'
HTTP_TIMEOUT = 45
POLITE_DELAY = 0.3
# OpenAlex accepts up to 50 OR-ed values in one filter.
ID_BATCH = 50
# How many times one batch waits out a 429 before giving up on it.
MAX_RATE_LIMIT_RETRIES = 5
# Consecutive failed batches that end the run. Without this the first full-corpus
# run pushed 1,714 doomed requests after OpenAlex had already cut it off.
MAX_CONSECUTIVE_ERRORS = 5
# A Retry-After longer than this means the daily budget is gone, not that a burst
# limit needs riding out. OpenAlex meters at 1,000 requests/day on the free tier
# and resets at midnight UTC, so the wait can be most of a day.
BUDGET_RESET_THRESHOLD = 900.0

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS astar_article_affiliations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER NOT NULL,
        author_position INTEGER NOT NULL,
        author_role TEXT,
        is_corresponding INTEGER NOT NULL DEFAULT 0,
        author_openalex_id TEXT,
        author_display_name TEXT,
        orcid TEXT,
        institution_openalex_id TEXT NOT NULL DEFAULT '',
        institution_ror TEXT,
        institution_display_name TEXT,
        institution_country_code TEXT,
        institution_type TEXT,
        raw_affiliation TEXT,
        source_type TEXT NOT NULL DEFAULT 'openalex',
        captured_at TEXT,
        UNIQUE(article_id, author_position, institution_openalex_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_aff_article ON astar_article_affiliations(article_id)",
    "CREATE INDEX IF NOT EXISTS idx_aff_ror ON astar_article_affiliations(institution_ror)",
    "CREATE INDEX IF NOT EXISTS idx_aff_inst ON astar_article_affiliations(institution_openalex_id)",
    "CREATE INDEX IF NOT EXISTS idx_aff_country ON astar_article_affiliations(institution_country_code)",
)

# Why a row was or was not produced.  A missing affiliation is recorded as an
# observed outcome, never left indistinguishable from "not attempted".
STATUS_VALUES = (
    'pending',                 # not attempted yet
    'recorded',                # at least one institution stored
    'authors_no_institution',  # OpenAlex has the authors but no institution
    'no_authorships',          # the work record carries no authorships at all
    'not_found',               # the openalex_id no longer resolves
    'no_openalex_id',          # nothing to look the work up by
)


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def ensure_affiliation_tables(conn):
    for statement in SCHEMA:
        conn.execute(statement)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(astar_articles)")}
    if 'affiliation_status' not in columns:
        conn.execute("ALTER TABLE astar_articles ADD COLUMN affiliation_status TEXT")
    if 'affiliation_checked_at' not in columns:
        conn.execute("ALTER TABLE astar_articles ADD COLUMN affiliation_checked_at TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_affiliation_status "
                 "ON astar_articles(affiliation_status)")


def _short_id(value, prefix='https://openalex.org/'):
    return (value or '').replace(prefix, '') or None


def parse_authorships(work):
    """Flatten one OpenAlex work's authorships into affiliation rows.

    An author with no institution still produces a row with an empty institution
    id, so "OpenAlex has no affiliation for this author" stays distinguishable
    from "we never looked".
    """
    rows = []
    for position, authorship in enumerate(work.get('authorships') or []):
        author = authorship.get('author') or {}
        base = {
            'author_position': position,
            'author_role': authorship.get('author_position'),
            'is_corresponding': 1 if authorship.get('is_corresponding') else 0,
            'author_openalex_id': _short_id(author.get('id')),
            'author_display_name': author.get('display_name'),
            'orcid': _short_id(author.get('orcid'), 'https://orcid.org/'),
            'raw_affiliation': next(iter(authorship.get('raw_affiliation_strings') or []), None),
        }
        institutions = authorship.get('institutions') or []
        if not institutions:
            rows.append({**base, 'institution_openalex_id': '', 'institution_ror': None,
                         'institution_display_name': None, 'institution_country_code': None,
                         'institution_type': None})
            continue
        for institution in institutions:
            rows.append({**base,
                         'institution_openalex_id': _short_id(institution.get('id')) or '',
                         'institution_ror': _short_id(institution.get('ror'), 'https://ror.org/'),
                         'institution_display_name': institution.get('display_name'),
                         'institution_country_code': institution.get('country_code'),
                         'institution_type': institution.get('type')})
    return rows


def record_affiliations(conn, article_id, rows, captured_at=None):
    """Replace one article's affiliation rows. Returns the status to store."""
    captured_at = captured_at or now_utc()
    conn.execute("DELETE FROM astar_article_affiliations WHERE article_id=?", (article_id,))
    if not rows:
        return 'no_authorships'
    conn.executemany("""
        INSERT OR REPLACE INTO astar_article_affiliations
          (article_id,author_position,author_role,is_corresponding,author_openalex_id,
           author_display_name,orcid,institution_openalex_id,institution_ror,
           institution_display_name,institution_country_code,institution_type,
           raw_affiliation,source_type,captured_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'openalex',?)
    """, [(article_id, r['author_position'], r['author_role'], r['is_corresponding'],
           r['author_openalex_id'], r['author_display_name'], r['orcid'],
           r['institution_openalex_id'], r['institution_ror'], r['institution_display_name'],
           r['institution_country_code'], r['institution_type'], r['raw_affiliation'],
           captured_at) for r in rows])
    if any(r['institution_openalex_id'] for r in rows):
        return 'recorded'
    return 'authors_no_institution'


class RateLimited(RuntimeError):
    """OpenAlex refused the request for rate reasons; back off before retrying."""

    def __init__(self, retry_after=None, remaining=None, limit=None, message=None):
        super().__init__(f"429 Too Many Requests (Retry-After={retry_after})")
        self.retry_after = retry_after
        self.remaining = remaining
        self.limit = limit
        self.message = message

    @property
    def budget_exhausted(self):
        """True when waiting would mean sleeping until the daily reset.

        OpenAlex meters by daily request budget (1,000/day on the free tier,
        reset at midnight UTC). A Retry-After of several hours is not a burst
        limit to ride out inside a run; it means the run is over.
        """
        try:
            return float(self.retry_after) > BUDGET_RESET_THRESHOLD
        except (TypeError, ValueError):
            return False


def _fetch_works(ids, session=None):
    """Fetch authorships for up to ID_BATCH work ids in one request."""
    getter = session.get if session is not None else requests.get
    params = {
        'filter': 'openalex_id:' + '|'.join(ids),
        'select': 'id,authorships',
        'per-page': len(ids),
        'mailto': MAILTO,
    }
    response = getter(OPENALEX_WORKS, params=params,
                      headers={'User-Agent': f'ABDC-AstarRadar/1.0 (mailto:{MAILTO})'},
                      timeout=HTTP_TIMEOUT)
    status = getattr(response, 'status_code', 200)
    if status == 429:
        headers = getattr(response, 'headers', {}) or {}
        message = None
        try:
            message = (response.json() or {}).get('message')
        except Exception:
            message = None
        raise RateLimited(headers.get('Retry-After'),
                          remaining=headers.get('x-ratelimit-remaining'),
                          limit=headers.get('x-ratelimit-limit'),
                          message=message)
    response.raise_for_status()
    return (response.json() or {}).get('results') or []


def _fetch_with_backoff(ids, session=None, attempts=MAX_RATE_LIMIT_RETRIES, base_delay=1.0):
    """Fetch one batch, waiting out rate limits instead of hammering through them.

    The first full-corpus run learned this the hard way: OpenAlex started
    refusing at ~990 requests and every later batch was thrown away because the
    loop moved straight on to the next one at full speed.
    """
    last = None
    for attempt in range(attempts):
        try:
            return _fetch_works(ids, session=session)
        except RateLimited as exc:
            last = exc
            if exc.budget_exhausted:
                # Sleeping until midnight UTC inside a run is not backoff.
                raise
            # An explicit Retry-After is the server stating what it wants; honour
            # it rather than overriding it with our own exponential guess.
            wait = None
            if exc.retry_after is not None:
                try:
                    wait = min(300.0, max(0.0, float(exc.retry_after)))
                except (TypeError, ValueError):
                    wait = None
            if wait is None:
                wait = base_delay * (2 ** attempt)
            if attempt < attempts - 1:
                LOG.warning("rate limited; waiting %.1fs before retry %s/%s",
                            wait, attempt + 2, attempts)
                time.sleep(wait)
    raise last


def backfill_affiliations(conn, limit=500, session=None, progress=None, delay=POLITE_DELAY):
    """Fill affiliations for articles that have never been checked.

    Resumable: only rows whose ``affiliation_status`` is NULL or 'pending' are
    selected, so an interrupted run continues where it stopped rather than
    refetching the whole corpus.
    """
    ensure_affiliation_tables(conn)
    conn.execute("""
        UPDATE astar_articles SET affiliation_status='no_openalex_id', affiliation_checked_at=?
        WHERE (affiliation_status IS NULL OR affiliation_status='pending')
          AND (openalex_id IS NULL OR openalex_id='')
    """, (now_utc(),))
    conn.commit()

    rows = conn.execute("""
        SELECT id, openalex_id FROM astar_articles
        WHERE (affiliation_status IS NULL OR affiliation_status='pending')
          AND openalex_id IS NOT NULL AND openalex_id!=''
        ORDER BY id LIMIT ?
    """, (int(limit),)).fetchall()

    stats = {'selected': len(rows), 'requests': 0, 'recorded': 0,
             'authors_no_institution': 0, 'no_authorships': 0, 'not_found': 0,
             'affiliation_rows': 0, 'errors': 0, 'stopped_early': False,
             'stop_reason': None}
    by_openalex = {}
    for row in rows:
        by_openalex.setdefault(row['openalex_id'], []).append(row['id'])
    ids = list(by_openalex)
    consecutive_errors = 0

    for offset in range(0, len(ids), ID_BATCH):
        chunk = ids[offset:offset + ID_BATCH]
        try:
            works = _fetch_with_backoff(chunk, session=session)
            stats['requests'] += 1
            consecutive_errors = 0
        except RateLimited as exc:
            if exc.budget_exhausted:
                # The daily budget is gone; every later batch would fail the same
                # way. Stop now and leave the rest pending for the next window.
                stats['stopped_early'] = True
                stats['stop_reason'] = (
                    f"OpenAlex daily budget exhausted (limit={exc.limit}, "
                    f"remaining={exc.remaining}, resets in {exc.retry_after}s); "
                    f"{len(ids) - offset} ids left pending")
                LOG.warning("stopping backfill: %s", stats['stop_reason'])
                break
            stats['errors'] += 1
            consecutive_errors += 1
            LOG.warning("affiliation batch rate limited offset=%s error=%s", offset, str(exc)[:200])
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                stats['stopped_early'] = True
                stats['stop_reason'] = (
                    f"{consecutive_errors} consecutive rate-limited batches; "
                    f"{len(ids) - offset} ids left pending")
                break
            continue
        except Exception as exc:
            stats['errors'] += 1
            consecutive_errors += 1
            LOG.warning("affiliation batch failed offset=%s error=%s", offset, str(exc)[:200])
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                # Everything past here would fail the same way. Stop and leave
                # the rest pending for a later run rather than burning requests.
                stats['stopped_early'] = True
                stats['stop_reason'] = (
                    f"{consecutive_errors} consecutive failed batches; "
                    f"{len(ids) - offset - ID_BATCH} ids left pending")
                LOG.warning("stopping backfill early: %s", stats['stop_reason'])
                break
            continue
        seen = set()
        checked_at = now_utc()
        with conn:
            for work in works:
                work_id = _short_id(work.get('id'))
                parsed = parse_authorships(work)
                for article_id in by_openalex.get(work_id, []):
                    status = record_affiliations(conn, article_id, parsed, checked_at)
                    stats[status] = stats.get(status, 0) + 1
                    stats['affiliation_rows'] += len(parsed)
                    conn.execute("UPDATE astar_articles SET affiliation_status=?, "
                                 "affiliation_checked_at=? WHERE id=?",
                                 (status, checked_at, article_id))
                seen.add(work_id)
            # An id OpenAlex did not return is recorded, not retried forever.
            for work_id in chunk:
                if work_id in seen:
                    continue
                for article_id in by_openalex.get(work_id, []):
                    stats['not_found'] += 1
                    conn.execute("UPDATE astar_articles SET affiliation_status='not_found', "
                                 "affiliation_checked_at=? WHERE id=?", (checked_at, article_id))
        if progress:
            progress(f"affiliations {min(offset + ID_BATCH, len(ids))}/{len(ids)}; "
                     f"rows={stats['affiliation_rows']}")
        if offset + ID_BATCH < len(ids):
            time.sleep(delay)
    return stats


def affiliation_coverage(conn):
    """Observed backfill coverage. Percentages are recomputed, never stored."""
    ensure_affiliation_tables(conn)
    total = conn.execute("SELECT COUNT(*) FROM astar_articles").fetchone()[0]
    by_status = {row[0] or 'pending': row[1] for row in conn.execute(
        "SELECT COALESCE(affiliation_status,'pending'), COUNT(*) FROM astar_articles GROUP BY 1")}
    institutions = conn.execute(
        "SELECT COUNT(DISTINCT institution_openalex_id) FROM astar_article_affiliations "
        "WHERE institution_openalex_id!=''").fetchone()[0]
    rows = conn.execute("SELECT COUNT(*) FROM astar_article_affiliations").fetchone()[0]
    checked = total - by_status.get('pending', 0)
    return {
        'articles_total': total,
        'articles_checked': checked,
        'checked_pct': round(100.0 * checked / total, 2) if total else 0.0,
        'by_status': by_status,
        'affiliation_rows': rows,
        'distinct_institutions': institutions,
    }


def institution_astar_profile(conn, institution_openalex_id=None, ror=None,
                              since_year=None, limit_journals=10):
    """A* publication record for one institution, derived from stored rows only."""
    ensure_affiliation_tables(conn)
    if not institution_openalex_id and not ror:
        raise ValueError("institution_openalex_id or ror is required")
    clauses, args = [], []
    if institution_openalex_id:
        clauses.append("f.institution_openalex_id=?")
        args.append(institution_openalex_id)
    else:
        clauses.append("f.institution_ror=?")
        args.append(ror)
    if since_year:
        clauses.append("a.publication_year>=?")
        args.append(int(since_year))
    where = " AND ".join(clauses)

    head = conn.execute(f"""
        SELECT MIN(f.institution_display_name) AS name,
               MIN(f.institution_country_code) AS country_code,
               MIN(f.institution_ror) AS ror,
               MIN(f.institution_openalex_id) AS openalex_id,
               COUNT(DISTINCT a.id) AS astar_articles,
               COUNT(DISTINCT f.author_openalex_id) AS distinct_authors
        FROM astar_article_affiliations f
        JOIN astar_articles a ON a.id=f.article_id
        WHERE {where}
    """, args).fetchone()
    by_year = [{'year': row[0], 'articles': row[1]} for row in conn.execute(f"""
        SELECT a.publication_year, COUNT(DISTINCT a.id)
        FROM astar_article_affiliations f JOIN astar_articles a ON a.id=f.article_id
        WHERE {where} AND a.publication_year IS NOT NULL
        GROUP BY a.publication_year ORDER BY a.publication_year
    """, args).fetchall()]
    top_journals = [{'journal': row[0], 'articles': row[1]} for row in conn.execute(f"""
        SELECT a.journal_title, COUNT(DISTINCT a.id) AS n
        FROM astar_article_affiliations f JOIN astar_articles a ON a.id=f.article_id
        WHERE {where} AND a.journal_title IS NOT NULL
        GROUP BY a.journal_title ORDER BY n DESC, a.journal_title LIMIT ?
    """, (*args, int(limit_journals))).fetchall()]
    return {
        'institution': {
            'display_name': head['name'], 'country_code': head['country_code'],
            'ror': head['ror'], 'openalex_id': head['openalex_id'],
        },
        'astar_articles': head['astar_articles'],
        'distinct_authors': head['distinct_authors'],
        'by_year': by_year,
        'top_journals': top_journals,
        'derived': True,
        'method': 'distinct A* articles with at least one authorship at this institution',
        'source': 'OpenAlex authorships stored in astar_article_affiliations',
    }


def top_institutions(conn, since_year=None, limit=50, country_code=None):
    """Institutions by observed A* article count.

    This is a count of what the corpus contains, not a ranking: coverage
    depends on how much of the corpus has been backfilled, so callers must read
    ``affiliation_coverage`` alongside it.
    """
    ensure_affiliation_tables(conn)
    clauses = ["f.institution_openalex_id!=''"]
    args = []
    if since_year:
        clauses.append("a.publication_year>=?")
        args.append(int(since_year))
    if country_code:
        clauses.append("f.institution_country_code=?")
        args.append(country_code)
    where = " AND ".join(clauses)
    rows = conn.execute(f"""
        SELECT f.institution_openalex_id AS openalex_id,
               MIN(f.institution_ror) AS ror,
               MIN(f.institution_display_name) AS display_name,
               MIN(f.institution_country_code) AS country_code,
               COUNT(DISTINCT a.id) AS astar_articles
        FROM astar_article_affiliations f JOIN astar_articles a ON a.id=f.article_id
        WHERE {where}
        GROUP BY f.institution_openalex_id
        ORDER BY astar_articles DESC, display_name LIMIT ?
    """, (*args, int(limit))).fetchall()
    return [dict(row) for row in rows]


__all__ = [
    'ensure_affiliation_tables', 'parse_authorships', 'record_affiliations',
    'backfill_affiliations', 'affiliation_coverage', 'institution_astar_profile',
    'top_institutions', 'STATUS_VALUES',
]
