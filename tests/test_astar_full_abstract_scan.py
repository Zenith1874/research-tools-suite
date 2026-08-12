import unittest

from scripts.run_astar_full_abstract_scan import (
    publisher_route,
    terminal_result,
)
from scripts.reclassify_astar_publisher_review_results import reclassify_result


class FullAbstractScanTests(unittest.TestCase):
    def test_routes_supported_blocked_and_generic_publishers(self):
        self.assertEqual(
            publisher_route('Springer Science+Business Media')[0],
            'live_springer')
        self.assertEqual(
            publisher_route('Elsevier BV')[0],
            'publisher_page_review')
        self.assertEqual(
            publisher_route('Elsevier BV', elsevier_api_enabled=True)[0],
            'live_elsevier_api')
        self.assertEqual(
            publisher_route('American Psychological Association')[0],
            'publisher_page_review')
        self.assertEqual(
            publisher_route('Cambridge University Press')[0],
            'live_generic')
        self.assertEqual(
            publisher_route('Association for Information Systems')[0],
            'live_generic')

    def test_every_non_network_route_has_a_terminal_result(self):
        base = {
            'article_id': 7,
            'doi': None,
            'title': 'Example',
            'publisher': 'Example Publisher',
            'journal_title': 'Example Journal',
            'route': 'no_doi',
            'route_reason': 'article_has_no_doi_for_publisher_resolution',
            'snapshot_abstract_characters': 0,
        }
        result = terminal_result(base)
        self.assertEqual(result['status'], 'skipped_no_doi')
        self.assertFalse(result['network_request_performed'])

        blocked = dict(base, doi='10.1/example',
                       route='publisher_page_review',
                       route_reason='publisher_landing_preflight_http_403')
        result = terminal_result(blocked)
        self.assertEqual(result['status'], 'publisher_page_review_pending')
        self.assertEqual(result['article_level_abstract_availability'], 'unknown')
        self.assertEqual(result['evidence_scope'],
                         'publisher_family_access_constraint')

    def test_historical_blocked_result_is_pending_or_resolved(self):
        prior = {
            'article_id': 616,
            'doi': '10.1016/j.dss.2026.114688',
            'title': 'Example',
            'publisher': 'Elsevier BV',
            'journal_title': 'Decision Support Systems',
            'status': 'publisher_route_unavailable',
            'policy_version': 'publisher-route-v1-2026-08-03',
            'reason': 'publisher_family_preflight',
        }
        pending = reclassify_result(prior, {
            'abstract': None,
            'abstract_status': 'missing',
            'data_status': 'title_only',
        }, generated_at='2026-08-04T00:00:00+00:00')
        self.assertEqual(pending['corrected_status'],
                         'publisher_page_review_pending')
        self.assertEqual(pending['article_level_abstract_availability'],
                         'unknown')

        resolved = reclassify_result(prior, {
            'abstract': 'A verified abstract with enough content.',
            'abstract_status': 'available',
            'data_status': 'publisher_metadata',
        }, source={'source_name': 'ScienceDirect'},
           generated_at='2026-08-04T00:00:00+00:00')
        self.assertEqual(resolved['corrected_status'],
                         'resolved_abstract_available')
        self.assertEqual(resolved['verified_source']['source_name'],
                         'ScienceDirect')

        ais = dict(prior, publisher='Association for Information Systems')
        false_match = reclassify_result(ais, {
            'abstract': None,
            'abstract_status': 'missing',
            'data_status': 'title_only',
        }, generated_at='2026-08-04T00:00:00+00:00')
        self.assertEqual(false_match['corrected_status'],
                         'metadata_recheck_pending')


if __name__ == '__main__':
    unittest.main()
