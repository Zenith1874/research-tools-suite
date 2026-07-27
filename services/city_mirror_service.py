# -*- coding: utf-8 -*-
"""第三方镜像通道：红黑统计公报库（tjgb.hongheiku.com）。

厦门、无锡的市级站点在本机网络不可达，合肥及安徽省级站点整站 403，
南京统计局未公开公报列表路径——这四个城市拿不到官方原站。
红黑统计公报库转存了这些市统计局的公报 PDF 原件，可作为退而求其次的来源。

纪律：镜像不是官方原站。本模块产出的观测一律 data_status='official_mirror'，
来源名写明"第三方镜像"，页面单独标注，绝不与直连官方原站的值混为一谈。
上线前用已有官方值的城市（广州/深圳/苏州/常州）做逐条对照，证明镜像忠实。
"""
import re
from urllib.parse import unquote, urljoin, quote

import requests

from services.city_official_service import (
    HEADERS, extract_value, fetch, plain_text, INDICATOR_PATTERNS, drop_yoy_outliers,
)

MIRROR_HOME = 'https://tjgb.hongheiku.com/'
MIRROR_NAME = '红黑统计公报库（第三方镜像）'
# 官方原站不可达的城市走镜像；其余城市仍以官方原站为准，镜像只用于对照。
MIRROR_CITIES = {'厦门': '350200', '无锡': '320200', '合肥': '340100', '南京': '320100'}
VERIFY_CITIES = {'广州': '440100', '深圳': '440300', '苏州': '320500', '常州': '320400'}
ALL_MIRROR_CODES = {**MIRROR_CITIES, **VERIFY_CITIES}


def tag_url(city):
    return urljoin(MIRROR_HOME, 'tag/' + quote(f'{city}市'))


def discover_bulletins(city):
    """城市 tag 页列出该市历年公报；返回 {年份: (页面URL, 标题)}。"""
    html = fetch(tag_url(city))
    found = {}
    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                             html, re.S):
        title = re.sub(r'<[^>]+>', ' ', match.group(2))
        title = re.sub(r'\s+', ' ', title).strip()
        if f'{city}市' not in title or '国民经济和社会发展统计公报' not in title:
            continue
        year = re.search(r'(19|20)\d{2}', title)
        if not year:
            continue
        found.setdefault(year.group(0), (urljoin(MIRROR_HOME, match.group(1)), title))
    return found


def pdf_url(page_html):
    """公报正文以 pdf.js 内嵌，file= 参数即 PDF 实际地址。"""
    match = re.search(r'viewer\.php\?file=([^&"\'#]+)', page_html)
    return urljoin(MIRROR_HOME, unquote(match.group(1))) if match else None


def pdf_text(url, timeout=90):
    import fitz
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    if not response.content.startswith(b'%PDF'):
        raise ValueError('不是 PDF')
    with fitz.open(stream=response.content, filetype='pdf') as document:
        text = ' '.join(page.get_text() for page in document)
    return re.sub(r'\s+', ' ', text)


def collect_city(city, limit_years=None):
    rows, errors = [], []
    try:
        bulletins = discover_bulletins(city)
    except Exception as exc:
        return [], [f'{city} 镜像列表: {exc}']
    for period, (page_url, title) in sorted(bulletins.items()):
        if limit_years and period not in limit_years:
            continue
        # 镜像页两种形态：内嵌 PDF 原件，或直接把公报正文排成 HTML
        try:
            page_html = fetch(page_url)
            source = pdf_url(page_html)
            text = pdf_text(source) if source else plain_text(page_html)
            source = source or page_url
        except Exception as exc:
            errors.append(f'{city} {period}: {exc}')
            continue
        if len(text) < 1500:
            errors.append(f'{city} {period}: 正文过短（{len(text)} 字），疑似未取到公报内容')
            continue
        values = {code: extract_value(text, code) for code in INDICATOR_PATTERNS}
        gdp, revenue = values.get('nominal_gdp'), values.get('general_budget_revenue')
        if gdp and revenue and gdp < revenue * 3:
            errors.append(f'{city} {period}: GDP 与预算收入比例异常，整篇丢弃')
            continue
        for code, value in values.items():
            if value is None:
                continue
            rows.append({'city': city, 'period': period, 'indicator_code': code,
                         'value': value, 'unit': '亿元', 'source_url': page_url,
                         'source_title': title, 'pdf_url': source})
    return drop_yoy_outliers(rows), errors


def update_city_mirror(db_path, cities=None):
    """只为官方原站不可达的城市入库，且一律标成 official_mirror。"""
    import sqlite3
    from services.city_official_service import store_rows
    targets = cities or list(MIRROR_CITIES)
    all_rows, errors, per_city = [], [], {}
    for city in targets:
        rows, city_errors = collect_city(city)
        all_rows.extend(rows)
        errors.extend(city_errors)
        per_city[city] = sorted({row['period'] for row in rows})
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    try:
        counts = store_rows(
            conn, all_rows, region_codes=ALL_MIRROR_CODES, data_status='official_mirror',
            source_name_fmt='{city}市统计局（经红黑统计公报库镜像）',
            notes_prefix='本机网络无法直连该市官方原站，值取自第三方镜像转存的公报原件：')
    finally:
        conn.close()
    return {'success': bool(all_rows), 'records': counts,
            'years_by_city': per_city, 'errors': errors,
            'data_status': 'official_mirror'}


def compare_with_official(db_path, cities=None, tolerance=0.005):
    """拿镜像值和库里已有的官方直连值逐条比对，用来判断镜像是否忠实。"""
    import sqlite3
    cities = cities or list(VERIFY_CITIES)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    official = {}
    try:
        for row in conn.execute('''SELECT region_code,period,value FROM gdp_region_observations
              WHERE country_code='CN' AND indicator_code='nominal_gdp' AND data_status='official' '''):
            official[(row['region_code'], 'nominal_gdp', row['period'])] = row['value']
        for row in conn.execute('''SELECT region_code,indicator_code,period,value
              FROM regional_fiscal_observations
              WHERE government_scope='city_total' AND data_status='official' '''):
            official[(row['region_code'], row['indicator_code'], row['period'])] = row['value']
    finally:
        conn.close()
    checked, mismatches, missing = 0, [], 0
    for city in cities:
        code = ALL_MIRROR_CODES[city]
        rows, _ = collect_city(city)
        for row in rows:
            key = (code, row['indicator_code'], row['period'])
            if key not in official:
                missing += 1
                continue
            checked += 1
            base = official[key]
            if base and abs(row['value'] - base) / base > tolerance:
                mismatches.append({'city': city, 'indicator': row['indicator_code'],
                                   'period': row['period'], 'official': base,
                                   'mirror': row['value']})
    return {'checked': checked, 'mismatches': mismatches,
            'mirror_only': missing, 'tolerance': tolerance}
