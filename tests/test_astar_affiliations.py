# -*- coding: utf-8 -*-
"""Affiliation grain for the A* corpus.

The point of the layer is that an absent affiliation stays distinguishable from
an unchecked one, so most of these assert on the recorded status rather than on
the row count.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.astar_affiliation_service import (
    affiliation_coverage,
    backfill_affiliations,
    ensure_affiliation_tables,
    institution_astar_profile,
    parse_authorships,
    record_affiliations,
    top_institutions,
)


def work(work_id, authorships):
    return {'id': f'https://openalex.org/{work_id}', 'authorships': authorships}


def authorship(name, author_id, institutions, role='first', corresponding=False, orcid=None):
    return {
        'author_position': role,
        'is_corresponding': corresponding,
        'author': {'id': f'https://openalex.org/{author_id}', 'display_name': name,
                   'orcid': f'https://orcid.org/{orcid}' if orcid else None},
        'institutions': institutions,
        'raw_affiliation_strings': [f'{name} affiliation string'],
    }


def institution(inst_id, name, ror=None, country='US', kind='education'):
    return {'id': f'https://openalex.org/{inst_id}', 'display_name': name,
            'ror': f'https://ror.org/{ror}' if ror else None,
            'country_code': country, 'type': kind}


class FakeResponse:
    def __init__(self, results):
        self._results = results

    def raise_for_status(self):
        return None

    def json(self):
        return {'results': self._results}


class FakeSession:
    """Return scripted OpenAlex results and record the filters requested."""

    def __init__(self, works):
        self.by_id = {w['id'].rsplit('/', 1)[-1]: w for w in works}
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(params or {})
        requested = (params or {}).get('filter', '').replace('openalex_id:', '').split('|')
        return FakeResponse([self.by_id[i] for i in requested if i in self.by_id])


class AffiliationDBTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = str(Path(self.dir.name) / 'test.db')
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE astar_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT, openalex_id TEXT, title TEXT,
                journal_title TEXT, publication_year INTEGER)
        """)
        ensure_affiliation_tables(self.conn)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def seed(self, rows):
        self.conn.executemany(
            "INSERT INTO astar_articles (openalex_id,title,journal_title,publication_year) "
            "VALUES (?,?,?,?)", rows)
        self.conn.commit()

    def test_parse_keeps_ror_and_author_identity(self):
        rows = parse_authorships(work('W1', [
            authorship('Mara Olekalns', 'A1',
                       [institution('I1', 'University of Melbourne', '01ej9dk98', 'AU')],
                       orcid='0000-0002-1825-0097'),
        ]))
        self.assertEqual(1, len(rows))
        self.assertEqual('01ej9dk98', rows[0]['institution_ror'])
        self.assertEqual('I1', rows[0]['institution_openalex_id'])
        self.assertEqual('AU', rows[0]['institution_country_code'])
        self.assertEqual('A1', rows[0]['author_openalex_id'])
        self.assertEqual('0000-0002-1825-0097', rows[0]['orcid'])

    def test_author_with_no_institution_still_produces_a_row(self):
        rows = parse_authorships(work('W1', [authorship('No Affil', 'A9', [])]))
        self.assertEqual(1, len(rows))
        self.assertEqual('', rows[0]['institution_openalex_id'])
        self.assertEqual('No Affil', rows[0]['author_display_name'])

    def test_dual_affiliation_produces_one_row_per_institution(self):
        rows = parse_authorships(work('W1', [
            authorship('Joint Appt', 'A2', [institution('I1', 'A University'),
                                            institution('I2', 'B University')]),
        ]))
        self.assertEqual(2, len(rows))
        self.assertEqual({'I1', 'I2'}, {r['institution_openalex_id'] for r in rows})

    def test_status_separates_no_institution_from_no_authorships(self):
        self.seed([('W1', 'x', 'AMJ', 2024)])
        article_id = self.conn.execute("SELECT id FROM astar_articles").fetchone()['id']
        self.assertEqual('no_authorships', record_affiliations(self.conn, article_id, []))
        self.assertEqual('authors_no_institution', record_affiliations(
            self.conn, article_id, parse_authorships(work('W1', [authorship('X', 'A1', [])]))))
        self.assertEqual('recorded', record_affiliations(
            self.conn, article_id,
            parse_authorships(work('W1', [authorship('X', 'A1', [institution('I1', 'U')])]))))

    def test_recording_twice_does_not_duplicate_rows(self):
        self.seed([('W1', 'x', 'AMJ', 2024)])
        article_id = self.conn.execute("SELECT id FROM astar_articles").fetchone()['id']
        parsed = parse_authorships(work('W1', [
            authorship('X', 'A1', [institution('I1', 'U')]),
            authorship('Y', 'A2', [institution('I2', 'V')], role='last'),
        ]))
        for _ in range(3):
            record_affiliations(self.conn, article_id, parsed)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM astar_article_affiliations WHERE article_id=?",
            (article_id,)).fetchone()[0]
        self.assertEqual(2, count)

    def test_backfill_is_resumable_and_batches_ids(self):
        self.seed([(f'W{i}', f'title {i}', 'AMJ', 2024) for i in range(1, 8)])
        works = [work(f'W{i}', [authorship('X', f'A{i}', [institution('I1', 'U', '01abc')])])
                 for i in range(1, 8)]
        session = FakeSession(works)

        first = backfill_affiliations(self.conn, limit=3, session=session, delay=0)
        self.assertEqual(3, first['selected'])
        self.assertEqual(3, first['recorded'])

        second = backfill_affiliations(self.conn, limit=100, session=session, delay=0)
        self.assertEqual(4, second['selected'], "already-checked rows must not be refetched")

        third = backfill_affiliations(self.conn, limit=100, session=session, delay=0)
        self.assertEqual(0, third['selected'], "a completed corpus selects nothing")

    def test_missing_openalex_id_is_recorded_not_retried(self):
        self.seed([(None, 'no id', 'AMJ', 2024), ('', 'blank id', 'AMJ', 2024)])
        stats = backfill_affiliations(self.conn, limit=100, session=FakeSession([]), delay=0)
        self.assertEqual(0, stats['selected'])
        statuses = {row[0] for row in self.conn.execute(
            "SELECT affiliation_status FROM astar_articles")}
        self.assertEqual({'no_openalex_id'}, statuses)

    def test_id_openalex_does_not_return_is_marked_not_found(self):
        self.seed([('W404', 'gone', 'AMJ', 2024)])
        stats = backfill_affiliations(self.conn, limit=10, session=FakeSession([]), delay=0)
        self.assertEqual(1, stats['not_found'])
        status = self.conn.execute("SELECT affiliation_status FROM astar_articles").fetchone()[0]
        self.assertEqual('not_found', status)

    def test_a_failed_batch_leaves_rows_pending_for_the_next_run(self):
        self.seed([('W1', 'x', 'AMJ', 2024)])

        class Broken:
            def get(self, *a, **k):
                raise RuntimeError("network down")

        stats = backfill_affiliations(self.conn, limit=10, session=Broken(), delay=0)
        self.assertEqual(1, stats['errors'])
        status = self.conn.execute("SELECT affiliation_status FROM astar_articles").fetchone()[0]
        self.assertIsNone(status, "a transport failure must not be recorded as a checked outcome")

    def test_profile_counts_distinct_articles_not_authorship_rows(self):
        self.seed([('W1', 'one', 'AMJ', 2023), ('W2', 'two', 'ASQ', 2024)])
        works = [
            # Two co-authors at the same school must count as one article.
            work('W1', [authorship('X', 'A1', [institution('I1', 'Melbourne', '01ej9dk98', 'AU')]),
                        authorship('Y', 'A2', [institution('I1', 'Melbourne', '01ej9dk98', 'AU')],
                                   role='last')]),
            work('W2', [authorship('Z', 'A3', [institution('I1', 'Melbourne', '01ej9dk98', 'AU')])]),
        ]
        backfill_affiliations(self.conn, limit=10, session=FakeSession(works), delay=0)
        profile = institution_astar_profile(self.conn, institution_openalex_id='I1')
        self.assertEqual(2, profile['astar_articles'])
        self.assertEqual(3, profile['distinct_authors'])
        self.assertEqual([{'year': 2023, 'articles': 1}, {'year': 2024, 'articles': 1}],
                         profile['by_year'])
        self.assertTrue(profile['derived'])

    def test_profile_is_reachable_by_ror(self):
        self.seed([('W1', 'one', 'AMJ', 2023)])
        works = [work('W1', [authorship('X', 'A1', [institution('I1', 'Melbourne', '01ej9dk98')])])]
        backfill_affiliations(self.conn, limit=10, session=FakeSession(works), delay=0)
        self.assertEqual(1, institution_astar_profile(self.conn, ror='01ej9dk98')['astar_articles'])

    def test_top_institutions_excludes_the_no_institution_bucket(self):
        self.seed([('W1', 'one', 'AMJ', 2023), ('W2', 'two', 'ASQ', 2023)])
        works = [work('W1', [authorship('X', 'A1', [institution('I1', 'Real University')])]),
                 work('W2', [authorship('Y', 'A2', [])])]
        backfill_affiliations(self.conn, limit=10, session=FakeSession(works), delay=0)
        rows = top_institutions(self.conn, limit=10)
        self.assertEqual(1, len(rows))
        self.assertEqual('Real University', rows[0]['display_name'])

    def test_coverage_reports_unchecked_rows_as_pending(self):
        self.seed([('W1', 'one', 'AMJ', 2023), ('W2', 'two', 'ASQ', 2023)])
        works = [work('W1', [authorship('X', 'A1', [institution('I1', 'U')])])]
        backfill_affiliations(self.conn, limit=1, session=FakeSession(works), delay=0)
        coverage = affiliation_coverage(self.conn)
        self.assertEqual(2, coverage['articles_total'])
        self.assertEqual(1, coverage['articles_checked'])
        self.assertEqual(1, coverage['by_status'].get('pending'))
        self.assertEqual(50.0, coverage['checked_pct'])


if __name__ == '__main__':
    unittest.main()
