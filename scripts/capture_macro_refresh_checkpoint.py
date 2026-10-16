#!/usr/bin/env python3
"""Capture current evidence and remaining requirements without repeating ingestion."""
import hashlib
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import requests
from services.us_macro_service import build_us_macro_payload
from services.macro_data_quality_service import build_macro_data_quality


def read_log(path):
    data=path.read_bytes()
    return data.decode('utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root',type=Path,default=ROOT/'outputs'/'macro_refresh_20261012')
    args=parser.parse_args()
    base=ROOT/'outputs'/'macro_refresh_20261010'
    current=ROOT/'outputs'/'macro_refresh_20261012'
    out=args.output_root/('checkpoint-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True,exist_ok=False)
    runs=[]
    checks=[]
    candidates=[path for parent in (base,current) if parent.exists() for path in parent.iterdir()
                if path.is_dir() and not path.name.startswith('checkpoint-')]
    candidates.extend((ROOT/'data/china_macro_raw').glob('safe_accounts_*'))
    for run in sorted(candidates):
        audit_path=run/'audit.json'
        if audit_path.is_file():
            audit=json.loads(audit_path.read_text(encoding='utf-8'))
            records=audit.get('source_manifest') or []
            runs.append({'run':run.name,'has_final_audit':True,'changes':len(audit.get('changes') or []),
                         'deferred':len(audit.get('deferred_candidates') or []),'errors':audit.get('errors'),
                         'us_result':audit.get('result')})
        elif (run/'manifest.jsonl').is_file():
            records=[json.loads(line) for line in (run/'manifest.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
            runs.append({'run':run.name,'has_final_audit':False,
                         'status':'interrupted_raw_journal_not_completion_evidence'})
        else:
            continue
        for row in records:
            path=(run/row['raw_path']).resolve()
            contained=path.is_relative_to(run.resolve())
            actual=hashlib.sha256(path.read_bytes()).hexdigest() if contained and path.is_file() else None
            checks.append({'run':run.name,'raw_path':row['raw_path'],
                           'expected':row['raw_sha256'],'actual':actual,'match':actual==row['raw_sha256']})
    quality={name:build_macro_data_quality(str(ROOT/'pboc_data.db'),name) for name in ('china','us')}
    payload=build_us_macro_payload(str(ROOT/'pboc_data.db'))
    (out/'us_payload_newcode.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    (out/'raw_integrity.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    backend={'health':None,'new_yield_api':False}
    session=requests.Session();session.trust_env=False
    try:
        backend['health']=session.get('http://127.0.0.1:5001/api/health',timeout=10).json()
        live=session.get('http://127.0.0.1:5001/api/us-macro/data',timeout=45).json()
        backend['new_yield_api']=bool(live.get('yield_curve_snapshots'))
        backend['loaded_registry_count']=live.get('data_quality',{}).get('registered_series')
        china=session.get('http://127.0.0.1:5001/api/china-macro/data',timeout=45).json()
        backend['loaded_china_registry_count']=china.get('data_quality',{}).get('registered_series')
        backend['new_safe_charts']=[chart['code'] for group in china.get('groups',[])
            if group['code']=='capital' for chart in group['charts']
            if chart['code'].startswith(('safe_bop_','safe_iip_'))]
        backend['bank_npl_periods']=[row['period'] for row in china.get('series',{}).get('CN_BANK_NPL_RATIO',[])]
    except requests.RequestException as exc:
        backend['error']=str(exc)
    previous=ROOT/'outputs/macro_completeness/recovery-20261002-231737-953965/final_artifact_manifest.json'
    overwritten=[]
    for row in json.loads(previous.read_text(encoding='utf-8')):
        if row['path'].startswith('output/playwright/'):
            path=ROOT/row['path']
            actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            if actual!=row['sha256']:
                overwritten.append({'path':row['path'],'original_sha256':row['sha256'],'current_sha256':actual})
    backend_logs=[]
    for path in sorted(current.glob('changed_backend_tests-*.log')):
        data=read_log(path);match=re.search(r'Ran (\d+) tests',data)
        backend_logs.append({'path':path.relative_to(ROOT).as_posix(),
            'count':int(match[1]) if match else None,'passed':bool(match and re.search(r'^OK\s*$',data,re.M))})
    chart_logs=[]
    for path in sorted(current.glob('chart_tests-*.log')):
        data=read_log(path);match=re.search(r'pass (\d+)\b',data)
        chart_logs.append({'path':path.relative_to(ROOT).as_posix(),
            'count':int(match[1]) if match else None,'passed':bool(match and re.search(r'fail 0\b',data))})
    regression=[]
    for journal in sorted(current.glob('repository-tests-*/events.jsonl')):
        events=[json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines() if line.strip()]
        completed=[event for event in events if event['event']=='result']
        summary_paths=sorted(journal.parent.glob('summary-*.json'))
        regression.append({'path':journal.relative_to(ROOT).as_posix(),'completed_modules':len(completed),
            'status':'terminal_receipt_available' if summary_paths else 'no_final_receipt_process_must_be_revalidated',
            'summary_path':summary_paths[-1].relative_to(ROOT).as_posix() if summary_paths else None,
            'failures':[{'module':event['module'],'status':event['status'],'log_path':event['log_path']}
                        for event in completed if event['status']!='passed']})
    result={'captured_at':datetime.now().astimezone().isoformat(),
        'status':'verified_progress_goal_still_active','ingestion_runs':runs,
        'raw_hash_records_checked':len(checks),'raw_hashes_all_match':all(row['match'] for row in checks),
        'quality':quality,'live_backend':backend,
        'historical_scoped_backend_receipt':{'path':'outputs/macro_refresh_20261010/targeted_tests_final.log',
            'count':189,'scope':'Earlier checkpoint only; not evidence for later source edits.'},
        'current_changed_backend_tests':backend_logs,'current_chart_tests':chart_logs,
        'full_regression_runs':regression,
        'us_newcode_curve':{'tenors':payload['yield_curve_tenors'],
                           'latest_full_day':next((row['period'] for row in reversed(payload['yield_curve_snapshots'])
                              if len(row['values'])==11),None)},
        'earlier_qa_screenshots_overwritten':overwritten,
        'screenshot_remediation':'Timestamp-scoped output names now prevent reuse. Original raw data and source archives were not changed by this QA incident.',
        'remaining_requirements':[
            'National survey unemployment is verified continuously for 2018-01 through 2026-08; large-city and annual livelihood historical gaps remain.',
            'Bank history earlier than 2022 remains unresolved; 2022 source workbook, image and all 52 new database cells match independently. The 2024 capital-rule break is rendered.',
            'MOFCOM FDI USD after 2023-07 and trade-detail coverage still need official source work; SAFE BOP/IIP are now independently audited.',
            'Full-repository regression is not all-green; see per-module receipts and corrected macro tests.',
            'Minor ingestion hardening saved on October 12 is scoped-tested; its loaded Python version is not independently established.'],
        'source_correction':'DGS2MO returned 404; H.15 actually publishes 11 nominal CMT tenors. Six real additions were retained; the unsupported identifier was removed, not replaced by an invented yield.',
        'git_actions':'No staging, commit, push or PR; unrelated modifications preserved.'}
    (out/'checkpoint_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output_dir':str(out),'raw_hashes_all_match':result['raw_hashes_all_match'],
                      'backend':backend,'latest_full_day':result['us_newcode_curve']['latest_full_day'],
                      'overwritten_earlier_qa_images':len(overwritten)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
