#!/usr/bin/env python3
"""Resume macro acceptance from durable evidence without repeating ingestion."""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import requests

TEST_MODULES=(
    'tests.test_macro_completeness','tests.test_china_macro_service','tests.test_rates_macro_parsers',
    'tests.test_macro_analytics','tests.test_macro_scenario_service','tests.test_china_demography_service',
    'tests.test_housing_structural_driver_service','tests.test_housing_scenario_service',
    'tests.test_fiscal_budget_service','tests.test_fiscal_cashflow_service',
)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',type=Path,default=ROOT/'outputs'/'macro_completeness')
    p.add_argument('--resume-dir',type=Path,help='Continue API acceptance in an existing recovery directory.')
    args=p.parse_args()
    if args.resume_dir:
        out=args.resume_dir.resolve()
        if not out.is_relative_to(args.output_dir.resolve()):
            p.error('--resume-dir must be inside --output-dir')
        integrity=json.loads((out/'checkpoint_integrity.json').read_text(encoding='utf-8'))
        test_output=(out/'targeted_tests.log').read_text(encoding='utf-8')
        if not test_output.rstrip().endswith('OK') or 'Ran ' not in test_output:
            p.error('The existing test log does not prove a passing checkpoint; inspect it before resuming.')
        finish_api_acceptance(out,integrity,0)
        return
    existing=sorted(path for path in args.output_dir.iterdir() if path.is_dir() and (path/'audit.json').is_file())
    out=args.output_dir/('recovery-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True,exist_ok=False)
    runs=[]
    file_checks=[]
    for run in existing:
        audit=json.loads((run/'audit.json').read_text(encoding='utf-8'))
        manifests=audit.get('source_manifest') or []
        runs.append({'run':run.name,'audit_path':str(run/'audit.json'),
                     'audit_sha256':hashlib.sha256((run/'audit.json').read_bytes()).hexdigest(),
                     'manifest_records':len(manifests),'errors':audit.get('errors'),
                     'parsed_observations':audit.get('parsed_observations'),
                     'quick_check':audit.get('quick_check'),
                     'old_originals_preserved':audit.get('preserved_original_values')})
        for record in manifests:
            path=(run/record['raw_path']).resolve()
            contained=path.is_relative_to(run.resolve())
            actual=hashlib.sha256(path.read_bytes()).hexdigest() if contained and path.is_file() else None
            file_checks.append({'run':run.name,'path':str(path),'exists':path.is_file(),
                                'expected_sha256':record['raw_sha256'],'actual_sha256':actual,
                                'matches':actual==record['raw_sha256']})
    integrity={'runs':runs,'raw_records_checked':len(file_checks),
               'all_recorded_raw_hashes_match':all(row['matches'] for row in file_checks),
               'failed_checks':[row for row in file_checks if not row['matches']]}
    (out/'checkpoint_integrity.json').write_text(json.dumps(integrity,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'raw_manifest_check.json').write_text(json.dumps(file_checks,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'decision_log.md').write_text(
        '# Recovery decisions\n\n'
        '- Existing completed ingestion audits and raw hashes control the checkpoint.\n'
        '- No source scraping, replay, model inference, or database upsert is repeated.\n'
        '- Tests, browser acceptance and final documentation lacked durable completion receipts; finish those now.\n'
        '- Retain invalidated historical records and original values; do not delete them.\n'
        '- Preserve unrelated working-tree changes and background jobs.\n',encoding='utf-8')
    (out/'reading_log.md').write_text(
        '# Recovery evidence inspection log\n\n'
        'This log starts after recovery; it does not manufacture pre-crash reading events.\n\n'
        f'- Inspected {len(runs)} existing audit JSON files.\n'
        f'- Checked {len(file_checks)} recorded local raw-response hashes; hash checks are not semantic full-text reading.\n'
        '- Prior raw downloads are parsed-source evidence, not proof that every report was read in full.\n'
        '- No existing macro reading_log, decision_log, or completion_audit was found at this checkpoint.\n',encoding='utf-8')
    command=[sys.executable,'-X','utf8','-m','unittest',*TEST_MODULES,'-q']
    tested=subprocess.run(command,cwd=ROOT,text=True,encoding='utf-8',errors='replace',
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
    (out/'targeted_tests.log').write_text(tested.stdout,encoding='utf-8')
    finish_api_acceptance(out,integrity,tested.returncode)


def finish_api_acceptance(out,integrity,test_returncode):
    api_path=out/'api_acceptance.json'
    api=json.loads(api_path.read_text(encoding='utf-8')) if api_path.is_file() else {}
    session=requests.Session()
    # Loopback checks must not inherit an unrelated system web proxy.
    session.trust_env=False
    for name,url in (
            ('health','http://127.0.0.1:5001/api/health'),
            ('china','http://127.0.0.1:5001/api/china-macro/data'),
            ('us','http://127.0.0.1:5001/api/us-macro/data'),
            ('quality','http://127.0.0.1:5001/api/macro-data-quality?country=china')):
        if api.get(name,{}).get('http_status')==200 and 'error' not in api[name]:
            continue
        started=time.monotonic()
        try:
            response=session.get(url,timeout=(5,40))
            response.raise_for_status();payload=response.json()
        except (requests.RequestException,ValueError) as exc:
            api[name]={'error':str(exc),'checked_at':datetime.now().astimezone().isoformat(),
                       'elapsed_seconds':round(time.monotonic()-started,3),'url':url}
            api_path.write_text(json.dumps(api,ensure_ascii=False,indent=2),encoding='utf-8')
            continue
        if name=='china':
            api[name]={'http_status':response.status_code,'groups':[g['code'] for g in payload['groups']],
                       'quality':{k:payload['data_quality'][k] for k in ('registered_series','series_with_data','missing_series')},
                       'latest':{code:payload['series'].get(code,[])[-1:] for code in (
                           'CN_CPI_CORE_YOY','CN_CPI_CORE_YTD_AVG_YOY','CN_IND_PROFIT_YTD_YOY',
                           'CN_BANK_NIM_YTD','CN_BANK_NPL_RATIO','CN_MARRIAGES','CN_DIVORCES_TOTAL')}}
        elif name=='us':
            api[name]={'http_status':response.status_code,'groups':[g['code'] for g in payload['groups']],
                       'quality':{k:payload['data_quality'][k] for k in ('registered_series','series_with_data','missing_series')},
                       'series_present':{k:bool(payload['series'].get(k)) for k in ('PCE_YOY','HOUST','TOTBKCR','EXPGS','DCOILWTICO')}}
        else:
            api[name]={'http_status':response.status_code,'payload':payload if name=='health' else
                       {k:payload[k] for k in ('registered_series','series_with_data','missing_series')}}
        api[name].update({'checked_at':datetime.now().astimezone().isoformat(),
                          'elapsed_seconds':round(time.monotonic()-started,3),'url':url})
        api_path.write_text(json.dumps(api,ensure_ascii=False,indent=2),encoding='utf-8')
    api_pass=all(api.get(name,{}).get('http_status')==200 and 'error' not in api[name]
                 for name in ('health','china','us','quality'))
    result={'recovered_at':datetime.now().astimezone().isoformat(),
            'checkpoint_integrity_pass':integrity['all_recorded_raw_hashes_match'],
            'targeted_tests_exit_code':test_returncode,
            'test_command':[sys.executable,'-X','utf8','-m','unittest',*TEST_MODULES,'-q'],
            'api_acceptance_saved':True,'api_acceptance_pass':api_pass,'browser_acceptance':'pending',
            'documentation':'pending','unrecoverable_intermediate_steps':[],
            'precrash_logs_not_present':['reading_log','decision_log','completion_audit'],
            'notes':['Lost terminal-only progress is not treated as completion evidence. No ingestion was repeated.']}
    (out/'completion_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output_dir':str(out),'raw_records_checked':integrity['raw_records_checked'],
                      'raw_hashes_match':integrity['all_recorded_raw_hashes_match'],
                      'tests_exit_code':test_returncode,'api_saved':True,'api_pass':api_pass},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
