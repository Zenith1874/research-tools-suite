# -*- coding: utf-8 -*-
"""Transparent market-proxy debt scenarios must remain auditable."""
import os
import sqlite3
import tempfile
import unittest

from services.lgfv_bond_market_service import ensure_lgfv_market_tables
from services.lgfv_bond_scenario_service import (
    build_lgfv_bond_scenario_payload,
    build_scenario_set,
    classify_lgfv_proxy,
    project_lgfv_cashflows,
)


class ProxyClassificationTests(unittest.TestCase):
    def test_strict_broad_and_unmatched_are_separate(self):
        self.assertEqual(
            classify_lgfv_proxy('常州市城市建设投资集团有限公司')['classification'],
            'strict',
        )
        self.assertEqual(
            classify_lgfv_proxy('福州市交通投资集团有限公司')['classification'],
            'broad',
        )
        self.assertEqual(
            classify_lgfv_proxy('某制造有限公司')['classification'],
            'unmatched',
        )


class CashflowProjectionTests(unittest.TestCase):
    def test_base_formula_and_refinanced_maturity_are_reproducible(self):
        rows = project_lgfv_cashflows(
            100.0, {2027: 30.0}, 2027, horizon=4,
            refinancing_rate=0.80, new_money_rate=0.0,
            funding_rate=0.04, term_years=3,
        )
        first = rows[0]
        self.assertEqual(first['closing_balance'], 94.0)
        self.assertEqual(first['cash_principal'], 6.0)
        self.assertEqual(first['estimated_interest'], 3.88)
        self.assertEqual(first['cash_debt_service'], 9.88)
        self.assertEqual(rows[-1]['period'], '2030')
        self.assertEqual(rows[-1]['projected_maturity'], 24.0)

    def test_first_partial_year_prorates_flow_and_interest_not_known_maturity(self):
        row = project_lgfv_cashflows(
            100.0, {2026: 20.0}, 2026, horizon=1,
            refinancing_rate=0.50, new_money_rate=0.10,
            funding_rate=0.04, term_years=3,
            first_period_fraction=0.50,
        )[0]
        self.assertEqual(row['contracted_maturity'], 20.0)
        self.assertEqual(row['new_money_issuance'], 5.0)
        self.assertEqual(row['closing_balance'], 95.0)
        self.assertEqual(row['estimated_interest'], 1.95)
        self.assertEqual(row['period_fraction'], 0.5)

    def test_three_scenarios_have_no_probability_claim(self):
        scenarios = build_scenario_set(100.0, {2027: 20.0}, 2027, horizon=5)
        self.assertEqual([row['scenario_code'] for row in scenarios],
                         ['easing', 'base', 'stress'])
        self.assertGreater(scenarios[0]['refinancing_rate'],
                           scenarios[1]['refinancing_rate'])
        self.assertGreater(scenarios[1]['refinancing_rate'],
                           scenarios[2]['refinancing_rate'])
        self.assertTrue(all(row['data_status'] == 'scenario' for row in scenarios))


