#!/usr/bin/env python3
"""Review archived provincial budget statements and selected official MOF table columns."""
import argparse
import hashlib
import json
import math
import sys
import io
from datetime import datetime, timezone
from pathlib import Path
from html import escape
from pypdf import PdfReader
import fitz

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.regional_fiscal_service import (parse_china_annual_fiscal_bulletin,
    parse_mof_regional_debt_html, parse_china_execution_report, parse_china_fiscal_completion_release,
    parse_china_fiscal_pdf_pages)


def verify_reviewed_raster_page(content, source, directory):
    """Bind a labelled visual transcript to its exact archived PDF/page render."""
    identity=(source['region_name'],source['statistical_year'],source['profile'])
    if identity!=('广东','2025','guangdong_2025_fiscal_raster'):
        raise ValueError('Use an explicitly inspected raster-PDF statement profile.')
    if not content.startswith(b'%PDF-'):
        raise ValueError('A complete archived original PDF is required for the visual transcript.')
    render=(directory/source['render_path']).resolve()
    if not render.is_relative_to(directory.resolve()) or hashlib.sha256(render.read_bytes()).hexdigest()!=source['render_sha256']:
        raise ValueError('Reviewed page render changed or escaped the original source run.')
    with fitz.open(stream=content,filetype='pdf') as pdf:
        if len(pdf)!=source['pdf_pages']:
            raise ValueError('Original PDF page count changed.')
        page=pdf[source['evidence_page']-1]
        if page.get_text().strip():
            raise ValueError('This explicit profile describes an image-only page, not a text parser.')
        reproduced=page.get_pixmap(matrix=fitz.Matrix(source['render_scale'],source['render_scale'])).tobytes('png')
        if hashlib.sha256(reproduced).hexdigest()!=source['render_sha256']:
            raise ValueError('The reviewed visual page is not the declared original PDF page.')


