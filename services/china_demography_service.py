# -*- coding: utf-8 -*-
"""中国人口与婚姻家庭年度快照。

该模块只同步仓库内已经核验过来源的年度 CSV，不在更新按钮中猜测或补齐
缺失值。出生人口使用 ``万人``，结婚/离婚使用官方 ``万对``；后者是夫妻
对数，不是人数，协议离婚和法院离婚的合计由 dashboard 层在两项同时存在
时派生。
"""
from __future__ import annotations

import csv
import math
import re
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from services.china_macro_service import (
    INDICATORS,
    connect,
    ensure_china_macro_tables,
)


SOURCE_TYPE = 'china_demography'
DATA_PATH = Path(__file__).resolve().parents[1] / 'data' / 'china_demography_annual_official.csv'
DEMOGRAPHY_CODES = (
    'CN_BIRTHS',
    'CN_MARRIAGES',
    'CN_DIVORCES_AGREEMENT',
    'CN_DIVORCES_COURT',
)
YEAR_PATTERN = re.compile(r'^(?:19|20)\d{2}$')
ALLOWED_DATA_STATUS = frozenset({
    'official', 'official_revised', 'official_reprinted', 'official_relayed',
})


def _invalid_row(row_number, message):
    raise ValueError(f'人口婚姻家庭快照第 {row_number} 行无效：{message}')


def _optional_value(raw, *names):
    """Read an optional provenance field while accepting the CSV aliases."""
    for name in names:
        value = (raw.get(name) or '').strip()
        if value:
            return value
    return None


def read_demography_rows(path=DATA_PATH, strict=True):
    """读取并校验年度快照。

    这是一个经核验的可复现快照，不应静默吞掉结构性错误。因此默认对
    无效值、单位、状态、URL 和重复键直接失败；``strict=False`` 只保留
    旧式的“计数后跳过”兼容行为，供需要宽松检查的调用方使用。
    ``release_date``/``retrieved_at`` 是可选的来源时间字段，空缺保持
    ``None``，不以本地同步时间冒充来源发布时间。
    """
    rows = []
    skipped = 0
    with Path(path).open('r', encoding='utf-8-sig', newline='') as handle:
        for row_number, raw in enumerate(csv.DictReader(handle), start=2):
            code = (raw.get('indicator_code') or '').strip()
            period = (raw.get('period') or '').strip()
            source_url = (raw.get('source_url') or '').strip()
            try:
                value = float(raw.get('value'))
            except (TypeError, ValueError):
                if strict:
                    _invalid_row(row_number, 'value 必须是有限数字')
                skipped += 1
                continue
            if code not in DEMOGRAPHY_CODES or code not in INDICATORS:
                if strict:
                    _invalid_row(row_number, f'不支持的 indicator_code={code!r}')
                skipped += 1
                continue
            if not YEAR_PATTERN.fullmatch(period):
                if strict:
                    _invalid_row(row_number, f'period 必须是四位年份，收到 {period!r}')
                skipped += 1
                continue
            if not math.isfinite(value):
                if strict:
                    _invalid_row(row_number, 'value 必须是有限数字')
                skipped += 1
                continue
            expected_unit = INDICATORS[code][1]
            raw_unit = (raw.get('unit') or '').strip()
            if raw_unit != expected_unit:
                if strict:
                    _invalid_row(row_number,
                                 f'{code} 的 unit 应为 {expected_unit!r}，收到 {raw_unit!r}')
                skipped += 1
                continue
            status = (raw.get('data_status') or '').strip()
            if status not in ALLOWED_DATA_STATUS:
                if strict:
                    _invalid_row(row_number, f'不支持的 data_status={status!r}')
                skipped += 1
                continue
            parsed_url = urlparse(source_url)
            if parsed_url.scheme not in {'http', 'https'} or not parsed_url.netloc:
                if strict:
                    _invalid_row(row_number, f'source_url 必须是 http(s) URL，收到 {source_url!r}')
                skipped += 1
                continue
            source_name = (raw.get('source_name') or '').strip()
            source_title = (raw.get('source_title') or '').strip()
            if not source_name or not source_title:
                if strict:
                    _invalid_row(row_number, 'source_name 和 source_title 不能为空')
                skipped += 1
                continue
            key = (code, period)
            if any(existing['indicator_code'] == key[0] and
                   existing['period'] == key[1] for existing in rows):
                if strict:
                    _invalid_row(row_number, f'重复观测键 {code}/{period}')
                skipped += 1
                continue
            release_date = _optional_value(raw, 'release_date', 'source_release_date')
            retrieved_at = _optional_value(raw, 'retrieved_at', 'source_retrieved_at')
            rows.append({
                'indicator_code': code,
                'period': period,
                'value': value,
                'unit': raw_unit,
                'data_status': status,
                'source_name': source_name,
                'source_url': source_url,
                'source_title': source_title,
                'parser_notes': (raw.get('parser_notes') or '').strip(),
                'release_date': release_date,
                'retrieved_at': retrieved_at,
                'release_date_not_provided': int(release_date is None),
                'release_date_reason': (
                    None if release_date else 'CSV 未提供逐行来源发布日期'),
            })
    return rows, skipped


