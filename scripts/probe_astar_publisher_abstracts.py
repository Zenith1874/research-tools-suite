#!/usr/bin/env python3
"""Probe public publisher landing pages for missing A* abstracts.

The database contains a large title-only tail.  This command is deliberately a
bounded, source-aware probe rather than an unrestricted crawler:

* it selects only non-duplicate articles whose abstract is still missing;
* it uses a low-frequency request delay and records every HTTP outcome;
* it auto-accepts only a strong Springer/Palgrave metadata field
  (``dc.description`` or ``citation_abstract``) after DOI/title checks;
* it never downloads full text and never treats a blocked/ambiguous page as an
  abstract.

By default the command is read-only and writes a reviewable JSON probe report.
Pass ``--apply`` only after reviewing the candidate records; candidates are
then sent through the audited ``apply_verified_publisher_abstract`` path.
"""

import argparse
import html
import json
import os
import re
import socket
import sqlite3
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import quote, urlparse

import requests


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, 'pboc_data.db')
DEFAULT_UA = 'ABDC-AstarRadar/1.0 (public metadata probe; no full text)'
DEFAULT_TIMEOUT = 20
DEFAULT_DELAY = 1.0

sys.path.insert(0, ROOT)
from services.abdc_astar_research_service import (  # noqa: E402
    apply_verified_publisher_abstract,
    normalize_title,
)


