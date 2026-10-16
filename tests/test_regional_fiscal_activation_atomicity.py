"""The CLI logs full failures and never commits only some year groups."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import Mock,patch

from scripts.activate_regional_fiscal_snapshot import main
from services.regional_fiscal_service import ensure_regional_fiscal_table,_upsert


class RegionalFiscalActivationAtomicityTests(unittest.TestCase):
    def run_failure(self,invalid_value=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);database=root/'test.db';snapshots=root/'snapshots';snapshots.mkdir()
            old={'country_code':'CN','government_scope':'province_total','region_code':'340000','region_name':'安徽',
                 'indicator_code':'general_budget_revenue','period':'2025','value':100.,'unit':'亿元','frequency':'annual',
                 'period_type':'calendar_year','data_status':'official','source_name':'Fixture fiscal department',
                 'source_url':'https://www.stats.gov.cn/fixture.html','source_title':'Fixture2025','parser_notes':'Fixture only'}
            new={**old,'indicator_code':'gov_fund_revenue','value':20.}
            snapshot={'schema_version':1,'review_status':'source_values_reviewed','statistical_year':'2025',
                      'generated_at':'2026-01-01T00:00:00+00:00','observations':[old,new]}
            (snapshots/'fixture.json').write_text(json.dumps(snapshot),encoding='utf-8')
            with closing(sqlite3.connect(database)) as conn:ensure_regional_fiscal_table(conn);_upsert(conn,old);conn.commit()
            response=Mock();response.json.return_value={'jobs':{},'update_lock_busy':False}
            session=Mock();session.get.return_value=response

            def importer(conn,*args):
                self.assertTrue(conn.in_transaction)
                _upsert(conn,{**new,'value':999.} if invalid_value else new)
                return {'inserted':1,'updated':0,'unchanged':1,'errors':[] if invalid_value else ['synthetic storage failure']}

            argv=['activate','--database',str(database),'--snapshot-dir',str(snapshots),'--output-dir',str(root/'outputs'),'--apply']
            with patch('sys.argv',argv),patch('scripts.activate_regional_fiscal_snapshot.requests.Session',return_value=session),patch('scripts.activate_regional_fiscal_snapshot.sync_reviewed_regional_fiscal',side_effect=importer):
                with self.assertRaises(ValueError):main()
            receipt=json.loads(next((root/'outputs').glob('*/audit.json')).read_text(encoding='utf-8'))
            self.assertEqual(receipt['phase'],'failed_rolled_back');self.assertEqual(receipt['committed_rows'],0)
            self.assertIn('error',receipt)
            with closing(sqlite3.connect(database)) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM regional_fiscal_observations').fetchone()[0],1)
                self.assertEqual(conn.execute('SELECT value FROM regional_fiscal_observations').fetchone()[0],100.)
            return receipt

    def test_import_error_keeps_full_details_and_rolls_back_attempted_rows(self):
        receipt=self.run_failure()
        self.assertEqual(receipt['import']['errors'],['synthetic storage failure'])

    def test_bad_readback_is_rolled_back_before_commit(self):
        receipt=self.run_failure(True)
        self.assertFalse(receipt['exact_value_readback'])


if __name__=='__main__':unittest.main()
