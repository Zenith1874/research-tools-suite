"""Provenance-only annotation must not repair, clear or reinterpret observations."""
import sqlite3
import unittest

from scripts.activate_nbs_price_history import (
    validated_cpi_article, annotate_existing_rows, append_missing_rows, observation_value_digest,
)
from services.china_macro_service import ensure_china_macro_tables


class PriceSourceMetadataTests(unittest.TestCase):
    def database(self):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
        ensure_china_macro_tables(conn);self.addCleanup(conn.close)
        return conn

    def row(self):
        return {'indicator_code':'CN_PPI_MOM','indicator_name':'PPI monthly change','period':'2026-09',
                'value':1.2,'unit':'%','frequency':'monthly','data_status':'official',
                'source_name':'国家统计局','source_type':'china_macro',
                'source_url':'https://www.stats.gov.cn/source.html','source_title':'reviewed source',
                'parser_notes':'original parser note','parser_version':'original-value-parser',
                'release_date':'2026-10-14','retrieved_at':'2026-10-15T00:00:00+00:00',
                'raw_sha256':'a'*64,'source_page_created_date':None,
                'release_date_not_provided':0,'release_date_reason':None,'updated_at':'initial'}

    def cpi(self):
        data=[('居民消费价格',0.2,0.9,0.9),('其中：食品',0.4,-1.7,-0.9),
              ('非食品',0.2,1.5,1.3),('其中：消费品',0.5,1.0,1.0),('服务',-0.2,0.8,0.8),
              ('其中：不包括食品和能源',0.0,1.0,1.1)]
        table='<table><tr><td></td><td>环比涨跌幅（%）</td><td>同比涨跌幅（%）</td><td>1—9月同比</td></tr>'
        table+=''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in data)+'</table>'
        return ('''<div class="detail-title"><h1>2026年9月份居民消费价格同比上涨0.9%</h1>
        <div class="detail-title-des">2026/10/14 09:30</div></div>
        全国居民消费价格同比上涨0.9%。全国居民消费价格环比上涨0.2%。
        <h3>2026年9月份居民消费价格主要数据</h3>'''+table)

    def test_cpi_monthly_fields_and_core_ytd_average_have_distinct_columns(self):
        values,released=validated_cpi_article(self.cpi(),'2026-09','2026年9月份居民消费价格同比上涨0.9%')
        self.assertEqual(len(values),13);self.assertEqual(released,'2026-10-14')
        self.assertEqual(values['CN_CPI_YOY'],0.9)
        self.assertEqual(values['CN_CPI_CORE_MOM'],0.0)
        self.assertEqual(values['CN_CPI_CORE_YOY'],1.0)
        self.assertEqual(values['CN_CPI_CORE_YTD_AVG_YOY'],1.1)

    def test_cpi_missing_core_average_or_reversed_columns_is_not_imputed(self):
        for html in (self.cpi().replace('<td>1.1</td>','<td>…</td>'),
                     self.cpi().replace('环比涨跌幅（%）','wrong column'),
                     self.cpi().replace('2026年9月份居民消费价格主要数据','2026年8月份居民消费价格主要数据')):
            with self.subTest(html=html), self.assertRaises(ValueError):
                validated_cpi_article(html,'2026-09','2026年9月份居民消费价格同比上涨0.9%')

    def test_annotations_preserve_values_originals_classification_and_value_parser(self):
        conn=self.database();row=self.row()
        incomplete={**row,'raw_sha256':None,'release_date':None,'retrieved_at':None}
        append_missing_rows(conn,[incomplete]);conn.execute('update china_macro_observations set original_value=0.9')
        before=observation_value_digest(conn)
        result=annotate_existing_rows(conn,[row])
        self.assertEqual(result,{'inserted':0,'updated_values':0,'updated_metadata':1,'unchanged':0})
        self.assertEqual(observation_value_digest(conn),before)
        actual=dict(conn.execute('select * from china_macro_observations').fetchone())
        self.assertEqual(actual['original_value'],0.9)
        self.assertEqual(actual['parser_version'],'original-value-parser')
        self.assertEqual(actual['release_date'],'2026-10-14')
        self.assertEqual(annotate_existing_rows(conn,[row])['updated_metadata'],0)
        self.assertEqual(actual,dict(conn.execute('select * from china_macro_observations').fetchone()))

    def test_conflicting_source_or_value_is_rejected_before_any_metadata_write(self):
        conn=self.database();row=self.row();second={**row,'period':'2026-08','raw_sha256':'b'*64}
        append_missing_rows(conn,[{**row,'raw_sha256':None},second])
        before=[dict(r) for r in conn.execute('select * from china_macro_observations order by id')]
        for invalid in ({**second,'raw_sha256':'c'*64},{**second,'value':99}):
            with self.assertRaises(ValueError):annotate_existing_rows(conn,[row,invalid])
            self.assertEqual(before,[dict(r) for r in conn.execute('select * from china_macro_observations order by id')])

    def test_only_verified_same_path_transport_upgrade_is_allowed(self):
        conn=self.database();row=self.row()
        append_missing_rows(conn,[{**row,'source_url':'http://www.stats.gov.cn/source.html','raw_sha256':None}])
        self.assertEqual(annotate_existing_rows(conn,[row])['updated_metadata'],1)
        self.assertEqual(conn.execute('select source_url from china_macro_observations').fetchone()[0],row['source_url'])
        with self.assertRaises(ValueError):annotate_existing_rows(conn,[{**row,'source_url':'https://www.stats.gov.cn/other.html'}])

    def test_creation_date_is_not_used_to_erase_a_known_release_date(self):
        conn=self.database();row=self.row();append_missing_rows(conn,[row])
        with self.assertRaises(ValueError):
            annotate_existing_rows(conn,[{**row,'release_date':None,'source_page_created_date':'2026-10-14',
                                         'release_date_not_provided':1,'release_date_reason':'creation only'}])
        self.assertEqual(conn.execute('select release_date from china_macro_observations').fetchone()[0],'2026-10-14')


if __name__=='__main__':
    unittest.main()
