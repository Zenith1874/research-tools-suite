# -*- coding: utf-8 -*-
"""付费判定不能被免费的规则法顶掉。

The radar re-fetches a 14-day window every day, so any article published
recently comes back through ``_upsert_article``'s update branch on every run.
That branch re-runs the free rules classifier and used to write its verdict --
and ``classification_method='rules'`` -- straight over whatever was there.

The loop that closed was expensive rather than merely lossy: an article reaches
the LLM only because the rules classifier called it ``uncertain``, and the rules
classifier is deterministic on the same input, so the overwritten row came back
as ``uncertain`` and re-entered the paid candidate pool. The log recorded 29
runs buying 4,326 classifications; 764 survived in the database.
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from services import abdc_astar_research_service as radar

ARTICLE = {
    'doi': '10.5465/amj.2026.0001',
    'title': 'Remote work and employee burnout',
    'abstract': 'We study remote work arrangements and burnout among knowledge workers.',
    'publication_date': '2026-08-20', 'publication_year': 2026,
    'journal_title': 'Academy of Management Journal', 'journal_issn': '0001-4273',
    'authors': [], 'concepts': [], 'keywords': [],
}
JOURNAL = {'journal_title': 'Academy of Management Journal', 'abdc_rating': 'A*',
           'abdc_version': '2025', '_area': 'OB / HR'}


class PaidClassificationTests(unittest.TestCase):
    def setUp(self):
        # 文件库而不是 :memory:，因为 reclassify_all 结束时会 close 自己那条连接
        self.path = os.path.join(tempfile.mkdtemp(), 'astar.db')
        self.conn = self.connect()
        radar.ensure_astar_tables(self.conn)
        _, self.aid = radar._upsert_article(self.conn, dict(ARTICLE), JOURNAL)
        self.conn.commit()
        self.addCleanup(self.conn.close)

    def connect(self, *args, **kwargs):
        # 吃掉 db_path：reclassify_all 在有些版本里会把它透传给 get_db
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def buy_llm_verdict(self):
        """Stand in for one paid llm_classify_articles pass over this row."""
        self.conn.execute(
            "UPDATE astar_article_classifications SET broad_area='OB / HR',"
            " relevance_score=88.0, classification_method='llm',"
            " classification_status='confident',"
            " classification_notes='LLM(deepseek): 远程办公与倦怠，高度相关'"
            " WHERE article_id=?", (self.aid,))
        self.conn.commit()

    def row(self):
        return self.conn.execute(
            'SELECT classification_method m, relevance_score s, classification_notes n,'
            ' classification_status st FROM astar_article_classifications WHERE article_id=?',
            (self.aid,)).fetchone()

    def test_recrawl_keeps_the_paid_verdict(self):
        self.buy_llm_verdict()
        status, aid = radar._upsert_article(self.conn, dict(ARTICLE), JOURNAL)
        self.assertEqual(('updated', self.aid), (status, aid), '前提：走的是更新分支')
        row = self.row()
        self.assertEqual('llm', row['m'])
        self.assertEqual(88.0, row['s'])
        self.assertIn('LLM(deepseek)', row['n'])

    def test_recrawl_does_not_push_the_row_back_into_the_paid_queue(self):
        # 候选池条件是 classification_method != 'llm' AND status = 'uncertain'。
        # 被覆盖过的行两条都满足，于是下一轮 LLM 会再买一次同一篇。
        self.buy_llm_verdict()
        radar._upsert_article(self.conn, dict(ARTICLE), JOURNAL)
        again = self.conn.execute(
            "SELECT count(*) FROM astar_article_classifications"
            " WHERE article_id=? AND classification_method!='llm'"
            " AND classification_status='uncertain'", (self.aid,)).fetchone()[0]
        self.assertEqual(0, again, '重抓之后这行不该再回到付费候选池')

    def test_recrawl_still_refreshes_a_rules_row(self):
        # 保护只针对付费判定；规则法的行照常更新，否则新抓到的元数据进不来。
        self.conn.execute("UPDATE astar_article_classifications"
                          " SET relevance_score=1.0 WHERE article_id=?", (self.aid,))
        self.conn.commit()
        radar._upsert_article(self.conn, dict(ARTICLE), JOURNAL)
        row = self.row()
        self.assertEqual('rules', row['m'])
        self.assertNotEqual(1.0, row['s'], '规则法的行应该被重算覆盖')

    def test_a_new_article_still_gets_classified(self):
        other = dict(ARTICLE, doi='10.5465/amj.2026.0002', title='Algorithmic management on platforms')
        _, aid = radar._upsert_article(self.conn, other, JOURNAL)
        method = self.conn.execute(
            'SELECT classification_method FROM astar_article_classifications WHERE article_id=?',
            (aid,)).fetchone()[0]
        self.assertEqual('rules', method)

    def test_reclassify_all_preserves_paid_verdicts_by_default(self):
        self.buy_llm_verdict()
        with patch.object(radar, 'get_db', side_effect=self.connect):
            radar.reclassify_all()
        self.assertEqual('llm', self.row()['m'])

    def test_reclassify_all_force_rebuilds_the_whole_baseline(self):
        self.buy_llm_verdict()
        with patch.object(radar, 'get_db', side_effect=self.connect):
            radar.reclassify_all(force=True)
        self.assertEqual('rules', self.row()['m'], 'force=True 是重建基线的逃生口')


if __name__ == '__main__':
    unittest.main()
