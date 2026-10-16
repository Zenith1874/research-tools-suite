# -*- coding: utf-8 -*-
"""美国宏观模块：就业、通胀、增长、财政、金融、住房与外贸官方序列。

数据源：圣路易斯联储 FRED 的免 key CSV 端点(2026-07 实测可用)
    https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>
数据本源分别为 BLS(UNRATE/JTSQUR)与美联储 H.15(FEDFUNDS/DGS10)，FRED 为官方镜像。

数据纪律：逐条 official + source_url(FRED series 页)；失败不清旧数据；缺失值('.')跳过。
"""
import csv
import io
import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import requests
from services.macro_data_quality_service import build_macro_data_quality

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
    ('JTSJOR', 'JOLTS 职位空缺率', '%', 'monthly', 'BLS JOLTS 经季调', 'labor'),
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
    ('USREC', 'NBER 衰退期标记', '0/1', 'monthly', 'NBER via FRED', 'growth'),
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
    ('DGS1MO', '1个月期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS3MO', '3个月期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS6MO', '6个月期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS1', '1年期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS2', '2年期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS3', '3年期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS5', '5年期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS7', '7年期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS10', '10年期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS20', '20年期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('DGS30', '30年期美债收益率', '%', 'daily', '美联储 H.15 市场日频', 'financial'),
    ('T10Y2Y', '10Y－2Y 国债期限利差', '百分点', 'daily', 'FRED 由美联储 H.15 序列计算', 'financial'),
    ('T10Y3M', '10Y－3M 国债期限利差', '百分点', 'daily', 'FRED 由美联储 H.15 序列计算', 'financial'),
    ('T10YIE', '10年期盈亏平衡通胀率', '%', 'daily', 'FRED 由名义与通胀保值国债计算', 'financial'),
    ('MORTGAGE30US', '30年期固定房贷利率', '%', 'weekly', 'Freddie Mac PMMS', 'financial'),
    ('WALCL', '美联储总资产', '百万美元', 'weekly', '美联储 H.4.1', 'financial'),
    ('M2SL', '美国 M2 货币供应', '十亿美元', 'monthly', '美联储 H.6 经季调', 'financial'),
    ('VIXCLS', 'VIX 波动率指数', '指数', 'daily', 'CBOE', 'financial'),
    ('DTWEXBGS', '广义美元指数', '指数(2006-01=100)', 'daily', '美联储 H.10 贸易加权', 'financial'),
    ('UMCSENT', '密歇根大学消费者信心指数', '指数', 'monthly', '密歇根大学消费者调查', 'growth'),
    ('QUSR628BIS', 'BIS 美国实际住宅价格指数（2010=100）', '指数', 'quarterly', 'BIS via FRED', 'financial'),
    ('PCEPI', 'PCE 总体价格指数', '指数', 'monthly', 'BEA PCE 经季调', 'inflation'),
    ('PCEC96', '实际个人消费支出', '十亿美元', 'monthly', 'BEA 链式美元，季调年率', 'growth'),
    ('DSPIC96', '实际可支配个人收入', '十亿美元', 'monthly', 'BEA 链式美元，季调年率', 'growth'),
    ('PSAVERT', '个人储蓄率', '%', 'monthly', 'BEA NIPA 经季调', 'growth'),
    ('GPDIC1', '实际私人国内总投资', '十亿美元', 'quarterly', 'BEA 链式美元，季调年率', 'growth'),
    ('CCSA', '持续申领失业救济人数', '人', 'weekly', '美国劳工部 ETA 经季调', 'labor'),
    ('AWHAETP', '私营非农平均每周工时', '小时', 'monthly', 'BLS CES 经季调', 'labor'),
    ('HOUST', '住房新开工', '千套', 'monthly', '美国人口普查局，季调年率', 'housing'),
    ('PERMIT', '住宅建筑许可', '千套', 'monthly', '美国人口普查局，季调年率', 'housing'),
    ('HSN1F', '新建独栋住宅销售', '千套', 'monthly', '美国人口普查局，季调年率', 'housing'),
    ('MSPUS', '新建住宅销售价格中位数', '美元', 'quarterly', '美国人口普查局/HUD，未季调', 'housing'),
    ('TOTBKCR', '商业银行总信贷', '十亿美元', 'weekly', '美联储 H.8 经季调', 'financial'),
    ('EXPGS', '货物与服务出口', '十亿美元', 'quarterly', 'BEA NIPA 现价，季调年率', 'external'),
    ('IMPGS', '货物与服务进口', '十亿美元', 'quarterly', 'BEA NIPA 现价，季调年率', 'external'),
    ('BOPGSTB', '货物与服务国际贸易差额', '百万美元', 'monthly', '美国人口普查局/BEA 经季调', 'external'),
    ('DCOILWTICO', 'WTI 原油现货价格', '美元/桶', 'daily', '美国能源信息署 EIA', 'external'),
    ('DCOILBRENTEU', 'Brent 原油现货价格', '美元/桶', 'daily', '美国能源信息署 EIA', 'external'),
]

