"""Annual source identity, vintage preservation and atomic supplement activation."""
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
from services.china_macro_service import ensure_china_macro_tables

TITLE = '2014年国民经济和社会发展统计公报'
URL = 'https://www.stats.gov.cn/sj/zxfb/202302/t20230203_fixture.html'
HTML = ('<title>' + TITLE + ' - 国家统计局</title><div class="detail-title-des">2015/02/26 09:30</div>'
        '<p>2014年年末人口数及其构成</p><p>全国居民人均消费支出14491元，比上年增长9.6%，扣除价格因素，实际增长7.5%。</p>').encode('utf-8')
REVIEW = {'source_url': URL, 'source_title': TITLE, 'kind': 'statistical_bulletin', 'year': 2014,
          'values': {'CN_CONSUMPTION_PC': 14491, 'CN_CONSUMPTION_REAL_YOY': 7.5}}


class AnnualSourceValidationTests(unittest.TestCase):
    def test_original_year_and_published_values_are_independently_verified(self):
        timing = importer.validate_livelihood_source(HTML, REVIEW)
        self.assertEqual(timing['release_date'], '2015-02-26')

    def test_wrong_year_value_scope_transport_or_original_date_is_rejected(self):
        for change in ({'year': 2013}, {'kind': 'yearend_economy'}, {'values': {'CN_INCOME_RURAL': 9892}},
                       {'source_url': URL.replace('https:', 'http:')}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                importer.validate_livelihood_source(HTML, {**REVIEW, **change})
        with self.assertRaises(ValueError):
            importer.validate_livelihood_source(HTML.replace(b'2015/02/26', b'2023/02/03'), REVIEW)

    def test_outer_title_whitespace_is_removed_without_fuzzy_title_matching(self):
        spaced = HTML.replace(b'<title>', b'<title>\n\t').replace(b'</title>', b'\n\t</title>')
        self.assertEqual(importer.validate_livelihood_source(spaced, REVIEW)['release_date'], '2015-02-26')
        with self.assertRaises(ValueError):
            importer.validate_livelihood_source(spaced, {**REVIEW, 'source_title': '2014年某省国民经济和社会发展统计公报'})

    def test_boolean_or_nonfinite_curated_values_are_not_observations(self):
        for value in (True, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                importer.validate_livelihood_source(HTML, {**REVIEW, 'values': {'CN_CONSUMPTION_PC': value}})


class AnnualActivationTests(unittest.TestCase):
    def setup_run(self, directory):
        root = Path(directory); archive = root / 'archive'; archive.mkdir()
        (archive / 'original.html').write_bytes(HTML)
        source = {'source_url': URL, 'resolved_url': URL, 'raw_path': 'original.html',
                  'raw_sha256': hashlib.sha256(HTML).hexdigest(), 'retrieved_at': '2026-10-15T12:00:00+00:00'}
        (archive / 'audit.json').write_text(json.dumps({'source_manifest': [source]}), encoding='utf-8')
        review = root / 'review.json'
        review.write_text(json.dumps({'schema_version': 1, 'sources': [{'archive': 'archive', **REVIEW}]}), encoding='utf-8')
        database = root / 'fixture.db'
        with closing(sqlite3.connect(database)) as conn:
            ensure_china_macro_tables(conn)
            conn.execute("INSERT INTO china_macro_observations(indicator_code,period,value,source_url,updated_at) VALUES('OTHER','2014',77,'original','keep')")
            conn.commit()
        return root, review, database

    def invoke(self, root, review, database, busy=False):
        response = Mock(); response.status_code = 200
        response.json.return_value = {'jobs': {}, 'update_lock_busy': busy}
        session = Mock(); session.get.return_value = response
        args = ['activate_livelihood_history', '--review', str(review), '--database', str(database),
                '--output-base', str(root / 'runs'), '--apply']
        with patch.object(importer, 'ROOT', root), patch.object(importer.requests, 'Session', return_value=session), \
                patch('sys.argv', args), redirect_stdout(io.StringIO()):
            importer.main()

    def test_success_and_second_run_leave_old_whole_rows_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root, review, database = self.setup_run(directory)
            self.invoke(root, review, database)
            with closing(sqlite3.connect(database)) as conn:
                before = conn.execute('SELECT * FROM china_macro_observations ORDER BY id').fetchall()
                self.assertEqual(len(before), 3)
            self.invoke(root, review, database)
            with closing(sqlite3.connect(database)) as conn:
                self.assertEqual(before, conn.execute('SELECT * FROM china_macro_observations ORDER BY id').fetchall())
            audit = json.loads(sorted((root / 'runs').glob('*/audit.json'))[-1].read_text(encoding='utf-8'))
            self.assertEqual(audit['committed_rows'], 0)
            self.assertTrue(audit['protected_unchanged'])

    def test_existing_revised_vintage_is_not_downgraded_to_preliminary(self):
        with tempfile.TemporaryDirectory() as directory:
            root, review, database = self.setup_run(directory)
            with closing(sqlite3.connect(database)) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute('INSERT INTO china_macro_observations(indicator_code,period,value,data_status,source_url,updated_at) VALUES(?,?,?,?,?,?)',
                             ('CN_CONSUMPTION_PC', '2014', 14491, 'official_revised', 'yearbook-original', 'keep'))
                conn.commit()
                before = dict(conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=?', ('CN_CONSUMPTION_PC',)).fetchone())
            self.invoke(root, review, database)
            with closing(sqlite3.connect(database)) as conn:
                conn.row_factory = sqlite3.Row
                self.assertEqual(before, dict(conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=?', ('CN_CONSUMPTION_PC',)).fetchone()))

    def test_mid_batch_failure_rolls_back_both_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root, review, database = self.setup_run(directory)
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("CREATE TRIGGER fail_annual BEFORE INSERT ON china_macro_observations WHEN NEW.indicator_code='CN_CONSUMPTION_REAL_YOY' BEGIN SELECT RAISE(ABORT,'fixture error'); END")
                conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                self.invoke(root, review, database)
            with closing(sqlite3.connect(database)) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM china_macro_observations').fetchone()[0], 1)
            audit = json.loads(next((root / 'runs').glob('*/audit.json')).read_text(encoding='utf-8'))
            self.assertEqual(audit['committed_rows'], 0)

    def test_protected_readback_failure_rolls_back_all_new_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root, review, database = self.setup_run(directory)
            with patch.object(importer, 'protected_digest', side_effect=[(1, 'before'), (1, 'different')]):
                with self.assertRaises(ValueError):
                    self.invoke(root, review, database)
            with closing(sqlite3.connect(database)) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM china_macro_observations').fetchone()[0], 1)

    def test_running_job_defers_without_importing(self):
        with tempfile.TemporaryDirectory() as directory:
            root, review, database = self.setup_run(directory)
            with self.assertRaises(RuntimeError):
                self.invoke(root, review, database, busy=True)
            audit = json.loads(next((root / 'runs').glob('*/audit.json')).read_text(encoding='utf-8'))
            self.assertEqual(audit['phase'], 'deferred_active_update_job')
            self.assertEqual(audit['committed_rows'], 0)


if __name__ == '__main__':
    unittest.main()
