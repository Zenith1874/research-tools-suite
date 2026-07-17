# -*- coding: utf-8 -*-
"""美国宏观模块：就业、通胀、增长、财政与金融条件五组官方序列。

数据源：圣路易斯联储 FRED 的免 key CSV 端点(2026-07 实测可用)
    https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>
数据本源分别为 BLS(UNRATE/JTSQUR)与美联储 H.15(FEDFUNDS/DGS10)，FRED 为官方镜像。

数据纪律：逐条 official + source_url(FRED series 页)；失败不清旧数据；缺失值('.')跳过。
"""
import csv
import io
import sqlite3
from contextlib import closing
from datetime import datetime

import requests

SOURCE_NAME = 'FRED (Federal Reserve Bank of St. Louis)'
SOURCE_TYPE = 'us_macro'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
HTTP_TIMEOUT = 25

SERIES = [
    # code, 名称, 单位, 频率, 本源说明, 分组
    ('UNRATE', '美国失业率', '%', 'monthly', 'BLS CPS 经季调', 'labor'),
    ('U6RATE', 'U-6 广义失业率', '%', 'monthly', 'BLS CPS 经季调', 'labor'),
    ('CIVPART', '劳动参与率', '%', 'monthly', 'BLS CPS 经季调', 'labor'),
    ('EMRATIO', '就业人口比', '%', 'monthly', 'BLS CPS 经季调', 'labor'),
    ('PAYEMS', '非农就业人数', '千人', 'monthly', 'BLS CES 经季调', 'labor'),
    ('ICSA', '首次申领失业救济人数', '人', 'weekly', '美国劳工部 ETA，经季调', 'labor'),
    ('JTSJOL', 'JOLTS 职位空缺数', '千人', 'monthly', 'BLS JOLTS 经季调', 'labor'),
    ('JTSHIR', 'JOLTS 招聘率', '%', 'monthly', 'BLS JOLTS 经季调', 'labor'),
    ('JTSLDL', 'JOLTS 裁员及解雇数', '千人', 'monthly', 'BLS JOLTS 经季调', 'labor'),
    ('JTSQUR', 'JOLTS 主动离职率', '%', 'monthly', 'BLS JOLTS 经季调', 'labor'),
    ('CES0500000003', '私营非农平均时薪', '美元/小时', 'monthly', 'BLS CES 经季调', 'labor'),
    ('OPHNFB', '非农商业劳动生产率指数', '指数', 'quarterly', 'BLS 非农商业部门，经季调', 'labor'),
    ('CPIAUCSL', 'CPI 城市消费者价格指数', '指数', 'monthly', 'BLS CPI-U 经季调', 'inflation'),
    ('CPILFESL', '核心 CPI 指数', '指数', 'monthly', 'BLS CPI-U 不含食品能源，经季调', 'inflation'),
    ('PCEPILFE', '核心 PCE 价格指数', '指数', 'monthly', 'BEA PCE 不含食品能源，经季调', 'inflation'),
    ('GDPC1', '实际 GDP', '十亿美元', 'quarterly', 'BEA 2017 年链式美元，季调年率', 'growth'),
    ('INDPRO', '工业产出指数', '指数', 'monthly', '美联储 G.17，经季调', 'growth'),
    ('RSAFS', '零售和餐饮销售额', '百万美元', 'monthly', '美国人口普查局，经季调', 'growth'),
    ('FGRECPT', '联邦政府经常性收入', '十亿美元', 'quarterly', 'BEA NIPA，季调年率', 'fiscal'),
    ('FGEXPND', '联邦政府经常性支出', '十亿美元', 'quarterly', 'BEA NIPA，季调年率', 'fiscal'),
    ('FYFSD', '联邦财政年度盈余/赤字', '百万美元', 'annual', '美国财政部/OMB，财政年度', 'fiscal'),
    ('GFDEBTN', '联邦公共债务总额', '百万美元', 'quarterly', '美国财政部 Fiscal Service', 'fiscal'),
    ('GFDEGDQ188S', '联邦公共债务占 GDP', '%', 'quarterly', 'OMB/FRED 由债务与 GDP 计算', 'fiscal'),
    ('A091RC1Q027SBEA', '联邦政府利息支付', '十亿美元', 'quarterly', 'BEA NIPA，季调年率', 'fiscal'),
    ('FEDFUNDS', '联邦基金有效利率', '%', 'monthly', '美联储 H.15', 'financial'),
    ('DFF', '联邦基金有效利率（日频）', '%', 'daily', '纽约联储/美联储 H.15', 'financial'),
    ('SOFR', '担保隔夜融资利率', '%', 'daily', '纽约联储', 'financial'),
    ('DPRIME', '银行优惠贷款利率', '%', 'daily', '美联储 H.15', 'financial'),
    ('DGS3MO', '3个月期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS2', '2年期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS5', '5年期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS10', '10年期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS30', '30年期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('T10Y2Y', '10Y－2Y 国债期限利差', '百分点', 'daily', 'FRED 由美联储 H.15 序列计算', 'financial'),
    ('T10YIE', '10年期盈亏平衡通胀率', '%', 'daily', 'FRED 由名义与通胀保值国债计算', 'financial'),
    ('MORTGAGE30US', '30年期固定房贷利率', '%', 'weekly', 'Freddie Mac PMMS', 'financial'),
]

GROUP_META = {
    'labor': {'title': '就业与劳动力市场', 'summary': '就业松紧、劳动供给与主动离职'},
    'inflation': {'title': '通胀', 'summary': '居民消费通胀与美联储重点关注的核心 PCE'},
    'growth': {'title': '增长与需求', 'summary': '实际 GDP、工业生产与消费需求'},
    'fiscal': {'title': '政府收支与债务', 'summary': '联邦收入、支出、赤字、公共债务与利息负担'},
    'financial': {'title': '利率与金融条件', 'summary': '政策利率、收益率曲线与住房融资成本'},
}


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_us_macro_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS us_macro_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator_code TEXT, indicator_name TEXT, period TEXT,
        value REAL, unit TEXT, frequency TEXT,
        data_status TEXT, source_name TEXT, source_type TEXT,
        source_url TEXT, source_title TEXT, parser_notes TEXT, formula TEXT,
        updated_at TEXT,
        UNIQUE(indicator_code, period)
    )''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_us_macro_code_period
                    ON us_macro_observations(indicator_code, period)''')
    conn.commit()


def parse_fred_csv(text, code):
    """fredgraph.csv -> obs 行。首列 observation_date，次列为系列值；缺失是 '.'。"""
    rows = []
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 2 or 'date' not in header[0].lower():
        raise ValueError(f'{code}: 非预期的 CSV 头 {header!r}')
    for line in reader:
        if len(line) < 2:
            continue
        d, v = line[0].strip(), line[1].strip()
        if not d or v in ('', '.'):
            continue
        try:
            rows.append({'period': d, 'value': float(v)})
        except ValueError:
            continue
    return rows


def fetch_series(code):
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}'
    r = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return parse_fred_csv(r.text, code)


def update_us_macro(db_path):
    """全量拉取(FRED CSV 本身就是整段历史，幂等 upsert)。单系列失败不影响其他。"""
    started = datetime.now().isoformat()
    errors, upserted = [], 0
    with closing(connect(db_path)) as conn:
        ensure_us_macro_tables(conn)
        now = datetime.now().isoformat()
        for code, name, unit, freq, origin, group in SERIES:
            try:
                rows = fetch_series(code)
            except Exception as exc:
                errors.append(f'{code}: {exc}')
                continue
            page = f'https://fred.stlouisfed.org/series/{code}'
            for o in rows:
                cur = conn.execute('''INSERT INTO us_macro_observations (
                    indicator_code,indicator_name,period,value,unit,frequency,data_status,
                    source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(indicator_code,period) DO UPDATE SET
                    value=excluded.value, updated_at=excluded.updated_at''',
                    (code, name, o['period'], o['value'], unit, freq, 'official',
                     SOURCE_NAME, SOURCE_TYPE, page, f'FRED {code}',
                     f'fredgraph.csv 免key端点；本源：{origin}', None, now))
                upserted += cur.rowcount
        conn.commit()
    return {'success': not errors or upserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(), 'records_upserted': upserted,
            'errors': errors}


def _downsample(rows, max_points=1200):
    """长序列等距降采样(保首尾)，只影响图表密度，存储仍是全量。"""
    n = len(rows)
    if n <= max_points:
        return rows
    stride = (n - 1) / (max_points - 1)
    idxs = sorted({round(i * stride) for i in range(max_points)} | {0, n - 1})
    return [rows[i] for i in idxs]


def _series_rows(conn, code, max_points=1200):
    rows = [dict(r) for r in conn.execute(
        'SELECT period, value FROM us_macro_observations WHERE indicator_code=? ORDER BY period', (code,))]
    return _downsample(rows, max_points)


def derive_change_series(rows, lag, annualize=False):
    """Create transparent derived changes without writing them to official rows."""
    result = []
    for idx in range(lag, len(rows)):
        current, previous = rows[idx], rows[idx - lag]
        if previous['value'] in (None, 0) or current['value'] is None:
            continue
        ratio = current['value'] / previous['value']
        value = ((ratio ** 4 - 1) if annualize else (ratio - 1)) * 100
        result.append({'period': current['period'], 'value': round(value, 4),
                       'data_status': 'derived'})
    return result


def derive_difference_series(rows, lag=1):
    result = []
    for idx in range(lag, len(rows)):
        current, previous = rows[idx], rows[idx - lag]
        if current['value'] is None or previous['value'] is None:
            continue
        result.append({'period': current['period'],
                       'value': round(current['value'] - previous['value'], 4),
                       'data_status': 'derived'})
    return result


def derive_aligned_spread(left_rows, right_rows):
    """Subtract right from left for exact matching periods."""
    right = {row['period']: row['value'] for row in right_rows}
    return [{'period': row['period'], 'value': round(row['value'] - right[row['period']], 4),
             'data_status': 'derived'}
            for row in left_rows if row['period'] in right]


def _latest_card(rows, label, unit, source_code, formula):
    latest = rows[-1] if rows else None
    # group 跟随源系列:扁平 cards 列表的消费方(如按组过滤)才不会漏掉 derived 卡
    group = next((g for c, _n, _u, _f, _o, g in SERIES if c == source_code), None)
    return {
        'label': label, 'value': latest['value'] if latest else None,
        'unit': unit, 'period': latest['period'] if latest else None,
        'group': group,
        'data_status': 'derived' if latest else 'missing',
        'source_name': SOURCE_NAME if latest else None,
        'source_url': f'https://fred.stlouisfed.org/series/{source_code}' if latest else None,
        'formula': formula if latest else None,
        'warning': None if latest else '原始系列尚未抓取。',
    }


def build_us_macro_payload(db_path):
    with closing(connect(db_path)) as conn:
        ensure_us_macro_tables(conn)
        cov = dict(conn.execute('''SELECT COUNT(*) records, MIN(period) earliest, MAX(period) latest
                                   FROM us_macro_observations''').fetchone())
        raw_cards, series, raw = {}, {}, {}
        indicator_coverage = {}
        for code, name, unit, freq, origin, group in SERIES:
            r = conn.execute('''SELECT * FROM us_macro_observations WHERE indicator_code=?
                                ORDER BY period DESC LIMIT 1''', (code,)).fetchone()
            raw_cards[code] = {
                'label': name, 'value': r['value'] if r else None,
                'unit': unit, 'period': r['period'] if r else None,
                'data_status': r['data_status'] if r else 'missing',
                'source_name': SOURCE_NAME if r else None,
                'source_url': r['source_url'] if r else None,
                'parser_notes': r['parser_notes'] if r else None,
                'warning': None if r else '尚未抓取，点击"更新数据"。',
                'group': group,
            }
            # 全量历史；超长序列(日频 DGS10 自 1962)等距降采样到 ~1200 点
            raw[code] = _series_rows(conn, code, max_points=50000)
            series[code] = _downsample(raw[code])
            indicator_coverage[code] = {
                'earliest': raw[code][0]['period'] if raw[code] else None,
                'latest': raw[code][-1]['period'] if raw[code] else None,
                'records': len(raw[code]),
            }

        derived = {
            'PAYEMS_MOM': derive_difference_series(raw['PAYEMS']),
            'CPI_YOY': derive_change_series(raw['CPIAUCSL'], 12),
            'CORE_CPI_YOY': derive_change_series(raw['CPILFESL'], 12),
            'CORE_PCE_YOY': derive_change_series(raw['PCEPILFE'], 12),
            'REAL_GDP_QOQ_AR': derive_change_series(raw['GDPC1'], 1, annualize=True),
            'INDPRO_YOY': derive_change_series(raw['INDPRO'], 12),
            'RETAIL_YOY': derive_change_series(raw['RSAFS'], 12),
            'AHE_YOY': derive_change_series(raw['CES0500000003'], 12),
            'PRODUCTIVITY_YOY': derive_change_series(raw['OPHNFB'], 4),
            'FED_CURRENT_BALANCE': derive_aligned_spread(raw['FGRECPT'], raw['FGEXPND']),
        }
        series.update({key: _downsample(value) for key, value in derived.items()})

        groups = [
            {**GROUP_META['labor'], 'code': 'labor', 'cards': [
                raw_cards['UNRATE'], raw_cards['U6RATE'], raw_cards['CIVPART'], raw_cards['EMRATIO'],
                _latest_card(derived['PAYEMS_MOM'], '非农就业月增', '千人', 'PAYEMS',
                             'PAYEMS(t) - PAYEMS(t-1)'),
                raw_cards['ICSA'], raw_cards['JTSJOL'],
                _latest_card(derived['AHE_YOY'], '私营非农平均时薪同比', '%', 'CES0500000003',
                             '(AHE(t) / AHE(t-12) - 1) × 100'),
            ]},
            {**GROUP_META['inflation'], 'code': 'inflation', 'cards': [
                _latest_card(derived['CPI_YOY'], 'CPI 同比', '%', 'CPIAUCSL',
                             '(CPI(t) / CPI(t-12) - 1) × 100'),
                _latest_card(derived['CORE_CPI_YOY'], '核心 CPI 同比', '%', 'CPILFESL',
                             '(Core CPI(t) / Core CPI(t-12) - 1) × 100'),
                _latest_card(derived['CORE_PCE_YOY'], '核心 PCE 同比', '%', 'PCEPILFE',
                             '(Core PCE(t) / Core PCE(t-12) - 1) × 100'),
            ]},
            {**GROUP_META['growth'], 'code': 'growth', 'cards': [
                _latest_card(derived['REAL_GDP_QOQ_AR'], '实际 GDP 环比年化', '%', 'GDPC1',
                             '((Real GDP(t) / Real GDP(t-1))^4 - 1) × 100'),
                _latest_card(derived['INDPRO_YOY'], '工业产出同比', '%', 'INDPRO',
                             '(INDPRO(t) / INDPRO(t-12) - 1) × 100'),
                _latest_card(derived['RETAIL_YOY'], '零售销售同比', '%', 'RSAFS',
                             '(RSAFS(t) / RSAFS(t-12) - 1) × 100'),
            ]},
            {**GROUP_META['fiscal'], 'code': 'fiscal', 'cards': [
                raw_cards['FGRECPT'], raw_cards['FGEXPND'],
                _latest_card(derived['FED_CURRENT_BALANCE'], '联邦经常性收支差额', '十亿美元',
                             'FGRECPT', 'FGRECPT(t) - FGEXPND(t)，季调年率'),
                raw_cards['FYFSD'], raw_cards['GFDEBTN'], raw_cards['GFDEGDQ188S'],
                raw_cards['A091RC1Q027SBEA'],
            ]},
            {**GROUP_META['financial'], 'code': 'financial', 'cards': [
                raw_cards['FEDFUNDS'], raw_cards['SOFR'], raw_cards['DPRIME'],
                raw_cards['DGS3MO'], raw_cards['DGS2'], raw_cards['DGS10'], raw_cards['DGS30'],
                raw_cards['T10Y2Y'], raw_cards['T10YIE'], raw_cards['MORTGAGE30US'],
            ]},
        ]
    return {
        'data_status': 'official' if cov.get('records') else 'missing',
        'source_name': SOURCE_NAME, 'coverage': cov,
        'cards': [card for group in groups for card in group['cards']],
        'groups': groups, 'series': series, 'indicator_coverage': indicator_coverage,
        'warnings': [] if cov.get('records') else ['尚无数据；未生成 mock。'],
        'notes': ['FRED 免 key CSV 为发布通道；本源包括 BLS、劳工部 ETA、BEA、财政部、OMB、美联储、人口普查局与 Freddie Mac。',
                  '原始序列逐条标 official；同比、月增与 GDP 环比年化只在响应中生成并标 derived。',
                  '联邦经常性收支是 BEA NIPA 季调年率；财政年度赤字是财政部/OMB 年度口径，两者不可混用。',
                  '不同指标发布日期不同；卡片逐项显示期数，不把尚未发布的月份补齐。'],
    }
