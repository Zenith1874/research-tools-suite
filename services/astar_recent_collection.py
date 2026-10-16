"""Uncapped, source-count-reconciled recent journal metadata collection."""

import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def collect_recent(journal, start, end, budget=None, raw_dir=None):
    # Local imports avoid changing the existing radar/history module initialization.
    from services import abdc_astar_research_service as radar
    from services.astar_history_service import parse_crossref, parse_openalex, normalize_doi, CROSSREF_FIELDS
    from services.astar_openalex_scope_supplement import assess_published_work, published_location_doi, SELECT_FIELDS
    issns = sorted({value for value in (journal.get('issn_print'), journal.get('issn_online')) if value})
    if not issns:
        return [], None, 'no_issn', {}
    coverage, errors, articles = {}, [], []
    raw_dir = Path(raw_dir) if raw_dir else None

    def save(provider, number, url, params, data):
        if raw_dir is None:
            return None
        directory = raw_dir / (hashlib.sha256((journal['journal_title'] + '|'+ '|'.join(issns)).encode()).hexdigest()[:20]) / provider
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ('page_%06d.json.gz' % number)
        envelope = {'requested_at': datetime.now(timezone.utc).isoformat(), 'url': url,
                    'params': {key: value for key, value in params.items() if key != 'mailto'},
                    'data': data, 'full_text_fetched': False}
        with path.open('xb') as target:
            with gzip.GzipFile(fileobj=target, mode='wb') as stream:
                stream.write(json.dumps(envelope, ensure_ascii=False).encode('utf-8'))
        return {'page': number, 'path': str(path.resolve()),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    for provider in ('crossref', 'openalex'):
        if provider == 'openalex' and budget is not None and budget.should_skip():
            coverage[provider] = {'status': 'WAITING_BUDGET', 'skipped': True}
            errors.append('openalex: daily budget exhausted')
            continue
        cursor, expected, observed, seen, page = '*', None, 0, set(), 0
        source_articles = []
        dispositions = Counter()
        raw_pages = []
        try:
            while cursor:
                if provider == 'crossref':
                    url = 'https://api.crossref.org/works'
                    params = {'filter': ','.join(['issn:' + value for value in issns] + [
                        'from-pub-date:' + start, 'until-pub-date:' + end]), 'rows': 1000,
                        'cursor': cursor, 'select': CROSSREF_FIELDS, 'mailto': radar.MAILTO}
                else:
                    url = radar.OPENALEX_BASE
                    params = {'filter': 'locations.source.issn:' + '|'.join(issns) +
                        ',from_publication_date:' + start + ',to_publication_date:' + end,
                        'per_page': 100, 'cursor': cursor, 'select': SELECT_FIELDS, 'mailto': radar.MAILTO}
                data = radar._http_get_json(url, params=params)
                page += 1
                receipt = save(provider, page, url, params, data)
                if receipt:
                    raw_pages.append(receipt)
                if provider == 'crossref':
                    message = data['message'];items = message.get('items') or []
                    count = int(message['total-results']);next_cursor = message.get('next-cursor')
                else:
                    items = data['results'];count = int(data['meta']['count']);next_cursor = data['meta'].get('next_cursor')
                if expected is not None and expected != count:
                    raise ValueError('provider count changed during pagination')
                expected = count
                for item in items:
                    source_id = item.get('DOI') if provider == 'crossref' else item.get('id')
                    source_id = source_id or hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
                    if source_id in seen:
                        raise ValueError('provider repeated a source record')
                    seen.add(source_id)
                    if provider == 'crossref':
                        article = parse_crossref(item, journal)
                    else:
                        disposition, evidence, location = assess_published_work(item, journal)
                        dispositions[disposition] += 1
                        if location is None:
                            continue
                        selected = dict(item, primary_location=location)
                        location_doi = published_location_doi(location)
                        if location_doi:
                            selected['doi'] = 'https://doi.org/' + location_doi
                        article = parse_openalex(selected, journal)
                        article['_journal_location_evidence'] = evidence
                    if article.get('title'):
                        source_articles.append(article)
                    else:
                        dispositions['EXCLUDED_MISSING_TITLE'] += 1
                observed += len(items)
                if items and next_cursor == cursor:
                    raise ValueError('provider cursor stalled')
                exhausted = not items or not next_cursor or observed >= expected
                if exhausted:
                    if observed != expected or len(seen) != expected:
                        raise ValueError('provider source count did not reconcile')
                    break
                cursor = next_cursor
                radar.time.sleep(radar.POLITE_DELAY)
            coverage[provider] = {'status': 'COMPLETE', 'expected': expected, 'observed': observed,
                                  'unique_source_records': len(seen), 'pages': page,
                                  'dispositions': dict(dispositions), 'raw_pages': raw_pages}
            articles.extend(source_articles)
        except Exception as error:
            if provider == 'openalex' and budget is not None:
                budget.note(error)
            coverage[provider] = {'status': 'INCOMPLETE', 'expected': expected, 'observed': observed,
                                  'unique_source_records': len(seen), 'pages': page,
                                  'dispositions': dict(dispositions), 'raw_pages': raw_pages,
                                  'error_type': type(error).__name__}
            errors.append(provider + ':' + type(error).__name__ + ':' + str(error)[:150])
            # Reconciled source results are usable; failed pagination cannot
            # silently return its first pages as a complete provider collection.
    merged = {}
    for article in articles:
        doi = normalize_doi(article.get('doi'))
        identity = ('doi', doi) if doi else ('openalex', article['openalex_id']) if article.get('openalex_id') else ('url', article.get('source_url'), article.get('title'))
        stored = merged.get(identity)
        if stored is None:
            merged[identity] = article
        else:
            # Both providers remain ingested for provenance/enrichment. Do not
            # discard a later source simply because its DOI is already present.
            merged[(identity, article.get('source_type'))] = article
    source = '+'.join(provider for provider, value in coverage.items() if value['status'] == 'COMPLETE') or None
    return list(merged.values()), source, '; '.join(errors) if errors else None, coverage
