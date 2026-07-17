# -*- coding: utf-8 -*-
"""全站研究导航的静态契约测试。"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'static'
PRIMARY_PAGES = (
    'index.html',
    'dashboard.html',
    'fiscal_debt.html',
    'china_rates.html',
    'housing.html',
    'us_macro.html',
    'abdc/index.html',
    'abdc_astar_research.html',
)


class ResearchNavigationContractTests(unittest.TestCase):
    def test_primary_pages_load_shared_navigation(self):
        missing = []
        for relative_path in PRIMARY_PAGES:
            html = (STATIC / relative_path).read_text(encoding='utf-8')
            if '/research-nav.css' not in html or '/research-nav.js' not in html:
                missing.append(relative_path)
        self.assertEqual(missing, [], f'以下页面未接入共享导航: {missing}')

    def test_navigation_has_exactly_three_primary_groups(self):
        script = (STATIC / 'research-nav.js').read_text(encoding='utf-8')
        group_block = script.split('const groups = {', 1)[1].split('};', 1)[0]
        self.assertEqual(group_block.count("label: '中国宏观'"), 1)
        self.assertEqual(group_block.count("label: '美国宏观'"), 1)
        self.assertEqual(group_block.count("label: 'ABDC 商科研究'"), 1)

    def test_existing_routes_are_present_in_navigation(self):
        script = (STATIC / 'research-nav.js').read_text(encoding='utf-8')
        for route in ('/dashboard', '/fiscal-debt', '/china-rates', '/housing',
                      '/us-macro', '/abdc', '/abdc-astar-research'):
            self.assertIn(f"href: '{route}'", script)

    def test_personal_research_fields_have_landing_filters(self):
        navigation = (STATIC / 'research-nav.js').read_text(encoding='utf-8')
        radar = (STATIC / 'abdc_astar_research.html').read_text(encoding='utf-8')
        for slug in ('information-systems', 'management', 'marketing', 'ob-hr',
                     'computational-social-science'):
            self.assertIn(slug, navigation)
            self.assertIn(slug, radar)

    def test_shared_navigation_exposes_access_mode(self):
        navigation = (STATIC / 'research-nav.js').read_text(encoding='utf-8')
        self.assertIn("fetch('/api/health'", navigation)
        self.assertIn('局域网只读', navigation)
        self.assertIn('本机管理', navigation)
        self.assertIn('protectReadOnlyControls', navigation)
        self.assertIn('MutationObserver', navigation)


if __name__ == '__main__':
    unittest.main()
