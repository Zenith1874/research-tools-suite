"""Official enterprise, capacity and annual livelihood release parsers.

This module contains only source definitions and pure parsing. Cumulative flows,
month-end stocks, official comparable growth and annual counts stay separate.
"""
import re
import unicodedata

from bs4 import BeautifulSoup


EXTENDED_INDICATORS = {
    'CN_IND_PROFIT_YTD': ('规上工业企业利润总额累计', '亿元', 'monthly'),
    'CN_IND_PROFIT_YTD_YOY': ('规上工业利润累计同比（官方可比口径）', '%', 'monthly'),
    'CN_IND_PROFIT_MONTH_YOY': ('规上工业利润当月同比（官方）', '%', 'monthly'),
    'CN_IND_REVENUE_YTD': ('规上工业营业收入累计', '亿元', 'monthly'),
    'CN_IND_REVENUE_YTD_YOY': ('规上工业营收累计同比（官方可比口径）', '%', 'monthly'),
    'CN_IND_COST_YTD': ('规上工业营业成本累计', '亿元', 'monthly'),
    'CN_IND_COST_YTD_YOY': ('规上工业成本累计同比（官方可比口径）', '%', 'monthly'),
    'CN_IND_PROFIT_MARGIN_YTD': ('规上工业营业收入利润率（累计）', '%', 'monthly'),
    'CN_IND_ASSETS': ('规上工业企业资产（月末）', '亿元', 'monthly'),
    'CN_IND_LIABILITIES': ('规上工业企业负债（月末）', '亿元', 'monthly'),
    'CN_IND_DEBT_ASSET_RATIO': ('规上工业资产负债率（月末）', '%', 'monthly'),
    'CN_IND_RECEIVABLES': ('规上工业应收账款（月末）', '亿元', 'monthly'),
    'CN_IND_RECEIVABLES_YOY': ('规上工业应收账款同比（官方）', '%', 'monthly'),
    'CN_IND_FINISHED_INVENTORY': ('规上工业产成品存货（月末）', '亿元', 'monthly'),
    'CN_IND_FINISHED_INVENTORY_YOY': ('规上工业产成品存货同比（官方）', '%', 'monthly'),
    'CN_IND_INVENTORY_DAYS': ('规上工业产成品存货周转天数', '天', 'monthly'),
    'CN_IND_RECEIVABLE_DAYS': ('规上工业应收账款平均回收期', '天', 'monthly'),
    'CN_CAPACITY_UTILIZATION': ('全国工业产能利用率', '%', 'quarterly'),
    'CN_CONSUMPTION_PC': ('全国居民人均消费支出', '元/人', 'annual'),
    'CN_DISPOSABLE_INCOME_MEDIAN': ('全国居民人均可支配收入中位数', '元/人', 'annual'),
    'CN_INCOME_URBAN': ('城镇居民人均可支配收入', '元/人', 'annual'),
    'CN_INCOME_RURAL': ('农村居民人均可支配收入', '元/人', 'annual'),
    'CN_INCOME_REAL_YOY': ('全国居民收入实际同比', '%', 'annual'),
    'CN_CONSUMPTION_REAL_YOY': ('全国居民消费支出实际同比', '%', 'annual'),
    'CN_URBANIZATION_RATE': ('常住人口城镇化率', '%', 'annual'),
    'CN_POP_60_PLUS': ('60岁及以上人口', '万人', 'annual'),
    'CN_POP_65_PLUS': ('65岁及以上人口', '万人', 'annual'),
    'CN_MIGRANT_WORKERS': ('全国农民工总量', '万人', 'annual'),
    'CN_MIGRANT_MONTHLY_INCOME': ('农民工月均收入（年度调查）', '元/人/月', 'annual'),
}
ANNUAL_RELEASE_CODES = (
    'CN_DEATHS', 'CN_URBAN_NEW_JOBS', 'CN_WORKING_AGE_POP',
    *[code for code, meta in EXTENDED_INDICATORS.items() if meta[2] == 'annual'],
)


def clean_text(html):
    return re.sub(r'\s+', '', BeautifulSoup(html or '', 'html.parser').get_text(' ', strip=True))


