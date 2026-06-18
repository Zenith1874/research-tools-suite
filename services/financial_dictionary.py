"""Financial indicator definitions used by the API and dashboard."""

SOURCE_REGISTRY = {
    'pboc_financial_statistics_report': {
        'source_name': '中国人民银行',
        'source_type': 'pboc_monthly',
        'source_label': '中国人民银行金融统计数据报告',
        'entry_url': 'https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html',
        'candidate_paths': ['沟通交流 / 新闻发布 / 金融统计数据报告'],
        'parser_notes': '从金融统计数据报告正文的货币供应、贷款、存款和银行间市场利率段落解析。'
    },
    'pboc_tsf_stock_report': {
        'source_name': '中国人民银行',
        'source_type': 'pboc_monthly',
        'source_label': '中国人民银行社会融资规模存量统计数据报告',
        'entry_url': 'https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html',
        'candidate_paths': ['沟通交流 / 新闻发布 / 社会融资规模存量统计数据报告'],
        'parser_notes': '优先从社会融资规模存量统计数据报告解析；当前已缓存月份若原文来自金融统计数据报告，则记录具体公告原文 URL。'
    },
    'pboc_tsf_increment_report': {
        'source_name': '中国人民银行',
        'source_type': 'pboc_monthly',
        'source_label': '中国人民银行社会融资规模增量统计数据报告',
        'entry_url': 'https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html',
        'candidate_paths': ['沟通交流 / 新闻发布 / 社会融资规模增量统计数据报告'],
        'parser_notes': '用于社融增量、政府债券融资、企业债券融资和对实体经济人民币贷款增量；未实现稳定抓取时不得生成 mock。'
    },
    'mof_local_debt_statistics': {
        'source_name': '财政部债务管理司',
        'source_type': 'mof_local_debt',
        'source_label': '财政部债务管理司：统计数据',
        'entry_url': 'https://zwgls.mof.gov.cn/tjsj/',
        'candidate_paths': ['债务管理司 / 统计数据'],
        'parser_notes': '候选入口，用于发现每月地方政府债券发行和债务余额情况原文页面。'
    },
    'mof_budget_local_debt_backup': {
        'source_name': '财政部预算司',
        'source_type': 'mof_local_debt',
        'source_label': '财政部预算司：地方政府债务管理 / 数据统计（备用）',
        'entry_url': 'https://yss.mof.gov.cn/',
        'candidate_paths': ['预算司 / 地方政府债务管理 / 数据统计'],
        'parser_notes': '地方债数据备用入口。'
    },
    'treasury_debt_placeholder': {
        'source_name': '财政部/债券市场公开信息',
        'source_type': 'treasury_debt',
        'source_label': '国债数据源待接入',
        'entry_url': None,
        'candidate_paths': [
            '财政部国债管理相关公告 / 国债发行兑付公告',
            '中国债券信息网',
            '中央国债登记结算有限责任公司相关公开统计',
            '上海证券交易所 / 深圳证券交易所债券信息公开页面',
        ],
        'parser_notes': '仅登记候选来源；未实现稳定抓取前 API 返回 missing，不生成 mock。'
    },
}

SOURCE_BY_INDICATOR = {
    'M2_BALANCE': 'pboc_financial_statistics_report',
    'M2_YOY': 'pboc_financial_statistics_report',
    'M1_BALANCE': 'pboc_financial_statistics_report',
    'M1_YOY': 'pboc_financial_statistics_report',
    'M0_YOY': 'pboc_financial_statistics_report',
    'RMB_LOAN_BALANCE': 'pboc_financial_statistics_report',
    'RMB_LOAN_YOY': 'pboc_financial_statistics_report',
    'RMB_DEPOSIT_BALANCE': 'pboc_financial_statistics_report',
    'RMB_DEPOSIT_YOY': 'pboc_financial_statistics_report',
    'IBOR_WEIGHTED_AVG': 'pboc_financial_statistics_report',
    'PLEDGED_REPO_WEIGHTED_AVG': 'pboc_financial_statistics_report',
    'TSF_STOCK': 'pboc_tsf_stock_report',
    'TSF_YOY': 'pboc_tsf_stock_report',
    'TSF_INCREMENT_CURRENT_MONTH': 'pboc_tsf_increment_report',
    'TSF_INCREMENT_YTD': 'pboc_tsf_increment_report',
    'GOVERNMENT_BOND_FINANCING_YTD': 'pboc_tsf_increment_report',
    'CORPORATE_BOND_FINANCING_YTD': 'pboc_tsf_increment_report',
    'RMB_LOANS_TO_REAL_ECONOMY_YTD': 'pboc_tsf_increment_report',
}