GROUP_META = {
    'labor': {'title': '就业与劳动力市场', 'summary': '就业松紧、劳动供给与主动离职'},
    'inflation': {'title': '通胀', 'summary': '居民消费通胀与美联储重点关注的核心 PCE'},
    'growth': {'title': '增长与需求', 'summary': '实际 GDP、工业生产与消费需求'},
    'fiscal': {'title': '政府收支与债务', 'summary': '联邦收入、支出、赤字、公共债务与利息负担'},
    'financial': {'title': '利率与金融条件', 'summary': '政策利率、收益率曲线与住房融资成本'},
    'housing': {'title': '住房与建设', 'summary': '许可、开工与新房销售为季调年率；房价为新房中位数，不是二手房指数'},
    'external': {'title': '外贸与大宗商品', 'summary': '美国货物与服务贸易；月度贸易差额与季度国民账户口径分别展示'},
}

NOMINAL_TENORS = (
    ('DGS1MO','1M',1), ('DGS3MO','3M',3), ('DGS6MO','6M',6),
    ('DGS1','1Y',12), ('DGS2','2Y',24), ('DGS3','3Y',36),
    ('DGS5','5Y',60), ('DGS7','7Y',84), ('DGS10','10Y',120),
    ('DGS20','20Y',240), ('DGS30','30Y',360),
)


def build_yield_curve_snapshots(raw):
    """Preserve actual same-date yields before independent history downsampling."""
    dates={}
    for code, _, _ in NOMINAL_TENORS:
        for row in raw.get(code, []):
            if row.get('value') is not None:
                dates.setdefault(row['period'], {})[code]=row['value']
    return [{'period':period,'values':values} for period,values in sorted(dates.items())]


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
    if not header or len(header) != 2 or 'date' not in header[0].lower() or header[1].strip()!=code:
        raise ValueError(f'{code}: 非预期的 CSV 头 {header!r}')
    seen={}
    for line in reader:
        if len(line) < 2:
            continue
        d, v = line[0].strip(), line[1].strip()
        if not d or v in ('', '.'):
            continue
        try:
            value = float(v)
            datetime.strptime(d, '%Y-%m-%d')
        except ValueError:
            continue
        if not math.isfinite(value):continue
        if d in seen:
            if seen[d]!=value:raise ValueError(f'{code}: conflicting duplicate date {d}')
            continue
        seen[d]=value
        rows.append({'period': d, 'value': value})
    return rows


