# -*- coding: utf-8 -*-
"""Resolve Theory, Construct, and Method source records against OpenAlex/Crossref.

``build_research_catalog.py`` writes each source record with author, year, title,
venue, and an evidence role, marked ``pending_verification``.  This script looks
each one up and, when a record matches confidently, records the real DOI,
source id, venue, and (where available) citation count and flips the row to a
source-specific verified status.  Nothing is invented: a work that cannot be
matched keeps its pending status and gains a note saying why.  It does not
claim that a metadata match is access to the original full text; that is the
separate source-access workflow.

Usage::

    python scripts/verify_research_sources.py              # all pending entity types
    python scripts/verify_research_sources.py --kind theories
    python scripts/verify_research_sources.py --all        # re-check everything
    python scripts/verify_research_sources.py --limit 20   # partial run
    python scripts/verify_research_sources.py --dry-run    # report, write nothing

OpenAlex now bills requests against a per-account daily budget.  When that
budget is spent the API answers 429 with an "Insufficient budget" body; the
script switches to Crossref for the current and remaining rows instead of
retrying a spent budget.  Already-verified rows are skipped, so repeated
partial runs converge.
"""

import argparse
import json
from pathlib import Path
import re
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'data' / 'research_catalog.json'
API = 'https://api.openalex.org/works'
CROSSREF_API = 'https://api.crossref.org/works'
MAILTO = 'zither1874@gmail.com'
POLITE_DELAY = 1.2
VERIFIED_STATUSES = {'verified_openalex', 'verified_crossref', 'verified_pubmed'}
ENTITY_KINDS = ('theories', 'constructs', 'methods')
BOOK_REVIEW_RE = re.compile(r'\bbook\s+reviews?\b|\breview\s*:', re.I)
REVIEW_TYPES = {'review', 'book-review', 'book_review', 'journal-review'}


class BudgetExhausted(RuntimeError):
    """OpenAlex daily budget is spent; the run cannot continue today."""


def _norm(value):
    return re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()