def sync_china_demography(conn, path=DATA_PATH, sync_at=None):
    """将 CSV 幂等写入统一 ``china_macro_observations`` 表。

    ``updated_at`` 表示本地记录真正发生变化的时间，而不是每次点击同步
    按钮的时间；这样页面可以区分本地快照同步时间和来源自身的发布时间。
    """
    rows, skipped = read_demography_rows(path)
    now = sync_at.isoformat() if isinstance(sync_at, datetime) else (
        str(sync_at) if sync_at is not None else datetime.now().isoformat())
    existing = {
        (row['indicator_code'], row['period']): dict(row)
        for row in conn.execute('''SELECT indicator_code,indicator_name,period,value,unit,frequency,
                                          data_status,source_name,source_type,source_url,
                                          source_title,parser_notes,formula,updated_at,
                                          release_date,retrieved_at,release_date_not_provided,
                                          release_date_reason
                                   FROM china_macro_observations
                                   WHERE indicator_code IN (?,?,?,?)''', DEMOGRAPHY_CODES)
    }
    upserted = 0
    unchanged = 0
    for raw in rows:
        code = raw['indicator_code']
        name, unit, frequency = INDICATORS[code]
        key = (code, raw['period'])
        previous = existing.get(key)
        fields = {
            'indicator_name': name,
            'value': raw['value'],
            'unit': unit,
            'frequency': frequency,
            'data_status': raw['data_status'],
            'source_name': raw['source_name'],
            'source_type': SOURCE_TYPE,
            'source_url': raw['source_url'],
            'source_title': raw['source_title'],
            'parser_notes': raw['parser_notes'],
            'formula': None,
            'release_date': raw['release_date'],
            'retrieved_at': raw['retrieved_at'],
            'release_date_not_provided': raw['release_date_not_provided'],
            'release_date_reason': raw['release_date_reason'],
        }
        changed = previous is None or any(previous.get(field) != value
                                          for field, value in fields.items())
        if previous is None:
            conn.execute('''INSERT INTO china_macro_observations (
            indicator_code,indicator_name,period,value,unit,frequency,data_status,
            source_name,source_type,source_url,source_title,parser_notes,formula,
            updated_at,release_date,retrieved_at,release_date_not_provided,release_date_reason
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (code, fields['indicator_name'], raw['period'], fields['value'],
                 fields['unit'], fields['frequency'], fields['data_status'],
                 fields['source_name'], fields['source_type'], fields['source_url'],
                 fields['source_title'], fields['parser_notes'], fields['formula'], now,
                 fields['release_date'], fields['retrieved_at'],
                 fields['release_date_not_provided'], fields['release_date_reason']))
            upserted += 1
        elif changed:
            conn.execute('''UPDATE china_macro_observations SET
                indicator_name=?,value=?,unit=?,frequency=?,data_status=?,source_name=?,
                source_type=?,source_url=?,source_title=?,parser_notes=?,formula=?,
                updated_at=?,release_date=?,retrieved_at=?,release_date_not_provided=?,
                release_date_reason=?
                WHERE indicator_code=? AND period=?''',
                (fields['indicator_name'], fields['value'], fields['unit'],
                 fields['frequency'], fields['data_status'], fields['source_name'],
                 fields['source_type'], fields['source_url'], fields['source_title'],
                 fields['parser_notes'], fields['formula'], now, fields['release_date'],
                 fields['retrieved_at'], fields['release_date_not_provided'],
                 fields['release_date_reason'], code, raw['period']))
            upserted += 1
        else:
            unchanged += 1
    conn.commit()
    return {
        'success': True,
        'records_upserted': upserted,
        'records_changed': upserted,
        'records_unchanged': unchanged,
        'rows_read': len(rows),
        'rows_skipped': skipped,
        'sync_at': now,
        'source_path': str(Path(path)),
    }


def update_china_demography(db_path, path=DATA_PATH):
    """本地年度快照更新入口，保持与其它宏观更新器相同的返回契约。"""
    with closing(connect(db_path)) as conn:
        ensure_china_macro_tables(conn)
        return sync_china_demography(conn, path=path)