def upsert_fred_observations(conn, code, rows, source_receipt=None):
    """Write one verified series; keep exact old records on equality and preserve revisions.

    Does not commit the caller's outer transaction. No network access occurs here.
    A failed series rolls back its own attempted values and revision-history rows.
    """
    metadata=next((s for s in SERIES if s[0]==code),None)
    if metadata is None:raise ValueError('Unknown registered FRED series: '+str(code))
    _,name,unit,freq,origin,_=metadata
    previous={r['period']:dict(r) for r in conn.execute('SELECT * FROM us_macro_observations WHERE indicator_code=?',(code,))}
    stats={'inserted':0,'updated':0,'unchanged':0};seen=set();now=datetime.now().isoformat()
    notes=f'fredgraph.csv 官方原始序列；本源：{origin}'
    if source_receipt:
        notes+='; raw_sha256='+source_receipt['raw_sha256']+'; source_retrieved_at='+source_receipt['retrieved_at']+'; archive_ref='+source_receipt['receipt_ref']
        if source_receipt.get('units_excerpt'):notes+='; source_units='+source_receipt['units_excerpt']
    conn.execute('SAVEPOINT us_macro_source')
    try:
        for row in rows:
            period=row['period'];value=row['value']
            datetime.strptime(period,'%Y-%m-%d')
            if period in seen or type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Duplicate date or nonfinite FRED amount.')
            seen.add(period);old=previous.get(period)
            if old and old['value']==value and old['unit']==unit and old['frequency']==freq and old['data_status'] in ('official','official_final'):
                stats['unchanged']+=1;continue
            if old:
                conn.execute('''CREATE TABLE IF NOT EXISTS us_macro_revision_history (
                    id INTEGER PRIMARY KEY,indicator_code TEXT,period TEXT,original_row_json TEXT,
                    replacement_value REAL,replacement_source_sha256 TEXT,replacement_archive_ref TEXT,preserved_at TEXT)''')
                conn.execute('INSERT INTO us_macro_revision_history VALUES(NULL,?,?,?,?,?,?,?)',
                    (code,period,json.dumps(old,ensure_ascii=False),value,
                     source_receipt.get('raw_sha256') if source_receipt else None,
                     source_receipt.get('receipt_ref') if source_receipt else None,now))
            conn.execute('''INSERT INTO us_macro_observations (
                indicator_code,indicator_name,period,value,unit,frequency,data_status,
                source_name,source_type,source_url,source_title,parser_notes,formula,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(indicator_code,period) DO UPDATE SET
                value=excluded.value,indicator_name=excluded.indicator_name,unit=excluded.unit,
                frequency=excluded.frequency,data_status=excluded.data_status,source_name=excluded.source_name,
                source_type=excluded.source_type,source_url=excluded.source_url,source_title=excluded.source_title,
                parser_notes=excluded.parser_notes,formula=excluded.formula,updated_at=excluded.updated_at''',
                (code,name,period,value,unit,freq,'official',SOURCE_NAME,SOURCE_TYPE,
                 f'https://fred.stlouisfed.org/series/{code}',f'FRED {code}',notes,None,now))
            stats['updated' if old else 'inserted']+=1
        conn.execute('RELEASE us_macro_source')
    except Exception:
        conn.execute('ROLLBACK TO us_macro_source');conn.execute('RELEASE us_macro_source');raise
    return stats


def fetch_series(code):
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}'
    r = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return parse_fred_csv(r.text, code)


def update_us_macro(db_path, codes=None, archive_dir=None):
    """全量拉取(FRED CSV 本身就是整段历史，幂等 upsert)。单系列失败不影响其他。"""
    started = datetime.now().isoformat()
    errors, upserted = [], 0
    known = {row[0] for row in SERIES}
    if codes is not None and set(codes) - known:
        raise ValueError(f'未知FRED系列: {sorted(set(codes) - known)}')
    with closing(connect(db_path)) as conn:
        ensure_us_macro_tables(conn)
        now = datetime.now().isoformat()
        for code, name, unit, freq, origin, group in SERIES:
            if codes is not None and code not in codes:
                continue
            try:
                if archive_dir:
                    response = requests.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}',
                                            headers=UA, timeout=HTTP_TIMEOUT)
                    response.raise_for_status()
                    directory = Path(archive_dir)
                    directory.mkdir(parents=True, exist_ok=True)
                    with (directory / f'{code}.csv').open('xb') as handle:
                        handle.write(response.content)
                    rows = parse_fred_csv(response.text, code)
                else:
                    rows = fetch_series(code)
            except Exception as exc:
                errors.append(f'{code}: {exc}')
                continue
            try:
                if not rows:raise ValueError('Source returned no finite observations.')
                stats=upsert_fred_observations(conn,code,rows)
                upserted+=stats['inserted']+stats['updated']
                conn.commit()  # Never hold a write transaction while fetching the next source.
            except Exception as exc:
                conn.rollback();errors.append(f'{code}: persist: {exc}')
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


