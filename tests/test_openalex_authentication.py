"""Verify credential destination boundaries and daily collector integration."""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from services import abdc_astar_research_service as radar
from services import astar_affiliation_service as affiliation
from services import openalex_budget as budget


class OpenAlexAuthenticationTests(unittest.TestCase):
    def test_only_openalex_https_receives_the_configured_key(self):
        with patch.dict(os.environ, {'OPENALEX_API_KEY': 'dummy-test-key'}):
            headers = budget.openalex_headers('https://api.openalex.org/works')
            self.assertEqual(headers['Authorization'], 'Bearer dummy-test-key')
            for url in ('https://api.crossref.org/works',
                        'https://api.openalex.org.example.com/works',
                        'http://api.openalex.org/works'):
                self.assertNotIn('Authorization', budget.openalex_headers(url))

    def test_cli_reads_only_the_openalex_setting_from_local_config(self):
        content = '# ignored\nOTHER_SECRET=never-load\nOPENALEX_API_KEY="dummy-local-key"\n'
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(type(budget._SOURCE_SETTINGS_PATH), 'read_text', return_value=content):
            headers = budget.openalex_headers('https://api.openalex.org/works')
            self.assertEqual(headers['Authorization'], 'Bearer dummy-local-key')
            self.assertNotIn('OTHER_SECRET', os.environ)

    def test_preserves_explicit_headers_and_allows_missing_config(self):
        original = {'authorization': 'Bearer caller-key', 'User-Agent': 'client'}
        with patch.dict(os.environ, {'OPENALEX_API_KEY': 'dummy-env-key'}):
            self.assertEqual(budget.openalex_headers('https://api.openalex.org/works', original), original)
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(type(budget._SOURCE_SETTINGS_PATH), 'read_text', side_effect=FileNotFoundError):
            self.assertEqual(budget.openalex_headers('https://api.openalex.org/works'), {})

    def test_radar_keeps_auth_out_of_query_parameters(self):
        response = SimpleNamespace(status_code=200, headers={}, json=lambda: {'results': []},
                                   raise_for_status=lambda: None)
        with patch.dict(os.environ, {'OPENALEX_API_KEY': 'dummy-test-key'}), \
             patch.object(radar.requests, 'get', return_value=response) as getter:
            radar.fetch_openalex('0001-4273', '2026-01-01', '2026-10-06')
            call = getter.call_args
            self.assertEqual(call.kwargs['headers']['Authorization'], 'Bearer dummy-test-key')
            self.assertEqual(call.kwargs['params']['per_page'], 100)
            self.assertNotIn('api_key', call.kwargs['params'])
            radar._http_get_json('https://api.crossref.org/works')
            self.assertNotIn('Authorization', getter.call_args.kwargs['headers'])

    def test_affiliation_batches_use_the_same_authenticated_header(self):
        response = SimpleNamespace(status_code=200, headers={}, json=lambda: {'results': []},
                                   raise_for_status=lambda: None)
        session = SimpleNamespace(get=lambda *args, **kwargs: response)
        with patch.dict(os.environ, {'OPENALEX_API_KEY': 'dummy-test-key'}), \
             patch.object(session, 'get', return_value=response) as getter:
            affiliation._fetch_works(['W123'], session)
            self.assertEqual(getter.call_args.kwargs['headers']['Authorization'], 'Bearer dummy-test-key')
            self.assertNotIn('api_key', getter.call_args.kwargs['params'])


if __name__ == '__main__':
    unittest.main()
