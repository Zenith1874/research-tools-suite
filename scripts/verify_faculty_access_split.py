"""Read live local/public access boundaries; negative writes use invalid payloads."""
import hashlib
import json
from pathlib import Path
import sqlite3
import requests

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'outputs/faculty_access_split_20261002'
QUERY='scope=business_school&q=Worcester'


def main():
    checks=[]
    public_paths=('/faculty-jobs','/school-explorer','/api/faculty-jobs/capabilities',
        '/api/faculty-jobs?'+QUERY+'&limit=2','/api/faculty-jobs/summary?'+QUERY,
        '/api/faculty-jobs/9','/api/faculty-jobs/requirements-comparison',
        '/api/faculty-jobs/export.csv?'+QUERY)
    private_paths=('/my-applications','/my_applications.html','/api/faculty-jobs/profile',
        '/api/faculty-jobs/9/gap','/api/my-applications','/api/faculty-jobs/saved-searches',
        '/api/faculty-jobs?private=1&'+QUERY,'/api/faculty-jobs/export.csv?private=1&'+QUERY)
    for surface,base in (('local','http://127.0.0.1:5001'),('public','https://research.zhengresearch.com')):
        for path in public_paths+private_paths:
            expected=403 if surface=='public' and path in private_paths else 200
            response=requests.get(base+path,timeout=45)
            check={'surface':surface,'method':'GET','path':path,'expected':expected,'status':response.status_code}
            print(json.dumps(check),flush=True)
            checks.append(check)
            assert response.status_code==expected,check
            if path.endswith('capabilities'):
                caps=response.json();assert caps['personal']==(surface=='local') and caps['manage']==(surface=='local')
            if surface=='public' and path.startswith('/api/') and expected==200:
                for key in ('"candidate_record"','"qualification_evidence"','"personal_state"','"fit"'):
                    assert key not in response.text,key
    for path,payload in (('/api/faculty-jobs/profile',[]),('/api/faculty-jobs/update',{'sources':'invalid-boundary-probe'})):
        response=requests.post('https://research.zhengresearch.com'+path,json=payload,timeout=20)
        check={'surface':'public','method':'POST','path':path,'expected':403,'status':response.status_code}
        checks.append(check);print(json.dumps(check),flush=True);assert response.status_code==403
    before=json.loads((OUTPUT/'private-before.json').read_text())
    conn=sqlite3.connect((ROOT/'data/faculty_jobs.db').resolve().as_uri()+'?mode=ro',uri=True)
    private={}
    for table in before['private_tables']:
        rows=conn.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
        private[table]={'rows':len(rows),'sha256':hashlib.sha256(json.dumps(rows,ensure_ascii=False,default=str).encode()).hexdigest()}
    conn.close()
    assert private==before['private_tables']
    assert hashlib.sha256((ROOT/'data/faculty_job_profile.json').read_bytes()).hexdigest()==before['profile_sha256']
    with (OUTPUT/'runtime-acceptance.json').open('x',encoding='utf8') as handle:
        json.dump({'checks':checks,'private_contents_unchanged':True,'policy':'direct_loopback_only'},handle,indent=2)
    print(json.dumps({'passed_checks':len(checks),'private_contents_unchanged':True}),flush=True)


if __name__=='__main__':
    main()