INDICATORS = {
    'M2_YOY': {
        'indicator_code': 'M2_YOY', 'display_name': 'M2同比增速', 'category': 'pboc_monthly',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '%',
        'unit_display': '%', 'scale_factor': 1, 'is_stock': False, 'is_flow': False,
        'is_ytd': False, 'description': '广义货币M2同比增速', 'notes': '央行月度金融统计数据报告'
    },
    'M1_YOY': {
        'indicator_code': 'M1_YOY', 'display_name': 'M1同比增速', 'category': 'pboc_monthly',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '%',
        'unit_display': '%', 'scale_factor': 1, 'is_stock': False, 'is_flow': False,
        'is_ytd': False, 'description': '狭义货币M1同比增速', 'notes': '2025-01起M1统计口径调整'
    },
    'M0_YOY': {
        'indicator_code': 'M0_YOY', 'display_name': 'M0同比增速', 'category': 'pboc_monthly',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '%',
        'unit_display': '%', 'scale_factor': 1, 'is_stock': False, 'is_flow': False,
        'is_ytd': False, 'description': '流通中货币M0同比增速', 'notes': ''
    },
    'M2_BALANCE': {
        'indicator_code': 'M2_BALANCE', 'display_name': 'M2余额', 'category': 'pboc_monthly',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '万亿元',
        'unit_display': '万亿元', 'scale_factor': 1, 'is_stock': True, 'is_flow': False,
        'is_ytd': False, 'description': '广义货币M2月末余额', 'notes': '时点余额'
    },
    'M1_BALANCE': {
        'indicator_code': 'M1_BALANCE', 'display_name': 'M1余额', 'category': 'pboc_monthly',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '万亿元',
        'unit_display': '万亿元', 'scale_factor': 1, 'is_stock': True, 'is_flow': False,
        'is_ytd': False, 'description': '狭义货币M1月末余额', 'notes': '2025-01起新口径'
    },
    'TSF_STOCK': {
        'indicator_code': 'TSF_STOCK', 'display_name': '社融存量', 'category': 'pboc_monthly',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '万亿元',
        'unit_display': '万亿元', 'scale_factor': 1, 'is_stock': True, 'is_flow': False,
        'is_ytd': False, 'description': '社会融资规模存量', 'notes': ''
    },
    'TSF_YOY': {
        'indicator_code': 'TSF_YOY', 'display_name': '社融存量同比', 'category': 'pboc_monthly',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '%',
        'unit_display': '%', 'scale_factor': 1, 'is_stock': False, 'is_flow': False,
        'is_ytd': False, 'description': '社会融资规模存量同比增速', 'notes': ''
    },
    'RMB_LOAN_BALANCE': {
        'indicator_code': 'RMB_LOAN_BALANCE', 'display_name': '人民币贷款余额', 'category': 'pboc_monthly',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '万亿元',
        'unit_display': '万亿元', 'scale_factor': 1, 'is_stock': True, 'is_flow': False,
        'is_ytd': False, 'description': '月末人民币贷款余额', 'notes': ''
    },
    'RMB_LOAN_YOY': {
        'indicator_code': 'RMB_LOAN_YOY', 'display_name': '人民币贷款余额同比', 'category': 'pboc_monthly',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '%',
        'unit_display': '%', 'scale_factor': 1, 'is_stock': False, 'is_flow': False,
        'is_ytd': False, 'description': '人民币贷款余额同比增速', 'notes': ''
    },
    'RMB_DEPOSIT_BALANCE': {
        'indicator_code': 'RMB_DEPOSIT_BALANCE', 'display_name': '人民币存款余额', 'category': 'pboc_monthly',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '万亿元',
        'unit_display': '万亿元', 'scale_factor': 1, 'is_stock': True, 'is_flow': False,
        'is_ytd': False, 'description': '月末人民币存款余额', 'notes': ''
    },
    'RMB_DEPOSIT_YOY': {
        'indicator_code': 'RMB_DEPOSIT_YOY', 'display_name': '人民币存款余额同比', 'category': 'pboc_monthly',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '%',
        'unit_display': '%', 'scale_factor': 1, 'is_stock': False, 'is_flow': False,
        'is_ytd': False, 'description': '人民币存款余额同比增速', 'notes': ''
    },
    'IBOR_WEIGHTED_AVG': {
        'indicator_code': 'IBOR_WEIGHTED_AVG', 'display_name': '同业拆借加权平均利率', 'category': 'rate',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '%',
        'unit_display': '%', 'scale_factor': 1, 'is_stock': False, 'is_flow': False,
        'is_ytd': False, 'description': '银行间同业拆借月加权平均利率', 'notes': ''
    },
    'PLEDGED_REPO_WEIGHTED_AVG': {
        'indicator_code': 'PLEDGED_REPO_WEIGHTED_AVG', 'display_name': '质押式回购加权平均利率', 'category': 'rate',
        'source_type': 'pboc_monthly', 'frequency': 'monthly', 'unit_raw': '%',
        'unit_display': '%', 'scale_factor': 1, 'is_stock': False, 'is_flow': False,
        'is_ytd': False, 'description': '银行间质押式回购月加权平均利率', 'notes': ''
    },
}

