# -*- coding: utf-8 -*-
"""Guards for the catalog's discipline tags.

The tags drive the discipline filter on all three tabs. Before this pass methods
carried no discipline at all, so the filter returned zero rows for every
discipline on the Methods tab and nobody noticed, because nothing asserted the
filter returns anything.
"""

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

CATALOG = json.loads((ROOT / 'data' / 'research_catalog.json').read_text(encoding='utf-8'))
THEORIES = CATALOG['theories']
CONSTRUCTS = CATALOG['constructs']
METHODS = CATALOG['methods']
ALL_ENTITIES = [('theory', e) for e in THEORIES] + \
               [('construct', e) for e in CONSTRUCTS] + \
               [('method', e) for e in METHODS]


class DisciplineVocabularyTests(unittest.TestCase):
    def test_module_vocabulary_matches_the_service(self):
        """A tag outside the service's tuple is one the UI can never select, so
        the two lists must not drift apart."""
        from research_catalog_disciplines import VALID_DISCIPLINES
        from services.business_research_service import DISCIPLINES
        self.assertEqual(tuple(VALID_DISCIPLINES), tuple(DISCIPLINES))

    def test_every_tag_is_in_the_vocabulary(self):
        from research_catalog_disciplines import VALID_DISCIPLINES
        valid = set(VALID_DISCIPLINES)
        bad = []
        for kind, entity in ALL_ENTITIES:
            for discipline in entity.get('discipline') or []:
                if discipline not in valid:
                    bad.append((kind, entity['id'], discipline))
        self.assertEqual(bad, [])

    def test_tags_are_unique(self):
        """Duplicates would double-count an entity in a discipline tally. Order is
        deliberately not sorted - see test_primary_discipline_is_preserved."""
        bad = []
        for kind, entity in ALL_ENTITIES:
            tags = entity.get('discipline') or []
            if len(tags) != len(set(tags)):
                bad.append((kind, entity['id'], tags))
        self.assertEqual(bad, [])

    def test_primary_discipline_is_preserved(self):
        """The first discipline reads as the entity's home field. Adding a
        cross-channel tag must not displace it: agency theory gains Accounting but
        stays a Management / Strategy theory, and JD-R stays an OB / HR one."""
        by_id = {e['id']: e.get('discipline') or [] for e in THEORIES + CONSTRUCTS}
        expected_first = {
            'job-demands-resources': 'OB / HR',
            'agency-theory': 'Management / Strategy',
            'technology-acceptance-model': 'Information Systems',
            'resource-based-view': 'Management / Strategy',
            'customer-satisfaction': 'Marketing',
            'job-satisfaction': 'OB / HR',
        }
        for entity_id, first in expected_first.items():
            self.assertEqual(by_id[entity_id][0], first,
                             '%s: home discipline displaced, now %s'
                             % (entity_id, by_id[entity_id]))


class DisciplineCoverageTests(unittest.TestCase):
    def test_every_entity_carries_at_least_one_discipline(self):
        missing = [(kind, e['id']) for kind, e in ALL_ENTITIES
                   if not (e.get('discipline') or [])]
        self.assertEqual(missing, [], 'an untagged entity is invisible to every filter')

    def test_methods_carry_disciplines(self):
        """The specific regression this pass fixed: all 36 methods had only a
        category, so filtering methods by any discipline returned nothing."""
        untagged = sorted(m['id'] for m in METHODS if not (m.get('discipline') or []))
        self.assertEqual(untagged, [])

    def test_every_discipline_returns_results_for_every_kind(self):
        """The filter offers all fourteen disciplines on all three tabs. A
        discipline with no entities of some kind is a dead option in the UI."""
        from research_catalog_disciplines import VALID_DISCIPLINES
        empty = []
        for discipline in VALID_DISCIPLINES:
            for label, group in (('theories', THEORIES), ('constructs', CONSTRUCTS),
                                 ('methods', METHODS)):
                n = sum(1 for e in group if discipline in (e.get('discipline') or []))
                if n == 0:
                    empty.append((discipline, label))
        self.assertEqual(empty, [])