def _exact_survey_months(scope, year):
    """Read ordered explicit month/value lists and single months, not rate ranges."""
    values={};ambiguous=set()
    def add(month,value):
        if not 1<=month<=12 or not 0<=value<=100:
            return
        if month in values and abs(values[month]-value)>1e-8:
            ambiguous.add(month)
        values[month]=value
    def same_year(match):
        declared=match.group('year')
        prefix=scope[max(0,match.start()-8):match.start()]
        return (not declared or int(declared)==int(year)) and not re.search(r'上年|去年',prefix)
    month_expression=r'\d{1,2}(?:月)?(?:[、和至—－-]\d{1,2}(?:月)?)+'
    pair=re.compile(r'(?:(?P<year>20\d{2})年)?(?<!\d)(?P<months>'+month_expression+r')月份?'
        r'(?P<middle>[^。；;]{0,55}?)(?:失业率(?:延续[^\d%。；;]{0,20}[，,])?(?:分别)?(?:为|是|升至|降至|处于)|连续回落[，,]分别(?:为|是))'
        r'(?P<rates>\d+(?:\.\d+)?%(?:[、和]\d+(?:\.\d+)?%)+)')
    pair_spans=[]
    for match in pair.finditer(scope):
        if not same_year(match) or re.search(r'岁|青年|本地|外来|大城市|平均',match['middle']):
            continue
        months=[int(value) for value in re.findall(r'\d+',match['months'])]
        if re.fullmatch(r'\d{1,2}[至—－-]\d{1,2}',match['months']):
            months=list(range(months[0],months[1]+1))
        rates=[float(value) for value in re.findall(r'\d+(?:\.\d+)?',match['rates'])]
        if len(months)!=len(rates) or len(set(months))!=len(months):
            continue
        pair_spans.append(match.span())
        for month,value in zip(months,rates):add(month,value)
    single=re.compile(r'(?:(?P<year>20\d{2})年)?(?<![\d、和至—－-])(?P<month>\d{1,2})月份'
        r'(?P<middle>[^。；;]{0,100}?)失业率(?:为|是|升至|降至|上升至|下降至|回落至)'
        r'[^\d。；;]{0,12}?(?P<value>\d+(?:\.\d+)?)%')
    for match in single.finditer(scope):
        if any(start<=match.start()<end for start,end in pair_spans) or not same_year(match):continue
        if re.search(r'岁|青年|本地|外来|大城市|平均|\d{1,2}月份',match['middle']):continue
        add(int(match['month']),float(match['value']))
    rows = [(f'{int(year)}-{month:02d}', 'CN_UNEMP_SURVEY', value)
            for month, value in sorted(values.items()) if month not in ambiguous]
    conflicts = {(f'{int(year)}-{month:02d}', 'CN_UNEMP_SURVEY') for month in ambiguous}
    return rows, conflicts


def parse_reported_survey_month_details(html, year, *, year_is_validated=False):
    """Return exact national monthly rates plus conflicts that must remain unavailable."""
    soup=BeautifulSoup(html or '', 'html.parser')
    paragraphs=[re.sub(r'\s+','',node.get_text(' ',strip=True)) for node in soup.find_all('p')]
    if not paragraphs:paragraphs=[clean_text(html)]
    headings=''.join(node.get_text('',strip=True) for node in soup.find_all(['title','h1','h2']))
    heading_years={int(value) for value in re.findall(r'(20\d{2})年(?=[^日]{0,45}(?:就业|经济))',headings)}
    intro_years={int(match[1]) for paragraph in paragraphs if '就业' in paragraph
                 for match in [re.match(r'^(20\d{2})年[，,]',paragraph)] if match}
    rows={};conflicts=set()
    for paragraph in paragraphs:
        if '全国城镇调查失业率' not in paragraph:continue
        declared=re.match(r'^(20\d{2})年[，,]',paragraph)
        if declared:
            if int(declared[1])!=int(year):continue
        elif not year_is_validated and int(year) not in heading_years and int(year) not in intro_years:
            continue
        national_start=paragraph.find('全国城镇调查失业率')
        sentence_start=paragraph.rfind('。',0,national_start)+1
        scope=re.split(r'31个大城市|本地户籍|外来(?:农业)?户籍|(?:16|25|30)[—-](?:24|59)岁',paragraph[sentence_start:],maxsplit=1)[0]
        paragraph_rows, paragraph_conflicts = _exact_survey_months(scope, year)
        conflicts.update(paragraph_conflicts)
        for period,code,value in paragraph_rows:
            key=(period,code)
            if key in rows and abs(rows[key]-value)>1e-8:conflicts.add(key)
            rows[key]=value
    valid_rows = [(period, code, value) for (period, code), value in sorted(rows.items())
                  if (period, code) not in conflicts]
    return {'rows': valid_rows, 'conflicts': sorted(conflicts)}