def _token_overlap(left, right):
    left_tokens = set(_norm(left).split())
    right_tokens = set(_norm(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _surnames(authors):
    """Pull surnames out of an 'A, B & C' author string."""
    parts = re.split(r',| & | and ', str(authors or ''))
    return [_norm(part).split()[-1] for part in parts if _norm(part)]


def _match(work, record):
    """Score a candidate. A title match alone is not enough to call it verified."""
    title_score = _token_overlap(record['title'], work.get('title') or '')
    year = work.get('publication_year')
    year_gap = abs((year or 0) - (record.get('year') or 0)) if year else 99
    candidate_authors = [_norm(a['author']['display_name']).split()[-1]
                         for a in work.get('authorships', [])[:8]
                         if a.get('author', {}).get('display_name')]
    wanted = _surnames(record['authors'])
    author_hits = sum(1 for name in wanted if name in candidate_authors)
    author_score = author_hits / len(wanted) if wanted else 0.0
    return title_score, author_score, year_gap


def _is_confident(title_score, author_score, year_gap):
    """Require title agreement plus author/year corroboration."""
    return title_score >= 0.6 and not (author_score < 0.34 and year_gap > 1)


def _candidate_rejection(record, work, provider):
    """Reject bibliographic objects that cannot be the requested source.

    A review may be the right object for an explicitly requested review source,
    but a book review is never the original theory, construct, or method work.
    Edition/reprint mismatches remain machine matches with a review flag rather
    than being silently collapsed into the original identity.
    """
    title = ((work.get('title') or '') if provider == 'OpenAlex'
             else ((work.get('title') or [''])[0]))
    if BOOK_REVIEW_RE.search(title):
        return 'provider record is a book review, not the requested original work'
    source_type = str(work.get('type') or '').lower().replace('_', '-')
    requested_kind = str(record.get('kind') or '').lower()
    if source_type in REVIEW_TYPES and requested_kind not in {'major_review', 'review'}:
        return 'provider record is a review object, not the requested original work'
    expected_type = str(record.get('source_type') or '').lower().replace('_', '-')
    if expected_type:
        compatible = {
            'article': {'article', 'journal-article', 'proceedings-article'},
            'journal-article': {'article', 'journal-article'},
            'book': {'book', 'monograph'},
            'book-chapter': {'book-chapter', 'book-part'},
            'review': {'review', 'journal-article'},
        }.get(expected_type, {expected_type})
        if source_type and source_type not in compatible:
            return 'provider work type %s does not match expected %s' % (source_type, expected_type)
    return None


def _version_review_status(record, candidate_year):
    if candidate_year and record.get('year'):
        gap = abs(int(candidate_year) - int(record['year']))
        if gap > 1:
            return 'VERSION_REVIEW_REQUIRED'
    return 'SAME_YEAR_OR_NEARBY'


def _crossref_year(work):
    """Return the first usable Crossref publication year."""
    for field in ('published-print', 'published-online', 'published',
                  'issued', 'created'):
        parts = (work.get(field) or {}).get('date-parts') or []
        if parts and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                pass
    return None


def _crossref_authors(work):
    names = []
    for author in work.get('author') or []:
        family = author.get('family') or ''
        name = author.get('name') or family
        if name:
            names.append(name)
    return names


def _match_crossref(work, record):
    """Score a Crossref item using the same conservative rule as OpenAlex."""
    title = (work.get('title') or [''])[0]
    year = _crossref_year(work)
    title_score = _token_overlap(record['title'], title)
    year_gap = abs((year or 0) - (record.get('year') or 0)) if year else 99
    candidate_authors = [_norm(name).split()[-1]
                         for name in _crossref_authors(work) if _norm(name)]
    wanted = _surnames(record['authors'])
    author_hits = sum(1 for name in wanted if name in candidate_authors)
    author_score = author_hits / len(wanted) if wanted else 0.0
    return title_score, author_score, year_gap


def _clean_doi(value):
    doi = str(value or '').strip()
    doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', doi, flags=re.I)
    if doi.lower().startswith('doi:'):
        doi = doi[4:].strip()
    return doi or None


def _lookup(session, record):
    params = {'search': record['title'], 'per-page': 8, 'mailto': MAILTO}
    for attempt in range(5):
        try:
            response = session.get(API, params=params, timeout=30)
        except requests.RequestException as error:
            if attempt == 4:
                return None, 'request failed: %s' % error
            time.sleep(3 * (attempt + 1))
            continue
        if response.status_code == 200:
            break
        if response.status_code == 429:
            # OpenAlex moved to a per-account daily budget. Retrying a spent
            # budget just burns time, so surface it and stop the run.
            body = response.text[:300]
            if 'budget' in body.lower():
                raise BudgetExhausted(body)
            time.sleep(5 * (attempt + 1))
            continue
        if response.status_code == 503:
            time.sleep(5 * (attempt + 1))
            continue
        return None, 'HTTP %d' % response.status_code
    else:
        return None, 'rate limited after retries'

    best = None
    rejected = []
    for work in response.json().get('results', []):
        rejection = _candidate_rejection(record, work, 'OpenAlex')
        if rejection:
            rejected.append(rejection)
            continue
        title_score, author_score, year_gap = _match(work, record)
        # Require a strong title match plus corroboration from either an author
        # surname or a near-exact year.  A bare title hit is how wrong records
        # get labelled "verified".
        if not _is_confident(title_score, author_score, year_gap):
            continue
        score = title_score + author_score - (year_gap * 0.05)
        if best is None or score > best[0]:
            best = (score, work)
    if best is None:
        return None, rejected[0] if rejected else 'no confident match'
    return best[1], None


def _lookup_crossref(session, record):
    params = {
        'query.bibliographic': record['title'],
        'rows': 8,
        'mailto': MAILTO,
    }
    for attempt in range(5):
        try:
            response = session.get(CROSSREF_API, params=params, timeout=30)
        except requests.RequestException as error:
            if attempt == 4:
                return None, 'Crossref request failed: %s' % error
            time.sleep(3 * (attempt + 1))
            continue
        if response.status_code == 200:
            break
        if response.status_code in (429, 503):
            time.sleep(5 * (attempt + 1))
            continue
        return None, 'Crossref HTTP %d' % response.status_code
    else:
        return None, 'Crossref rate limited after retries'

    best = None
    rejected = []
    items = (response.json().get('message') or {}).get('items') or []
    for item in items:
        rejection = _candidate_rejection(record, item, 'Crossref')
        if rejection:
            rejected.append(rejection)
            continue
        title_score, author_score, year_gap = _match_crossref(item, record)
        if not _is_confident(title_score, author_score, year_gap):
            continue
        score = title_score + author_score - (year_gap * 0.05)
        if best is None or score > best[0]:
            best = (score, item)
    if best is None:
        return None, rejected[0] if rejected else 'no confident Crossref match'
    return best[1], None


def _apply(record, work):
    source = (work.get('primary_location') or {}).get('source') or {}
    location = work.get('primary_location') or {}
    landing_url = location.get('landing_page_url')
    full_text_url = location.get('pdf_url')
    record.update({
        'doi': _clean_doi(work.get('doi')),
        'openalex_id': (work.get('id') or '').replace('https://openalex.org/', '') or None,
        'openalex_title': work.get('title'),
        'openalex_year': work.get('publication_year'),
        'openalex_venue': source.get('display_name'),
        'cited_by_count': work.get('cited_by_count'),
        'verification': 'verified_openalex',
        'bibliographic_verification_status': 'machine_matched',
        'verification_status': 'MACHINE_MATCHED',
        'source_type': work.get('type'),
        'version_review_status': _version_review_status(record, work.get('publication_year')),
        'verification_source': 'OpenAlex',
        'verified_at': time.strftime('%Y-%m-%d'),
        'verification_note': None,
        'landing_url': landing_url or ('https://doi.org/' + _clean_doi(work.get('doi'))
                                       if _clean_doi(work.get('doi')) else None),
        'full_text_url': full_text_url,
        'full_text_version': location.get('version'),
        'retrieval_note': None,
    })


def _apply_crossref(record, work):
    titles = work.get('title') or []
    doi = _clean_doi(work.get('DOI') or work.get('doi'))
    links = work.get('link') or []
    pdf_link = next((item.get('URL') for item in links
                     if 'pdf' in str(item.get('content-type', '')).lower()), None)
    record.update({
        'doi': doi,
        'crossref_title': titles[0] if titles else None,
        'crossref_year': _crossref_year(work),
        'crossref_venue': (work.get('container-title') or [None])[0],
        'crossref_type': work.get('type'),
        'crossref_cited_by_count': work.get('is-referenced-by-count'),
        'verification': 'verified_crossref',
        'bibliographic_verification_status': 'machine_matched',
        'verification_status': 'MACHINE_MATCHED',
        'source_type': work.get('type'),
        'version_review_status': _version_review_status(record, _crossref_year(work)),
        'verification_source': 'Crossref',
        'verified_at': time.strftime('%Y-%m-%d'),
        'verification_note': None,
        'landing_url': work.get('URL') or ('https://doi.org/' + doi if doi else None),
        'full_text_url': pdf_link,
        'full_text_version': None,
        'retrieval_note': None,
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--all', action='store_true', help='re-check verified rows too')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--kind', choices=ENTITY_KINDS, default='all',
                        help='entity type to verify; default is theories, constructs, and methods')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    kinds = ENTITY_KINDS if args.kind == 'all' else (args.kind,)
    pending = []
    for kind in kinds:
        for entity in catalog[kind]:
            for work in entity.get('seminal_works', []):
                if args.all or work.get('verification') not in VERIFIED_STATUSES:
                    pending.append((kind, entity['id'], work))
    if args.limit:
        pending = pending[:args.limit]

    print('%d seminal works to check' % len(pending))
    session = requests.Session()
    session.headers.update({'User-Agent': 'research-tools (mailto:%s)' % MAILTO})

    verified = failed = 0
    openalex_available = True
    fallback_announced = False
    for index, (kind, entity_id, record) in enumerate(pending, 1):
        work = reason = None
        if openalex_available:
            try:
                work, reason = _lookup(session, record)
            except BudgetExhausted as error:
                openalex_available = False
                if not fallback_announced:
                    print('')
                    print('OpenAlex daily budget exhausted; switching to Crossref for this run.')
                    print('  %s' % str(error)[:200])
                    fallback_announced = True
        if not work:
            crossref_work, crossref_reason = _lookup_crossref(session, record)
            if crossref_work:
                _apply_crossref(record, crossref_work)
                verified += 1
                print('  [%3d/%d] OK   %-10s %-28s %s (%s, Crossref)' % (
                    index, len(pending), kind[:-1], entity_id, record['doi'], record.get('crossref_year')))
                time.sleep(POLITE_DELAY)
                continue
            reason = '%s; %s' % (reason or 'OpenAlex unavailable', crossref_reason)
        if work:
            _apply(record, work)
            verified += 1
            print('  [%3d/%d] OK   %-10s %-28s %s (%s, OpenAlex)' % (
                index, len(pending), kind[:-1], entity_id, record['doi'], record.get('openalex_year')))
        else:
            record['verification'] = 'pending_verification'
            record['verification_note'] = reason
            failed += 1
            print('  [%3d/%d] MISS %-10s %-28s %s — %s' % (
                index, len(pending), kind[:-1], entity_id, record['title'][:44], reason))
        time.sleep(POLITE_DELAY)

    print('verified %d, unresolved %d' % (verified, failed))
    if args.dry_run:
        print('dry run: catalog not written')
        return 0
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + chr(10), encoding='utf-8')
    print('wrote', CATALOG)
    print('NOTE: the catalog builder preserves verified source fields when it regenerates')
    print('      the scaffold; pending rows remain pending until a confident match exists.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