class DisciplineAssignmentTests(unittest.TestCase):
    def test_assignment_module_covers_every_method(self):
        from research_catalog_disciplines import METHOD_DISCIPLINES
        catalog_ids = {m['id'] for m in METHODS}
        assigned = set(METHOD_DISCIPLINES)
        self.assertEqual(sorted(catalog_ids - assigned), [],
                         'a method with no assignment would lose its tags on rebuild')
        self.assertEqual(sorted(assigned - catalog_ids), [],
                         'an assignment for a method that no longer exists is stale')

    def test_extra_disciplines_name_real_entities(self):
        from research_catalog_disciplines import EXTRA_DISCIPLINES
        known = {e['id'] for e in THEORIES} | {e['id'] for e in CONSTRUCTS}
        unknown = sorted(set(EXTRA_DISCIPLINES) - known)
        self.assertEqual(unknown, [])

    def test_extra_disciplines_actually_landed(self):
        """Guards against an entry being added to the module but silently lost."""
        from research_catalog_disciplines import EXTRA_DISCIPLINES
        by_id = {e['id']: e for e in THEORIES + CONSTRUCTS}
        missing = []
        for entity_id, extra in EXTRA_DISCIPLINES.items():
            have = set(by_id[entity_id].get('discipline') or [])
            for discipline in extra:
                if discipline not in have:
                    missing.append((entity_id, discipline))
        self.assertEqual(missing, [])

    def test_cross_channel_examples_are_tagged_both_ways(self):
        """The cases that prompted the pass. Job design is studied in OB and in
        management; technology acceptance in IS and in marketing; agency theory in
        strategy, accounting and finance."""
        by_id = {e['id']: set(e.get('discipline') or []) for e in THEORIES + CONSTRUCTS}
        expected = {
            'job-demands-resources': {'OB / HR', 'Management / Strategy'},
            'job-characteristics-model': {'OB / HR', 'Management / Strategy'},
            'technology-acceptance-model': {'Information Systems', 'Marketing'},
            'agency-theory': {'Management / Strategy', 'Accounting', 'Finance'},
            'resource-based-view': {'Management / Strategy', 'Marketing'},
        }
        for entity_id, required in expected.items():
            self.assertTrue(
                required.issubset(by_id[entity_id]),
                '%s: expected %s, has %s' % (entity_id, sorted(required),
                                             sorted(by_id[entity_id])))


class DisciplineSearchTests(unittest.TestCase):
    """Exercises the filter itself.

    _catalog_search does the discipline filtering and needs only the catalog. The
    payload builders call _ensure_index, which rebuilds the entire paper-link
    index whenever the catalog fingerprint moves, so they are used once rather
    than once per discipline.
    """

    @classmethod
    def setUpClass(cls):
        from services import business_research_service
        cls.svc = business_research_service
        cls.catalog = business_research_service.load_catalog()

    def test_every_discipline_filters_every_kind(self):
        from research_catalog_disciplines import VALID_DISCIPLINES
        for discipline in VALID_DISCIPLINES:
            for kind in ('theories', 'constructs', 'methods'):
                rows = self.svc._catalog_search(self.catalog, kind, '', discipline)
                self.assertTrue(
                    rows, 'no %s for discipline %r' % (kind, discipline))
                for entity in rows:
                    self.assertIn(discipline, entity.get('discipline') or [],
                                  '%s: %s leaked past the %r filter'
                                  % (kind, entity['id'], discipline))

    def test_filter_actually_narrows(self):
        """A filter that returns everything for every discipline would pass the
        test above while telling the reader nothing."""
        narrowed = False
        for discipline in ('Computational Social Science', 'Economics',
                           'Business Analytics / Operations Research'):
            for kind in ('theories', 'constructs', 'methods'):
                everything = self.svc._catalog_search(self.catalog, kind, '', None)
                subset = self.svc._catalog_search(self.catalog, kind, '', discipline)
                self.assertLessEqual(len(subset), len(everything))
                if len(subset) < len(everything):
                    narrowed = True
        self.assertTrue(narrowed, 'the discipline filter never narrows the list')

    def test_methods_payload_carries_the_filter_end_to_end(self):
        """One trip through the real payload builder, which is the path the
        Methods tab uses and the one that returned nothing before this pass."""
        payload = self.svc.build_methods_payload({'discipline': 'Marketing'})
        self.assertTrue(payload['entities'])
        for card in payload['entities']:
            self.assertIn('Marketing', card.get('discipline') or [])


if __name__ == '__main__':
    unittest.main()
