import unittest
import json
import copy
import sqlite3
import hashlib
import tempfile
from contextlib import closing
from pathlib import Path
from services.province_gdp_bulletin_service import parse_province_gdp_release, validate_reviewed_province_snapshot, sync_reviewed_province_gdp
from services.regional_fiscal_service import CN_PROVINCES
from services.gdp_service import ensure_gdp_tables, build_gdp_payload
from scripts.review_province_gdp_bulletins import write_reviewed_snapshot


class ProvincialGdpBulletinTests(unittest.TestCase):
    def parse(self, text, province='北京', title='北京市2025年国民经济和社会发展统计公报'):
        return parse_province_gdp_release('<p>' + text + '</p>', province, 2025, title)

    def test_nominal_level_and_official_real_growth_are_different_measures(self):
        rows = self.parse('2025年，初步核算，全年实现地区生产总值52073.4亿元，'
                          '按不变价格计算，比上年增长5.4%。其中第一产业增加值109.2亿元。')
        values = {row['indicator_code']: row['value'] for row in rows}
        self.assertEqual(values, {'nominal_gdp': 52073.4, 'real_growth': 5.4})
        self.assertEqual({row['region_code'] for row in rows}, {'110000'})

    def test_multiregion_article_uses_named_target_not_another_province(self):
        rows = self.parse('2025年，重庆市地区生产总值33757.93亿元，四川省地区生产总值67665.34亿元，'
                          '分别比上年增长5.3%、5.5%。', '四川', '2025年川渝经济总量突破10万亿元')
        self.assertEqual(rows[0]['value'], 67665.34)
        self.assertNotIn(33757.93, [row['value'] for row in rows])
        self.assertEqual(len(rows), 1, 'A separate two-region growth list must not be assigned to one province.')

    def test_bulletin_publication_date_is_not_the_statistical_year(self):
        rows = self.parse('2025年福建省统计公报，福建省统计局2026年3月19日一、综合'
                          '初步核算，全年实现地区生产总值[2]60199.45亿元，比上年增长5.0%。',
                          '福建', '2025年福建省国民经济和社会发展统计公报')
        self.assertEqual([r['value'] for r in rows], [60199.45, 5.0])

    def test_preceding_plan_completion_is_not_a_forecast(self):
        rows = self.parse('2025年，全区高质量发展取得新成效，圆满完成十四五规划目标。'
                          '根据地区生产总值统一核算结果，2025年全区生产总值5696.49亿元，'
                          '按不变价格计算，比上年增长5.3%。', '宁夏', '2025年全区经济运行情况')
        self.assertEqual([r['value'] for r in rows], [5696.49, 5.3])

    def test_fullwidth_numbers_and_trillion_unit_are_normalized_not_currency_converted(self):
        rows = self.parse('２０２５年，全省地区生产总值为２．５４９５７万亿元，'
                          '按不变价格计算，比上年增长４．０％。', '山西', '2025年全省经济运行情况')
        self.assertAlmostEqual(rows[0]['value'], 25495.7)
        self.assertEqual(rows[0]['raw_unit'], '万亿元')
        self.assertEqual(rows[1]['value'], 4.0)

    def test_forecast_subannual_and_unverified_year_are_not_annual_observations(self):
        for text, title in (
            ('2025年，预计全年地区生产总值50000亿元，比上年增长5.0%。', '2025年全省经济情况'),
            ('2025年，上半年全省地区生产总值20000亿元，比上年增长5.0%。', '2025年上半年经济情况'),
            ('2024年，全年全省地区生产总值50000亿元，比上年增长5.0%。', '2025年全省经济情况')):
            with self.assertRaises(ValueError):
                self.parse(text, '北京', title)

    def test_missing_growth_does_not_become_zero_or_industry_growth(self):
        rows = self.parse('2025年，全年实现地区生产总值52073.4亿元。其中第一产业增加值109.2亿元，增长1.0%。')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['indicator_code'], 'nominal_gdp')

    def test_title_without_year_requires_explicit_statistical_year_by_gdp(self):
        rows = self.parse('2025年，四川全省地区生产总值67665.34亿元，比上年增长5.5%。',
                          '四川', '四川经济发展情况')
        self.assertEqual(rows[0]['period'], '2025')