def load_local_secret(variable_name, path=None):
    """Load one named secret from the gitignored project file if needed.

    The caller's environment takes precedence.  Only the requested variable is
    loaded, and neither its value nor the other entries in ``.secrets`` are
    returned or logged.
    """
    if os.environ.get(variable_name):
        return 'environment'
    secrets_path = path or os.path.join(ROOT, '.secrets')
    try:
        with open(secrets_path, encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                if key.strip() == variable_name and value.strip():
                    os.environ[variable_name] = value.strip()
                    return 'local_secrets'
    except OSError:
        pass
    return 'missing'


class _MetaParser(HTMLParser):
    """Collect HTML meta tags without depending on BeautifulSoup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'meta':
            self.meta.append(dict(attrs))


def _compact(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def _clean_abstract_text(value):
    """Convert publisher metadata markup to plain abstract text."""
    without_tags = re.sub(r'<[^>]+>', ' ', value or '')
    cleaned = _compact(html.unescape(without_tags))
    return re.sub(r'^abstract\s*[:\-–—]?\s*', '', cleaned,
                  flags=re.IGNORECASE)


def _doi(value):
    value = _compact(value).lower()
    return re.sub(r'^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)', '', value)


def _publisher_family(publisher):
    value = (publisher or '').lower()
    if 'springer' in value or 'palgrave' in value:
        return 'springer'
    if 'elsevier' in value:
        return 'elsevier'
    return 'other'


def _candidate_url(row):
    doi = _compact(row['doi'])
    if _publisher_family(row['publisher']) == 'springer':
        # Springer and Palgrave articles share the public Springer Nature page.
        return f'https://link.springer.com/article/{doi}'
    return f'https://doi.org/{doi}'


def _meta_values(parser):
    values = {}
    for item in parser.meta:
        key = (item.get('name') or item.get('property') or '').strip().lower()
        content = _compact(item.get('content'))
        if key and content and key not in values:
            values[key] = content
    return values


def _springer_abstract(meta, row):
    """Return (abstract, parser_name, reason) for strong Springer fields."""
    expected_doi = _doi(row['doi'])
    page_doi = _doi(meta.get('citation_doi'))
    if page_doi and page_doi != expected_doi:
        return None, 'springer_metadata', 'doi_mismatch'

    page_title = meta.get('citation_title')
    if page_title and normalize_title(page_title) != normalize_title(row['title']):
        return None, 'springer_metadata', 'title_mismatch'

    # These are article-description fields on Springer Nature pages.  The
    # generic ``description``/OpenGraph fields are often truncated, so they
    # are intentionally not accepted for an automatic write-back.
    for key, parser_name in (
        ('citation_abstract', 'springer_citation_abstract'),
        ('dc.description', 'springer_dc_description'),
    ):
        value = _clean_abstract_text(meta.get(key))
        if len(value) >= 80:
            return value, parser_name, 'verified_doi_title_and_public_metadata'
    return None, 'springer_metadata', 'strong_abstract_field_missing'


def _generic_strong_abstract(meta, row):
    """Verify a generic publisher abstract using page DOI and title metadata.

    Only explicit scholarly metadata fields are accepted.  Generic page and
    OpenGraph descriptions are deliberately excluded because they are often
    truncated marketing/cookie text rather than the article abstract.
    """
    page_doi = ''
    for key in ('citation_doi', 'dc.identifier.doi', 'prism.doi', 'dc.identifier'):
        candidate = _doi(meta.get(key))
        if candidate.startswith('10.'):
            page_doi = candidate
            break
    if not page_doi:
        return None, 'generic_scholarly_metadata', 'page_doi_missing'
    if page_doi != _doi(row['doi']):
        return None, 'generic_scholarly_metadata', 'doi_mismatch'

    page_title = ''
    for key in ('citation_title', 'dc.title'):
        if _compact(meta.get(key)):
            page_title = _compact(meta.get(key))
            break
    if not page_title:
        return None, 'generic_scholarly_metadata', 'page_title_missing'
    if normalize_title(page_title) != normalize_title(row['title']):
        return None, 'generic_scholarly_metadata', 'title_mismatch'

    reject_fragments = (
        'this website uses cookies', 'enable javascript', 'access denied',
        'sign in to access', 'purchase this article', 'subscribe to access',
    )
    for key, parser_name in (
        ('citation_abstract', 'generic_citation_abstract'),
        ('dc.description.abstract', 'generic_dc_description_abstract'),
        ('dcterms.abstract', 'generic_dcterms_abstract'),
        ('dc.description', 'generic_dc_description'),
    ):
        value = _clean_abstract_text(meta.get(key))
        value_lower = value.lower()
        if (len(value) >= 80 and len(value.split()) >= 12
                and not any(fragment in value_lower for fragment in reject_fragments)):
            return value, parser_name, 'verified_doi_title_and_public_metadata'
    return None, 'generic_scholarly_metadata', 'strong_abstract_field_missing'


def _json_text(value):
    """Return plain text from common Elsevier XML-to-JSON scalar shapes."""
    if isinstance(value, str):
        return _compact(value)
    if isinstance(value, list):
        for item in value:
            text = _json_text(item)
            if text:
                return text
        return ''
    if isinstance(value, dict):
        for key in ('$', '_', '#text'):
            text = _json_text(value.get(key))
            if text:
                return text
    return ''


def _elsevier_api_abstract(payload, row):
    """Validate and extract the abstract-only META view from Elsevier JSON."""
    root = (payload or {}).get('full-text-retrieval-response') or {}
    core = root.get('coredata') or {}
    page_doi = _doi(_json_text(core.get('prism:doi')))
    if not page_doi:
        return None, None, 'api_doi_missing'
    if page_doi != _doi(row['doi']):
        return None, None, 'doi_mismatch'

    page_title = _json_text(core.get('dc:title'))
    if not page_title:
        return None, None, 'api_title_missing'
    if normalize_title(page_title) != normalize_title(row['title']):
        return None, None, 'title_mismatch'

    abstract = _clean_abstract_text(_json_text(core.get('dc:description')))
    if len(abstract) < 80 or len(abstract.split()) < 12:
        return None, None, 'api_abstract_missing_or_short'

    pii = _json_text(core.get('pii')) or _json_text(core.get('dc:identifier'))
    pii = re.sub(r'^PII:', '', pii, flags=re.IGNORECASE)
    return abstract, pii or None, 'verified_elsevier_meta_doi_title_abstract'


def _elsevier_api_url(doi):
    encoded = quote(_doi(doi), safe='')
    return (f'https://api.elsevier.com/content/article/doi/{encoded}'
            '?view=META&httpAccept=application/json')


def probe_elsevier_api_row(session, row, api_key, delay=DEFAULT_DELAY,
                           timeout=DEFAULT_TIMEOUT):
    """Probe Elsevier's authorized Article Retrieval API META view only."""
    doi = _doi(row['doi'])
    url = _elsevier_api_url(doi)
    result = {
        'article_id': row['id'],
        'doi': doi,
        'title': row['title'],
        'publisher': row['publisher'],
        'journal_title': row['journal_title'],
        'probe_url': url,
        'publisher_family': 'elsevier',
        'status': 'error',
        'parser': 'elsevier_article_retrieval_meta',
        'http_status': None,
        'content_length': None,
        'reason': None,
    }
    if not (api_key or '').strip():
        result.update(status='authorization_required',
                      reason='elsevier_api_key_missing')
        return result
    try:
        response = session.get(
            url,
            headers={
                'X-ELS-APIKey': api_key.strip(),
                'Accept': 'application/json',
            },
            timeout=timeout,
        )
        result.update(http_status=response.status_code,
                      content_length=len(response.content))
        if response.status_code == 401:
            result.update(status='authentication_error',
                          reason='invalid_or_missing_elsevier_api_key')
            return result
        if response.status_code == 403:
            result.update(status='authorization_error',
                          reason='elsevier_api_entitlement_required')
            return result
        if response.status_code == 429:
            result.update(status='rate_limited', reason='elsevier_api_http_429')
            return result
        if response.status_code >= 400:
            result.update(status='http_error',
                          reason=f'elsevier_api_http_{response.status_code}')
            return result

        try:
            payload = response.json()
        except ValueError:
            result.update(status='parse_error', reason='invalid_json_response')
            return result
        abstract, pii, reason = _elsevier_api_abstract(payload, row)
        result['reason'] = reason
        if not abstract:
            result['status'] = 'metadata_only'
            return result

        result.update(
            status='candidate',
            abstract=abstract,
            source_name='Elsevier Article Retrieval API',
            source_type='publisher_api',
            source_id=pii or doi,
            source_url=url,
            publisher_page_url=(
                f'https://www.sciencedirect.com/science/article/pii/{pii}'
                if pii else f'https://doi.org/{doi}'
            ),
            verification_notes=(
                'Elsevier Article Retrieval API view=META verified against '
                'DOI/title; abstract-only metadata stored; '
                'full_text_fetched=false; parser=elsevier_article_retrieval_meta'
            ),
        )
        return result
    except (requests.RequestException, socket.timeout) as exc:
        result.update(status='network_error',
                      reason=f'{type(exc).__name__}: {exc}')
        return result
    finally:
        if delay:
            time.sleep(delay)


def probe_row(session, row, delay=DEFAULT_DELAY, timeout=DEFAULT_TIMEOUT):
    """Probe one row and return a JSON-serializable audit record."""
    doi = _doi(row['doi'])
    url = _candidate_url(row)
    result = {
        'article_id': row['id'],
        'doi': doi,
        'title': row['title'],
        'publisher': row['publisher'],
        'journal_title': row['journal_title'],
        'probe_url': url,
        'publisher_family': _publisher_family(row['publisher']),
        'status': 'error',
        'parser': None,
        'http_status': None,
        'final_url': None,
        'content_length': None,
        'reason': None,
    }
    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
        result.update({
            'http_status': response.status_code,
            'final_url': response.url,
            'content_length': len(response.content),
        })
        if response.status_code in (401, 403, 429):
            result.update(status='blocked', reason=f'http_{response.status_code}')
            return result
        if response.status_code >= 400:
            result.update(status='http_error', reason=f'http_{response.status_code}')
            return result

        parser = _MetaParser()
        parser.feed(response.text)
        meta = _meta_values(parser)
        family = result['publisher_family']
        host = (urlparse(response.url).hostname or '').lower()
        if family == 'springer' and host.endswith('link.springer.com'):
            abstract, parser_name, reason = _springer_abstract(meta, row)
            result.update(parser=parser_name, reason=reason)
            if abstract:
                result.update(
                    status='candidate',
                    abstract=abstract,
                    source_name=(
                        'Palgrave Macmillan' if 'palgrave' in (row['publisher'] or '').lower()
                        else 'Springer Nature'
                    ),
                    source_id=doi,
                    source_url=response.url,
                    verification_notes=(
                        'Public publisher metadata field verified against DOI/title; '
                        'full_text_fetched=false; parser=' + parser_name
                    ),
                )
            else:
                result['status'] = 'no_candidate'
            return result

        abstract, parser_name, reason = _generic_strong_abstract(meta, row)
        result.update(parser=parser_name, reason=reason)
        if abstract:
            result.update(
                status='candidate',
                abstract=abstract,
                source_name=row['publisher'] or host or 'Publisher page',
                source_id=doi,
                source_url=response.url,
                verification_notes=(
                    'Public publisher scholarly metadata verified against DOI/title; '
                    'full_text_fetched=false; parser=' + parser_name
                ),
            )
            return result

        # A successful DOI redirect is not evidence that the page exposed an
        # abstract.  Keep it explicit so unsupported publishers can be handled
        # by a future, separately verified adapter.
        result.update(status='metadata_only')
        return result
    except (requests.RequestException, socket.timeout) as exc:
        result.update(status='network_error', reason=f'{type(exc).__name__}: {exc}')
        return result
    finally:
        if delay:
            time.sleep(delay)


def _open_db(path):
    uri = f'file:{os.path.abspath(path)}?mode=ro'
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def select_rows(conn, publisher=None, journal=None, limit=None):
    sql = """SELECT id, doi, title, publisher, journal_title
             FROM astar_articles
             WHERE abstract_status='missing' AND is_duplicate=0
               AND doi IS NOT NULL AND trim(doi)!=''
               AND length(trim(COALESCE(abstract, ''))) = 0"""
    args = []
    if publisher:
        sql += ' AND lower(COALESCE(publisher,\'\')) LIKE ?'
        args.append('%' + publisher.lower() + '%')
    if journal:
        sql += ' AND lower(COALESCE(journal_title,\'\')) LIKE ?'
        args.append('%' + journal.lower() + '%')
    sql += ' ORDER BY publication_date DESC, id DESC'
    if limit:
        sql += ' LIMIT ?'
        args.append(int(limit))
    return conn.execute(sql, args).fetchall()


def count_excluded_nonempty(conn, publisher=None, journal=None):
    """Count title rows marked missing even though text is already present.

    These are data-quality inconsistencies, not safe backfill targets.  Keeping
    the count in the report makes the exclusion visible instead of silently
    treating them as ordinary missing abstracts.
    """
    sql = """SELECT COUNT(*) FROM astar_articles
             WHERE abstract_status='missing' AND is_duplicate=0
               AND doi IS NOT NULL AND trim(doi)!=''
               AND length(trim(COALESCE(abstract, ''))) > 0"""
    args = []
    if publisher:
        sql += ' AND lower(COALESCE(publisher,\'\')) LIKE ?'
        args.append('%' + publisher.lower() + '%')
    if journal:
        sql += ' AND lower(COALESCE(journal_title,\'\')) LIKE ?'
        args.append('%' + journal.lower() + '%')
    return conn.execute(sql, args).fetchone()[0]


def _default_output():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return os.path.join(ROOT, 'data', f'astar_publisher_abstract_probe_{stamp}.json')


def main():
    parser = argparse.ArgumentParser(
        description='Probe public publisher pages for missing A* abstracts')
    parser.add_argument('--db', default=DEFAULT_DB, help='SQLite database path')
    parser.add_argument('--publisher', help='case-insensitive publisher substring')
    parser.add_argument('--journal', help='case-insensitive journal substring')
    parser.add_argument('--limit', type=int, default=25,
                        help='bounded number of missing-abstract DOI rows (default: 25)')
    parser.add_argument('--delay', type=float, default=DEFAULT_DELAY,
                        help='seconds between requests (default: 1.0)')
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument('--elsevier-api-key-env', default='ELSEVIER_API_KEY',
                        help='environment variable containing an Elsevier API key')
    parser.add_argument('--output', default=None,
                        help='JSON report path (default: timestamped data/ path)')
    parser.add_argument('--apply', action='store_true',
                        help='apply only status=candidate records through the audited writer')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit('--limit must be positive')
    if args.delay < 0:
        raise SystemExit('--delay must be non-negative')

    with _open_db(args.db) as conn:
        rows = select_rows(conn, publisher=args.publisher, journal=args.journal,
                           limit=args.limit)
        excluded_nonempty = count_excluded_nonempty(
            conn, publisher=args.publisher, journal=args.journal)

    elsevier_authorization_source = load_local_secret(
        args.elsevier_api_key_env)
    elsevier_api_key = os.environ.get(args.elsevier_api_key_env, '')
    session = requests.Session()
    session.headers.update({'User-Agent': DEFAULT_UA, 'Accept': 'text/html,application/xhtml+xml'})
    records = []
    for row in rows:
        if _publisher_family(row['publisher']) == 'elsevier':
            records.append(probe_elsevier_api_row(
                session, row, elsevier_api_key,
                delay=args.delay, timeout=args.timeout))
        else:
            records.append(probe_row(
                session, row, delay=args.delay, timeout=args.timeout))

    apply_results = []
    if args.apply:
        for record in records:
            if record.get('status') != 'candidate':
                continue
            try:
                applied = apply_verified_publisher_abstract(
                    doi=record['doi'],
                    abstract=record['abstract'],
                    source_url=record['source_url'],
                    source_name=record['source_name'],
                    source_id=record['source_id'],
                    verified_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    verification_notes=record['verification_notes'],
                    expected_title=record['title'],
                    source_type=record.get('source_type') or 'publisher_page',
                    db_path=args.db,
                )
                record['apply_status'] = 'applied'
                apply_results.append(applied)
            except Exception as exc:  # keep the batch auditable and moving
                record['apply_status'] = 'error'
                record['apply_error'] = f'{type(exc).__name__}: {exc}'

    counts = {}
    for record in records:
        counts[record['status']] = counts.get(record['status'], 0) + 1
    report = {
        'success': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'db_path': os.path.abspath(args.db),
        'selection': {
            'publisher': args.publisher,
            'journal': args.journal,
            'limit': args.limit,
            'selected': len(rows),
            'excluded_missing_status_but_nonempty_abstract': excluded_nonempty,
        },
        'probe': {
            'delay_seconds': args.delay,
            'timeout_seconds': args.timeout,
            'user_agent': DEFAULT_UA,
            'elsevier_authorized_api_configured': bool(elsevier_api_key),
            'elsevier_authorization_source': elsevier_authorization_source,
            'counts': counts,
        },
        'apply': {
            'requested': bool(args.apply),
            'candidates_applied': len(apply_results),
            'candidate_apply_errors': sum(
                1 for record in records if record.get('apply_status') == 'error'
            ),
            'results': apply_results,
        },
        'records': records,
    }
    output = args.output or _default_output()
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, 'w', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({
        'success': True,
        'output': os.path.abspath(output),
        'selected': len(rows),
        'counts': counts,
        'candidates_applied': len(apply_results),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
