#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract a compact China housing-demography snapshot from UN WPP 2024.

The upstream file is an official, versioned UN CSV compressed with gzip.  This
script streams it, keeps only China and the four dashboard years, and writes a
small auditable CSV.  It does not turn projections into observations.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import math
import os
import tempfile
import urllib.request
from datetime import date
from pathlib import Path


SOURCE_URL = (
    'https://population.un.org/wpp/assets/Excel%20Files/'
    '1_Indicator%20(Standard)/CSV_FILES/'
    'WPP2024_Population1JanuaryByAge5GroupSex_Medium.csv.gz'
)
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / 'data' / 'housing_demographic_capacity_inputs.csv'
)
DEFAULT_YEARS = (2025, 2030, 2040, 2050)
FIELDNAMES = (
    'indicator_code', 'period', 'value', 'unit', 'data_status',
    'source_name', 'source_url', 'parser_notes',
)


def extract_china_age_groups(stream, years=DEFAULT_YEARS):
    """Return total, age 20-39, and age 60+ population in thousands."""
    wanted = {int(year) for year in years}
    totals = {
        year: {'un_total_population_1jan': 0.0,
               'un_population_age_20_39': 0.0,
               'un_population_age_60_plus': 0.0,
               'groups': 0}
        for year in wanted
    }
    with gzip.GzipFile(fileobj=stream) as zipped:
        text = io.TextIOWrapper(zipped, encoding='utf-8-sig', newline='')
        for row in csv.DictReader(text):
            if row.get('ISO3_code') != 'CHN':
                continue
            year = int(row['Time'])
            if year not in wanted:
                continue
            age_start = int(row['AgeGrpStart'])
            value = float(row['PopTotal'])
            if not math.isfinite(value) or value < 0:
                raise ValueError(f'Invalid WPP population value: {year} {row["AgeGrp"]}')
            totals[year]['un_total_population_1jan'] += value
            if 20 <= age_start < 40:
                totals[year]['un_population_age_20_39'] += value
            if age_start >= 60:
                totals[year]['un_population_age_60_plus'] += value
            totals[year]['groups'] += 1
    for year, values in totals.items():
        if values['groups'] < 21:
            raise ValueError(f'Incomplete China age groups for {year}: {values["groups"]}')
        if not (0 < values['un_population_age_20_39'] <
                values['un_total_population_1jan']):
            raise ValueError(f'Invalid age 20-39 aggregate for {year}')
        if not (0 < values['un_population_age_60_plus'] <
                values['un_total_population_1jan']):
            raise ValueError(f'Invalid age 60+ aggregate for {year}')
    return totals


def build_rows(totals, retrieved_on=None):
    retrieved_on = retrieved_on or date.today().isoformat()
    labels = {
        'un_total_population_1jan': '各年龄组加总；1月1日人口',
        'un_population_age_20_39': '20-24至35-39岁组加总；1月1日人口',
        'un_population_age_60_plus': '60-64岁至100岁以上组加总；1月1日人口',
    }
    rows = []
    for year in sorted(totals):
        for indicator_code in labels:
            rows.append({
                'indicator_code': indicator_code,
                'period': str(year),
                'value': f'{totals[year][indicator_code]:.3f}',
                'unit': '千人',
                'data_status': 'official_projection',
                'source_name': 'United Nations, DESA, Population Division · WPP 2024',
                'source_url': SOURCE_URL,
                'parser_notes': (
                    f'WPP2024 Medium variant；{labels[indicator_code]}；'
                    f'提取日期 {retrieved_on}'
                ),
            })
    return rows


def write_rows(rows, output_path):
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode='w', encoding='utf-8-sig', newline='', delete=False,
        dir=output.parent, prefix=output.name + '.', suffix='.tmp')
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(handle.name, output)
    except Exception:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--timeout', type=float, default=90.0)
    args = parser.parse_args()
    request = urllib.request.Request(
        SOURCE_URL, headers={'User-Agent': 'ChinaMacroResearch/1.0'})
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        totals = extract_china_age_groups(response)
    output = write_rows(build_rows(totals), args.output)
    print(f'wrote {len(DEFAULT_YEARS) * 3} rows to {output}')


if __name__ == '__main__':
    main()
