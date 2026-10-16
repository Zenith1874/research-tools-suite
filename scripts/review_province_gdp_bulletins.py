#!/usr/bin/env python3
"""Compare manually inspected GDP values with archived official-source evidence."""
import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.province_gdp_bulletin_service import parse_province_gdp_release, validate_reviewed_province_snapshot
from services.regional_fiscal_service import CN_PROVINCES


def build_reviewed_snapshot(collection_dir, review_path):
    collection_dir, review_path = Path(collection_dir), Path(review_path)
    audit = json.loads((collection_dir / 'audit.json').read_text(encoding='utf-8'))
    review = json.loads(review_path.read_text(encoding='utf-8'))
    year = review['statistical_year']
    if audit['statistical_year'] != year or review['schema_version'] != 1:
        raise ValueError('The source collection and manual review must refer to the same year.')
    cached = {item['release']['region_code']: item for item in audit['parsed']}
    expected = review['expected']
    if len(expected) != 31 or {r[0] for r in expected} != set(CN_PROVINCES.values()):
        raise ValueError('The review must explicitly cover the 31 distinct province-level identities.')
    observations, sources = [], []
    for code, name, nominal, growth in expected:
        if CN_PROVINCES.get(name) != code:
            raise ValueError('Province name and code do not match.')
        evidence = review['supplemental_evidence'].get(code)
        if code in cached:
            item = cached[code]
            record = item['source_record']
            path = (collection_dir / record['raw_path']).resolve()
            if not path.is_relative_to(collection_dir.resolve()):
                raise ValueError('Source file escaped the collection directory.')
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != record['raw_sha256']:
                raise ValueError('Archived HTML hash changed after collection.')
            release = item['release']
            parsed = parse_province_gdp_release(content.decode('utf-8'), name, year, release['source_title'])
            source = {**release, 'access_type': 'archived_official_html',
                      'source_archive': path.relative_to(ROOT).as_posix(), 'raw_sha256': record['raw_sha256'],
                      'retrieved_at': record['retrieved_at'], 'excerpt': parsed[0]['evidence']}
            values = {r['indicator_code']: r['value'] for r in parsed}
        elif evidence:
            source = {'region_code': code, 'region_name': name, **evidence}
            if evidence['access_type'] == 'official_government_relay_image':
                path = (ROOT / evidence['image_path']).resolve()
                if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != evidence['image_sha256']:
                    raise ValueError('Reviewed government image is missing or changed.')
                if code != '630000' or str(nominal) not in evidence['excerpt'] or str(growth) + '%' not in evidence['excerpt']:
                    raise ValueError('Only the explicitly visually reviewed Qinghai row is authorized from this image.')
                values = {'nominal_gdp': nominal, 'real_growth': growth}
            else:
                parsed = parse_province_gdp_release(evidence['excerpt'], name, year, evidence['source_title'])
                values = {r['indicator_code']: r['value'] for r in parsed}
                if 'growth_subject_order' in evidence:
                    order = evidence['growth_subject_order']
                    matches = re.search(r'分别比上年增长([\d.%、]+)', evidence['excerpt'])
                    rates = re.findall(r'([\d.]+)%', matches[1]) if matches else []
                    if len(rates) != len(order) or len(set(order)) != len(order):
                        raise ValueError('The explicit multi-province growth ordering is not verified.')
                    values['real_growth'] = float(rates[order.index(name)])
            source['excerpt_sha256'] = hashlib.sha256(evidence['excerpt'].encode('utf-8')).hexdigest()
            source['reviewed_at'] = review['review_date']
        else:
            raise ValueError(f'{name}: no reviewed source evidence exists; do not substitute zero.')
        for indicator, expected_value in (('nominal_gdp', nominal), ('real_growth', growth)):
            value = values.get(indicator)
            if value is None or not math.isclose(value, expected_value, rel_tol=0, abs_tol=1e-6):
                raise ValueError(f'{name} {indicator}: source value {value} differs from manual review {expected_value}.')
        relayed = '转述' in source['source_name'] or source['access_type'] == 'official_government_relay_image'
        status = 'official_relayed' if relayed else 'official_preliminary'
        source['data_status'] = status
        source['source_id'] = 'province-gdp-' + str(year) + '-' + code
        sources.append(source)
        for indicator in ('nominal_gdp', 'real_growth'):
            observations.append({'region_code': code, 'region_name': name, 'period': str(year),
                                 'indicator_code': indicator, 'value': values[indicator],
                                 'unit': '%' if indicator == 'real_growth' else '亿元',
                                 'data_status': status, 'source_id': source['source_id']})
    snapshot = {'schema_version': 1, 'statistical_year': year, 'review_status': 'source_values_reviewed',
                'generated_at': datetime.now().astimezone().isoformat(), 'review_method': review['review_method'],
                'manual_review_sha256': hashlib.sha256(review_path.read_bytes()).hexdigest(),
                'observations': observations, 'sources': sources,
                'caveats': ['绝对额为现价名义GDP，官方增长速度按不变价格计算，不能相互替代。',
                            '2025年为初步核算或政府官网转述，后续最终核实可能修订；历史年鉴数值保持原采集版本。',
                            '完整原文、网页摘录和汇总图表分别记录；访问失败不被写成完整原文阅读。',
                            '青海仅取得政府官网转述图表，尚未取得省统计局原始公报。']}
    validate_reviewed_province_snapshot(snapshot)
    return snapshot


def write_reviewed_snapshot(snapshot, directory):
    """Persist exact UTF-8/LF bytes; filename and manifest hash the bytes on disk."""
    content = (json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    digest = hashlib.sha256(content).hexdigest()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{snapshot['statistical_year']}-{digest[:12]}.json"
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError('Refuse to overwrite a conflicting reviewed snapshot.')
    else:
        path.write_bytes(content)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('Persisted snapshot bytes do not match the declared hash.')
    return path, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection-dir', type=Path, required=True)
    parser.add_argument('--review', type=Path, default=ROOT / 'data/province_gdp_release_review_2025.json')
    parser.add_argument('--snapshot-dir', type=Path, default=ROOT / 'data/province_gdp_reviewed')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs/macro_refresh_20261013')
    args = parser.parse_args()
    snapshot = build_reviewed_snapshot(args.collection_dir, args.review)
    snapshot_path, digest = write_reviewed_snapshot(snapshot, args.snapshot_dir)
    out = args.output_dir / ('province-gdp-review-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True, exist_ok=False)
    counts = {kind: sum(s['access_type'] == kind for s in snapshot['sources'])
              for kind in sorted({s['access_type'] for s in snapshot['sources']})}
    result = {'snapshot': str(snapshot_path), 'snapshot_sha256': digest,
              'observations': len(snapshot['observations']), 'provinces': len(snapshot['sources']),
              'access_counts': counts, 'source_values_reviewed': True,
              'database_written': False, 'network_requests': 0}
    (out / 'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({**result, 'output_dir': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
