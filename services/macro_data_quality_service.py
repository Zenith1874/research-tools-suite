"""Read-only macro catalog coverage: missing series and calendar gaps, not scores."""
import re
import sqlite3
from contextlib import closing
from datetime import datetime


def calendar_coverage(periods, frequency, merge_jan_feb=False):
    """Check gaps only inside the observed span; never invent release history."""
    periods = sorted(set(str(period) for period in periods if period))
    if frequency not in ('monthly', 'quarterly', 'annual'):
        return {'internal_gap_count': None, 'missing_periods': [],
                'gap_note': '日/周频包含节假日及发布安排，不按所有日历日判缺失。'}
    keys = set()
    for period in periods:
        match = re.match(r'^(\d{4})(?:-(\d{2}))?', period)
        if not match:
            continue
        year, month = int(match[1]), int(match[2] or 1)
        if not 1 <= month <= 12:
            continue
        keys.add(year if frequency == 'annual' else (
            year * 4 + (month - 1) // 3 if frequency == 'quarterly' else year * 12 + month - 1))
    if not keys:
        return {'internal_gap_count': 0, 'missing_periods': [], 'gap_note': '没有可核对的实际观测区间。'}
    missing = [key for key in range(min(keys), max(keys) + 1) if key not in keys
               and not (frequency == 'monthly' and merge_jan_feb and key % 12 == 0)]
    def label(key):
        if frequency == 'annual':
            return str(key)
        if frequency == 'quarterly':
            return f'{key // 4}-Q{key % 4 + 1}'
        return f'{key // 12}-{key % 12 + 1:02d}'
    return {'internal_gap_count': len(missing), 'missing_periods': [label(key) for key in missing[:24]],
            'gap_note': '只核对首个实际观测到最新实际观测，不表示更早历史完整；最多列出24个缺期。'}


def build_macro_data_quality(db_path, country='china', as_of=None):
    """Summarize existing observation tables without creating or changing them."""
    if country == 'china':
        from services.china_macro_service import INDICATORS
        from services.china_external_service import EXTERNAL_INDICATORS
        registry = {**INDICATORS, **EXTERNAL_INDICATORS}
        table = 'china_macro_observations'
    elif country == 'us':
        from services.us_macro_service import SERIES
        registry = {row[0]: row[1:4] for row in SERIES}
        table = 'us_macro_observations'
    else:
        raise ValueError('country must be china or us')
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        rows = conn.execute(f'''SELECT indicator_code,period,value,source_url,data_status
                                FROM {table} ORDER BY indicator_code,period''').fetchall() if exists else []
    grouped = {}
    for row in rows:
        grouped.setdefault(row['indicator_code'], []).append(row)
    quality = {}
    today = datetime.fromisoformat(str(as_of)).date() if as_of else datetime.now().date()
    for code, meta in registry.items():
        observed = grouped.get(code, [])
        periods = [row['period'] for row in observed if row['value'] is not None]
        merge = country == 'china' and code.startswith(('CN_FAI_', 'CN_IND_', 'CN_RETAIL_'))
        coverage = calendar_coverage(periods, meta[2], merge_jan_feb=merge)
        status = ('missing' if not periods else 'single_observation' if len(periods) == 1
                  else 'internal_gaps' if coverage['internal_gap_count'] else 'observed_span')
        age_days = None
        if periods:
            latest = max(periods)
            normalized = latest + ('-01-01' if len(latest) == 4 else '-01' if len(latest) == 7 else '')
            try:
                age_days = max(0, (today - datetime.fromisoformat(normalized).date()).days)
            except ValueError:
                pass
        lag_threshold = {'monthly': 100, 'quarterly': 240, 'annual': 1100,
                         'weekly': 35, 'daily': 14}.get(meta[2])
        quality[code] = {
            'code': code, 'name': meta[0], 'unit': meta[1], 'frequency': meta[2],
            'n_obs': len(periods), 'start_period': min(periods) if periods else None,
            'end_period': max(periods) if periods else None,
            'duplicate_periods': len(periods) - len(set(periods)),
            'missing_source_rows': sum(not row['source_url'] for row in observed),
            'invalidated_rows': sum(row['data_status'] == 'invalidated_source_value' for row in observed),
            'status': status, **coverage,
            'age_days_from_period_label': age_days,
            'needs_freshness_review': age_days is not None and lag_threshold is not None and age_days > lag_threshold,
        }
    return {
        'country': country, 'generated_at': datetime.now().astimezone().isoformat(),
        'registered_series': len(registry), 'series_with_data': sum(q['n_obs'] > 0 for q in quality.values()),
        'missing_series': [code for code, q in quality.items() if not q['n_obs']],
        'single_observation_series': [code for code, q in quality.items() if q['n_obs'] == 1],
        'series_with_internal_gaps': [code for code, q in quality.items() if q['internal_gap_count']],
        'freshness_review_series': [code for code, q in quality.items() if q['needs_freshness_review']],
        'indicators': quality,
        'notes': ['目录覆盖不等于整个宏观领域完整；只统计已注册序列。',
                  '1—2月合并累计不补1月；日周频不把休市日判成缺数据。',
                  '滞后提示按资料期标签与当前日期粗筛，不等于已证实官方发布了下一期；季度期初标签允许更长滞后。'],
    }