class ReviewedProvinceSnapshotTests(unittest.TestCase):
    def test_snapshot_digest_matches_actual_utf8_lf_bytes_on_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot=self.snapshot()
            path,digest=write_reviewed_snapshot(snapshot,directory)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
            self.assertIn(digest[:12],path.name)
            self.assertNotIn(b'\r\n',path.read_bytes())
            self.assertEqual(write_reviewed_snapshot(snapshot,directory),(path,digest))

    def snapshot(self):
        sources, rows = [], []
        for name, code in CN_PROVINCES.items():
            source_id='gdp-2025-'+code
            sources.append({'source_id':source_id,'region_code':code,'region_name':name,
                            'source_url':'https://www.stats.gov.cn/'+code+'.html','source_name':'Test official source',
                            'data_status':'official_preliminary','access_type':'official_site_page_excerpt',
                            'excerpt':f'2025年{name}地区生产总值1000亿元，比上年增长5.0%。'})
            for indicator,value,unit in [('nominal_gdp',1000,'亿元'),('real_growth',5,'%')]:
                rows.append({'region_code':code,'region_name':name,'indicator_code':indicator,'period':'2025',
                             'value':value,'unit':unit,'data_status':'official_preliminary','source_id':source_id})
        return {'schema_version':1,'review_status':'source_values_reviewed','statistical_year':2025,
                'generated_at':'2026-10-13T01:00:00+00:00','sources':sources,'observations':rows}

    def test_rejects_city_wrong_unit_duplicate_and_unofficial_source(self):
        for mutation in ('city','unit','duplicate','unofficial','bool'):
            snapshot=self.snapshot()
            if mutation=='city': snapshot['observations'][0]['region_code']='110100'
            elif mutation=='unit': snapshot['observations'][0]['unit']='万美元'
            elif mutation=='duplicate': snapshot['observations'].append(copy.deepcopy(snapshot['observations'][0]))
            elif mutation=='unofficial': snapshot['sources'][0]['source_url']='https://example.com/gdp'
            else: snapshot['observations'][0]['value']=True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_reviewed_province_snapshot(snapshot)

    def test_idempotent_and_preserves_old_year_city_and_us_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'snapshot.json'; path.write_text(json.dumps(self.snapshot()),encoding='utf-8')
            with sqlite3.connect(':memory:') as conn:
                ensure_gdp_tables(conn)
                conn.executemany('''INSERT INTO gdp_region_observations
                    (country_code,region_code,region_name,indicator_code,period,value,unit)
                    VALUES (?,?,?,?,?,?,?)''', [('CN','110000','北京','nominal_gdp','2024',900,'亿元'),
                    ('CN','110100','北京','nominal_gdp','2025',777,'亿元'),('US','06','California','nominal_gdp','2025',123,'USD')])
                first=sync_reviewed_province_gdp(conn,directory)
                second=sync_reviewed_province_gdp(conn,directory)
                self.assertEqual((first['inserted'],second['inserted'],second['updated'],second['unchanged']),(62,0,0,62))
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM gdp_region_observations').fetchone()[0],65)
                self.assertEqual(conn.execute("SELECT value FROM gdp_region_observations WHERE region_code='110100'").fetchone()[0],777)
                self.assertEqual(conn.execute("SELECT value FROM gdp_region_observations WHERE period='2024'").fetchone()[0],900)
                self.assertEqual(conn.execute("SELECT value FROM gdp_region_observations WHERE country_code='US'").fetchone()[0],123)

    def test_revision_keeps_complete_original_row(self):
        with tempfile.TemporaryDirectory() as directory, sqlite3.connect(':memory:') as conn:
            ensure_gdp_tables(conn); path=Path(directory)/'snapshot.json'; snapshot=self.snapshot()
            path.write_text(json.dumps(snapshot),encoding='utf-8'); sync_reviewed_province_gdp(conn,directory)
            snapshot['observations'][0]['value']=1100
            snapshot['sources'][0]['excerpt']='2025年北京地区生产总值1100亿元，增长5.0%。'
            path.write_text(json.dumps(snapshot),encoding='utf-8'); result=sync_reviewed_province_gdp(conn,directory)
            self.assertEqual(result['updated'],1)
            old=json.loads(conn.execute('SELECT original_row_json FROM gdp_province_revision_history').fetchone()[0])
            self.assertEqual(old['value'],1000); self.assertEqual(old['unit'],'亿元'); self.assertIn('source_url',old)

    def test_invalid_snapshot_does_not_clear_existing_data(self):
        with tempfile.TemporaryDirectory() as directory, sqlite3.connect(':memory:') as conn:
            ensure_gdp_tables(conn); path=Path(directory)/'snapshot.json'; snapshot=self.snapshot()
            path.write_text(json.dumps(snapshot),encoding='utf-8'); sync_reviewed_province_gdp(conn,directory)
            snapshot['observations'].pop(); path.write_text(json.dumps(snapshot),encoding='utf-8')
            result=sync_reviewed_province_gdp(conn,directory)
            self.assertTrue(result['errors']); self.assertEqual(conn.execute('SELECT COUNT(*) FROM gdp_region_observations').fetchone()[0],62)

    def test_latest_reviewed_version_wins_without_deleting_older_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, sqlite3.connect(':memory:') as conn:
            ensure_gdp_tables(conn)
            older=self.snapshot(); newer=self.snapshot()
            newer['generated_at']='2026-10-13T02:00:00+00:00'; newer['observations'][0]['value']=1100
            (Path(directory)/'z-older.json').write_text(json.dumps(older),encoding='utf-8')
            (Path(directory)/'a-newer.json').write_text(json.dumps(newer),encoding='utf-8')
            result=sync_reviewed_province_gdp(conn,directory)
            self.assertEqual(result['inserted'],62)
            self.assertEqual(conn.execute("SELECT value FROM gdp_region_observations WHERE region_code='110000' AND indicator_code='nominal_gdp'").fetchone()[0],1100)
            self.assertTrue((Path(directory)/'z-older.json').exists())

    def test_modified_qualified_snapshot_is_rejected_without_changing_existing_values(self):
        with tempfile.TemporaryDirectory() as directory, sqlite3.connect(':memory:') as conn:
            ensure_gdp_tables(conn); snapshot=self.snapshot(); path,_=write_reviewed_snapshot(snapshot,directory)
            sync_reviewed_province_gdp(conn,directory)
            snapshot['observations'][0]['value']=1200
            path.write_text(json.dumps(snapshot),encoding='utf-8')
            result=sync_reviewed_province_gdp(conn,directory)
            self.assertTrue(result['errors']); self.assertEqual(result['updated'],0)
            self.assertEqual(conn.execute("SELECT value FROM gdp_region_observations WHERE region_code='110000' AND indicator_code='nominal_gdp'").fetchone()[0],1000)

    def test_payload_preserves_provenance_and_official_growth_without_city_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'gdp.db'; snapshot_dir=Path(directory)/'review'; snapshot_dir.mkdir()
            (snapshot_dir/'snapshot.json').write_text(json.dumps(self.snapshot()),encoding='utf-8')
            with closing(sqlite3.connect(database)) as conn:
                ensure_gdp_tables(conn); sync_reviewed_province_gdp(conn,snapshot_dir); conn.commit()
            payload=build_gdp_payload(str(database))
            self.assertEqual(payload['coverage']['CN']['regions'],31)
            self.assertEqual(len(payload['regions']['CN']),62)
            row=payload['regions']['CN'][0]
            self.assertEqual(row['data_status'],'official_preliminary'); self.assertIn('source_url',row)
            self.assertIn('2025',payload['methods']['CN'])


if __name__ == '__main__':
    unittest.main()
