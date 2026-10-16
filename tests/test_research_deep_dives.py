import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

CATALOG = json.loads((ROOT / 'data' / 'research_catalog.json').read_text(encoding='utf-8'))
THEORIES = {t['id']: t for t in CATALOG['theories']}
CONSTRUCTS = {c['id']: c for c in CATALOG['constructs']}
METHODS = {m['id']: m for m in CATALOG['methods']}
ALL_ENTITIES = dict(THEORIES, **CONSTRUCTS, **METHODS)
WITH_DIVE = {eid: e for eid, e in ALL_ENTITIES.items() if e.get('deep_dive')}


class DeepDiveShapeTests(unittest.TestCase):
    def test_some_theories_carry_an_analysis(self):
        self.assertGreaterEqual(len(WITH_DIVE), 10)

    def test_every_entity_declares_its_depth(self):
        """A page must be able to say whether an analysis exists, so the status is
        required on theories, constructs, and methods alike."""
        missing = [eid for eid, e in ALL_ENTITIES.items() if not e.get('deep_dive_status')]
        self.assertEqual(missing, [])
        for eid, entity in ALL_ENTITIES.items():
            expected = 'authored_analysis' if entity.get('deep_dive') else 'not_written'
            self.assertEqual(entity['deep_dive_status'], expected, eid)

    def test_every_method_has_an_analysis(self):
        """The method catalog is complete. A method added later without a deep
        dive would sit in a finished section with nothing to say, so this guards
        the completion rather than merely recording it."""
        missing = sorted(mid for mid, m in METHODS.items() if not m.get('deep_dive'))
        self.assertEqual(missing, [], 'every catalog method needs a written analysis')

    def test_every_construct_has_an_analysis(self):
        """The construct catalog is complete, like the method catalog. A construct
        added later without a deep dive would sit in a finished channel with only
        a one-line definition, which is the gap this work exists to close."""
        missing = sorted(cid for cid, c in CONSTRUCTS.items() if not c.get('deep_dive'))
        self.assertEqual(missing, [], 'every catalog construct needs a written analysis')

    def test_every_theory_has_an_analysis(self):
        """All three catalogs are complete. An entity added later without a deep
        dive would sit in a finished channel carrying only a one-line record,
        which is the gap this work exists to close."""
        missing = sorted(tid for tid, t in THEORIES.items() if not t.get('deep_dive'))
        self.assertEqual(missing, [], 'every catalog theory needs a written analysis')

    def test_no_paragraph_is_reused_across_entries(self):
        """Several entities share a name across kinds - transformational leadership
        is both a theory and a construct, and so are cognitive appraisal, goal
        orientation, regulatory focus, self-control and social information. The
        split is deliberate: the construct entry covers measurement and the theory
        entry covers the argument. Reusing a paragraph verbatim collapses that
        split and shows the reader the same sentence twice."""
        seen = {}
        for eid, entity in ALL_ENTITIES.items():
            dive = entity.get('deep_dive')
            if not dive:
                continue
            paragraphs = []
            for section in ('situation', 'argument', 'development', 'today'):
                paragraphs.extend(dive.get(section) or [])
            limits = dive.get('limitations') or {}
            for section in ('theoretical', 'empirical', 'temporal'):
                paragraphs.extend(limits.get(section) or [])
            for para in paragraphs:
                seen.setdefault(para['en'], []).append(eid)
        reused = {text: ids for text, ids in seen.items() if len(ids) > 1}
        self.assertEqual(
            reused, {},
            'these paragraphs appear in more than one entry: %s'
            % sorted((tuple(ids), text[:60]) for text, ids in reused.items()))

    def test_all_three_kinds_have_analyses(self):
        for label, group in (('theories', THEORIES), ('constructs', CONSTRUCTS), ('methods', METHODS)):
            written = [eid for eid, e in group.items() if e.get('deep_dive')]
            self.assertGreaterEqual(len(written), 5, '%s has too few analyses' % label)

    def test_no_discipline_is_left_without_an_analysis(self):
        """A workspace that claims to cover business research should not have a
        discipline channel where every theory is a one-line record."""
        from collections import Counter
        written, total = Counter(), Counter()
        for theory in THEORIES.values():
            for discipline in theory.get('discipline', []):
                total[discipline] += 1
                if theory.get('deep_dive'):
                    written[discipline] += 1
        uncovered = sorted(d for d in total if written[d] == 0)
        self.assertEqual(uncovered, [], 'these disciplines have no written analysis at all')

    def test_each_analysis_answers_every_question_it_promises(self):
        for tid, theory in WITH_DIVE.items():
            dive = theory['deep_dive']
            for block in ('situation', 'argument', 'development', 'today'):
                self.assertTrue(dive.get(block), '%s has no %s' % (tid, block))
            self.assertTrue(dive.get('era'), '%s has no era' % tid)
            self.assertTrue(dive.get('debates'), '%s records no debate' % tid)

    def test_limitations_are_separated_by_kind(self):
        """The whole point is that a measurement artefact and an era-bound
        assumption are different problems needing different responses."""
        for tid, theory in WITH_DIVE.items():
            limits = theory['deep_dive']['limitations']
            for kind in ('theoretical', 'empirical', 'temporal'):
                self.assertTrue(limits.get(kind), '%s has no %s limitation' % (tid, kind))

    def test_every_theory_with_an_analysis_states_an_era_bound_limit(self):
        """This is the field the user asked for and the one most easily skipped."""
        for tid, theory in WITH_DIVE.items():
            temporal = theory['deep_dive']['limitations']['temporal']
            self.assertGreaterEqual(len(temporal), 2, '%s needs at least two era-bound limits' % tid)

    def test_every_paragraph_is_bilingual_and_substantive(self):
        for tid, theory in WITH_DIVE.items():
            dive = theory['deep_dive']
            blocks = [dive[k] for k in ('situation', 'argument', 'development', 'today')]
            blocks += list(dive['limitations'].values())
            for block in blocks:
                for para in block:
                    self.assertIn('en', para)
                    self.assertIn('zh', para)
                    self.assertGreater(len(para['en']), 80, '%s: english too short' % tid)
                    self.assertGreater(len(para['zh']), 20, '%s: chinese missing' % tid)

    def test_debates_record_opposing_positions_and_a_status(self):
        for tid, theory in WITH_DIVE.items():
            for debate in theory['deep_dive']['debates']:
                self.assertTrue(debate['name'] and debate['name_zh'], tid)
                self.assertGreaterEqual(len(debate['positions']), 2,
                                        '%s: a debate needs opposing positions' % tid)
                for position in debate['positions']:
                    self.assertTrue(position['holder'], tid)
                    self.assertTrue(position['claim'] and position['claim_zh'], tid)
                self.assertTrue(debate['status'] and debate['status_zh'], tid)

    def test_analysis_is_substantially_longer_than_the_short_record(self):
        """The complaint this answers was that entries only said what a theory is."""
        for tid, theory in WITH_DIVE.items():
            dive = theory['deep_dive']
            total = 0
            for key in ('situation', 'argument', 'development', 'today'):
                total += sum(len(p['en']) for p in dive[key])
            for block in dive['limitations'].values():
                total += sum(len(p['en']) for p in block)
            self.assertGreater(total, 1500, '%s analysis is too thin to be worth a section' % tid)


class DeepDiveServiceTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT))
        from services import business_research_service
        self.svc = business_research_service

    def test_list_payload_carries_the_flag_but_not_the_text(self):
        """151 full analyses would bloat the catalog page for a badge's worth of
        information, so the list must carry the flag only."""
        payload = self.svc.build_theories_payload({})
        self.assertGreaterEqual(payload['deep_dive_total'], 10)
        for card in payload['entities']:
            self.assertNotIn('deep_dive', card)
            self.assertIn('has_deep_dive', card)

    def test_depth_filter_returns_only_analysed_theories(self):
        payload = self.svc.build_theories_payload({'depth': 'deep'})
        self.assertTrue(payload['entities'])
        for card in payload['entities']:
            self.assertTrue(card['has_deep_dive'])
        self.assertEqual(len(payload['entities']), payload['deep_dive_total'])

    def test_detail_serves_the_analysis_and_labels_it_as_written(self):
        detail = self.svc.build_theory_detail('resource-based-view')
        self.assertEqual(detail['deep_dive_status'], 'authored_analysis')
        self.assertTrue(detail['deep_dive']['limitations']['temporal'])
        self.assertIn('Written analysis', detail['deep_dive_note'])

    def test_construct_and_method_details_serve_the_analysis(self):
        construct = self.svc.build_construct_detail('autonomy', {})
        self.assertEqual(construct['deep_dive_status'], 'authored_analysis')
        self.assertTrue(construct['deep_dive']['limitations']['temporal'])
        method = self.svc.build_method_detail('difference-in-differences')
        self.assertEqual(method['deep_dive_status'], 'authored_analysis')
        self.assertTrue(method['deep_dive']['limitations']['temporal'])

    def test_depth_filter_works_for_constructs_and_methods(self):
        for payload in (self.svc.build_constructs_payload({'depth': 'deep'}),
                        self.svc.build_methods_payload({'depth': 'deep'})):
            self.assertTrue(payload['entities'])
            for card in payload['entities']:
                self.assertTrue(card['has_deep_dive'])

    def test_detail_says_so_when_no_analysis_exists(self):
        """Coverage is still partial, so this normally runs against a real entry.
        Once every entity carries an analysis the data no longer reaches the
        branch, and the branch itself is checked instead - the page must keep
        being able to say 'not written' for an entry added later."""
        without = next((tid for tid, t in THEORIES.items() if not t.get('deep_dive')), None)
        if without is None:
            note = self.svc._deep_dive_note({'id': 'unwritten'})
            self.assertIn('No long-form analysis', note)
            return
        detail = self.svc.build_theory_detail(without)
        self.assertEqual(detail['deep_dive_status'], 'not_written')
        self.assertIsNone(detail['deep_dive'])
        self.assertIn('No long-form analysis', detail['deep_dive_note'])


