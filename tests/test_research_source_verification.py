import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    'verify_research_sources', ROOT / 'scripts' / 'verify_research_sources.py')
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)


def work(title, year, surnames, doi='10.1000/x', venue='Some Journal', cited=100):
    return {
        'id': 'https://openalex.org/W1',
        'doi': 'https://doi.org/' + doi,
        'title': title,
        'publication_year': year,
        'cited_by_count': cited,
        'authorships': [{'author': {'display_name': name}} for name in surnames],
        'primary_location': {'source': {'display_name': venue}},
    }


def crossref_work(title, year, surnames, doi='10.1000/x', venue='Some Journal', cited=100):
    return {
        'DOI': doi,
        'title': [title],
        'published-print': {'date-parts': [[year, 1, 1]]},
        'container-title': [venue],
        'is-referenced-by-count': cited,
        'author': [{'family': name.split()[-1], 'given': name.rsplit(' ', 1)[0]
                    if ' ' in name else ''} for name in surnames],
        'type': 'journal-article',
    }


class StubResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = '{}'

    def json(self):
        return self._payload


class StubSession:
    def __init__(self, results, status=200):
        self.results = results
        self.status = status
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return StubResponse({'results': self.results}, self.status)


class CrossrefStubSession(StubSession):
    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return StubResponse({'message': {'items': self.results}}, self.status)


class SourceMatchingTests(unittest.TestCase):
    """The matcher decides what gets labelled 'verified', so a wrong match is
    worse than no match at all."""

    def setUp(self):
        self.record = {
            'authors': 'Demerouti, Bakker, Nachreiner & Schaufeli',
            'year': 2001,
            'title': 'The job demands-resources model of burnout',
            'venue': 'Journal of Applied Psychology',
            'verification': 'pending_verification',
        }

    def test_exact_record_is_matched_and_applied(self):
        candidate = work('The job demands-resources model of burnout', 2001,
                         ['Evangelia Demerouti', 'Arnold Bakker', 'Friedhelm Nachreiner'],
                         doi='10.1037/0021-9010.86.3.499')
        session = StubSession([candidate])
        found, reason = verify._lookup(session, self.record)
        self.assertIsNotNone(found, reason)
        verify._apply(self.record, found)
        self.assertEqual(self.record['verification'], 'verified_openalex')
        self.assertEqual(self.record['doi'], '10.1037/0021-9010.86.3.499')
        self.assertEqual(self.record['cited_by_count'], 100)
        self.assertIsNone(self.record['verification_note'])

    def test_crossref_fallback_is_matched_and_applied(self):
        candidate = crossref_work(
            'The job demands-resources model of burnout', 2001,
            ['Evangelia Demerouti', 'Arnold Bakker', 'Friedhelm Nachreiner'],
            doi='10.1037/0021-9010.86.3.499')
        found, reason = verify._lookup_crossref(CrossrefStubSession([candidate]), self.record)
        self.assertIsNotNone(found, reason)
        verify._apply_crossref(self.record, found)
        self.assertEqual(self.record['verification'], 'verified_crossref')
        self.assertEqual(self.record['verification_source'], 'Crossref')
        self.assertEqual(self.record['doi'], '10.1037/0021-9010.86.3.499')
        self.assertEqual(self.record['crossref_year'], 2001)
        self.assertEqual(self.record['crossref_cited_by_count'], 100)

    def test_same_title_by_different_authors_and_year_is_rejected(self):
        """A title-only hit is how a wrong paper gets stamped verified."""
        candidate = work('The job demands-resources model of burnout', 1975,
                         ['Someone Else', 'Another Person'])
        found, reason = verify._lookup(StubSession([candidate]), self.record)
        self.assertIsNone(found)
        self.assertEqual(reason, 'no confident match')

    def test_unrelated_title_is_rejected(self):
        candidate = work('A completely different paper about supply chains', 2001,
                         ['Evangelia Demerouti'])
        found, reason = verify._lookup(StubSession([candidate]), self.record)
        self.assertIsNone(found)
        self.assertEqual(reason, 'no confident match')

    def test_book_review_is_not_accepted_as_original_source(self):
        candidate = crossref_work(
            'Book Review: The Constitution of Society: Outline of the Theory of Structuration',
            1985, ['Anthony Giddens'])
        found, reason = verify._lookup_crossref(
            CrossrefStubSession([candidate]), {
                'authors': 'Anthony Giddens', 'year': 1984,
                'title': 'The Constitution of Society: Outline of the Theory of Structuration',
                'kind': 'origin', 'verification': 'pending_verification',
            })
        self.assertIsNone(found)
        self.assertIn('book review', reason)

    def test_machine_match_records_version_review_flag(self):
        candidate = work('The job demands-resources model of burnout', 2010,
                         ['Evangelia Demerouti', 'Arnold Bakker'])
        record = dict(self.record)
        verify._apply(record, candidate)
        self.assertEqual(record['verification_status'], 'MACHINE_MATCHED')
        self.assertEqual(record['version_review_status'], 'VERSION_REVIEW_REQUIRED')

    def test_right_authors_but_wrong_year_still_matches(self):
        """Recorded years are often a reprint or an online-first date."""
        candidate = work('The job demands-resources model of burnout', 2002,
                         ['Evangelia Demerouti', 'Arnold Bakker'])
        found, _ = verify._lookup(StubSession([candidate]), self.record)
        self.assertIsNotNone(found)

    def test_best_candidate_wins_over_weaker_one(self):
        weak = work('The job demands-resources model', 1990, ['Unrelated Author'])
        strong = work('The job demands-resources model of burnout', 2001,
                      ['Evangelia Demerouti', 'Arnold Bakker'], doi='10.1037/correct')
        found, _ = verify._lookup(StubSession([weak, strong]), self.record)
        self.assertIsNotNone(found)
        self.assertIn('correct', found['doi'])

    def test_exhausted_budget_raises_instead_of_retrying(self):
        class BudgetSession(StubSession):
            def get(self, url, params=None, timeout=None):
                self.calls += 1
                response = StubResponse({}, 429)
                response.text = '{"error":"Rate limit exceeded","message":"Insufficient budget."}'
                return response

        session = BudgetSession([])
        with self.assertRaises(verify.BudgetExhausted):
            verify._lookup(session, self.record)
        self.assertEqual(session.calls, 1, 'a spent budget must not be retried')

    def test_surname_parsing(self):
        self.assertEqual(verify._surnames('Blau'), ['blau'])
        self.assertEqual(verify._surnames('Cropanzano & Mitchell'), ['cropanzano', 'mitchell'])
        self.assertEqual(
            verify._surnames('Mitchell, Holtom, Lee, Sablynski & Erez'),
            ['mitchell', 'holtom', 'lee', 'sablynski', 'erez'])


