import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[1] / 'pboc_data.db'


def rows(conn, sql):
    return [dict(row) for row in conn.execute(sql).fetchall()]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    tables = [
        ('fiscal_debt_observations', 'period'),
        ('pboc_balance_sheet_observations', 'period'),
        ('pboc_gov_bond_omo_observations', 'period'),
    ]
    for table, period in tables:
        print(f'\nTABLE {table}')
        row = conn.execute(f'''SELECT COUNT(*) records,MIN({period}) earliest,MAX({period}) latest,
            SUM(CASE WHEN COALESCE(TRIM(source_url),'')='' THEN 1 ELSE 0 END) missing_source_url
            FROM {table}''').fetchone()
        print(dict(row))

    print('\nFiscal debt indicators')
    for row in rows(conn, '''SELECT module_code,indicator_code,COUNT(*) n,MIN(period) earliest,
        MAX(period) latest,GROUP_CONCAT(DISTINCT data_status) statuses,
        SUM(CASE WHEN COALESCE(TRIM(source_url),'')='' THEN 1 ELSE 0 END) missing_source_url
        FROM fiscal_debt_observations GROUP BY module_code,indicator_code ORDER BY module_code,indicator_code'''):
        print(row)

    print('\nData discipline violations')
    checks = {
        'official_missing_source_url': "SELECT COUNT(*) n FROM fiscal_debt_observations WHERE data_status='official' AND COALESCE(TRIM(source_url),'')=''",
        'derived_missing_formula': "SELECT COUNT(*) n FROM fiscal_debt_observations WHERE data_status='derived' AND COALESCE(TRIM(formula),'')=''",
        'scenario_in_official_observations': "SELECT COUNT(*) n FROM fiscal_debt_observations WHERE data_status='scenario'",
        'mock_or_seed': 'SELECT COUNT(*) n FROM fiscal_debt_observations WHERE is_mock=1 OR is_seed=1',
    }
    for name, sql in checks.items():
        print(name, conn.execute(sql).fetchone()['n'])

    print('\nPBOC gov bond OMO')
    for row in rows(conn, '''SELECT period,operation_status,net_purchase_amount,unit,source_title,source_url
        FROM pboc_gov_bond_omo_observations ORDER BY period DESC LIMIT 20'''):
        print(row)

    print('\nUpdate logs')
    for row in rows(conn, '''SELECT module_code,status,http_status,source_url,started_at,finished_at,
        records_inserted,records_updated,error_message,warnings
        FROM fiscal_debt_update_logs ORDER BY id DESC LIMIT 20'''):
        print(row)
    conn.close()


if __name__ == '__main__':
    main()
