"""Recent collection must reconcile every page and retain both provider evidence."""

import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.astar_recent_collection import collect_recent
from services import abdc_astar_research_service as radar
from services.astar_history_service import parse_crossref
from services.openalex_budget import BudgetState, RateLimited

JOURNAL = {'journal_title': 'Fixture Journal', 'issn_print': '1111-1111', 'issn_online': '2222-2222',
           'abdc_rating': 'A', 'abdc_version': '2025'}


def crossref_work(number):
    return {'DOI': f'10.1234/item-{number}', 'title': [f'Paper {number}'],
            'published': {'date-parts': [[2026, 9, 25]]}, 'type': 'journal-article'}


def oa_work(number, kind='review', primary_issn='9999-9999'):
    location = {'source': {'id': 'S1', 'issn': ['1111-1111'], 'type': 'journal', 'display_name': JOURNAL['journal_title']},
                'version': 'publishedVersion', 'is_published': True}
    return {'id': f'https://openalex.org/W{number}', 'doi': None, 'title': f'Other paper {number}',
            'type': kind, 'publication_date': '2026-09-25', 'publication_year': 2026,
            'primary_location': {'source': {'issn': [primary_issn], 'type': 'repository'}}, 'locations': [location]}


class RecentCollectionTests(unittest.TestCase):
    def test_crossref_exceeds_200_and_both_issns_are_requested_as_one_union(self):
        requests = []
        def response(url, params):
            requests.append((url, dict(params)))
            if 'crossref' in url:
                if params['cursor'] == '*':
                    return {'message': {'items': [crossref_work(i) for i in range(201)], 'total-results': 202, 'next-cursor': 'next'}}
                return {'message': {'items': [crossref_work(202)], 'total-results': 202, 'next-cursor': None}}
            return {'results': [], 'meta': {'count': 0, 'next_cursor': None}}
        with tempfile.TemporaryDirectory() as temporary, \
             patch('services.abdc_astar_research_service._http_get_json', side_effect=response), \
             patch('services.abdc_astar_research_service.time.sleep'):
            rows, source, error, coverage = collect_recent(JOURNAL, '2026-09-01', '2026-10-07', raw_dir=temporary)
            self.assertEqual(202, len(rows))
            self.assertEqual(202, coverage['crossref']['observed'])
            self.assertEqual(3, len(list(Path(temporary).rglob('*.gz'))))
            for provider in coverage.values():
                for receipt in provider['raw_pages']:
                    saved = Path(receipt['path'])
                    self.assertEqual(receipt['sha256'], hashlib.sha256(saved.read_bytes()).hexdigest())
                    with gzip.open(saved, 'rt', encoding='utf-8') as stream:
                        self.assertNotIn('mailto', json.load(stream)['params'])
        self.assertIn('issn:1111-1111,issn:2222-2222', requests[0][1]['filter'])
        self.assertIsNone(error)

    def test_secondary_review_and_primary_article_with_published_copy_are_retained(self):
        def response(url, params):
            if 'crossref' in url:
                return {'message': {'items': [], 'total-results': 0, 'next-cursor': None}}
            return {'results': [oa_work(1), oa_work(2, 'article', '1111-1111')], 'meta': {'count': 2, 'next_cursor': None}}
        with patch('services.abdc_astar_research_service._http_get_json', side_effect=response):
            rows, source, error, coverage = collect_recent(JOURNAL, '2026-09-01', '2026-10-07')
        self.assertEqual(2, len(rows))
        self.assertEqual('COMPLETE', coverage['openalex']['status'])
        self.assertIsNone(error)

    def test_unconfirmed_repository_location_is_recorded_for_review_not_imported(self):
        item = oa_work(1);item['locations'][0]['source']['type'] = 'repository'
        def response(url, params):
            return {'message': {'items': [], 'total-results': 0, 'next-cursor': None}} if 'crossref' in url else {'results': [item], 'meta': {'count': 1, 'next_cursor': None}}
        with patch('services.abdc_astar_research_service._http_get_json', side_effect=response):
            rows, _, _, coverage = collect_recent(JOURNAL, '2026-09-01', '2026-10-07')
        self.assertEqual([], rows)
        self.assertEqual(1, coverage['openalex']['dispositions']['REVIEW_PUBLICATION_STATUS_UNCONFIRMED'])

    def test_count_shortfall_is_not_treated_as_complete_provider_data(self):
        def response(url, params):
            return {'message': {'items': [crossref_work(1)], 'total-results': 2, 'next-cursor': None}} if 'crossref' in url else {'results': [], 'meta': {'count': 0, 'next_cursor': None}}
        with patch('services.abdc_astar_research_service._http_get_json', side_effect=response):
            rows, _, error, coverage = collect_recent(JOURNAL, '2026-09-01', '2026-10-07')
        self.assertEqual([], rows)
        self.assertEqual('INCOMPLETE', coverage['crossref']['status'])
        self.assertIsNotNone(error)

    def test_budget_refusal_disables_later_openalex_but_keeps_crossref(self):
        state = BudgetState();calls = []
        def response(url, params):
            if 'crossref' in url:
                return {'message': {'items': [crossref_work(1)], 'total-results': 1, 'next-cursor': None}}
            calls.append(url)
            raise RateLimited(retry_after='36000', remaining='0', limit='10000')
        with patch('services.abdc_astar_research_service._http_get_json', side_effect=response):
            first = collect_recent(JOURNAL, '2026-09-01', '2026-10-07', state)
            second = collect_recent(JOURNAL, '2026-09-01', '2026-10-07', state)
        self.assertEqual(1, len(calls))
        self.assertEqual(1, len(first[0]))
        self.assertEqual('WAITING_BUDGET', second[3]['openalex']['status'])

    def test_failed_later_page_keeps_raw_evidence_and_no_partial_articles(self):
        def response(url, params):
            if 'crossref' not in url:
                return {'results': [], 'meta': {'count': 0, 'next_cursor': None}}
            if params['cursor'] == '*':
                return {'message': {'items': [crossref_work(1)], 'total-results': 2, 'next-cursor': 'next'}}
            raise OSError('fixture transport failure')
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(radar, '_http_get_json', side_effect=response), \
             patch.object(radar.time, 'sleep'):
            rows, _, error, coverage = collect_recent(JOURNAL, '2026-09-01', '2026-10-07', raw_dir=temporary)
            self.assertEqual([], rows)
            self.assertEqual('INCOMPLETE', coverage['crossref']['status'])
            self.assertEqual(1, len(coverage['crossref']['raw_pages']))
            self.assertIn('transport failure', error)

    def test_upsert_retains_known_month_without_fabricating_a_day(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        radar.ensure_astar_tables(conn)
        raw = crossref_work(1)
        raw['published']['date-parts'] = [[2026, 9]]
        article = parse_crossref(raw, JOURNAL)
        status, identifier = radar._upsert_article(conn, article, JOURNAL)
        row = conn.execute('SELECT publication_date,publication_year,publication_month FROM astar_articles WHERE id=?',
                           (identifier,)).fetchone()
        self.assertEqual('inserted', status)
        self.assertEqual((None, 2026, '2026-09'), tuple(row))
        raw['published']['date-parts'] = [[2026, 9, 25]]
        radar._upsert_article(conn, parse_crossref(raw, JOURNAL), JOURNAL)
        radar._upsert_article(conn, article, JOURNAL)
        self.assertEqual('2026-09-25', conn.execute('SELECT publication_date FROM astar_articles WHERE id=?',
                                                 (identifier,)).fetchone()[0])
