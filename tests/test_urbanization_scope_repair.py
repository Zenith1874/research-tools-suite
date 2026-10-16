"""Resident and hukou population have different denominators; preserve repair originals."""
import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import activate_livelihood_history as importer
from services.china_macro_extended_service import parse_annual_livelihood_article
from services.china_macro_service import ensure_china_macro_tables
from services.china_macro_service import macro_ingestion_runtime, PARSERS

TITLE='2018年国民经济和社会发展统计公报'
URL='https://www.stats.gov.cn/xxgk/sjfb/tjgb2020/201902/fixture.html'
HTML=('<title>国家统计局信息公开</title><h1 class="xxgkNbXqTitle">'+TITLE+'</h1>'
      '<p>成文日期2019年02月28日</p><p>常住人口城镇化率）为59.58%。户籍人口城镇化率为43.37%。</p>'
      '<table><tr><td>2018年年末人口数及其构成 单位：万人</td></tr>'
      '<tr><td>指标</td><td>年末数（万人）</td><td>比重（%）</td></tr>'
      '<tr><td>其中：城镇</td><td>83137</td><td>59.58</td></tr></table>').encode('utf-8')


class UrbanizationParsingTests(unittest.TestCase):
    def test_hukou_only_text_never_supplies_resident_rate(self):
        self.assertNotIn('CN_URBANIZATION_RATE',parse_annual_livelihood_article('户籍人口城镇化率为43.37%。'))

    def test_closed_parenthesis_before_resident_rate_does_not_fall_through_to_hukou(self):
        self.assertEqual(parse_annual_livelihood_article('占总人口比重（常住人口城镇化率）为59.58%。户籍人口城镇化率为43.37%。')['CN_URBANIZATION_RATE'],59.58)

    def test_explicit_hukou_table_is_not_a_resident_population_table(self):
        text='<table><tr><td>户籍人口数 单位：万人</td></tr><tr><td>指标</td><td>年末数</td><td>比重</td></tr><tr><td>城镇</td><td>60000</td><td>43.37</td></tr></table>'
        self.assertNotIn('CN_URBANIZATION_RATE',parse_annual_livelihood_article(text))

    def test_seed_snapshot_uses_the_verified_resident_rates(self):
        with (importer.ROOT/'data/china_macro_annual_supplement.csv').open(encoding='utf-8-sig',newline='') as handle:
            values={row['period']:float(row['value']) for row in csv.DictReader(handle) if row['indicator_code']=='CN_URBANIZATION_RATE'}
        self.assertEqual({year:values[year] for year in ('2016','2017','2018','2019')},
                         {'2016':57.35,'2017':58.52,'2018':59.58,'2019':60.6})

    def test_precise_resident_prose_is_not_rounded_to_the_table_precision(self):
        html='<p>常住人口城镇化率为64.72%。</p><table><tr><td>年末人口 单位：万人</td></tr><tr><td>指标</td><td>年末数</td><td>比重</td></tr><tr><td>城镇</td><td>91425</td><td>64.7</td></tr></table>'
        self.assertEqual(parse_annual_livelihood_article(html)['CN_URBANIZATION_RATE'],64.72)

    def test_runtime_probe_checks_the_actual_update_dispatch_callable(self):
        self.assertTrue(all(macro_ingestion_runtime()['annual_resident_scope_probe'].values()))
        with patch.dict(PARSERS, {'annual': lambda html: {'CN_URBANIZATION_RATE':43.37}}):
            self.assertFalse(any(macro_ingestion_runtime()['annual_resident_scope_probe'].values()))


class UrbanizationRepairTests(unittest.TestCase):
    def setup_run(self,directory):
        root=Path(directory);archive=root/'archive';archive.mkdir();(archive/'original.html').write_bytes(HTML)
        digest=hashlib.sha256(HTML).hexdigest()
        (archive/'audit.json').write_text(json.dumps({'source_manifest':[{'source_url':URL,'raw_path':'original.html','raw_sha256':digest,'retrieved_at':'2026-10-02T21:00:00-06:00'}]}),encoding='utf-8')
        review=root/'review.json';review.write_text(json.dumps({'schema_version':1,'sources':[{'archive':'archive','source_url':URL,'source_title':TITLE,'kind':'urbanization_measure_repair','year':2018,'expected_wrong_hukou_value':43.37,'values':{'CN_URBANIZATION_RATE':59.58}}]}),encoding='utf-8')
        database=root/'fixture.db'
        with closing(sqlite3.connect(database)) as conn:
            ensure_china_macro_tables(conn)
            conn.execute('INSERT INTO china_macro_observations(indicator_code,period,value,source_url,raw_sha256,updated_at) VALUES(?,?,?,?,?,?)',('CN_URBANIZATION_RATE','2018',43.37,URL,digest,'keep-original'))
            conn.commit()
        return root,review,database

    def invoke(self,root,review,database,repair=True):
        response=Mock();response.status_code=200;response.json.return_value={'jobs':{},'update_lock_busy':False}
        session=Mock();session.get.return_value=response
        args=['activate_livelihood_history','--review',str(review),'--database',str(database),'--output-base',str(root/'runs'),'--apply']
        if repair:args.append('--repair-urbanization-scope')
        with patch.object(importer,'ROOT',root),patch.object(importer.requests,'Session',return_value=session),patch('sys.argv',args),redirect_stdout(io.StringIO()):importer.main()

    def test_repair_keeps_original_row_and_idempotent_second_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root,review,database=self.setup_run(directory);self.invoke(root,review,database)
            with closing(sqlite3.connect(database)) as conn:
                before=conn.execute('SELECT * FROM china_macro_observations').fetchall()
                self.assertEqual(conn.execute('SELECT value,original_value FROM china_macro_observations').fetchone(),(59.58,43.37))
            audit=json.loads(next((root/'runs').glob('*/audit.json')).read_text(encoding='utf-8'))
            self.assertEqual(audit['old_repaired'][0]['value'],43.37);self.assertEqual(audit['corrected_existing_rows'],1);self.assertEqual(audit['inserted_keys'],0)
            self.invoke(root,review,database)
            with closing(sqlite3.connect(database)) as conn:self.assertEqual(before,conn.execute('SELECT * FROM china_macro_observations').fetchall())

    def test_without_explicit_mode_the_baseline_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root,review,database=self.setup_run(directory)
            with self.assertRaises(ValueError):self.invoke(root,review,database,repair=False)
            with closing(sqlite3.connect(database)) as conn:self.assertEqual(conn.execute('SELECT value FROM china_macro_observations').fetchone()[0],43.37)

    def test_unexpected_live_value_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root,review,database=self.setup_run(directory)
            with closing(sqlite3.connect(database)) as conn:conn.execute('UPDATE china_macro_observations SET value=44.38');conn.commit()
            with self.assertRaises(ValueError):self.invoke(root,review,database)
            with closing(sqlite3.connect(database)) as conn:self.assertEqual(conn.execute('SELECT value FROM china_macro_observations').fetchone()[0],44.38)

    def test_failed_protected_hash_rolls_back_the_scope_correction(self):
        with tempfile.TemporaryDirectory() as directory:
            root,review,database=self.setup_run(directory)
            with patch.object(importer,'protected_digest',side_effect=[(0,'before'),(0,'after')]):
                with self.assertRaises(ValueError):self.invoke(root,review,database)
            with closing(sqlite3.connect(database)) as conn:self.assertEqual(conn.execute('SELECT value,original_value FROM china_macro_observations').fetchone(),(43.37,None))


if __name__=='__main__':unittest.main()