class DeepDivePageTests(unittest.TestCase):
    def setUp(self):
        self.script = (ROOT / 'static' / 'business_research.js').read_text(encoding='utf-8')

    def test_page_renders_each_analysis_block(self):
        for marker in ('Why this theory exists', 'How the argument runs', 'Open debates',
                       'Limitations · 局限性', 'Bound to its era', 'Where it stands today',
                       'deepDiveSections', 'bilingualParagraphs', 'debateList'):
            self.assertIn(marker, self.script)

    def test_short_lists_are_suppressed_when_an_analysis_exists(self):
        """Otherwise the page repeats itself with less detail."""
        self.assertIn("(data.deep_dive ? '' :", self.script)

    def test_catalog_page_exposes_the_depth_filter(self):
        self.assertIn('br-depth-filter', self.script)
        self.assertIn('has_deep_dive', self.script)

    def test_section_labels_differ_by_entity_kind(self):
        """The same schema means different things for a theory, a construct, and a
        method; labelling a construct page 'Why this theory exists' would be wrong."""
        self.assertIn('DIVE_LABELS', self.script)
        for marker in ('What it is trying to capture', 'What problem it solves',
                       'How it is defined and measured', 'How the inference works',
                       'Assumptions that bite', 'Measurement and validity'):
            self.assertIn(marker, self.script)
        for kind in ("deepDiveSections(data, 'theory')", "deepDiveSections(data, 'construct')",
                     "deepDiveSections(data, 'method')"):
            self.assertIn(kind, self.script)


if __name__ == '__main__':
    unittest.main()