def parse_reported_survey_months(html, year, *, year_is_validated=False):
    """Read a national paragraph; the caller may provide an independently checked year."""
    return parse_reported_survey_month_details(
        html, year, year_is_validated=year_is_validated)['rows']


def parse_reported_city_survey_month_details(html, year, *, year_is_validated=False):
    """Read explicitly dated 31-city rates, including separately stated ordered lists.

    A shared month list in the same national/31-city paragraph is valid context.
    The city values must still be stated separately; averages and missing months
    are never allocated, carried forward, or copied from the national series.
    """
    soup = BeautifulSoup(html or '', 'html.parser')
    paragraphs = [re.sub(r'\s+', '', unicodedata.normalize('NFKC', node.get_text(' ', strip=True)))
                  for node in soup.find_all('p')]
    if not paragraphs:
        paragraphs = [re.sub(r'\s+', '', unicodedata.normalize('NFKC', soup.get_text(' ', strip=True)))]
    headings = ''.join(node.get_text('', strip=True) for node in soup.find_all(['title', 'h1', 'h2']))
    heading_valid = bool(re.search(str(int(year)) + r'年[^日]{0,45}(?:就业|经济)', headings))
    month_pattern = re.compile(
        r'(?:(?P<year>20\d{2})年)?(?<![\d、和至—－-])'
        r'(?P<months>\d{1,2}(?:月)?(?:[、和至—－-]\d{1,2}(?:月)?)*)月份?')
    city_pattern = re.compile(
        r'31个大城市(?:城镇)?调查失业率(?P<verb>分别(?:为|是)|为|是|升至|降至|上升至|下降至|回落至)'
        r'(?P<rates>\d+(?:\.\d+)?%(?:[、和]\d+(?:\.\d+)?%)*)')
    values, conflicts = {}, set()
    for paragraph in paragraphs:
        if not year_is_validated and not heading_valid and not paragraph.startswith(str(int(year)) + '年'):
            continue
        for match in city_pattern.finditer(paragraph):
            prefix = paragraph[:match.start()]
            # A comparison such as "down from February" does not move a March
            # observation to February. Keep the explicit observation anchor.
            dates = [date for date in month_pattern.finditer(prefix)
                     if not re.search(r'(?:比|较|与)(?:上年|去年)?$',
                                      prefix[max(0, date.start()-6):date.start()])]
            if not dates:
                continue
            date = dates[-1]
            if match.start() - date.end() > 500:
                continue
            if (date['year'] and int(date['year']) != int(year)
                    or re.search(r'上年|去年', prefix[max(0, date.start()-6):date.start()])):
                continue
            expression = date['months'].replace('月', '')
            months = [int(value) for value in re.findall(r'\d+', expression)]
            if re.fullmatch(r'\d{1,2}[至—－-]\d{1,2}', expression):
                months = list(range(months[0], months[1] + 1))
            rates = [float(value) for value in re.findall(r'\d+(?:\.\d+)?', match['rates'])]
            if (len(months) != len(rates) or len(set(months)) != len(months)
                    or any(not 1 <= month <= 12 for month in months)
                    or any(not 0 <= value <= 100 for value in rates)
                    or len(months) > 1 and not match['verb'].startswith('分别')):
                continue
            for month, value in zip(months, rates):
                key = (f'{int(year)}-{month:02d}', 'CN_UNEMP_31_CITIES')
                if key in values and abs(values[key] - value) > 1e-8:
                    conflicts.add(key)
                values[key] = value
    return {'rows': [(period, code, value) for (period, code), value in sorted(values.items())
                     if (period, code) not in conflicts], 'conflicts': sorted(conflicts)}


def parse_annual_unemployment_commentary(html, year):
    """Compatibility entry point; commentary still requires a declared reporting year."""
    return parse_reported_survey_months(html,year)


