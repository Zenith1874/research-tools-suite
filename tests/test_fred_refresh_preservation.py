"""Keep current official values idempotent and make numerical revisions auditable."""
import json
import sqlite3
import unittest
from contextlib import closing

from services.us_macro_service import ensure_us_macro_tables,parse_fred_csv,upsert_fred_observations


class FredRefreshPreservationTests(unittest.TestCase):
    def connection(self):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row;ensure_us_macro_tables(conn);return conn

    def test_wrong_series_and_conflicting_dates_are_rejected(self):
        for text in ('observation_date,DGS2\n2026-10-01,4.1\n',
                     'observation_date,DGS10,EXTRA\n2026-10-01,4.1,7\n',
                     'observation_date,DGS10\n2026-10-01,4.1\n2026-10-01,4.2\n'):
            with self.assertRaises(ValueError):parse_fred_csv(text,'DGS10')
        rows=parse_fred_csv('observation_date,DGS10\n2026-10-01,4.1\n2026-10-01,4.1\n2026-10-02,.\n2026-10-03,NaN\n','DGS10')
        self.assertEqual(rows,[{'period':'2026-10-01','value':4.1}])

    def test_equal_value_keeps_primary_source_and_entire_existing_row(self):
        with closing(self.connection()) as conn:
            upsert_fred_observations(conn,'DGS10',[{'period':'2026-10-01','value':4.1}])
            conn.execute("UPDATE us_macro_observations SET source_name='Federal Reserve H15',source_url='https://www.federalreserve.gov/releases/h15/',parser_notes='Original primary-source proof',updated_at='2026-10-02T00:00:00'")
            before=dict(conn.execute('SELECT * FROM us_macro_observations').fetchone())
            result=upsert_fred_observations(conn,'DGS10',[{'period':'2026-10-01','value':4.1}])
            self.assertEqual(result,{'inserted':0,'updated':0,'unchanged':1})
            self.assertEqual(dict(conn.execute('SELECT * FROM us_macro_observations').fetchone()),before)

    def test_revisions_keep_full_old_record_and_latest_receipt(self):
        receipt={'raw_sha256':'a'*64,'retrieved_at':'2026-10-15T10:00:00Z','receipt_ref':'run/DGS10.receipt.json','units_excerpt':'Percent'}
        with closing(self.connection()) as conn:
            upsert_fred_observations(conn,'DGS10',[{'period':'2026-10-01','value':4.1}])
            old=dict(conn.execute('SELECT * FROM us_macro_observations').fetchone())
            result=upsert_fred_observations(conn,'DGS10',[{'period':'2026-10-01','value':4.2}],receipt)
            self.assertEqual(result['updated'],1)
            revision=conn.execute('SELECT * FROM us_macro_revision_history').fetchone()
            self.assertEqual(json.loads(revision['original_row_json']),old)
            self.assertEqual(revision['replacement_source_sha256'],'a'*64)
            self.assertEqual(upsert_fred_observations(conn,'DGS10',[{'period':'2026-10-01','value':4.2}],receipt)['unchanged'],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM us_macro_revision_history').fetchone()[0],1)

    def test_series_failure_rolls_back_new_values_and_history(self):
        with closing(self.connection()) as conn:
            upsert_fred_observations(conn,'DGS10',[{'period':'2026-10-01','value':4.1}])
            old=dict(conn.execute('SELECT * FROM us_macro_observations').fetchone())
            with self.assertRaises(ValueError):
                upsert_fred_observations(conn,'DGS10',[{'period':'2026-10-01','value':4.2},{'period':'2026-10-02','value':float('inf')}])
            self.assertEqual(dict(conn.execute('SELECT * FROM us_macro_observations').fetchone()),old)
            table=conn.execute("SELECT name FROM sqlite_master WHERE name='us_macro_revision_history'").fetchone()
            self.assertIsNone(table)


if __name__=='__main__':unittest.main()
