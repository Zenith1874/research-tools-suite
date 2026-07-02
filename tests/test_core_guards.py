# -*- coding: utf-8 -*-
"""核心防线测试：
1. classify_article 领域回归防护——防止 2026-06 那种"法学/统计被商科关键词改写"复发
2. _card 数据纪律不变量——official 必须有 source_url、derived 必须有 formula
3. fiscal monitor payload 契约——全部卡片满足数据纪律(集成测试，需本地 DB)
"""
import os
import unittest

from services.abdc_astar_research_service import classify_article
from services.fiscal_monitor_service import _card

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pboc_data.db')


def _article(area, title='A study', abstract=''):
    return {'title': title, 'abstract': abstract, 'concepts': [],
            '_journal_discipline_area': area}


class ClassifyArticleAreaGuards(unittest.TestCase):
    """单一学科期刊的 broad_area 不得被零星商科关键词改写。"""

    def test_statistics_journal_not_overridden_by_management_keywords(self):
        art = _article('Statistics / Methods',
                       title='Estimating panel models',
                       abstract='We study firm performance and corporate governance data with a new estimator.')
        self.assertEqual(classify_article(art)['broad_area'], 'Statistics / Methods')

    def test_law_journal_not_overridden_by_marketing_keywords(self):
        art = _article('Law', title='Consumer protection statutes',
                       abstract='Consumer brand advertising disputes in federal courts.')
        self.assertEqual(classify_article(art)['broad_area'], 'Law')

    def test_finance_journal_not_overridden(self):
        art = _article('Finance', title='Asset pricing',
                       abstract='Employee turnover at the workplace affects strategy.')
        self.assertEqual(classify_article(art)['broad_area'], 'Finance')

    def test_other_can_be_refined_by_keywords(self):
        art = _article('Other', title='Brand study',
                       abstract='Consumer brand advertising and customer response.')
        self.assertEqual(classify_article(art)['broad_area'], 'Marketing')

    def test_management_can_be_refined_by_keywords(self):
        art = _article('Management / Strategy', title='Ad spending',
                       abstract='Consumer brand advertising and customer response.')
        self.assertEqual(classify_article(art)['broad_area'], 'Marketing')

    def test_unknown_journal_defaults_other_without_keywords(self):
        art = _article(None, title='Untitled work', abstract='')
        self.assertEqual(classify_article(art)['broad_area'], 'Other')


class CardDisciplineInvariants(unittest.TestCase):
    """_card 是数据纪律的守门员：违规展示必须被自动降级。"""

    def test_official_without_source_url_downgraded(self):
        c = _card('测试', 100.0, '亿元', '2026-01', 'official', source_url=None)
        self.assertEqual(c['data_status'], 'missing')
        self.assertIsNone(c['value'])
        self.assertTrue(c['warning'])

    def test_derived_without_formula_downgraded(self):
        c = _card('测试', 100.0, '亿元', '2026-01', 'derived', source_url='https://x', formula=None)
        self.assertEqual(c['data_status'], 'missing')
        self.assertIsNone(c['value'])

    def test_official_with_source_url_kept(self):
        c = _card('测试', 100.0, '亿元', '2026-01', 'official', source_url='https://gov.example/a')
        self.assertEqual(c['data_status'], 'official')
        self.assertEqual(c['value'], 100.0)

    def test_derived_with_formula_kept(self):
        c = _card('测试', 1.0, '%', '2026-01', 'derived', source_url='https://x', formula='a/b')
        self.assertEqual(c['data_status'], 'derived')

    def test_missing_never_carries_value(self):
        c = _card('测试', 123.0, '亿元', '2026-01', 'missing')
        self.assertIsNone(c['value'])


@unittest.skipUnless(os.path.exists(DB_PATH), '本地 pboc_data.db 不存在，跳过集成契约测试')
class FiscalPayloadContract(unittest.TestCase):
    """整个 fiscal monitor payload 里不允许出现违反数据纪律的卡片。"""

    @classmethod
    def setUpClass(cls):
        from services.fiscal_monitor_service import build_fiscal_monitor_payload
        cls.payload = build_fiscal_monitor_payload(DB_PATH)

    def test_has_core_sections(self):
        for key in ('government_debt_overview', 'debt_rollover_pressure', 'pboc_monetization_pressure'):
            self.assertIn(key, self.payload['sections'])

    def test_all_cards_satisfy_data_discipline(self):
        violations = []
        for sec_name, sec in self.payload['sections'].items():
            cards = list(sec.get('cards') or []) + list(sec.get('repo_cards') or []) \
                    + list(sec.get('budget_cards') or [])
            for c in cards:
                if c.get('data_status') == 'official' and not c.get('source_url'):
                    violations.append(f"{sec_name}/{c.get('label')}: official 无 source_url")
                if c.get('data_status') == 'derived' and not c.get('formula'):
                    violations.append(f"{sec_name}/{c.get('label')}: derived 无 formula")
                if c.get('data_status') in ('missing', 'error') and c.get('value') is not None:
                    violations.append(f"{sec_name}/{c.get('label')}: missing 却带 value")
        self.assertEqual(violations, [], '数据纪律违规:\n' + '\n'.join(violations))


if __name__ == '__main__':
    unittest.main()