_EXTRA = [
    ('HOUSEHOLD_LOAN_BALANCE', '住户贷款余额', '万亿元', True, False),
    ('HOUSEHOLD_SHORT_LOAN_BALANCE', '住户短期贷款余额', '万亿元', True, False),
    ('HOUSEHOLD_LONG_LOAN_BALANCE', '住户中长期贷款余额', '万亿元', True, False),
    ('CORPORATE_LOAN_BALANCE', '企事业单位贷款余额', '万亿元', True, False),
    ('CORPORATE_SHORT_LOAN_BALANCE', '企事业单位短期贷款余额', '万亿元', True, False),
    ('CORPORATE_LONG_LOAN_BALANCE', '企事业单位中长期贷款余额', '万亿元', True, False),
    ('BILL_FINANCING_BALANCE', '票据融资余额', '万亿元', True, False),
    ('HOUSEHOLD_LOAN_YTD', '住户贷款年初至今新增', '万亿元', False, True),
    ('CORPORATE_LOAN_YTD', '企业贷款年初至今新增', '万亿元', False, True),
    ('HOUSEHOLD_DEPOSIT_YTD', '住户存款年初至今新增', '万亿元', False, True),
    ('CORPORATE_DEPOSIT_YTD', '企业存款年初至今新增', '万亿元', False, True),
    ('GOVERNMENT_BOND_FINANCING_YTD', '政府债券融资年初至今新增', '万亿元', False, True),
    ('TSF_INCREMENT_CURRENT_MONTH', '社会融资规模当月增量', '万亿元', False, False),
    ('TSF_INCREMENT_YTD', '社会融资规模年初至今增量', '万亿元', False, True),
    ('CORPORATE_BOND_FINANCING_YTD', '企业债券融资年初至今新增', '万亿元', False, True),
    ('RMB_LOANS_TO_REAL_ECONOMY_YTD', '对实体经济人民币贷款年初至今新增', '万亿元', False, True),
    ('USD_CNY', '美元人民币', '', False, False),
    ('SHANGHAI_COMPOSITE', '上证指数', '点', False, False),
    ('CSI_300', '沪深300', '点', False, False),
    ('CN_10Y_BOND_YIELD', '中国10年期国债收益率', '%', False, False),
    ('LPR_1Y', '1年期LPR', '%', False, False),
    ('LPR_5Y', '5年期以上LPR', '%', False, False),
    ('COMEX_GOLD', 'COMEX黄金', '美元/盎司', False, False),
    ('WTI_CRUDE', 'WTI原油', '美元/桶', False, False),
]

for code, name, unit, is_stock, is_ytd in _EXTRA:
    INDICATORS.setdefault(code, {
        'indicator_code': code, 'display_name': name, 'category': 'structure',
        'source_type': 'pboc_monthly' if 'USD_' not in code and code not in {'SHANGHAI_COMPOSITE', 'CSI_300', 'COMEX_GOLD', 'WTI_CRUDE'} else 'market',
        'frequency': 'monthly', 'unit_raw': unit, 'unit_display': unit, 'scale_factor': 1,
        'is_stock': is_stock, 'is_flow': not is_stock, 'is_ytd': is_ytd,
        'description': name, 'notes': '预留或结构指标'
    })

FIELD_TO_INDICATOR = {
    'M2': 'M2_BALANCE', 'M2y': 'M2_YOY', 'M1': 'M1_BALANCE', 'M1y': 'M1_YOY', 'M0y': 'M0_YOY',
    'SF': 'TSF_STOCK', 'SFy': 'TSF_YOY', 'loan': 'RMB_LOAN_BALANCE', 'loany': 'RMB_LOAN_YOY',
    'dep': 'RMB_DEPOSIT_BALANCE', 'depy': 'RMB_DEPOSIT_YOY', 'ibor': 'IBOR_WEIGHTED_AVG',
    'repo': 'PLEDGED_REPO_WEIGHTED_AVG', 'loan_hh_bal': 'HOUSEHOLD_LOAN_BALANCE',
    'loan_hh_st_bal': 'HOUSEHOLD_SHORT_LOAN_BALANCE', 'loan_hh_lt_bal': 'HOUSEHOLD_LONG_LOAN_BALANCE',
    'loan_corp_bal': 'CORPORATE_LOAN_BALANCE', 'loan_corp_st_bal': 'CORPORATE_SHORT_LOAN_BALANCE',
    'loan_corp_lt_bal': 'CORPORATE_LONG_LOAN_BALANCE', 'loan_bill_bal': 'BILL_FINANCING_BALANCE',
    'loan_hh_ytd': 'HOUSEHOLD_LOAN_YTD', 'loan_corp_ytd': 'CORPORATE_LOAN_YTD',
}
