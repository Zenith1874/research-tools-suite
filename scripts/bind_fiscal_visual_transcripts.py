#!/usr/bin/env python3
"""Bind already reviewed labelled excerpts to immutable original PDF page renders."""
import argparse
import copy
import hashlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.review_province_fiscal_supplement import visual_transcript_digest,verified_visual_pages


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--declarations',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--render-audit',type=Path,action='append',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--additional-review',type=Path,action='append',default=[])
    args=parser.parse_args();archive=args.archive.resolve()
    declarations=json.loads(args.declarations.read_text(encoding='utf8'))
    originals={r['id']:r for r in json.loads((archive/'audit.json').read_text(encoding='utf8'))['source_manifest']}
    renders={}
    for path in args.render_audit:
        for r in json.loads(path.read_text(encoding='utf8'))['records']:
            if r.get('locator_only'):continue
            key=(r['id'],r['page'])
            if key in renders:raise ValueError('Only one exact selected render per page is accepted.')
            renders[key]=r
    output=args.output_dir/('fiscal-visual-binding-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True,exist_ok=False);documents=[]
    for declared in declarations['documents']:
        source=copy.deepcopy(declared);original=originals[source['id']]
        if source['source_url']!=original['source_url'] or source['raw_sha256']!=original['raw_sha256']:
            raise ValueError('Visual declaration source identity differs from the acquired original.')
        texts=source.pop('transcript_texts')
        if set(map(int,texts))!=set(source['reviewed_pages']):raise ValueError('All and only the inspected pages need excerpts.')
        source['visual_transcript_pages']={}
        for n in source['reviewed_pages']:
            r=renders[source['id'],n]
            if r['raw_sha256']!=source['raw_sha256'] or r['pdf_pages']!=source['pdf_pages']:
                raise ValueError('The labelled excerpt is not the declared original PDF/page count.')
            source['visual_transcript_pages'][str(n)]={k:r[k] for k in ('render_path','render_scale','render_sha256')}
            source['visual_transcript_pages'][str(n)]['text']=texts[str(n)]
        source['transcript_sha256']=visual_transcript_digest(source)
        content=(archive/original['raw_path']).read_bytes()
        if hashlib.sha256(content).hexdigest()!=source['raw_sha256']:raise ValueError('Original PDF bytes changed.')
        verified_visual_pages(content,source,archive,PdfReader(io.BytesIO(content)))
        documents.append(source)
    extra=[]
    for additional in args.additional_review:
        value=json.loads(additional.read_text(encoding='utf8'))
        if value.get('schema_version')!=1:raise ValueError('Unsupported additional review schema.')
        extra.extend(value['documents'])
    if len({d['id'] for d in documents+extra})!=len(documents+extra):raise ValueError('Duplicate reviewed source identity.')
    review={'schema_version':1,'documents':documents+extra}
    path=output/'review.json';path.write_bytes((json.dumps(review,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
    audit={'phase':'visual_excerpts_bound_not_applied','database_written':False,'network_requests':0,
           'declarations_path':str(args.declarations),'declarations_sha256':hashlib.sha256(args.declarations.read_bytes()).hexdigest(),
           'review_path':str(path),'review_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
           'additional_reviews':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in args.additional_review],
           'documents':[{'id':s['id'],'transcript_sha256':s['transcript_sha256'],'reviewed_pages':s['reviewed_pages']} for s in documents]}
    (output/'audit.json').write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
    print(json.dumps({'output_dir':str(output),**audit},ensure_ascii=False))


if __name__=='__main__':main()
