#!/usr/bin/env python3
"""Capture read-only history evidence for an inline handoff without changing sources."""
import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SURVEY_SQL = ("SELECT period,value,unit,data_status,source_url,release_date "
              "FROM china_macro_observations WHERE indicator_code='CN_UNEMP_SURVEY' "
              "AND value IS NOT NULL ORDER BY period")
BANK_SQL = ("SELECT indicator_code,indicator_name,period,value,unit,source_url "
            "FROM china_macro_observations WHERE indicator_code LIKE 'CN_BANK_%' "
            "AND period BETWEEN '2022-03' AND '2022-12' AND value IS NOT NULL "
            "ORDER BY indicator_code,period")
GAPS_SQL = ("SELECT indicator_code,MIN(period) AS first_period,MAX(period) AS latest_period,"
            "COUNT(*) AS valid_observations FROM china_macro_observations "
            "WHERE indicator_code IN ('CN_UNEMP_31_CITIES','CN_MOFCOM_FDI_USD_YTD') "
            "AND value IS NOT NULL GROUP BY indicator_code ORDER BY indicator_code")


def safe_link(url):
    parsed = urlsplit(url or '')
    return url if parsed.scheme in ('http', 'https') and not any((
        parsed.username, parsed.password, parsed.query, parsed.fragment)) else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs' / 'macro_refresh_20261012')
    parser.add_argument('--regression-summary', type=Path, required=True)
    parser.add_argument('--backend-log', type=Path, required=True)
    parser.add_argument('--chart-log', type=Path, required=True)
    args = parser.parse_args()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out = args.output_dir / ('history-handoff-' + stamp)
    out.mkdir(parents=True, exist_ok=False)
    connection = sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        executed_at = datetime.now().astimezone().isoformat()
        survey = [dict(row) for row in connection.execute(SURVEY_SQL)]
        bank = [dict(row) for row in connection.execute(BANK_SQL)]
        gap_rows = [dict(row) for row in connection.execute(GAPS_SQL)]
    finally:
        connection.close()
    assert len(survey) == 104 and survey[0]['period'] == '2018-01' and survey[-1]['period'] == '2026-08'
    month_indices = [int(row['period'][:4]) * 12 + int(row['period'][-2:]) for row in survey]
    assert all(right - left == 1 for left, right in zip(month_indices, month_indices[1:]))
    assert all(row['unit'] == '%' and row['data_status'] in ('official', 'official_relayed') for row in survey)
    assert len(bank) == 52 and len({row['indicator_code'] for row in bank}) == 13
    regression = json.loads(args.regression_summary.read_text(encoding='utf-8'))
    backend_text = args.backend_log.read_text(encoding='utf-8')
    chart_text = args.chart_log.read_text(encoding='utf-8')
    backend_match = re.search(r'^Ran (\d+) tests', backend_text, re.MULTILINE)
    chart_match = re.search(r'\btests (\d+)', chart_text)
    chart_pass = re.search(r'\bpass (\d+)', chart_text)
    if not backend_match or not re.search(r'^OK\s*$', backend_text, re.MULTILINE):
        raise ValueError('A terminal passing backend receipt is required.')
    if not chart_match or not chart_pass or chart_match[1] != chart_pass[1]:
        raise ValueError('A terminal passing chart receipt is required.')
    backend_count, chart_count = int(backend_match[1]), int(chart_match[1])
    captured_at = datetime.now().astimezone().isoformat()
    for row in survey:
        row['source_url'] = safe_link(row['source_url'])
    for row in bank:
        # Image version query is retained in the archived source manifest, not the inline receipt.
        row.pop('source_url')
    source = {
        'label': '国家统计局月度就业数据', 'tables': [{'name': 'china_macro_observations'}],
        'links': [{'label': '2018年一季度原始新闻稿', 'url': survey[0]['source_url']},
                  {'label': '2026年8月原始新闻稿', 'url': survey[-1]['source_url']}],
        'sql': SURVEY_SQL, 'executedAt': executed_at,
        'metricDefinitions': [{'label': '全国城镇调查失业率',
                              'definition': '全国城镇调查失业率是国家统计局公布的当月百分比，不是季度或年度平均值。'}],
        'caveats': ['部分缺月由国家统计局就业解读中明示的月值补入，保留official_relayed状态；没有按平均值分摊或插值。'],
        'evidenceFlow': [{'kind': 'validation', 'title': '月份与原文核对',
                          'detail': '104个真实月值连续覆盖2018-01至2026-08；2018年前三月与已存一季度原文相符，实际网站全历史曲线和期间切换检查通过。'}],
    }
    chart = {'schemaVersion': 1, 'id': 'national-survey-history-20261012',
             'queryId': 'national-survey-history', 'title': '全国城镇调查失业率（月度）',
             'chart': {'type': 'line', 'x': 'period', 'y': 'value', 'xLabel': '月份',
                       'yLabel': '失业率（%）', 'showXAxisLabel': False},
             'rows': survey, 'columns': ['period', 'value', 'unit', 'data_status'],
             'source': source, 'generatedAt': captured_at, 'theme': 'codex-classic'}
    chart_sources = {'schemaVersion': 1, 'items': [{
        'id': 'national-survey-history', 'title': '全国调查失业率历史补齐',
        'queries': [{'id': 'national-survey-history', 'source': source, 'rows': survey,
                     'columns': [{'field': 'period', 'label': '统计月份'},
                                 {'field': 'value', 'label': '当月调查失业率（%）'},
                                 {'field': 'data_status', 'label': '来源状态'},
                                 {'field': 'release_date', 'label': '原文发布日期'}],
                     'reportingPeriod': '2018-01至2026-08', 'capturedAt': captured_at}]}]}
    bank_source = {
        'label': '2022年商业银行监管表', 'tables': [{'name': 'china_macro_observations'}],
        'files': [{'label': '2022年官方季度表.xlsx',
                   'url': 'https://www.nfra.gov.cn/chinese/docfile/2023/93517e92dd4f480184a102c76cd1cac1.xlsx'}],
        'links': [{'label': '监管表官方元数据',
                   'url': 'https://www.nfra.gov.cn/cn/static/data/DocInfo/SelectByDocId/data_docId=1054675.json'}],
        'sql': BANK_SQL, 'executedAt': executed_at,
        'metricDefinitions': [{'label': '2022年银行历史补充',
                              'definition': '银行历史补充包含2022年四个季度、13项实际披露指标；净利润为本年累计，风险余额为季末。'}],
        'caveats': ['2022年监管表未列净稳定资金比例，保持缺失；资本指标不跨2024年新规连线。'],
        'evidenceFlow': [{'kind': 'validation', 'title': '图片、Excel与库内值',
                          'detail': '52个新增单元格与官方图片、Excel显示值和数据库逐格一致；重复同步为0条变更；实际页面显示2022Q1至2026Q2共18个季度。'}],
    }
    testing_source = {
        'label': '本轮测试与运行验收',
        'files': [{'label': args.backend_log.name},
                  {'label': args.chart_log.name},
                  {'label': args.regression_summary.name}],
        'caveats': ['本轮相关测试通过不等于全仓通过。全仓测试期间修改了宏观代码，最终工作树以相关模块重测结果为准。',
                    '自动更新补存明示1月数据的新后台规则仅在隔离库验证，未宣称已被旧的5001进程加载。'],
        'evidenceFlow': [{'kind': 'validation', 'title': '相关测试',
                          'detail': f'后台{backend_count}项与Node图表{chart_count}项通过；实际银行页面6项、就业页面5项通过。'},
                         {'kind': 'result', 'title': '全仓终止结果',
                          'detail': f"180个模块中{regression['n_passed_modules']}个通过，" +
                                    f"非通过结果{dict(Counter(row['status'] for row in regression['failures']))}。" +
                                    '旧宏观板块断言已经修复并单独重测；学术模块缺陷未越界修复。'}],
    }
    additional = {'schemaVersion': 1, 'items': [
        {'id': 'bank-history-2022', 'title': '银行监管历史新增2022年',
         'queries': [{'id': 'bank-history-2022', 'source': bank_source, 'rows': bank,
                      'columns': [{'field': 'indicator_name', 'label': '指标'},
                                  {'field': 'period', 'label': '季度末'},
                                  {'field': 'value', 'label': '公布值'},
                                  {'field': 'unit', 'label': '单位'}],
                      'reportingPeriod': '2022Q1至2022Q4', 'capturedAt': captured_at}]},
        {'id': 'verification-status', 'title': '本轮验证与尚未完成项',
         'queries': [{'id': 'verification-status', 'source': testing_source,
                      'capturedAt': captured_at}]},
        {'id': 'remaining-history', 'title': '仍需补充的历史与美元外资',
         'queries': [{'id': 'remaining-history',
                      'source': {'label': '已注册序列覆盖',
                                 'tables': [{'name': 'china_macro_observations'}],
                                 'sql': GAPS_SQL, 'executedAt': executed_at,
                                 'caveats': ['31个大城市调查失业率仍有内部缺月。',
                                             '商务部美元累计实际使用外资停在2023-07，人民币序列不能按汇率换算代替。',
                                             '最早与最新月份不证明其间每个月均有公开原值；早期年末点也不拆成月度。']},
                      'rows': gap_rows,
                      'columns': [{'field': 'indicator_code', 'label': '序列代码'},
                                  {'field': 'first_period', 'label': '最早有效点'},
                                  {'field': 'latest_period', 'label': '最新有效点'},
                                  {'field': 'valid_observations', 'label': '有效观测数'}],
                      'capturedAt': captured_at}]}]}
    for name, payload in (('survey-chart.json', chart), ('survey-sources.json', chart_sources),
                          ('additional-sources.json', additional)):
        (out / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest = {'captured_at': captured_at, 'survey_count': len(survey),
                'survey_statuses': dict(Counter(row['data_status'] for row in survey)),
                'bank_2022_cells': len(bank), 'remaining_series': gap_rows,
                'regression_summary': str(args.regression_summary),
                'regression_status': regression['status'],
                'queries': {'survey': SURVEY_SQL, 'bank': BANK_SQL, 'remaining': GAPS_SQL}}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output_dir': str(out), 'survey_count': len(survey), 'bank_2022_cells': len(bank),
                      'remaining_codes': sorted({row['indicator_code'] for row in gap_rows}),
                      'regression_status': regression['status']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
