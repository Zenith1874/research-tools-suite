#!/usr/bin/env python3
"""Render bounded fiscal PDF locators or hash-bound selected review pages."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import fitz
from PIL import Image,ImageDraw


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--pages',action='append',default=[],help='Exact source-id=1,2,5 physical pages; omit for locator sheets.')
    args=parser.parse_args();archive=args.archive.resolve()
    manifest=json.loads((archive/'audit.json').read_text(encoding='utf8'))['source_manifest']
    selections={}
    for value in args.pages:
        name,pages=value.split('=',1)
        if name in selections:raise ValueError('Declare each source once.')
        selections[name]=sorted({int(n) for n in pages.split(',')})
    known={r['id'] for r in manifest if r['format']=='pdf'}
    if not set(selections).issubset(known):raise ValueError('Unknown original PDF selection.')
    output=archive/('visual-review-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(exist_ok=False);records=[]
    for record in manifest:
        if record['format']!='pdf' or (selections and record['id'] not in selections):continue
        raw=(archive/record['raw_path']).resolve()
        if not raw.is_relative_to(archive) or hashlib.sha256(raw.read_bytes()).hexdigest()!=record['raw_sha256']:
            raise ValueError('Original fiscal PDF identity changed.')
        with fitz.open(raw) as doc:
            if selections:
                for n in selections[record['id']]:
                    if not 1<=n<=len(doc):raise ValueError('Selected physical page outside the original PDF.')
                    data=doc[n-1].get_pixmap(matrix=fitz.Matrix(1.6,1.6)).tobytes('png')
                    path=output/(record['id']+'-page-'+str(n)+'.png');path.write_bytes(data)
                    records.append({'id':record['id'],'page':n,'pdf_pages':len(doc),'raw_sha256':record['raw_sha256'],
                                    'render_path':path.relative_to(archive).as_posix(),'render_scale':1.6,
                                    'render_sha256':hashlib.sha256(data).hexdigest()})
            else:
                if len(doc)>24:raise ValueError('Select pages explicitly for documents longer than24 pages.')
                for start in range(0,len(doc),8):
                    sheet=Image.new('RGB',(1280,960),'#e2e8ef');draw=ImageDraw.Draw(sheet)
                    for i in range(start,min(start+8,len(doc))):
                        pix=doc[i].get_pixmap(matrix=fitz.Matrix(430/doc[i].rect.height,430/doc[i].rect.height))
                        thumb=Image.frombytes('RGB',(pix.width,pix.height),pix.samples);thumb.thumbnail((310,430))
                        col,row=(i-start)%4,(i-start)//4
                        sheet.paste(thumb,(col*320+(320-thumb.width)//2,row*480+30))
                        draw.text((col*320+8,row*480+7),'Physical page '+str(i+1),fill='black')
                    path=output/(record['id']+'-locator-'+str(start//8+1)+'.png');sheet.save(path)
                    records.append({'id':record['id'],'locator_only':True,'pages':list(range(start+1,min(start+8,len(doc))+1)),
                                    'render_path':path.relative_to(archive).as_posix(),'render_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    audit={'render_engine':'PyMuPDF '+fitz.VersionBind,'network_requests':0,'database_written':False,
           'mode':'selected_pages' if selections else 'locator_only','records':records}
    (output/'render_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'output_dir':str(output),'files':len(records),'mode':audit['mode']},ensure_ascii=False))


if __name__=='__main__':main()
