"""Province-level annual GDP release parsing without city/province substitutions."""
import math
import json
import hashlib
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from services.regional_fiscal_service import CN_PROVINCES

ROOT = Path(__file__).resolve().parents[1]


def verify_snapshot_file_integrity(path):
    """Qualified immutable snapshots must match their filename's digest prefix."""
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    match = re.fullmatch(r'20\d{2}-([a-f0-9]{12})\.json', path.name)
    if match and not digest.startswith(match[1]):
        raise ValueError('Selected snapshot filename digest does not match its actual bytes.')
    return digest


def validate_reviewed_province_snapshot(snapshot):
    """Validate all identities, grains, units, statuses and source links before any write."""
    if snapshot.get('schema_version') != 1 or snapshot.get('review_status') != 'source_values_reviewed':
        raise ValueError('Only a source-value-reviewed snapshot is accepted.')
    year = str(snapshot['statistical_year'])
    if not re.fullmatch(r'20\d{2}', year):
        raise ValueError('Annual statistical year is required.')
    sources = {s['source_id']: s for s in snapshot['sources']}
    if len(sources) != len(snapshot['sources']):
        raise ValueError('Duplicate source identity.')
    keys = set()
    for row in snapshot['observations']:
        code, indicator = row['region_code'], row['indicator_code']
        if CN_PROVINCES.get(row['region_name']) != code or row['period'] != year:
            raise ValueError('Wrong province identity or annual statistical period.')
        if indicator not in ('nominal_gdp', 'real_growth') or row['unit'] != ('%' if indicator == 'real_growth' else '亿元'):
            raise ValueError('GDP level, growth and units must remain separate.')
        value = row['value']
        if type(value) not in (int, float) or not math.isfinite(value) or (indicator == 'nominal_gdp' and value <= 0):
            raise ValueError('Missing/invalid values are not observations.')
        if indicator == 'real_growth' and not -100 < value < 100:
            raise ValueError('Official annual GDP growth is outside the valid domain.')
        key = (code, indicator, year)
        if key in keys:
            raise ValueError('Duplicate observation grain.')
        keys.add(key)
        source = sources[row['source_id']]
        host = urlsplit(source['source_url'])
        if host.scheme != 'https' or not (host.hostname or '').endswith('.gov.cn') or host.username or host.password:
            raise ValueError('A verified public government source URL is required.')
        if source['region_code'] != code or source['region_name'] != row['region_name']:
            raise ValueError('Source and observation identify different provinces.')
        if row['data_status'] not in ('official_preliminary', 'official_relayed') or source['data_status'] != row['data_status']:
            raise ValueError('Preliminary/relayed classifications must be explicit.')
        if not source.get('access_type') or not source.get('excerpt') or not source.get('source_name'):
            raise ValueError('Source access scope and reviewed statement must be recoverable.')
    expected = {(code, indicator, year) for code in CN_PROVINCES.values() for indicator in ('nominal_gdp', 'real_growth')}
    if keys != expected or len(sources) != 31:
        raise ValueError('This reviewed annual snapshot must contain exactly 31 provinces and two GDP measures each.')
    return sources


