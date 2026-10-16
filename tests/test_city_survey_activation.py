"""The reviewed city importer preserves old observations and rolls back the whole batch."""
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import activate_city_survey_history as importer
from services.china_macro_service import ensure_china_macro_tables


TITLE = '一季度国民经济实现良好开局'
URL = 'https://www.stats.gov.cn/sj/zxfb/202302/t20230203_fixture.html'
HTML = ('<title>' + TITLE + ' - 国家统计局</title><div class="detail-title-des">2018/04/17 10:00</div>'
        '<p>2018年3月份及一季度主要统计数据</p>'
        '<p>1至3月份，全国城镇调查失业率分别为5.0%、5.0%和5.1%；'
        '31个大城市城镇调查失业率分别为4.9%、4.8%和4.9%。</p>').encode('utf-8')
REVIEW = {'source_url': URL, 'source_title': TITLE, 'release_period': '2018-03',
          'observations': {'2018-01': 4.9, '2018-02': 4.8, '2018-03': 4.9}}


class CityReleaseValidationTests(unittest.TestCase):
    def test_title_month_original_date_and_explicit_values_match(self):
        values, timing, _ = importer.validated_city_release(HTML, REVIEW)
        self.assertEqual(values, REVIEW['observations'])
        self.assertEqual(timing['release_date'], '2018-04-17')

    def test_wrong_title_month_date_value_or_transport_is_rejected(self):
        for changed in ({'source_title': 'Another release'}, {'release_period': '2023-03'},
                        {'observations': {'2018-01': 5.0}}, {'source_url': URL.replace('https:', 'http:')}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                importer.validated_city_release(HTML, {**REVIEW, **changed})
        with self.assertRaises(ValueError):
            importer.validated_city_release(HTML.replace(b'2018/04/17', b'2023/02/03'), REVIEW)


class CityActivationTests(unittest.TestCase):
    def setup_run(self, directory):
        root = Path(directory); archive = root / 'archive'; archive.mkdir()
        (archive / 'original.html').write_bytes(HTML)
        source = {'source_url': URL, 'resolved_url': URL, 'raw_path': 'original.html',
                  'raw_sha256': hashlib.sha256(HTML).hexdigest(), 'retrieved_at': '2026-10-10T18:00:00-06:00'}
        (archive / 'audit.json').write_text(json.dumps({'source_manifest': [source]}), encoding='utf-8')
        review = root / 'review.json'
        review.write_text(json.dumps({'schema_version': 1, 'indicator_code': importer.CODE,
                                      'sources': [{'archive': 'archive', **REVIEW}]}), encoding='utf-8')
        database = root / 'fixture.db'
        with closing(sqlite3.connect(database)) as conn:
            ensure_china_macro_tables(conn)
            conn.execute("INSERT INTO china_macro_observations(indicator_code,period,value,source_url,updated_at) VALUES('OTHER','2018',77,'original','keep')")
            conn.commit()
        return root, review, database

    def invoke(self, root, review, database, jobs=None, repair=False):
        response = Mock(); response.json.return_value = jobs or {'jobs': {}, 'update_lock_busy': False}
        session = Mock(); session.get.return_value = response
        arguments = ['activate_city_survey_history', '--review', str(review), '--database', str(database),
                     '--output-base', str(root / 'runs'), '--apply']
        if repair:
            arguments.append('--repair-own-missing-flags')
        with patch.object(importer, 'ROOT', root), patch.object(importer.requests, 'Session', return_value=session), \
                patch('sys.argv', arguments), redirect_stdout(io.StringIO()):
            importer.main()

    def test_success_preserves_old_rows_and_second_run_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root, review, database = self.setup_run(directory)
            self.invoke(root, review, database)
            with closing(sqlite3.connect(database)) as conn:
                before = conn.execute('SELECT * FROM china_macro_observations ORDER BY id').fetchall()
                self.assertEqual(len(before), 4)
            self.invoke(root, review, database)
            with closing(sqlite3.connect(database)) as conn:
                self.assertEqual(before, conn.execute('SELECT * FROM china_macro_observations ORDER BY id').fetchall())
            audit = json.loads(sorted((root / 'runs').glob('*/audit.json'))[-1].read_text(encoding='utf-8'))
            self.assertEqual(audit['committed_rows'], 0)
            self.assertTrue(audit['protected_unchanged'])

    def test_mid_batch_sql_failure_rolls_back_every_new_month(self):
        with tempfile.TemporaryDirectory() as directory:
            root, review, database = self.setup_run(directory)
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("CREATE TRIGGER fail_city BEFORE INSERT ON china_macro_observations WHEN NEW.period='2018-02' BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
                conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                self.invoke(root, review, database)
            with closing(sqlite3.connect(database)) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM china_macro_observations').fetchone()[0], 1)
            audit = json.loads(next((root / 'runs').glob('*/audit.json')).read_text(encoding='utf-8'))
            self.assertEqual(audit['committed_rows'], 0)
            self.assertIn('fixture failure', audit['error'])

    def test_readback_hash_failure_rolls_back_all_attempted_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root, review, database = self.setup_run(directory)
            with patch.object(importer, 'protected_digest', side_effect=[(1, 'before'), (1, 'different')]):
                with self.assertRaises(ValueError):
                    self.invoke(root, review, database)
            with closing(sqlite3.connect(database)) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM china_macro_observations').fetchone()[0], 1)

    def test_busy_job_creates_a_deferred_receipt_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root, review, database = self.setup_run(directory)
            with self.assertRaises(RuntimeError):
                self.invoke(root, review, database, {'jobs': {}, 'update_lock_busy': True})
            audit = json.loads(next((root / 'runs').glob('*/audit.json')).read_text(encoding='utf-8'))
            self.assertEqual(audit['phase'], 'deferred_active_update_job')
            self.assertEqual(audit['committed_rows'], 0)

    def test_filling_invalidated_null_clears_only_current_missing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root, review, database = self.setup_run(directory)
            with closing(sqlite3.connect(database)) as conn:
                conn.execute('INSERT INTO china_macro_observations(indicator_code,period,value,missing_reason,original_value) VALUES(?,?,?,?,?)',
                             (importer.CODE, '2018-02', None, 'Old wrong reporting period', 5.8))
                conn.commit()
            self.invoke(root, review, database)
            with closing(sqlite3.connect(database)) as conn:
                actual = conn.execute('SELECT value,missing_reason,original_value FROM china_macro_observations WHERE indicator_code=? AND period=?',
                                      (importer.CODE, '2018-02')).fetchone()
            self.assertEqual(actual, (4.8, None, 5.8))

    def test_explicit_own_flag_repair_preserves_full_other_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root, review, database = self.setup_run(directory)
            self.invoke(root, review, database)
            with closing(sqlite3.connect(database)) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute('UPDATE china_macro_observations SET missing_reason=? WHERE indicator_code=? AND period=?',
                             ('Stale flag from this importer', importer.CODE, '2018-02'))
                conn.commit()
                before = dict(conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?',
                                           (importer.CODE, '2018-02')).fetchone())
            self.invoke(root, review, database, repair=True)
            with closing(sqlite3.connect(database)) as conn:
                conn.row_factory = sqlite3.Row
                actual = dict(conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?',
                                           (importer.CODE, '2018-02')).fetchone())
            self.assertEqual(actual, {**before, 'missing_reason': None})


if __name__ == '__main__':
    unittest.main()