class PrivateDatabasePayloadTests(unittest.TestCase):
    SNAPSHOT = '2026-08-08'

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db_path = handle.name
        handle.close()
        conn = sqlite3.connect(self.db_path)
        ensure_lgfv_market_tables(conn)
        now = '2026-08-08T12:00:00'
        inventory = [
            ('S1', '26常州城投债', '常州市城市建设投资集团有限公司'),
            ('S2', '23新区建设债', '某新区建设投资有限公司'),
            ('SMISS', '待补城投债', '某城市建设投资有限公司'),
            ('F1', '待发行城投债', '某城市发展投资有限公司'),
            ('B1', '26福州交投债', '福州市交通投资集团有限公司'),
            ('U1', '26制造债', '某制造有限公司'),
        ]
        conn.executemany('''
            INSERT INTO lgfv_bond_inventory
              (snapshot_date,source_type,bond_defined_code,bond_name,issuer,
               source_url,raw_json,data_status,current_balance_status,
               created_at,updated_at)
            VALUES (?,?,?,?,?,'https://example.test','{}','official_inventory',
                    'not_disclosed',?,?)
        ''', [(self.SNAPSHOT, 'test', code, name, issuer, now, now)
              for code, name, issuer in inventory])
        terms = [
            ('S1', '26常州城投债', '常州城市建设投资债券',
             '常州市城市建设投资集团有限公司', 100.0, '2026-01-01', '2030-06-30', 4.0),
            ('S2', '23新区建设债', '某新区建设投资债券',
             '某新区建设投资有限公司', 20.0, '2023-01-01', '2026-12-31', 3.8),
            ('F1', '待发行城投债', '某城市发展投资债券',
             '某城市发展投资有限公司', 10.0, '2026-09-01', '2031-09-01', 3.6),
            ('B1', '26福州交投债', '福州交通投资债券',
             '福州市交通投资集团有限公司', 50.0, '2026-02-01', '2029-06-30', 3.0),
            ('U1', '26制造债', '某制造企业债券',
             '某制造有限公司', 200.0, '2026-02-01', '2029-06-30', 3.5),
        ]
        conn.executemany('''
            INSERT INTO lgfv_bond_terms
              (snapshot_date,source_type,bond_defined_code,bond_name,bond_full_name,
               issuer,actual_issue_amount,issue_date,maturity_date,coupon_rate,coupon_frequency,
               exercise_info_json,additional_issue_json,source_url,raw_json,
               data_status,detail_status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,'每年','[]','[]','https://example.test','{}',
                    'official_terms','success',?,?)
        ''', [(self.SNAPSHOT, 'detail', *row, now, now) for row in terms])
        conn.executemany('''
            INSERT INTO lgfv_bond_cashflows
              (snapshot_date,bond_defined_code,event_type,event_date,amount,
               amount_unit,data_status,method,source_url,raw_json,created_at,updated_at)
            VALUES (?,?,'scheduled_interest','2027-06-30',4.0,'亿元',
                    'derived_schedule','test','https://example.test','{}',?,?)
        ''', [
            (self.SNAPSHOT, 'S1', now, now),
        ])
        conn.execute('''
            INSERT INTO lgfv_bond_cashflows
              (snapshot_date,bond_defined_code,event_type,event_date,amount,
               amount_unit,data_status,method,source_url,raw_json,created_at,updated_at)
            VALUES (?,?,'scheduled_interest','2027-06-30',0.36,'亿元',
                    'derived_schedule','test','https://example.test','{}',?,?)
        ''', (self.SNAPSHOT, 'F1', now, now))
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_strict_scope_is_not_scaled_for_missing_details(self):
        payload = build_lgfv_bond_scenario_payload(
            self.db_path, scope='strict', horizon=5, as_of=self.SNAPSHOT)
        self.assertEqual(payload['scope_terms_count'], 3)
        self.assertEqual(payload['scope_inventory_count'], 4)
        self.assertAlmostEqual(payload['scope_detail_coverage_pct'], 75.0)
        self.assertEqual(payload['active_issue_amount_upper_bound'], 120.0)
        self.assertEqual(payload['active_missing_issue_date_count'], 0)
        self.assertEqual(payload['next_three_year_maturity'], 20.0)
        self.assertEqual(payload['contracted_cashflows'][0]['period'], '2026')
        self.assertEqual(payload['contracted_cashflows'][0]['maturing_principal'], 20.0)
        self.assertEqual(payload['contracted_cashflows'][1]['known_coupon_interest'], 4.0)
        self.assertEqual(len(payload['scenarios']), 3)
        self.assertEqual(payload['data_status'], 'scenario')
        self.assertEqual(payload['scope_status'],
                         'keyword_proxy_not_official_classification')

    def test_scope_switch_changes_only_the_transparent_proxy_universe(self):
        strict = build_lgfv_bond_scenario_payload(
            self.db_path, scope='strict', horizon=5, as_of=self.SNAPSHOT)
        broad = build_lgfv_bond_scenario_payload(
            self.db_path, scope='broad', horizon=5, as_of=self.SNAPSHOT)
        all_candidates = build_lgfv_bond_scenario_payload(
            self.db_path, scope='all', horizon=5, as_of=self.SNAPSHOT)
        self.assertEqual(strict['active_issue_amount_upper_bound'], 120.0)
        self.assertEqual(broad['active_issue_amount_upper_bound'], 170.0)
        self.assertEqual(all_candidates['active_issue_amount_upper_bound'], 370.0)

    def test_manual_market_anchor_scales_schedule_but_keeps_sample_diagnostic(self):
        payload = build_lgfv_bond_scenario_payload(
            self.db_path, scope='strict', horizon=5, as_of=self.SNAPSHOT,
            balance_anchor=1500.0)
        self.assertTrue(payload['manual_balance_anchor_enabled'])
        self.assertEqual(payload['scenario_opening_balance'], 1500.0)
        self.assertEqual(payload['active_issue_amount_upper_bound'], 120.0)
        self.assertEqual(payload['candidate_active_issue_amount_upper_bound'], 370.0)
        self.assertAlmostEqual(payload['schedule_scale_factor'], 1500.0 / 370.0)
        self.assertEqual(payload['scenarios'][1]['path'][0]['opening_balance'], 1500.0)
        self.assertAlmostEqual(
            payload['contracted_cashflows'][0]['maturing_principal'],
            20.0 * 1500.0 / 370.0,
            places=4,
        )
        self.assertIn('用户指定的15万亿元市场基准',
                      payload['method']['opening_balance'])

    def test_missing_database_fails_closed(self):
        payload = build_lgfv_bond_scenario_payload(self.db_path + '.missing')
        self.assertEqual(payload['status'], 'missing')
        self.assertEqual(payload['scenarios'], [])


if __name__ == '__main__':
    unittest.main()