class CatalogSourceTests(unittest.TestCase):
    def test_every_theory_records_at_least_one_seminal_work(self):
        import json
        catalog = json.loads((ROOT / 'data' / 'research_catalog.json').read_text(encoding='utf-8'))
        missing = [t['id'] for t in catalog['theories'] if not t.get('seminal_works')]
        self.assertEqual(missing, [], 'every theory needs a recorded origin reference')

    def test_unverified_works_carry_no_doi(self):
        """An unverified row must not display a DOI that nobody checked."""
        import json
        catalog = json.loads((ROOT / 'data' / 'research_catalog.json').read_text(encoding='utf-8'))
        bad = []
        for kind in ('theories', 'constructs', 'methods'):
            for entity in catalog[kind]:
                for record in entity.get('seminal_works', []):
                    if record.get('verification') not in verify.VERIFIED_STATUSES and record.get('doi'):
                        bad.append((kind, entity['id'], record['title']))
        self.assertEqual(bad, [])

    def test_verified_records_have_a_provider_and_access_state(self):
        import json
        catalog = json.loads((ROOT / 'data' / 'research_catalog.json').read_text(encoding='utf-8'))
        allowed_access = {
            'not_checked', 'open_full_text', 'open_landing_page',
            'publisher_page', 'metadata_only', 'access_lookup_failed',
        }
        for kind in ('theories', 'constructs', 'methods'):
            for entity in catalog[kind]:
                for record in entity.get('seminal_works', []):
                    if record.get('verification') in verify.VERIFIED_STATUSES:
                        self.assertTrue(record.get('verification_source'))
                        self.assertTrue(record.get('doi'), '%s %s lacks DOI' % (kind, entity['id']))
                        self.assertIn(record.get('access_status'), allowed_access)

    def test_theories_and_constructs_are_bilingual(self):
        import json
        catalog = json.loads((ROOT / 'data' / 'research_catalog.json').read_text(encoding='utf-8'))
        for kind, name_field, def_field in (('theories', 'name_zh', 'definition_zh'),
                                            ('constructs', 'name_zh', 'definition_zh'),
                                            ('methods', 'name_zh', 'description_zh')):
            for entity in catalog[kind]:
                self.assertTrue(entity.get(name_field), '%s %s has no %s' % (kind, entity['id'], name_field))
                self.assertTrue(entity.get(def_field), '%s %s has no %s' % (kind, entity['id'], def_field))


if __name__ == '__main__':
    unittest.main()
