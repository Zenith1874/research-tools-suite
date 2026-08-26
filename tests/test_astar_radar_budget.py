# -*- coding: utf-8 -*-
"""The radar loops over 219 A* journals sharing one daily OpenAlex budget.

Before this, a spent budget cost a request per journal (two, for journals with
both a print and an online ISSN) to rediscover the same refusal, and the run was
still written to astar_update_logs with success=1.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import abdc_astar_research_service as radar
from services.abdc_astar_research_service import fetch_recent_articles_for_journal
from services.openalex_budget import BudgetState, RateLimited


def budget_error():
    return RateLimited(retry_after='60561', limit='1000', remaining='0',
                       message='Insufficient budget. Resets at midnight UTC')


JOURNAL = {'journal_title': 'Academy of Management Journal',
           'issn_print': '0001-4273', 'issn_online': '1948-0989'}


class RadarBudgetTests(unittest.TestCase):
    def test_exhausted_budget_costs_one_request_not_one_per_journal(self):
        state = BudgetState()
        calls = []

        def openalex(issn, *a, **k):
            calls.append(issn)
            raise budget_error()

        with patch('services.abdc_astar_research_service.fetch_openalex', side_effect=openalex), \
             patch('services.abdc_astar_research_service.fetch_crossref', return_value=[]):
            for _ in range(50):
                fetch_recent_articles_for_journal(JOURNAL, '2026-08-01', '2026-08-26',
                                                  budget=state)

        self.assertEqual(1, len(calls),
                         "the first refusal must stop every later OpenAlex attempt")
        self.assertTrue(state.exhausted)
        self.assertEqual(49, state.as_dict()['openalex_calls_skipped'])

    def test_both_issns_are_not_burned_on_a_spent_budget(self):
        state = BudgetState()
        calls = []

        def openalex(issn, *a, **k):
            calls.append(issn)
            raise budget_error()

        with patch('services.abdc_astar_research_service.fetch_openalex', side_effect=openalex), \
             patch('services.abdc_astar_research_service.fetch_crossref', return_value=[]):
            fetch_recent_articles_for_journal(JOURNAL, '2026-08-01', '2026-08-26', budget=state)

        self.assertEqual(['0001-4273'], calls,
                         "the second ISSN would be refused the same way")

    def test_crossref_still_serves_articles_while_openalex_is_shut_out(self):
        state = BudgetState()
        state.note(budget_error())
        article = {'doi': '10.1/x', 'title': 'A paper', 'source_type': 'crossref'}

        with patch('services.abdc_astar_research_service.fetch_openalex') as openalex, \
             patch('services.abdc_astar_research_service.fetch_crossref', return_value=[article]):
            arts, source, err = fetch_recent_articles_for_journal(
                JOURNAL, '2026-08-01', '2026-08-26', budget=state)

        openalex.assert_not_called()
        self.assertEqual('crossref', source)
        self.assertEqual([article], arts)
        self.assertIsNone(err, "a working fallback is not an error")

    def test_a_burst_limit_does_not_shut_openalex_out_for_the_run(self):
        state = BudgetState()
        calls = []

        def openalex(issn, *a, **k):
            calls.append(issn)
            raise RateLimited(retry_after='2')

        with patch('services.abdc_astar_research_service.fetch_openalex', side_effect=openalex), \
             patch('services.abdc_astar_research_service.fetch_crossref', return_value=[]), \
             patch('services.abdc_astar_research_service.time.sleep'):
            fetch_recent_articles_for_journal(JOURNAL, '2026-08-01', '2026-08-26', budget=state)
            fetch_recent_articles_for_journal(JOURNAL, '2026-08-01', '2026-08-26', budget=state)

        self.assertFalse(state.exhausted)
        self.assertEqual(4, len(calls), "a burst limit must not disable the source")

    def test_without_a_budget_state_behaviour_is_unchanged(self):
        # The parameter is optional; existing callers keep working.
        with patch('services.abdc_astar_research_service.fetch_openalex', return_value=[{'x': 1}]):
            arts, source, err = fetch_recent_articles_for_journal(
                JOURNAL, '2026-08-01', '2026-08-26')
        self.assertEqual('openalex', source)
        self.assertEqual([{'x': 1}], arts)
        self.assertIsNone(err)

    def test_a_journal_without_issn_is_reported_not_charged_to_the_budget(self):
        state = BudgetState()
        arts, source, err = fetch_recent_articles_for_journal(
            {'journal_title': 'No ISSN'}, '2026-08-01', '2026-08-26', budget=state)
        self.assertEqual('no_issn', err)
        self.assertEqual([], arts)
        self.assertEqual(0, state.as_dict()['openalex_calls_skipped'])


class UpdateLogHonestyTests(unittest.TestCase):
    """A run where every journal failed must not be logged as a success."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = str(Path(self.dir.name) / 'radar.db')

    def tearDown(self):
        self.dir.cleanup()

    def seed(self, journal_count):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        radar.ensure_astar_tables(conn)
        now = '2026-08-26T00:00:00'
        conn.executemany(
            "INSERT INTO abdc_astar_journals "
            "(journal_title,issn_print,issn_online,abdc_rating,abdc_version,is_active,"
            " source_table,created_at,updated_at) VALUES (?,?,?,'A*','latest',1,'abdc',?,?)",
            [(f'Journal {i}', f'0001-{i:04d}', None, now, now) for i in range(journal_count)])
        conn.commit()
        conn.close()

    def run_update(self, fetch_side_effect, journal_count=5):
        self.seed(journal_count)
        with patch.object(radar, 'DB_PATH', self.db), \
             patch.object(radar, 'load_astar_journals_from_abdc',
                          return_value={'abdc_version': 'latest'}), \
             patch.object(radar, 'ensure_prestige_extra_journals', return_value=None), \
             patch.object(radar, 'fetch_recent_articles_for_journal',
                          side_effect=fetch_side_effect), \
             patch.object(radar.time, 'sleep'):
            return radar._run_update('daily_incremental', days=7)

    def read_log(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM astar_update_logs ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        return dict(row)

    def test_total_failure_is_recorded_as_failure_with_the_reason(self):
        def always_fail(journal, *a, **kwargs):
            state = kwargs.get('budget')
            if state is not None:
                state.note(budget_error())
            return [], None, 'openalex:daily budget exhausted; skipped'

        result = self.run_update(always_fail)
        log = self.read_log()
        self.assertEqual(0, log['success'], "every journal failed; this is not a success")
        self.assertIn('daily budget exhausted', log['error_message'])
        self.assertIn('daily budget exhausted', result['error_message'])
        self.assertTrue(result['openalex_budget_exhausted'])

    def test_a_partly_successful_run_is_still_a_success(self):
        calls = {'n': 0}

        def half_fail(journal, *a, **kwargs):
            calls['n'] += 1
            if calls['n'] % 2:
                return [], None, 'openalex:boom'
            return [], 'crossref', None

        self.run_update(half_fail)
        self.assertEqual(1, self.read_log()['success'])

    def test_a_healthy_run_records_no_budget_warning(self):
        result = self.run_update(lambda journal, *a, **kw: ([], 'openalex', None))
        log = self.read_log()
        self.assertEqual(1, log['success'])
        self.assertIsNone(log['error_message'])
        self.assertFalse(result['openalex_budget_exhausted'])
        self.assertEqual('[]', log['warnings'])


if __name__ == '__main__':
    unittest.main()