def number(value):
    text = str(value).replace(',', '').replace('，', '').strip()
    return float(text) if re.fullmatch(r'-?\d+(?:\.\d+)?', text) else None


def table_rows(table):
    return [[re.sub(r'\s+', '', cell.get_text(' ', strip=True))
             for cell in row.find_all(['td', 'th'])] for row in table.find_all('tr')]


def profit_period(title, url=''):
    match = re.match(r'^(20\d{2})年(?:1[—－–-](\d{1,2})月份?|全年|全国)'
                     r'.*?规模以上工业企业', title)
    if match:
        return f"{match[1]}-{int(match[2] or 12):02d}"
    return None


def capacity_period(title, url=''):
    match = re.match(r'^(20\d{2})年([一二三四])季度.*?工业产能利用率', title)
    return f"{match[1]}-{'一二三四'.index(match[2]) * 3 + 3:02d}" if match else None


def annual_period(title, url=''):
    match = re.search(r'(20\d{2})年国民经济和社会发展统计公报', title)
    return match[1] if match else None


def parse_industrial_profit_article(html):
    text = clean_text(html)
    out = {}
    # Tables preserve precision that the prose rounds to trillions of yuan.
    for table in BeautifulSoup(html or '', 'html.parser').find_all('table'):
        rows = table_rows(table)
        header = ''.join(''.join(row) for row in rows[:3])
        total = next((row for row in rows if row and row[0] == '总计'), None)
        if total and len(total) >= 7 and all(label in header for label in ('营业收入', '营业成本', '利润总额')):
            codes = ('CN_IND_REVENUE_YTD', 'CN_IND_REVENUE_YTD_YOY',
                     'CN_IND_COST_YTD', 'CN_IND_COST_YTD_YOY',
                     'CN_IND_PROFIT_YTD', 'CN_IND_PROFIT_YTD_YOY')
            for code, cell in zip(codes, total[1:7]):
                value = number(cell)
                if value is not None:
                    out[code] = value
        if total and len(total) >= 9 and '应收账款平均回收期' in header:
            for code, position in (('CN_IND_PROFIT_MARGIN_YTD', 1),
                                   ('CN_IND_DEBT_ASSET_RATIO', 6),
                                   ('CN_IND_INVENTORY_DAYS', 7),
                                   ('CN_IND_RECEIVABLE_DAYS', 8)):
                value = number(total[position])
                if value is not None:
                    out[code] = value
    def amount(code, label, growth_code=None):
        match = re.search(label + r'([\d,.]+)(万亿元|亿元)(?:，?(?:同比|比上年(?:同期)?)?'
                          r'(增长|下降)([\d.]+)(%|倍))?', text)
        if not match:
            return
        out.setdefault(code, float(match[1].replace(',', '')) * (10000 if match[2] == '万亿元' else 1))
        if growth_code and match[4]:
            multiplier = 100 if match[5] == '倍' else 1
            out.setdefault(growth_code, float(match[4]) * multiplier * (-1 if match[3] == '下降' else 1))
    amount('CN_IND_PROFIT_YTD', r'全国规模以上工业企业实现利润总额', 'CN_IND_PROFIT_YTD_YOY')
    amount('CN_IND_REVENUE_YTD', r'规模以上工业企业实现营业收入', 'CN_IND_REVENUE_YTD_YOY')
    amount('CN_IND_COST_YTD', r'发生营业成本', 'CN_IND_COST_YTD_YOY')
    amount('CN_IND_ASSETS', r'规模以上工业企业资产总计')
    amount('CN_IND_LIABILITIES', r'负债合计')
    amount('CN_IND_RECEIVABLES', r'规模以上工业企业应收账款', 'CN_IND_RECEIVABLES_YOY')
    amount('CN_IND_FINISHED_INVENTORY', r'产成品存货', 'CN_IND_FINISHED_INVENTORY_YOY')
    for code, label, unit in (
            ('CN_IND_PROFIT_MARGIN_YTD', '营业收入利润率', '%'),
            ('CN_IND_DEBT_ASSET_RATIO', '资产负债率', '%'),
            ('CN_IND_INVENTORY_DAYS', '产成品存货周转天数', '天'),
            ('CN_IND_RECEIVABLE_DAYS', '应收账款平均回收期', '天')):
        match = re.search(label + r'(?:为)?([\d.]+)' + unit, text)
        if match:
            out.setdefault(code, float(match[1]))
    match = re.search(r'(?<![—-])\d{1,2}月份，?规模以上工业企业利润同比(增长|下降)([\d.]+)%', text)
    if match:
        out['CN_IND_PROFIT_MONTH_YOY'] = float(match[2]) * (-1 if match[1] == '下降' else 1)
    return out


