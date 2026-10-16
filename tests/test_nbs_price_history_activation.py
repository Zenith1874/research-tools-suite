"""Source-period, original-column and append-only checks for PPI history imports."""
import copy
import sqlite3
import unittest

from scripts.activate_nbs_price_history import (validated_ppi_article, append_missing_rows,
                                               reconcile_existing_rows, row_fingerprint, price_source_timing)
from bs4 import BeautifulSoup
from services.china_macro_service import ensure_china_macro_tables


class PriceHistoryTests(unittest.TestCase):
    def article(self):
        return '''<div class="detail-title"><h1>2012年1月份工业生产者价格变动情况</h1>
        <div class="detail-title-des">2012/02/09 09:30</div></div>
        <p>2012年1月份，全国工业生产者出厂价格同比上涨0.7%，环比下降0.1%。
        工业生产者购进价格同比上涨2.0%，环比下降0.3%。
        一、各类产品价格同比变动情况。生产资料价格同比上涨0.3%，生活资料价格上涨2.1%。
        二、工业生产者价格环比变动情况。生活资料价格上涨0.1%。</p>
        <h3>2012年1月份工业生产者价格主要数据</h3>
        <table><tr><td></td><td>环比涨跌幅（%）</td><td>同比涨跌幅（%）</td><td>累计同比</td></tr>
        <tr><td>一、工业生产者出厂价格</td><td>-0.1</td><td>0.7</td><td>99</td></tr>
        <tr><td>生产资料</td><td>-0.1</td><td>0.3</td><td>88</td></tr>
        <tr><td>生活资料</td><td>0.1</td><td>2.1</td><td>77</td></tr>
        <tr><td>二、工业生产者购进价格</td><td>-0.3</td><td>2.0</td><td>66</td></tr></table>'''

    def test_original_table_matches_prose_and_preserves_growth_grain(self):
        values, released = validated_ppi_article(self.article(), '2012-01',
                                               '2012年1月份工业生产者价格变动情况')
        self.assertEqual(released, '2012-02-09')
        self.assertEqual(values, {'CN_PPI_YOY':0.7, 'CN_PPI_MOM':-0.1,
                                 'CN_PPIRM_YOY':2.0, 'CN_PPIRM_MOM':-0.3,
                                 'CN_PPI_PRODUCTION_YOY':0.3, 'CN_PPI_LIVING_YOY':2.1})

    def test_current_style_headline_still_requires_exact_source_heading_and_period(self):
        title='2012年1月份工业生产者出厂价格同比上涨0.7% 环比下降0.1%'
        html=self.article().replace('2012年1月份工业生产者价格变动情况', title)
        values,released=validated_ppi_article(html,'2012-01',title)
        self.assertEqual(values['CN_PPI_YOY'],0.7)
        self.assertEqual(released,'2012-02-09')
        with self.assertRaises(ValueError):validated_ppi_article(html,'2012-01',title.replace('0.7','0.8'))

    def test_disclosure_creation_date_is_not_relabelled_as_publication_date(self):
        html=self.article().replace('<div class="detail-title"><h1>','<div><h2 class="xxgkNbXqTitle">').replace('</h1>','</h2>')
        html=html.replace('<div class="detail-title-des">2012/02/09 09:30</div>','<div>成文日期2012年2月9日</div>')
        values,released=validated_ppi_article(html,'2012-01','2012年1月份工业生产者价格变动情况')
        self.assertIsNone(released)
        timing=price_source_timing(BeautifulSoup(html,'html.parser'))
        self.assertEqual(timing['source_page_created_date'],'2012-02-09')
        self.assertEqual(timing['release_date_not_provided'],1)
        self.assertTrue(timing['release_date_reason'])
        html='<meta name="PubDate" content="2012/02/09 09:30">'+html
        self.assertEqual(validated_ppi_article(html,'2012-01','2012年1月份工业生产者价格变动情况')[1],'2012-02-09')

    def test_script_rendered_heading_requires_exact_nonexecuted_article_metadata(self):
        title='2012年1月份工业生产者价格变动情况'
        html=self.article().replace('<h1>'+title+'</h1>', '<h1><script>document.write("unexecuted")</script></h1>')
        with self.assertRaises(ValueError):validated_ppi_article(html,'2012-01',title)
        html='<meta name="ArticleTitle" content="'+title+'">'+html
        self.assertEqual(validated_ppi_article(html,'2012-01',title)[0]['CN_PPI_YOY'],0.7)

    def test_split_multilevel_header_keeps_monthly_columns_not_ytd(self):
        for empty_labels in ('','<td></td>','<td></td><td></td>'):
            html=self.article().replace('<td></td><td>环比涨跌幅（%）</td>',
                                        empty_labels+'<td>环比涨跌幅（%）</td>')
            values,_=validated_ppi_article(html,'2012-01','2012年1月份工业生产者价格变动情况')
            self.assertEqual(values['CN_PPI_YOY'],0.7)
            self.assertEqual(values['CN_PPIRM_YOY'],2.0)

    def test_migration_dates_wrong_periods_and_wrong_headers_are_rejected(self):
        for html, period, title in (
            (self.article(),'2023-03','2012年1月份工业生产者价格变动情况'),
            (self.article(),'2012-01','2012年2月份工业生产者价格变动情况'),
            (self.article().replace('2012/02/09','2023/03/01'),'2012-01','2012年1月份工业生产者价格变动情况'),
            (self.article().replace('<td>环比涨跌幅（%）</td><td>同比涨跌幅（%）</td>',
                                    '<td>同比涨跌幅（%）</td><td>环比涨跌幅（%）</td>'),'2012-01','2012年1月份工业生产者价格变动情况'),
            (self.article().replace('2012年1月份工业生产者价格主要数据','2012年2月份工业生产者价格主要数据'),'2012-01','2012年1月份工业生产者价格变动情况')):
            with self.subTest(period=period), self.assertRaises(ValueError):
                validated_ppi_article(html, period, title)

    def test_missing_source_cells_or_conflicts_do_not_become_official_zero(self):
        for html in (self.article().replace('<td>0.7</td>', '<td>…</td>'),
                     self.article().replace('<td>0.7</td>', '<td>0.8</td>'),
                     self.article().replace('</table>', '<tr><td>生产资料</td><td>-0.1</td><td>0.4</td></tr></table>')):
            with self.subTest(html=html), self.assertRaises(ValueError):
                validated_ppi_article(html,'2012-01','2012年1月份工业生产者价格变动情况')

    def row(self):
        return {'indicator_code':'CN_PPI_MOM','indicator_name':'PPI month-on-month',
                'period':'2012-01','value':-0.1,'unit':'%','frequency':'monthly','data_status':'official',
                'source_name':'国家统计局','source_type':'china_macro',
                'source_url':'https://www.stats.gov.cn/source.html','source_title':'reviewed fixture',
                'parser_notes':'actual monthly source','updated_at':'2026-10-15T00:00:00',
                'release_date':'2012-02-09','retrieved_at':'2026-10-15T00:00:00+00:00',
                'raw_sha256':'a'*64,'parser_version':'fixture'}

    def database(self):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
        ensure_china_macro_tables(conn)
        self.addCleanup(conn.close)
        return conn

    def test_replay_is_idempotent_and_preserves_every_existing_field(self):
        conn=self.database();row=self.row()
        self.assertEqual(append_missing_rows(conn,[row]), {'inserted':1,'updated':0,'unchanged':0})
        before=dict(conn.execute('select * from china_macro_observations').fetchone())
        repeated={**row,'source_title':'new metadata must not overwrite old','updated_at':'later'}
        self.assertEqual(append_missing_rows(conn,[repeated]), {'inserted':0,'updated':0,'unchanged':1})
        self.assertEqual(dict(conn.execute('select * from china_macro_observations').fetchone()), before)

    def test_source_conflict_is_preflighted_before_any_new_row_is_inserted(self):
        conn=self.database();row=self.row();append_missing_rows(conn,[row])
        new={**row,'period':'2012-02'};conflict={**row,'value':99}
        with self.assertRaises(ValueError):append_missing_rows(conn,[new,conflict])
        self.assertEqual(conn.execute('select count(*) from china_macro_observations').fetchone()[0],1)
        with self.assertRaises(ValueError):append_missing_rows(conn,[copy.deepcopy(row),copy.deepcopy(row)])

    def test_explicit_repair_preserves_original_and_replays_without_updates(self):
        conn=self.database();old=self.row();append_missing_rows(conn,[old])
        original=dict(conn.execute('select * from china_macro_observations').fetchone())
        corrected={**old,'value':0.0}
        review=[{'indicator_code':old['indicator_code'],'period':old['period'],
                 'expected_old_value':old['value'],'expected_old_row_sha256':row_fingerprint(original)}]
        result=reconcile_existing_rows(conn,[corrected],review)
        self.assertEqual(result,{'inserted':0,'updated':1,'unchanged':0})
        actual=dict(conn.execute('select * from china_macro_observations').fetchone())
        self.assertEqual(actual['value'],0.0)
        self.assertEqual(actual['original_value'],-0.1)
        self.assertIn('旧解析错读',actual['parser_notes'])
        self.assertEqual(reconcile_existing_rows(conn,[corrected],review),{'inserted':0,'updated':0,'unchanged':1})
        self.assertEqual(actual,dict(conn.execute('select * from china_macro_observations').fetchone()))

    def test_repair_refuses_stale_and_undeclared_changes_before_any_write(self):
        conn=self.database();row=self.row();second={**row,'period':'2012-02'}
        append_missing_rows(conn,[row,second])
        before=[dict(r) for r in conn.execute('select * from china_macro_observations order by id')]
        review=[{'indicator_code':r['indicator_code'],'period':r['period'],'expected_old_value':r['value'],
                 'expected_old_row_sha256':row_fingerprint(r)} for r in before]
        corrected=[{**row,'value':0},{**second,'value':0}]
        for invalid in (review[:1],[review[0],{**review[1],'expected_old_row_sha256':'b'*64}]):
            with self.assertRaises(ValueError):reconcile_existing_rows(conn,corrected,invalid)
            self.assertEqual(before,[dict(r) for r in conn.execute('select * from china_macro_observations order by id')])

    def test_repair_does_not_erase_a_preexisting_first_original_value(self):
        conn=self.database();old=self.row();append_missing_rows(conn,[old])
        conn.execute('update china_macro_observations set original_value=99')
        original=dict(conn.execute('select * from china_macro_observations').fetchone())
        review=[{'indicator_code':old['indicator_code'],'period':old['period'],'expected_old_value':old['value'],
                 'expected_old_row_sha256':row_fingerprint(original)}]
        reconcile_existing_rows(conn,[{**old,'value':0}],review)
        self.assertEqual(conn.execute('select original_value from china_macro_observations').fetchone()[0],99)


if __name__ == '__main__':
    unittest.main()