def _calendar_key(period, frequency):
    match = re.match(r'^(\d{4})-(\d{2})', str(period or ''))
    if not match:
        return None
    year, month = map(int, match.groups())
    if not 1 <= month <= 12:
        return None
    return year * 4 + (month - 1) // 3 if frequency == 'quarterly' else year * 12 + month - 1


def derive_change_series(rows, lag, annualize=False, frequency='monthly'):
    """Create transparent derived changes without writing them to official rows."""
    result = []
    if annualize:
        frequency = 'quarterly'
    by_period = {_calendar_key(row['period'], frequency): row for row in rows}
    for current in rows:
        key = _calendar_key(current['period'], frequency)
        previous = by_period.get(key - lag) if key is not None else None
        if previous is None:
            continue
        if previous['value'] in (None, 0) or current['value'] is None:
            continue
        if not all(math.isfinite(float(row['value'])) for row in (previous, current)):
            continue
        ratio = current['value'] / previous['value']
        value = ((ratio ** 4 - 1) if annualize else (ratio - 1)) * 100
        result.append({'period': current['period'], 'value': round(value, 4),
                       'data_status': 'derived'})
    return result


def derive_difference_series(rows, lag=1, frequency='monthly'):
    result = []
    by_period = {_calendar_key(row['period'], frequency): row for row in rows}
    for current in rows:
        key = _calendar_key(current['period'], frequency)
        previous = by_period.get(key - lag) if key is not None else None
        if previous is None:
            continue
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
                'frequency': freq,
                'earliest': raw[code][0]['period'] if raw[code] else None,
                'latest': raw[code][-1]['period'] if raw[code] else None,
                'records': len(raw[code]),
            }

        derived = {
            'PAYEMS_MOM': derive_difference_series(raw['PAYEMS']),
            'CPI_YOY': derive_change_series(raw['CPIAUCSL'], 12),
            'CORE_CPI_YOY': derive_change_series(raw['CPILFESL'], 12),
            'CORE_PCE_YOY': derive_change_series(raw['PCEPILFE'], 12),
            'PCE_YOY': derive_change_series(raw['PCEPI'], 12),
            'REAL_PCE_YOY': derive_change_series(raw['PCEC96'], 12),
            'REAL_DISPOSABLE_INCOME_YOY': derive_change_series(raw['DSPIC96'], 12),
            'REAL_PRIVATE_INVESTMENT_YOY': derive_change_series(raw['GPDIC1'], 4, frequency='quarterly'),
            'REAL_GDP_QOQ_AR': derive_change_series(raw['GDPC1'], 1, annualize=True, frequency='quarterly'),
            'INDPRO_YOY': derive_change_series(raw['INDPRO'], 12),
            'RETAIL_YOY': derive_change_series(raw['RSAFS'], 12),
            'AHE_YOY': derive_change_series(raw['CES0500000003'], 12),
            'PRODUCTIVITY_YOY': derive_change_series(raw['OPHNFB'], 4, frequency='quarterly'),
            'FED_CURRENT_BALANCE': derive_aligned_spread(raw['FGRECPT'], raw['FGEXPND']),
        }
        series.update({key: _downsample(value) for key, value in derived.items()})
        yield_snapshots=build_yield_curve_snapshots(raw)
        for code, values in derived.items():
            indicator_coverage[code] = {
                'frequency': 'quarterly' if code in ('REAL_GDP_QOQ_AR', 'PRODUCTIVITY_YOY', 'REAL_PRIVATE_INVESTMENT_YOY', 'FED_CURRENT_BALANCE') else 'monthly',
                'earliest': values[0]['period'] if values else None,
                'latest': values[-1]['period'] if values else None,
                'records': len(values),
            }

        groups = [
            {**GROUP_META['labor'], 'code': 'labor', 'cards': [
                raw_cards['UNRATE'], raw_cards['U6RATE'], raw_cards['CIVPART'], raw_cards['EMRATIO'],
                _latest_card(derived['PAYEMS_MOM'], '非农就业月增', '千人', 'PAYEMS',
                             'PAYEMS(t) - PAYEMS(t-1)'),
                raw_cards['ICSA'], raw_cards['JTSJOL'],
                raw_cards['CCSA'], raw_cards['AWHAETP'],
                _latest_card(derived['AHE_YOY'], '私营非农平均时薪同比', '%', 'CES0500000003',
                             '(AHE(t) / AHE(t-12) - 1) × 100'),
            ]},
            {**GROUP_META['inflation'], 'code': 'inflation', 'cards': [
                _latest_card(derived['PCE_YOY'], 'PCE总体同比', '%', 'PCEPI', '(PCEPI(t)/PCEPI(t-12)-1)×100'),
                _latest_card(derived['CPI_YOY'], 'CPI 同比', '%', 'CPIAUCSL',
                             '(CPI(t) / CPI(t-12) - 1) × 100'),
                _latest_card(derived['CORE_CPI_YOY'], '核心 CPI 同比', '%', 'CPILFESL',
                             '(Core CPI(t) / Core CPI(t-12) - 1) × 100'),
                _latest_card(derived['CORE_PCE_YOY'], '核心 PCE 同比', '%', 'PCEPILFE',
                             '(Core PCE(t) / Core PCE(t-12) - 1) × 100'),
            ]},
            {**GROUP_META['growth'], 'code': 'growth', 'cards': [
                _latest_card(derived['REAL_PCE_YOY'], '实际个人消费同比', '%', 'PCEC96', '(PCEC96(t)/PCEC96(t-12)-1)×100'),
                _latest_card(derived['REAL_DISPOSABLE_INCOME_YOY'], '实际可支配收入同比', '%', 'DSPIC96', '(DSPIC96(t)/DSPIC96(t-12)-1)×100'),
                raw_cards['PSAVERT'],
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
                raw_cards['TOTBKCR'], raw_cards['WALCL'], raw_cards['M2SL'],
            ]},
            {**GROUP_META['housing'], 'code': 'housing', 'cards': [
                raw_cards['HOUST'], raw_cards['PERMIT'], raw_cards['HSN1F'], raw_cards['MSPUS']]},
            {**GROUP_META['external'], 'code': 'external', 'cards': [
                raw_cards['EXPGS'], raw_cards['IMPGS'], raw_cards['BOPGSTB'],
                raw_cards['DCOILWTICO'], raw_cards['DCOILBRENTEU']]},
        ]
    return {
        'data_status': 'official' if cov.get('records') else 'missing',
        'source_name': SOURCE_NAME, 'coverage': cov,
        'cards': [card for group in groups for card in group['cards']],
        'groups': groups, 'series': series, 'indicator_coverage': indicator_coverage,
        'yield_curve_snapshots': yield_snapshots,
        'yield_curve_tenors': [{'code':code,'label':label,'months':months} for code,label,months in NOMINAL_TENORS],
        'data_quality': build_macro_data_quality(db_path, 'us'),
        'warnings': [] if cov.get('records') else ['尚无数据；未生成 mock。'],
        'notes': ['FRED 免 key CSV 为发布通道；本源包括 BLS、劳工部 ETA、BEA、财政部、OMB、美联储、人口普查局与 Freddie Mac。',
                  '原始序列逐条标 official；同比、月增与 GDP 环比年化只在响应中生成并标 derived。',
                  '联邦经常性收支是 BEA NIPA 季调年率；财政年度赤字是财政部/OMB 年度口径，两者不可混用。',
                  '不同指标发布日期不同；卡片逐项显示期数，不把尚未发布的月份补齐。'],
    }