def parse_capacity_article(html):
    text = clean_text(html)
    match = re.search(r'(?:全国)?工业产能利用率为([\d.]+)%', text)
    return {'CN_CAPACITY_UTILIZATION': float(match[1])} if match else {}


def parse_annual_livelihood_article(html):
    soup = BeautifulSoup(html or '', 'html.parser')
    for marker in soup.find_all('sup'):
        marker.decompose()
    text = re.sub(r'\[\d+\]|［\d+］', '', clean_text(str(soup)))
    out = {}
    fields = {
        'CN_DEATHS': (r'死亡人口([\d.]+)万人',),
        'CN_URBAN_NEW_JOBS': (r'(?:全年|全国)?城镇新增就业(?:人员|人数)?([\d.]+)万人',),
        'CN_WORKING_AGE_POP': (r'16[—－–-]59岁(?:劳动年龄)?人口(?:为)?([\d.]+)万人',),
        'CN_CONSUMPTION_PC': (r'全国居民人均消费支出([\d,.]+)元',),
        'CN_DISPOSABLE_INCOME_MEDIAN': (r'全国居民人均可支配收入中位数(?:为)?([\d,.]+)元',),
        'CN_INCOME_URBAN': (r'城镇居民人均可支配收入([\d,.]+)元',),
        'CN_INCOME_RURAL': (r'农村居民人均可支配收入([\d,.]+)元',),
        'CN_URBANIZATION_RATE': (r'常住人口城镇化率[）)]?(?:为|达到|达)?([\d.]+)%',),
        'CN_POP_60_PLUS': (r'60(?:周)?岁(?:及|和)以上人口(?:为)?([\d.]+)万人',),
        'CN_POP_65_PLUS': (r'65(?:周)?岁(?:及|和)以上人口(?:为)?([\d.]+)万人',),
        'CN_MIGRANT_WORKERS': (r'(?:全国)?农民工总量(?:为|达)?([\d.]+)万人',),
        'CN_MIGRANT_MONTHLY_INCOME': (r'(?<!外出)农民工(?:人均月收入|月均收入)(?:水平)?(?:为)?([\d.]+)元',),
    }
    for code, patterns in fields.items():
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                out[code] = float(match[1].replace(',', ''))
                break
    for table in BeautifulSoup(html or '', 'html.parser').find_all('table'):
        rows = table_rows(table)
        header = ''.join(''.join(row) for row in rows[:3])
        if '人口' not in header or '万人' not in header or '户籍' in header:
            continue
        share_header = any(len(candidate) >= 3 and candidate[0] == '指标'
                           and '年末' in candidate[1] and '比重' in candidate[2]
                           for candidate in rows)
        for row in rows:
            if len(row) < 2:
                continue
            value = number(row[1])
            if value is None:
                continue
            label = re.sub(r'\[[^]]+\]|其中[：:]?|[（(].*?[）)]', '', row[0]).replace('周岁', '岁')
            # Use the explicitly labelled population-share column, not a ratio
            # computed from independently revised population vintages.
            if label == '城镇' and len(row) >= 3 and share_header:
                share = number(row[2])
                if share is not None and 0 <= share <= 100:
                    out.setdefault('CN_URBANIZATION_RATE', share)
            for code, age in (('CN_WORKING_AGE_POP', '16—59岁'),
                              ('CN_POP_60_PLUS', '60岁及以上'),
                              ('CN_POP_65_PLUS', '65岁及以上')):
                if label.replace('-', '—') == age:
                    out[code] = value
    for code, subject in (('CN_INCOME_REAL_YOY', '全国居民人均可支配收入'),
                           ('CN_CONSUMPTION_REAL_YOY', '全国居民人均消费支出')):
        match = re.search(subject + r'[\d,.]+元[^。]{0,90}?扣除价格因素(?:，|,)?实际(增长|下降)([\d.]+)%', text)
        if match:
            out[code] = float(match[2]) * (-1 if match[1] == '下降' else 1)
    return out