def sync_reviewed_province_gdp(conn, snapshot_dir=None):
    """Idempotent official-source import; revisions preserve complete previous rows."""
    folder = Path(snapshot_dir) if snapshot_dir else ROOT / 'data/province_gdp_reviewed'
    result = {'inserted': 0, 'updated': 0, 'unchanged': 0, 'errors': [], 'snapshots': []}
    if not folder.exists():
        return result
    conn.execute('''CREATE TABLE IF NOT EXISTS gdp_province_revision_history (
        id INTEGER PRIMARY KEY, country_code TEXT NOT NULL, region_code TEXT NOT NULL,
        indicator_code TEXT NOT NULL, period TEXT NOT NULL, original_row_json TEXT NOT NULL,
        replacement_source_id TEXT NOT NULL, preserved_at TEXT NOT NULL)''')
    latest = {}
    for path in sorted(folder.glob('*.json')):
        try:
            snapshot = json.loads(path.read_text(encoding='utf-8'))
            validate_reviewed_province_snapshot(snapshot)
            year = snapshot['statistical_year']
            if year not in latest or snapshot['generated_at'] > latest[year][1]['generated_at']:
                latest[year] = (path, snapshot)
        except Exception as exc:
            result['errors'].append(f'{path.name}: {exc}')
    for path, snapshot in (latest[year] for year in sorted(latest)):
        changes = {'inserted': 0, 'updated': 0, 'unchanged': 0}
        try:
            verify_snapshot_file_integrity(path)
            sources = validate_reviewed_province_snapshot(snapshot)
            now = datetime.now().astimezone().isoformat()
            conn.execute('SAVEPOINT province_gdp_snapshot')
            for row in snapshot['observations']:
                source = sources[row['source_id']]
                notes = '年度公报/经济运行，统计期' + row['period']
                notes += ('；绝对额为现价GDP（亿元）' if row['indicator_code'] == 'nominal_gdp'
                          else '；官方按不变价格公布的实际增速（%），不由现价金额直除')
                notes += f"；access_type={source['access_type']}；source_id={source['source_id']}"
                notes += '；evidence_sha256=' + source.get('raw_sha256', source.get('excerpt_sha256', source.get('image_sha256', '')))
                if source.get('access_limit'):
                    notes += '；' + source['access_limit']
                if row['data_status'] == 'official_relayed':
                    notes += '；政府官网转述，尚未核验省局原始发布'
                notes += '；初步统计/核算口径，后续最终核实可能修订；不同版本不可机械相减。'
                fields = ('country_code','region_code','region_name','indicator_code','period','value','unit',
                          'data_status','source_name','source_url','parser_notes')
                new_values = ('CN', row['region_code'], row['region_name'], row['indicator_code'], row['period'],
                              row['value'], row['unit'], row['data_status'], source['source_name'], source['source_url'], notes)
                old = conn.execute('''SELECT * FROM gdp_region_observations WHERE country_code='CN'
                      AND region_code=? AND indicator_code=? AND period=?''',
                      (row['region_code'], row['indicator_code'], row['period'])).fetchone()
                if old is not None:
                    names = [c[1] for c in conn.execute('PRAGMA table_info(gdp_region_observations)')]
                    previous = dict(zip(names, old))
                    if tuple(previous[f] for f in fields) == new_values:
                        changes['unchanged'] += 1
                        continue
                    conn.execute('''INSERT INTO gdp_province_revision_history
                        (country_code,region_code,indicator_code,period,original_row_json,replacement_source_id,preserved_at)
                        VALUES (?,?,?,?,?,?,?)''', ('CN',row['region_code'],row['indicator_code'],row['period'],
                        json.dumps(previous,ensure_ascii=False),source['source_id'],now))
                    changes['updated'] += 1
                else:
                    changes['inserted'] += 1
                conn.execute('''INSERT INTO gdp_region_observations
                    (country_code,region_code,region_name,indicator_code,period,value,unit,data_status,source_name,source_url,parser_notes,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(country_code,region_code,indicator_code,period)
                    DO UPDATE SET region_name=excluded.region_name,value=excluded.value,unit=excluded.unit,
                        data_status=excluded.data_status,source_name=excluded.source_name,source_url=excluded.source_url,
                        parser_notes=excluded.parser_notes,updated_at=excluded.updated_at''', (*new_values,now))
            conn.execute('RELEASE province_gdp_snapshot')
            for key in changes:
                result[key] += changes[key]
            result['snapshots'].append({'file': path.name, 'year': snapshot['statistical_year'], 'provinces': len(sources)})
        except Exception as exc:
            if conn.in_transaction:
                try:
                    conn.execute('ROLLBACK TO province_gdp_snapshot')
                    conn.execute('RELEASE province_gdp_snapshot')
                except Exception:
                    pass
            result['errors'].append(f'{path.name}: {exc}')
    return result


