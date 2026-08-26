import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BusinessResearchContractTests(unittest.TestCase):
    def test_shared_phase2_page_assets_exist(self):
        html = (ROOT / 'static' / 'business_research.html').read_text(encoding='utf-8')
        self.assertIn('/business_research.css', html)
        self.assertIn('/business_research.js', html)
        self.assertIn('/research-nav.css', html)
        self.assertIn('/research-nav.js', html)
        self.assertIn('Business Research Workspace', html)

    def test_business_research_reuses_global_tabs_and_shared_page_band(self):
        script = (ROOT / 'static' / 'business_research.js').read_text(encoding='utf-8')
        stylesheet = (ROOT / 'static' / 'business_research.css').read_text(encoding='utf-8')
        self.assertIn('function fallbackNav(kind)', script)
        self.assertIn('research-nav-mounted', script)
        self.assertIn('class="br-page-banner"', script)
        self.assertIn('--br-bg: #f0f2f5', stylesheet)
        self.assertIn('.br-page-banner {', stylesheet)
        self.assertIn('.br-detail-head { margin-top: 18px', stylesheet)

    def test_homepage_and_navigation_expose_connected_workspace(self):
        homepage = (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
        navigation = (ROOT / 'static' / 'research-nav.js').read_text(encoding='utf-8')
        for route in ('/abdc/research', '/abdc/theories', '/abdc/constructs',
                      '/abdc/methods', '/abdc/landscape', '/abdc/library'):
            self.assertIn('href="' + route + '"', homepage)
            self.assertIn("href: '" + route + "'", navigation)
        self.assertIn('8 个研究入口 · 5 个学科频道', homepage)
        self.assertIn('Literature Landscape', navigation)

    def test_page_has_required_states_and_data_boundaries(self):
        script = (ROOT / 'static' / 'business_research.js').read_text(encoding='utf-8')
        for marker in ('Unable to load research data', 'br-loading', 'emptyView',
                       'Underexplored Combinations', 'do not by themselves establish',
                       'ResearchStore', 'localStorage', 'Copy APA',
                       'No catalog relationship recorded', 'source_authors',
                       'Key scholars / source authors', 'Theory', 'Constructs', 'Methods',
                       'Origin & measurement sources', 'Foundational method sources',
                       'Original/full text', 'Original chapter text', 'Evidence ledger',
                       'source_works'):
            self.assertIn(marker, script)

    def test_server_registers_phase2_api_and_routes(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        for route in ('/api/abdc/research/overview', '/api/abdc/research/theories',
                      '/api/abdc/research/constructs', '/api/abdc/research/methods',
                      '/api/abdc/research/papers', '/api/abdc/research/landscape',
                      '/api/abdc/research/library', '/abdc/research'):
            self.assertIn(route, server)
        self.assertIn('ensure_business_research_tables', server)
        self.assertIn('rebuild_link_index', server)

    def test_no_theory_specific_diagram_is_hard_coded_in_the_page(self):
        """Every theory page once rendered the same JD-R pathway diagram.

        The model must come from the catalog record for the theory being shown,
        so no theory-specific vocabulary belongs in the view layer.
        """
        script = (ROOT / 'static' / 'business_research.js').read_text(encoding='utf-8')
        for leaked in ('Job Demands', 'Job Resources', 'Exhaustion'):
            self.assertNotIn(leaked, script,
                             'theory-specific content must come from the catalog, not the view')

    def test_years_are_not_formatted_as_thousands(self):
        """`num()` renders 2026 as "2,026"; years must use `plain()`."""
        script = (ROOT / 'static' / 'business_research.js').read_text(encoding='utf-8')
        for banned in ('num(overview.from_year)', 'num(overview.to_year)',
                       'num(paper.year)', 'num(theory.origin_year)'):
            self.assertNotIn(banned, script)
        self.assertIn('plain(overview.from_year)', script)
        self.assertIn('plain(paper.year', script)

    def test_accessible_tab_and_dialog_semantics(self):
        script = (ROOT / 'static' / 'business_research.js').read_text(encoding='utf-8')
        for marker in ('aria-selected', 'aria-controls', "role=\"tabpanel\"",
                       'aria-modal', "event.key === 'Escape'", 'br-visually-hidden',
                       'aria-label='):
            self.assertIn(marker, script)

    def test_note_delete_route_reads_the_right_path_segments(self):
        """`…/papers/<id>/notes/<note_id>/delete` has the paper id 4 segments from
        the end. Indexing -3 lands on the literal "notes" and raised ValueError
        before the handler could answer, so the request died with no response."""
        path = '/api/abdc/research/papers/31/notes/7/delete'
        self.assertEqual(path.split('/')[-3], 'notes')
        match = re.match(r'^/api/abdc/research/papers/(\d+)/notes/(\d+)/delete$', path)
        self.assertEqual((match.group(1), match.group(2)), ('31', '7'))
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertNotIn("int(path.split('/')[-3])", server)

    def test_catalog_cross_references_all_resolve(self):
        catalog = json.loads((ROOT / 'data' / 'research_catalog.json').read_text(encoding='utf-8'))
        theories = {item['id'] for item in catalog['theories']}
        constructs = {item['id'] for item in catalog['constructs']}
        methods = {item['id'] for item in catalog['methods']}
        dangling = []
        for theory in catalog['theories']:
            dangling += [('theory', theory['id'], ref) for ref in theory.get('core_constructs', [])
                         if ref not in constructs]
            dangling += [('theory', theory['id'], ref) for ref in theory.get('related_theories', [])
                         if ref not in theories]
            for pathway in (theory.get('conceptual_model') or {}).get('pathways', []):
                dangling += [('theory', theory['id'], step) for step in pathway['steps']
                             if step not in constructs]
        for construct in catalog['constructs']:
            dangling += [('construct', construct['id'], ref)
                         for ref in construct.get('related_theories', []) if ref not in theories]
            for field in ('antecedents', 'outcomes', 'mediators', 'moderators'):
                dangling += [('construct', construct['id'], ref)
                             for ref in construct.get(field, []) if ref not in constructs]
        for method in catalog['methods']:
            dangling += [('method', method['id'], ref)
                         for ref in method.get('related_methods', []) if ref not in methods]
        self.assertEqual(dangling, [], 'catalog cross-references must resolve to real entities')

    def test_every_method_category_is_populated(self):
        catalog = json.loads((ROOT / 'data' / 'research_catalog.json').read_text(encoding='utf-8'))
        counts = {}
        for method in catalog['methods']:
            counts[method['category']] = counts.get(method['category'], 0) + 1
        for category in ('quantitative', 'experimental', 'computational', 'qualitative'):
            self.assertGreaterEqual(
                counts.get(category, 0), 4,
                'category %s has too few methods to be a usable section' % category)

    def test_broad_tags_are_never_also_precise_tags(self):
        """An umbrella tag must not be counted as if it denoted the entity."""
        catalog = json.loads((ROOT / 'data' / 'research_catalog.json').read_text(encoding='utf-8'))
        for kind in ('theories', 'methods'):
            for entity in catalog[kind]:
                overlap = set(entity.get('tags') or []) & set(entity.get('broad_tags') or [])
                self.assertEqual(overlap, set(),
                                 '%s declares %s as both precise and broad' % (entity['id'], overlap))

    def test_theory_expansion_keeps_book_pack_and_domain_pack_distinct(self):
        catalog = json.loads((ROOT / 'data' / 'research_catalog.json').read_text(encoding='utf-8'))
        theories = catalog['theories']
        book = [item for item in theories
                if item.get('source_pack') == 'management-organization-60']
        self.assertEqual(len(book), 60)
        self.assertTrue(all(item.get('source_page') for item in book))
        self.assertEqual({item.get('source_status') for item in book}, {'book_scan_scaffold'})
        self.assertGreaterEqual(len(theories), 151)
        required = {
            'Operations Management', 'Supply Chain Management', 'Decision Sciences',
            'Finance', 'Accounting', 'Entrepreneurship', 'International Business',
            'Business Analytics / Operations Research', 'Economics',
        }
        exposed = {discipline for item in theories for discipline in item.get('discipline', [])}
        self.assertTrue(required.issubset(exposed))
        self.assertIn('supply-chain-resilience', {item['id'] for item in theories})
        self.assertIn('capital-asset-pricing-model', {item['id'] for item in theories})
        self.assertIn('effectuation-theory', {item['id'] for item in theories})

    def test_service_exposes_expanded_catalog_disciplines(self):
        from services.business_research_service import DISCIPLINES

        for discipline in (
            'Operations Management', 'Supply Chain Management', 'Decision Sciences',
            'Finance', 'Accounting', 'Entrepreneurship', 'International Business',
            'Business Analytics / Operations Research', 'Economics',
        ):
            self.assertIn(discipline, DISCIPLINES)

    def test_theory_construct_method_share_source_evidence_contract(self):
        catalog = json.loads((ROOT / 'data' / 'research_catalog.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(catalog.get('schema_version', 0), 5)
        for kind in ('theories', 'constructs', 'methods'):
            for entity in catalog[kind]:
                works = entity.get('seminal_works') or []
                self.assertTrue(works, '%s %s has no source record' % (kind, entity['id']))
                for work in works:
                    self.assertTrue(work.get('source_role'),
                                    '%s %s source has no evidence role' % (kind, entity['id']))
                    self.assertIn(work.get('access_status'),
                                  {'not_checked', 'open_full_text', 'open_landing_page',
                                   'publisher_page', 'metadata_only', 'access_lookup_failed'})


if __name__ == '__main__':
    unittest.main()