COMPILED_ANNUAL_TABLES = {
    'population_china': {
        'page': 32, 'caption': '表2.2.4人口——中国', 'unit_marker': '年末人口数(万人)',
        'rows': {'CN_POP_60_PLUS': '60岁及以上', 'CN_POP_65_PLUS': '65岁及以上'},
    },
    'livelihood_china': {
        'page': 98, 'caption': '表6.2.4居民生活水平——中国', 'unit_marker': '人民币元',
        'rows': {'CN_INCOME_URBAN': '城镇居民可支配收入', 'CN_INCOME_RURAL': '农村居民可支配收入',
                 'CN_CONSUMPTION_PC': '居民人均消费支出'},
    },
}
COMPILED_ANNUAL_YEARS = (2000, *range(2013, 2023))


def parse_compiled_annual_words(words, text, profile, year):
    """Read an explicitly labelled year column using original PDF word coordinates."""
    definition = COMPILED_ANNUAL_TABLES[profile]
    normalize = lambda value: re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))
    if normalize(definition['caption']) not in normalize(text) or definition['unit_marker'] not in normalize(text):
        raise ValueError('Expected Chinese table caption and original unit are absent.')
    grouped = []
    for word in sorted(words, key=lambda item: ((item[1] + item[3]) / 2, item[0])):
        center = (word[1] + word[3]) / 2
        row = next((row for row in reversed(grouped) if abs(row['y'] - center) <= 2), None)
        if row is None:
            row = {'y': center, 'words': []}; grouped.append(row)
        row['words'].append(word)
    headers = []
    for row in grouped:
        years = sorted((word for word in row['words'] if str(word[4]) in {str(value) for value in COMPILED_ANNUAL_YEARS}), key=lambda item: item[0])
        if tuple(int(word[4]) for word in years) == COMPILED_ANNUAL_YEARS:
            headers.append(years)
    if len(headers) != 1 or year not in COMPILED_ANNUAL_YEARS:
        raise ValueError('A unique, complete original year header is required; missing years are not synthesized.')
    centers = [(word[0] + word[2]) / 2 for word in headers[0]]
    lower = centers[0] - min(b-a for a, b in zip(centers, centers[1:])) / 2
    selected = COMPILED_ANNUAL_YEARS.index(year)
    result = {}
    for code, label in definition['rows'].items():
        candidates = []
        for row in grouped:
            left = ''.join(str(word[4]) for word in sorted(row['words'], key=lambda item: item[0]) if (word[0]+word[2])/2 < lower)
            if normalize(left) != normalize(label):
                continue
            cells = [[] for _ in centers]
            for word in row['words']:
                x = (word[0] + word[2]) / 2
                if x >= lower:
                    index = min(range(len(centers)), key=lambda index: abs(centers[index]-x))
                    cells[index].append(normalize(str(word[4])))
            if any(len(cell) != 1 for cell in cells):
                raise ValueError('An original table row has an ambiguous/missing column token.')
            token = cells[selected][0].replace(',', '')
            if token in ('…', '...', '-', '—'):
                candidates.append(None)
            elif re.fullmatch(r'-?\d+(?:\.\d+)?', token):
                candidates.append(float(token))
            else:
                raise ValueError('A selected original annual cell is not a number or explicit missing marker.')
        if len(candidates) != 1:
            raise ValueError('The original target row is absent or duplicated: ' + label)
        if candidates[0] is not None:
            result[code] = candidates[0]
    return result


def parse_compiled_annual_pdf(content, profile, year):
    """Read only the already-reviewed table page, not an inferred country/age series."""
    import fitz
    with fitz.open(stream=content, filetype='pdf') as document:
        page = document[COMPILED_ANNUAL_TABLES[profile]['page'] - 1]
        return parse_compiled_annual_words(page.get_text('words'), page.get_text(), profile, year)


def parse_urbanization_retrospective(html):
    """Keep both explicitly dated official rates; never move a later rate to an earlier year."""
    text = clean_text(html)
    pairs = re.findall(r'全国常住人口城镇化率从(20\d{2})年的([\d.]+)%提高至(20\d{2})年的([\d.]+)%', text)
    if len(set(pairs)) != 1:
        return {}
    first, a, last, b = pairs[0]
    return {first: float(a), last: float(b)}