def parse_province_gdp_release(html, province, year, title):
    """Read a declared annual GDP level and its official real growth, not a forecast."""
    if province not in CN_PROVINCES:
        raise ValueError('A known mainland province-level identity is required.')
    text = unicodedata.normalize('NFKC', BeautifulSoup(html, 'html.parser').get_text(' ', strip=True))
    compact = re.sub(r'\s+', '', text)
    compact = re.sub(r'\[[\d]+\]', '', compact)
    clean_title = re.sub(r'\s+', '', unicodedata.normalize('NFKC', title))
    explicit_gdp_year = re.search(re.escape(f'{year}年') + r'[^。；]{0,35}(?:地区)?生产总值', compact)
    if f'{year}年' not in compact or (str(year) not in clean_title and not explicit_gdp_year):
        raise ValueError('Statistical year must be confirmed by the source heading or explicit GDP statement.')
    if re.search(r'上半年|前三季度|[一二三四]季度|\d{1,2}月', clean_title):
        raise ValueError('A subannual release cannot supply an annual GDP point.')
    candidates = []
    pattern = re.compile(r'(?:地区)?生产总值(?:\(GDP\))?(?:为|达到|达|实现)?'
                         r'(?P<value>[\d,]+(?:\.[\d]+)?)(?P<unit>万亿元|亿元)')
    for match in pattern.finditer(compact):
        before = compact[max(0, match.start() - 65):match.start()]
        named_subjects = [(before.rfind(name), name) for name in CN_PROVINCES if name in before[-24:]]
        if named_subjects and max(named_subjects)[1] != province:
            continue
        clause_before = re.split(r'。|；|[!?！？]', before)[-1]
        if re.search(r'人均|全国|民营经济|都市圈|经济圈|目标|预算|预计|力争|计划', clause_before[-28:]):
            continue
        if not re.search(r'全年|全省|全区|全市|' + re.escape(province), before):
            continue
        # A explicitly named earlier-year comparison is not the current annual value.
        # Publication dates beside a bulletin heading are not statistical periods.
        years = re.findall(r'(20\d{2})年(?!\d+月)', clause_before[-28:])
        if years and int(years[-1]) != int(year):
            continue
        value = float(match['value'].replace(',', ''))
        if match['unit'] == '万亿元':
            value *= 10000
        if not math.isfinite(value) or value <= 0:
            continue
        after = compact[match.end():match.end() + 90]
        after = re.split(r'其中|分产业|第一产业|。|；', after, maxsplit=1)[0]
        growth = None if '分别' in after else re.search(r'(?:比上年|同比)?(?:增长|下降)([\d.]+)%', after)
        real_growth = None
        if growth:
            real_growth = float(growth[1]) * (-1 if '下降' in growth[0] else 1)
        candidates.append({'nominal_gdp': value, 'real_growth': real_growth,
                           'evidence': compact[max(0, match.start() - 35):match.end() + len(after)],
                           'raw_value': match['value'], 'raw_unit': match['unit']})
    if not candidates:
        raise ValueError('No unambiguous annual province GDP statement was found.')
    first = candidates[0]
    # The same announcement can quote smaller subregional GDP later. Preserve the
    # first full-province statement, not a sum or a guessed national allocation.
    rows = []
    for code in ('nominal_gdp', 'real_growth'):
        if first[code] is not None:
            rows.append({'region_code': CN_PROVINCES[province], 'region_name': province,
                         'indicator_code': code, 'period': str(year), 'value': first[code],
                         'unit': '%' if code == 'real_growth' else '亿元',
                         'evidence': first['evidence'], 'raw_value': first['raw_value'],
                         'raw_unit': first['raw_unit']})
    return rows
