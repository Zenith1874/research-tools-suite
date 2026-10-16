#!/usr/bin/env python3
"""Review archived supplemental fiscal PDFs and append to immutable annual snapshots."""
import argparse
import hashlib
import io
import json
import math
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader
import fitz

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.regional_fiscal_service import (
    CN_PROVINCES, parse_china_fiscal_pdf_pages, validate_reviewed_regional_fiscal_snapshot)
from scripts.review_province_fiscal_sources import write_snapshot
from services.provincial_issuer_visual_profiles import VISUAL_PROFILES
from services.provincial_fiscal_report_profiles import (
    JIANGSU_GAZETTE_PROFILES, PROVINCIAL_ANNEX_PROFILES, parse_hunan_final_report,
    parse_jiangsu_gazette_pages, parse_provincial_fiscal_annex_pages)
from services.provincial_fiscal_six_profiles import SIX_TEXT_PROFILES


def visual_transcript_digest(source):
    texts={str(n):d['text'] for n,d in source['visual_transcript_pages'].items()}
    return hashlib.sha256(json.dumps(texts,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def verified_visual_pages(content, source, directory, reader):
    """Bind labelled transcript excerpts to exact original pages and render bytes."""
    if source.get('profile') not in VISUAL_PROFILES or set(map(int,source['visual_transcript_pages']))!=set(source['reviewed_pages']):
        raise ValueError('Only the exact inspected raster profile and complete declared page set are accepted.')
    if visual_transcript_digest(source)!=source['transcript_sha256']:
        raise ValueError('The labelled visual transcript changed after review.')
    pages={}
    with fitz.open(stream=content,filetype='pdf') as document:
        for page in source['reviewed_pages']:
            allowed_text_pages=VISUAL_PROFILES[source['profile']].get('allow_text_layer_pages',set())
            if (reader.pages[page-1].extract_text() or '').strip() and page not in allowed_text_pages:
                raise ValueError('This profile describes an image-only original, not a text-layer parser.')
            proof=source['visual_transcript_pages'][str(page)]
            path=(directory/proof['render_path']).resolve()
            if not path.is_relative_to(directory.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=proof['render_sha256']:
                raise ValueError('Reviewed PDF page render changed or escaped its original run.')
            reproduced=document[page-1].get_pixmap(matrix=fitz.Matrix(proof['render_scale'],proof['render_scale'])).tobytes('png')
            if hashlib.sha256(reproduced).hexdigest()!=proof['render_sha256']:
                raise ValueError('The labelled transcript is not tied to the reproduced original page.')
            pages[page]=proof['text']
    return pages


def merge_new_observations(prior, additions):
    """Append new keys only; never revise or drop an old reviewed observation."""
    rows=list(prior)
    keys={(r['region_code'],r['indicator_code'],r['period']) for r in rows}
    for row in additions:
        key=(row['region_code'],row['indicator_code'],row['period'])
        if key in keys:
            raise ValueError('A supplement cannot replace an existing reviewed key: '+str(key))
        keys.add(key);rows.append(row)
    return rows


def verify_issuer_unit_overlap(source, parsed, conn):
    """Confirm the unlabelled fiscal-table scale against independent NBS history."""
    if source.get('profile') in VISUAL_PROFILES:return []  # These parsers require the printed亿元 heading.
    if source.get('profile')=='hubei_2026_fiscal_annex':return []  # The inspected table explicitly prints亿元.
    if source.get('source_class')!='government_issuer_filing':return []
    checks=source.get('unit_overlap_checks',[])
    required={(p,c) for p in ('2023','2024') for c in
              ('general_budget_revenue','general_budget_expenditure')}
    if len(checks)!=4 or {(c['period'],c['indicator_code']) for c in checks}!=required:
        raise ValueError('Four distinct historical fiscal unit/scope checks are required.')
    result=[]
    for check in checks:
        period=check['period'];code=check['indicator_code'];value=check['value']
        old=conn.execute('''SELECT value,unit,source_url FROM regional_fiscal_observations
            WHERE country_code='CN' AND government_scope='province_total' AND region_code=?
            AND indicator_code=? AND period=?''',(CN_PROVINCES[source['region_name']],code,period)).fetchone()
        if (old is None or old['unit']!='亿元' or not old['source_url'].startswith('https://www.stats.gov.cn/')
                or not math.isclose(old['value'],value,abs_tol=1e-6,rel_tol=0)
                or not math.isclose(parsed[period][code],value,abs_tol=1e-6,rel_tol=0)):
            raise ValueError('Historical NBS amount, unit or full-province scope does not corroborate the issuer table.')
        result.append({**check,'region_name':source['region_name'],
                       'matched_unit':old['unit'],'controlling_source':old['source_url']})
    return result


def review_documents(review, archives, conn):
    """Return reviewed rows and authority/unit evidence without modifying SQLite."""
    grouped={};provenance={};unit_checks=[]
    for source in review['documents']:
        directory,record=archives[source['id']]
        raw=(directory/record['raw_path']).resolve()
        if not raw.is_relative_to(directory.resolve()):
            raise ValueError('Archived source escaped its original run.')
        content=raw.read_bytes();digest=hashlib.sha256(content).hexdigest()
        if digest!=record['raw_sha256'] or digest!=source['raw_sha256'] or record['source_url']!=source['source_url']:
            raise ValueError('Reviewed source identity or bytes changed.')
        source_format=source.get('format','pdf')
        if source_format=='pdf':
            reader=PdfReader(io.BytesIO(content))
            if len(reader.pages)!=source['pdf_pages']:
                raise ValueError('Reviewed PDF page count changed.')
            pages=(verified_visual_pages(content,source,directory,reader) if source.get('visual_transcript_pages')
                   else {n:reader.pages[n-1].extract_text() for n in source['reviewed_pages']})
        elif source_format=='html' and source.get('profile')=='hunan_annual_final_report':
            reader=None
        else:
            raise ValueError('An explicitly reviewed document format and parser profile are required.')
        parsed={}
        for period,definition in source['periods'].items():
            if source_format=='html':
                rows=parse_hunan_final_report(content,source['region_name'],period,source['profile'])
            elif source['profile'] in JIANGSU_GAZETTE_PROFILES:
                rows=parse_jiangsu_gazette_pages(pages,source['region_name'],period,source['profile'])
            elif source['profile'] in PROVINCIAL_ANNEX_PROFILES:
                rows=parse_provincial_fiscal_annex_pages(pages,source['region_name'],period,source['profile'])
            else:
                rows=parse_china_fiscal_pdf_pages(pages,source['region_name'],period,source['profile'])
            values={r['indicator_code']:r['value'] for r in rows}
            expected=definition['expected_values']
            if set(values)!=set(expected) or any(not math.isclose(values[k],v,abs_tol=1e-6,rel_tol=0) for k,v in expected.items()):
                raise ValueError('Parsed fiscal amounts differ from the inspected original: '+period)
            selected=set(definition['import_codes'])
            if not selected or not selected.issubset(expected):
                raise ValueError('Import only a declared nonempty subset of inspected fields.')
            parsed[period]=values
            for row in rows:
                if row['indicator_code'] not in selected:continue
                row.update(source_name=source['source_name'],source_title=source['source_title'],
                    source_url=source['source_url']+('#page='+str(row['evidence_page']) if source_format=='pdf' else ''),
                    parser_notes='access_type='+source.get('source_class','archived_official_pdf')
                    +'; raw_sha256='+digest+'; statement='+row['evidence']+'; '+source['scope_notes'])
                if source.get('visual_transcript_pages'):
                    proof=source['visual_transcript_pages'][str(row['evidence_page'])]
                    row['parser_notes']+='; parse_mode=reviewed_visual_transcript; unit_evidence=explicit_source_heading; visual_transcript_sha256='+source['transcript_sha256']+'; render_sha256='+proof['render_sha256']
                if source.get('profile')=='hubei_2026_fiscal_annex':
                    row['parser_notes']+='; unit_evidence=explicit_source_heading'
                if source.get('profile') in SIX_TEXT_PROFILES:
                    row['parser_notes'] += ('; parse_mode=reviewed_text_layer; unit_evidence=explicit_source_heading; raw_unit='
                                            + row['raw_unit'] + ('; formula=source_amount/10000' if row['raw_unit']=='万元' else '; formula=source_amount'))
                grouped.setdefault(period,[]).append(row)
            provenance.setdefault(period,[]).append({
                'source_url':source['source_url'],'raw_sha256':digest,
                'raw_path':raw.relative_to(ROOT).as_posix(),
                'source_class':source.get('source_class','government_website'),
                'format':source_format,'reviewed_pages':source.get('reviewed_pages',[]),
                'pdf_pages':len(reader.pages) if reader is not None else None,
                'reviewed_sections':source.get('reviewed_sections',[]),
                'inspected_codes':sorted(expected),'import_codes':sorted(selected),
                'scope_notes':source['scope_notes']})
        checks=verify_issuer_unit_overlap(source,parsed,conn)
        unit_checks.extend(checks)
        if checks:
            for period in source['periods']:
                for row in grouped[period]:
                    if row['source_url'].startswith(source['source_url']+'#'):
                        row['parser_notes']+='; unit_overlap_verified=4'
    return grouped,provenance,unit_checks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--documents-dir',type=Path,action='append',required=True)
    parser.add_argument('--database',type=Path,default=ROOT/'pboc_data.db')
    parser.add_argument('--snapshot-dir',type=Path,default=ROOT/'data/regional_fiscal_reviewed')
    parser.add_argument('--baseline-dir',type=Path,
                        help='Read existing immutable snapshots here while writing candidates separately.')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/macro_refresh_20261015')
    args=parser.parse_args()
    if not args.database.is_file():raise ValueError('Never create a substitute production database.')
    review=json.loads(args.review.read_text(encoding='utf-8'))
    if review['schema_version']!=1:raise ValueError('Unsupported review schema.')
    archives={}
    for directory in args.documents_dir:
        audit=json.loads((directory/'audit.json').read_text(encoding='utf-8'))
        for record in audit['source_manifest']:
            if record['id'] in archives:raise ValueError('One immutable original per reviewed document is required.')
            archives[record['id']]=(directory,record)
    latest={}
    for path in (args.baseline_dir or args.snapshot_dir).glob('*.json'):
        snapshot=json.loads(path.read_text(encoding='utf-8'))
        validate_reviewed_regional_fiscal_snapshot(snapshot)
        period=str(snapshot['statistical_year'])
        if period not in latest or snapshot['generated_at']>latest[period][1]['generated_at']:
            latest[period]=(path,snapshot)
    with closing(sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        conn.row_factory=sqlite3.Row
        additions,provenance,checks=review_documents(review,archives,conn)
    candidates=[]
    for period,rows in sorted(additions.items()):
        prior_path,prior=latest.get(period,(None,{'observations':[],'provenance':[]}))
        merged=merge_new_observations(prior['observations'],rows)
        candidate={'schema_version':1,'review_status':'source_values_reviewed',
                   'statistical_year':period,'observations':merged}
        validate_reviewed_regional_fiscal_snapshot(candidate)
        candidates.append((period,merged,prior['provenance']+provenance[period],len(rows),
                           str(prior_path) if prior_path else None))
    output=args.output_dir/('province-fiscal-supplement-review-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True,exist_ok=False)
    snapshots=[]
    for period,rows,provenance,new_count,prior_path in candidates:
        snapshots.append({**write_snapshot(period,rows,provenance,args.snapshot_dir),
                          'new_observations':new_count,'prior_snapshot':prior_path})
    audit={'phase':'reviewed_not_applied','database_written':False,'network_requests':0,
           'snapshots':snapshots,'unit_overlap_checks':checks,
           'added_observations':sum(s['new_observations'] for s in snapshots),
           'reading_scope':'Selected pages or annual HTML sections explicitly recorded per source; not full-document reading.'}
    (output/'audit.json').write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'output_dir':str(output),**audit},ensure_ascii=False))


if __name__=='__main__':main()
