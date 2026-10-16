#!/usr/bin/env python3
"""Extract and stage only the explicitly reviewed annual Appendix 1 PDF pages."""
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.mofcom_fdi_bulletin_service import parse_fdi_annual_appendix, annual_snapshot_observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--release-date', required=True, help='Publication date independently checked on the original official release page.')
    parser.add_argument('--publication-source-url', required=True)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs' / 'macro_refresh_20261013')
    parser.add_argument('--install-reviewed-snapshot', action='store_true')
    args = parser.parse_args()
    out = args.output_dir / ('fdi-annual-review-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True, exist_ok=False)
    archive = json.loads((args.source_dir / 'audit.json').read_text(encoding='utf-8'))
    record = next(item for item in archive['source_manifest'] if item['raw_path'] == 'bulletin.pdf')
    pdf = args.source_dir / record['raw_path']
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if digest != record['raw_sha256']:
        raise ValueError('The archived PDF no longer matches its recorded checksum.')
    reader = PdfReader(pdf)
    selected = {index: reader.pages[index].extract_text(extraction_mode='layout') for index in (6, 37, 38)}
    appendix = parse_fdi_annual_appendix(selected[37] + '\n' + selected[38])
    if '银行、证券、保险' not in selected[6] or '2022' not in selected[6]:
        raise ValueError('The original scope/collection footnote has not been recovered.')
    reviewed_at = datetime.now().astimezone().isoformat()
    snapshot = {'schema_version': 1, **appendix, 'source_title': '中国外资统计公报2026 附表1',
                'source_url': record['source_url'], 'publication_source_url': args.publication_source_url,
                'release_date': args.release_date, 'retrieved_at': record['retrieved_at'],
                'reviewed_at': reviewed_at, 'raw_sha256': digest,
                'pdf_pages_reviewed': [7, 38, 39], 'pdf_page_count': len(reader.pages),
                'parser_notes': '商务部公报附表1年度原值；年度与月报累计分开，不换汇，不拆分1979—1982合并块。公报含金融领域年度数据，早期月报排除银行、证券、保险领域，两者不可混接。2022金融领域采集制度变化见PDF第7页；月报实际金额自2022-05起纳入金融领域，同比仍依官方可比口径。发布日期为当前公报版本日期，不是各年度首报日。'}
    rows = annual_snapshot_observations(snapshot)
    (out / 'reviewed_annual.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
    for index, text in selected.items():
        (out / f'pdf-page-{index + 1}.txt').write_text(text, encoding='utf-8')
    installed = None
    if args.install_reviewed_snapshot:
        directory = ROOT / 'data' / 'mofcom_fdi_bulletin_reviewed'
        directory.mkdir(exist_ok=True)
        installed = directory / f"{appendix['statistical_year']}-{digest[:12]}.json"
        content = (out / 'reviewed_annual.json').read_bytes()
        if installed.exists():
            previous = json.loads(installed.read_text(encoding='utf-8'))
            if previous['raw_sha256'] != digest or previous['annual_rows'] != snapshot['annual_rows']:
                raise ValueError('An existing reviewed snapshot differs; it will not be overwritten.')
        else:
            installed.write_bytes(content)
    audit = {'captured_at': reviewed_at, 'source_pdf_sha256': digest, 'annual_rows': len(appendix['annual_rows']),
             'observation_rows': len(rows), 'statistical_year': appendix['statistical_year'],
             'combined_early_block': appendix['combined_early_block'],
             'reading_scope': 'Selected pages 7, 38, 39 only; not a full 140-page reading.',
             'installed_snapshot': str(installed) if installed else None, 'success': True}
    (out / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output_dir': str(out), **audit}, ensure_ascii=False))


if __name__ == '__main__':
    main()
