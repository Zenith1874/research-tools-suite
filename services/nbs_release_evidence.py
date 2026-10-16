"""Immutable local evidence for public NBS release ingestion, independent of data parsers."""
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from bs4 import BeautifulSoup

RAW_ROOT=Path(__file__).resolve().parents[1]/'data'/'china_macro_raw'/'nbs'
MAX_BYTES=16*1024*1024
CAPTURE_VERSION='nbs-release-evidence-v1'
CAPTURE_CODE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def nbs_https_url(url):
    """Upgrade an existing official HTTP path; never guess an article or change hosts."""
    parts=urlsplit(url)
    if (parts.hostname!='www.stats.gov.cn' or parts.username or parts.password or
            parts.scheme not in ('http','https') or parts.query or parts.fragment or
            parts.port not in (None,80 if parts.scheme=='http' else 443) or
            not parts.path.lower().endswith(('.html','.htm'))):
        raise ValueError('Use an exact public NBS article URL without credentials or parameters.')
    return urlunsplit(('https','www.stats.gov.cn',parts.path,'',''))


def nbs_release_dates(soup, require_original=False):
    """Publication, creation-only and unresolved metadata are different evidence roles."""
    dates=set()
    for node in soup.select('.detail-title-des'):
        dates.update(re.findall(r'\b(20\d{2}/\d{2}/\d{2})\s+\d{2}:\d{2}',node.get_text(' ',strip=True)))
    for node in soup.find_all('meta'):
        if str(node.get('name') or '').lower()=='pubdate':
            match=re.match(r'(20\d{2}[/-]\d{2}[/-]\d{2})',node.get('content') or '')
            if match:dates.add(match[1].replace('-','/'))
    text=re.sub(r'\s+','',unicodedata.normalize('NFKC',soup.get_text(' ',strip=True)))
    for match in re.finditer(r'[（(](20\d{2})年(\d{1,2})月(\d{1,2})日[）)]中华人民共和国国家统计局',text):
        dates.add(datetime(*map(int,match.groups())).strftime('%Y/%m/%d'))
    created=re.search(r'成文日期(20\d{2})年(\d{1,2})月(\d{1,2})日',text)
    created=datetime(*map(int,created.groups())).strftime('%Y-%m-%d') if created else None
    if len(dates)>1:
        if require_original:raise ValueError('Conflicting explicit publication dates remain unresolved.')
        return {'release_date':None,'source_page_created_date':created,'release_date_not_provided':0,
                'release_date_reason':'原文日期字段冲突，发布日期待核对；不从URL推断。'}
    published=datetime.strptime(next(iter(dates)),'%Y/%m/%d').strftime('%Y-%m-%d') if dates else None
    if not published and not created and require_original:
        raise ValueError('No explicit original publication or creation metadata; do not use the URL date.')
    return {'release_date':published,'source_page_created_date':created,
            'release_date_not_provided':int(published is None and created is not None),
            'release_date_reason':None if published else
            '该信息公开页只标成文日期，未明确提供发布日期；不以成文日或迁移URL冒充发布日期。' if created else
            '未解析到明确发布日期，尚不能判断是否未披露；不从URL推断。'}


def nbs_reported_month(soup,kind):
    """Read a literal dated price-table caption, never a migrated archive path."""
    family={'cpi':'居民消费价格','ppi':'工业生产者价格'}.get(kind)
    if not family:return None
    text=re.sub(r'\s+','',soup.get_text(' ',strip=True))
    dates={(year,int(month)) for year,month in re.findall(
        r'(20\d{2})年(\d{1,2})月份?'+family+r'主要数据',text)}
    if len(dates)>1:raise ValueError('Conflicting explicitly reported monthly table periods.')
    if not dates:return None
    year,month=next(iter(dates))
    if not 1<=month<=12:raise ValueError('Invalid reported table month.')
    return f'{year}-{month:02d}'


def archive_nbs_release(content, source_url, *, original_url, kind, period_hint, title,
                        parser_version, parser_sha256, root=None, access_mode='http_response',
                        source_retrieved_at=None, replay_parent_ref=None, http_status=200):
    """Publish evidence only after raw bytes and an immutable receipt both exist."""
    if not isinstance(content,bytes) or not content or len(content)>MAX_BYTES:
        raise ValueError('Archive requires nonempty original bytes within the16-MB release limit.')
    if http_status!=200:
        raise ValueError('Only a complete HTTP200 response can become an official release capture.')
    if access_mode not in ('http_response','archived_response_replay'):
        raise ValueError('Capture mode must distinguish a live response from an archived replay.')
    if access_mode=='archived_response_replay':
        if not source_retrieved_at or not replay_parent_ref:
            raise ValueError('Replay evidence needs its real original acquisition time and parent reference.')
        datetime.fromisoformat(source_retrieved_at)
    if urlsplit(source_url).scheme!='https':
        raise ValueError('A response downgraded to HTTP cannot be recorded as verified HTTPS.')
    source_url=nbs_https_url(source_url)
    digest=hashlib.sha256(content).hexdigest()
    now=datetime.now(timezone.utc)
    capture_id=now.strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid4().hex[:12]
    directory=Path(root or RAW_ROOT)/capture_id
    directory.mkdir(parents=True,exist_ok=False)
    raw_name='response-'+digest[:16]+'.html'
    # Each capture has an exclusive directory; interrupted captures remain on
    # disk without a completed receipt and are never overwritten by another fetch.
    with (directory/raw_name).open('xb') as handle:handle.write(content)
    if hashlib.sha256((directory/raw_name).read_bytes()).hexdigest()!=digest:
        raise ValueError('Written release bytes failed readback verification.')
    soup=BeautifulSoup(content,'html.parser')
    timing=nbs_release_dates(soup)
    reported_period=nbs_reported_month(soup,kind)
    receipt={'schema_version':1,'capture_version':CAPTURE_VERSION,'capture_code_sha256':CAPTURE_CODE_SHA256,'capture_id':capture_id,
             'source_url':source_url,'original_requested_url':original_url,'kind':kind,
             'period_hint':period_hint,'source_title':title,'raw_path':raw_name,'bytes':len(content),
             'reported_period':reported_period,
             'http_status':http_status,
             'raw_sha256':digest,'retrieved_at':source_retrieved_at if access_mode=='archived_response_replay' else now.isoformat(),
             'captured_at':now.isoformat(),'access_mode':access_mode,'replay_parent_ref':replay_parent_ref,
             'parser_version':parser_version,
             'parser_code_sha256':parser_sha256,**timing}
    with (directory/'receipt.json').open('xb') as handle:
        handle.write((json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    return {**timing,'raw_sha256':digest,'retrieved_at':receipt['retrieved_at'],
            'raw_archive_ref':'nbs/'+capture_id+'/receipt.json','_archive_dir':str(directory),'access_mode':access_mode,
            'reported_period':reported_period}


def preserve_prior_observation(evidence, row):
    """Freeze an entire old observation in its governing capture before replacing it."""
    identity=hashlib.sha256((row['indicator_code']+'|'+row['period']).encode('utf-8')).hexdigest()[:20]
    content=(json.dumps(dict(row),ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
    target=Path(evidence['_archive_dir'])/('before-'+identity+'.json')
    if target.exists():
        if target.read_bytes()!=content:raise ValueError('A prior observation snapshot must not be overwritten.')
    else:
        with target.open('xb') as handle:handle.write(content)
