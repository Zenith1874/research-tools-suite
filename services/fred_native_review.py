"""Validate immutable public FRED CSV downloads and their visible source metadata."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit,parse_qs

from services.us_macro_service import SERIES,parse_fred_csv

METADATA={s[0]:dict(zip(('code','name','unit','frequency','origin','group'),s)) for s in SERIES}


def fred_unit_matches(code,expected,text):
    unit=re.sub(r'\s+',' ',text or '').casefold().split(',')[0].strip()
    if expected in ('%','百分点'):return 'percent' in unit or (code in ('JTSHIR','JTSJOR','JTSQUR') and unit=='rate')
    if expected=='千人':return 'thousand' in unit and 'dollar' not in unit and 'unit' not in unit
    if expected=='人':return unit=='number'
    if expected=='千套':return 'thousand' in unit and ('unit' in unit or code=='HSN1F')
    if expected=='十亿美元':
        if code in ('GDPC1','GPDIC1','PCEC96','DSPIC96') and 'chained 2017' not in unit:return False
        return 'billion' in unit and 'dollar' in unit
    if expected=='百万美元':return 'million' in unit and 'dollar' in unit
    if expected=='美元/小时':return 'dollars per hour' in unit
    if expected=='美元/桶':return 'dollars per barrel' in unit
    if expected=='小时':return unit=='hours'
    if expected=='美元':return 'dollar' in unit and not any(s in unit for s in ('thousand','million','billion'))
    if expected=='0/1':return bool(re.search(r'\+?1 or 0|0 or 1',unit))
    if expected.startswith('指数'):return 'index' in unit and ('2006' in unit if '2006' in expected else '2010' in unit if code=='QUSR628BIS' else True)
    return False


def validate_fred_native_source(receipt,content,meta):
    code=meta['code'];url=urlsplit(receipt['source_url']);query=parse_qs(url.query)
    if (receipt['series_code']!=code or url.scheme!='https' or url.hostname!='fred.stlouisfed.org'
            or url.path!='/graph/fredgraph.csv' or query.get('id')!=[code]
            or (query.get('fml') is not None and query['fml']!=['a'])
            or (query.get('transformation') is not None and query['transformation']!=['lin'])):
        raise ValueError('Source is not this raw single FRED series.')
    if receipt.get('certificate_or_proxy_override') is not False or receipt.get('account_login_used') is not False:
        raise ValueError('Only the normal public-source capture is accepted.')
    if receipt.get('access_mode') not in ('native_public_fred_csv_endpoint','public_native_browser_download'):
        raise ValueError('Unknown source-capture method.')
    if len(content)!=receipt['bytes'] or hashlib.sha256(content).hexdigest()!=receipt['raw_sha256']:
        raise ValueError('Original CSV bytes changed or are incomplete.')
    frequency=receipt.get('frequency_excerpt') or (query.get('fq') or [''])[0]
    if not frequency.casefold().startswith(meta['frequency']):raise ValueError('Original native frequency does not match the series definition.')
    if not fred_unit_matches(code,meta['unit'],receipt.get('units_excerpt')):raise ValueError('Original unit does not match the registered unit.')
    rows=parse_fred_csv(content.decode('utf-8-sig'),code)
    if not rows:raise ValueError('No finite observed values in the source.')
    return rows


def load_fred_native_archive(directory):
    root=Path(directory).resolve();sources={}
    for path in sorted(root.rglob('*.receipt.json')):
        receipt=json.loads(path.read_text(encoding='utf-8'));code=receipt.get('series_code')
        if code not in METADATA:raise ValueError('An unregistered series is not part of this refresh.')
        if code in sources:raise ValueError('More than one completed source per code; review vintages explicitly.')
        if receipt['raw_path']!=code+'.csv':raise ValueError('Unexpected source filename.')
        raw=(path.parent/receipt['raw_path']).resolve()
        if not raw.is_relative_to(root):raise ValueError('Original escaped source run.')
        content=raw.read_bytes();rows=validate_fred_native_source(receipt,content,METADATA[code])
        receipt.update(receipt_ref=path.relative_to(root).as_posix(),source_run=root.name)
        sources[code]={'receipt':receipt,'rows':rows,'csv_path':raw,'receipt_path':path}
    if set(sources)!=set(METADATA):raise ValueError('All68 registered sources must be complete; missing='+','.join(sorted(set(METADATA)-set(sources))))
    return sources