def write_snapshot(period, rows, provenance, directory):
    snapshot={'schema_version':1,'statistical_year':period,'review_status':'source_values_reviewed',
              'generated_at':datetime.now(timezone.utc).isoformat(),'observations':rows,'provenance':provenance}
    content=(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    digest=hashlib.sha256(content).hexdigest()
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/(str(period)+'-'+digest[:12]+'.json')
    if path.exists() and path.read_bytes()!=content:raise ValueError('Conflicting immutable snapshot.')
    if not path.exists():path.write_bytes(content)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Snapshot byte/hash mismatch.')
    return {'path':str(path),'sha256':digest,'observations':len(rows)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection-dir',type=Path,required=True)
    parser.add_argument('--review',type=Path,default=ROOT/'data/province_fiscal_release_review_2025.json')
    parser.add_argument('--debt-review',type=Path,default=ROOT/'data/mof_regional_debt_table_review.json')
    parser.add_argument('--documents-dir',type=Path,action='append',
                        help='Archived document run; repeat to combine bounded acquisition batches.')
    parser.add_argument('--documents-review',type=Path,default=ROOT/'data/province_fiscal_document_review_2025.json')
    parser.add_argument('--snapshot-dir',type=Path,default=ROOT/'data/regional_fiscal_reviewed')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/macro_refresh_20261013')
    args=parser.parse_args()
    review=json.loads(args.review.read_text(encoding='utf-8'))
    collection=json.loads((args.collection_dir/'audit.json').read_text(encoding='utf-8'))
    cached={item['release']['region_code']:item for item in collection['parsed']}
    result, provenance=[],[]
    for code,name,revenue,expenditure,tax in review['expected']:
        item=cached[code];record=item['source_record'];source=item['release']
        path=(args.collection_dir/record['raw_path']).resolve()
        if not path.is_relative_to(args.collection_dir.resolve()):raise ValueError('Source path escaped collection.')
        content=path.read_bytes()
        if hashlib.sha256(content).hexdigest()!=record['raw_sha256']:raise ValueError('Source hash mismatch.')
        rows=parse_china_annual_fiscal_bulletin(content,name,str(review['statistical_year']),source['source_title'])
        expected={'general_budget_revenue':revenue,'general_budget_expenditure':expenditure}
        if tax is not None:expected['tax_revenue']=tax
        values={row['indicator_code']:row['value'] for row in rows}
        if set(values)!=set(expected) or any(not math.isclose(values[k],v,rel_tol=0,abs_tol=1e-6) for k,v in expected.items()):
            raise ValueError(f'{name}: annual fiscal parser differs from inspected statement.')
        for row in rows:
            row.update(source_name=source['source_name'],source_url=source['source_url'],source_title=source['source_title'],
                       parser_notes='年度统计公报直接披露的全省地方一般预算口径；初步数，不是预算安排数。'
                       +f" evidence_sha256={record['raw_sha256']}; statement={row['evidence']}")
            result.append(row)
        provenance.append({'region_code':code,'source_url':source['source_url'],'access_type':'archived_official_html',
                           'raw_sha256':record['raw_sha256'],'raw_path':path.relative_to(ROOT).as_posix()})
    for source in review.get('supplemental_evidence',[]):
        rows=parse_china_annual_fiscal_bulletin(source['excerpt'],source['region_name'],str(review['statistical_year']),source['source_title'])
        values={row['indicator_code']:row['value'] for row in rows}
        expected=source['expected_values']
        if set(values)!=set(expected) or any(not math.isclose(values[k],v,rel_tol=0,abs_tol=1e-6) for k,v in expected.items()):
            raise ValueError('Supplemental fiscal excerpt differs from inspected values.')
        digest=hashlib.sha256(source['excerpt'].encode('utf-8')).hexdigest()
        for row in rows:
            row.update(source_name=source['source_name'],source_url=source['source_url'],source_title=source['source_title'],
                       parser_notes='年度一般预算全省地方口径，初步统计数；'
                       +f"access_type={source['access_type']}; excerpt_sha256={digest}; "+source['caveat'])
            result.append(row)
        provenance.append({'region_code':source['region_code'],'source_url':source['source_url'],
                           'access_type':source['access_type'],'excerpt_sha256':digest})
    if args.documents_dir:
        records = {}
        for directory in args.documents_dir:
            archive=json.loads((directory/'audit.json').read_text(encoding='utf-8'))
            for record in archive['source_manifest']:
                old = records.get(record['id'])
                if old and (old[1]['raw_sha256'],old[1]['source_url']) != (record['raw_sha256'],record['source_url']):
                    raise ValueError('Conflicting originals share a document identity; review the versions separately.')
                records[record['id']] = (directory,record)
        docs=json.loads(args.documents_review.read_text(encoding='utf-8'))
        for source in docs['documents']:
            archived=records.get(source['id'])
            if archived is None:raise ValueError('Reviewed document has no archived original; do not import a search snippet instead.')
            directory,record=archived
            path=(directory/record['raw_path']).resolve()
            if not path.is_relative_to(directory.resolve()):raise ValueError('Document path escaped its run.')
            content=path.read_bytes()
            if hashlib.sha256(content).hexdigest()!=record['raw_sha256'] or record['source_url']!=source['source_url']:
                raise ValueError('Reviewed document identity or raw hash changed.')
            document_type=source.get('document_type','execution_report')
            if document_type=='execution_report':
                rows=parse_china_execution_report(content,source['region_name'],source['statistical_year'],source['profile'])
            elif document_type=='annual_completion_release':
                rows=parse_china_fiscal_completion_release(content,source['region_name'],source['statistical_year'],source['profile'])
            elif document_type=='annual_statistical_bulletin':
                rows=parse_china_annual_fiscal_bulletin(content,source['region_name'],source['statistical_year'],source['source_title'])
            elif document_type=='reviewed_pdf_tables':
                if record['format']!='pdf' or not content.startswith(b'%PDF-'):
                    raise ValueError('Reviewed PDF tables require the archived PDF original.')
                reader=PdfReader(io.BytesIO(content))
                if source.get('pdf_pages') is not None and len(reader.pages) != source['pdf_pages']:
                    raise ValueError('The visually reviewed PDF page count changed.')
                pages={n:reader.pages[n-1].extract_text() for n in source['reviewed_pages']}
                rows=parse_china_fiscal_pdf_pages(pages,source['region_name'],source['statistical_year'],source['profile'])
            elif document_type=='reviewed_raster_pdf_statement':
                if record['format']!='pdf':
                    raise ValueError('A declared PDF original is required.')
                verify_reviewed_raster_page(content,source,directory)
                # Parse the labelled review transcript, never pretend it came from
                # automatic PDF text extraction or unreviewed OCR.
                rows=parse_china_annual_fiscal_bulletin(source['reviewed_excerpt'],source['region_name'],
                                                       source['statistical_year'],source['source_title'])
                for row in rows:
                    row['evidence_page']=source['evidence_page']
            else:
                raise ValueError('Unsupported reviewed document type.')
            expected=source['expected_values'];values={r['indicator_code']:r['value'] for r in rows}
            if set(values)!=set(expected) or any(not math.isclose(values[k],v,rel_tol=0,abs_tol=1e-6) for k,v in expected.items()):
                raise ValueError('Execution chapter differs from manually inspected source values.')
            import_codes = set(source.get('import_codes', expected))
            if not import_codes or not import_codes.issubset(expected):
                raise ValueError('Import fields must be a nonempty subset of inspected actuals.')
            for row in rows:
                if row['indicator_code'] not in import_codes:
                    continue
                reference_url=source['source_url']
                if document_type in ('reviewed_pdf_tables','reviewed_raster_pdf_statement'):
                    reference_url+='#page='+str(row['evidence_page'])
                row.update(source_name=source['source_name'],source_url=reference_url,source_title=source['source_title'],
                           parser_notes=source.get('parser_scope_note','2025年度全省实际执行数（报告摘要），非2026预算、非省本级、非最终决算；')
                           +f"raw_sha256={record['raw_sha256']}; statement={row['evidence']}; "+source['scope_notes'])
                result.append(row)
            provenance.append({'region_code':source['region_code'],'source_url':source['source_url'],
                               'access_type':record['access_type'],'raw_sha256':record['raw_sha256'],
                               'scope_notes':source['scope_notes'],'inspected_codes':sorted(expected),
                               'import_codes':sorted(import_codes)})
    debt=json.loads(args.debt_review.read_text(encoding='utf-8'))
    older=[];tables=[]
    for table in debt['tables']:
        # A derived parser replay of the selected cells, never described as full source HTML.
        html='<table><tr>'+''.join('<th>'+escape(str(v))+'</th>' for v in table['columns'])+'</tr>'
        html+=''.join('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in table['rows'])+'</table>'
        rows=parse_mof_regional_debt_html(html,table['indicator_code'],table['period'],table['source_url'],require_balance_header=True)
        total=round(sum(row['value'] for row in rows),2)
        if abs(total-table['official_total'])>0.01:raise ValueError('Province balances do not reconcile with the official total.')
        for row in rows:
            row.update(data_status='official_final' if table['period']=='2025' else 'official',
                       source_title=table['source_title'],
                       parser_notes=row['parser_notes']+'；access_type=official_site_table_excerpt；'+table['caveat'])
        (result if table['period']=='2025' else older).extend(rows)
        tables.append({'source_url':table['source_url'],'period':table['period'],'indicator_code':table['indicator_code'],
                       'province_rows':len(rows),'sum':total,'official_total':table['official_total'],'access_type':debt['access_type']})
    outputs=[write_snapshot('2025',result,provenance+[t for t in tables if t['period']=='2025'],args.snapshot_dir),
             write_snapshot('2019',older,[t for t in tables if t['period']=='2019'],args.snapshot_dir)]
    out=args.output_dir/('province-fiscal-review-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True,exist_ok=False)
    audit={'snapshots':outputs,'annual_budget_rows':sum(r['indicator_code'] in ('general_budget_revenue','general_budget_expenditure','tax_revenue') for r in result),'debt_table_checks':tables,
           'original_scope':'31 province-level identities; annual local budget, year-end government debt.',
           'incomplete_2025_budget_coverage':True,'database_written':False,'network_requests':0}
    (out/'audit.json').write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({**audit,'output_dir':str(out)},ensure_ascii=False))


if __name__=='__main__':main()
