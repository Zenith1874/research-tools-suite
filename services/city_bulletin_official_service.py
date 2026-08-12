# -*- coding: utf-8 -*-
"""Direct official supplements for city bulletin gaps.

The mirror backfill is useful for discovery, but a small set of recent values
can be verified directly on city/statistics-government pages.  Keep those rows
in an explicit, auditable list so a later mirror refresh cannot downgrade them
or silently replace an already revised official series.
"""
import sqlite3

from services.city_nbs_service import ensure_city_indicator_table


BEIJING_2024 = (
    'https://www.beijing.gov.cn/gongkai/shuju/tjgb/202505/'
    't20250529_4102086.html')
SHANGHAI_2024 = (
    'https://tjj.sh.gov.cn/tjgb/20250324/'
    'a7fe18c6d5c24d66bfca89c5bb4cdcfb.html')
GUANGZHOU_2024 = (
    'https://tjj.gz.gov.cn/gkmlpt/content/10/10203/'
    'mpost_10203416.html')
SHENZHEN_2024 = (
    'https://www.sz.gov.cn/cn/xxgk/zfxxgj/tjsj/tjgb/'
    'content/mpost_12190855.html')
XIAMEN_2024 = (
    'https://tjj.xm.gov.cn/zfxxgk/zfxxgkml/tjsjzl/ndgb/202503/'
    't20250326_2924164.htm')
NANJING_2024 = (
    'https://tjj.nanjing.gov.cn/njstjj/202504/'
    't20250401_5108470.html')
HEFEI_2024 = (
    'https://www.hfyaohai.gov.cn/public/19621/111162315.html')
CHANGSHA_2024 = (
    'https://tjj.hunan.gov.cn/tjfx/tjgb/szgb/zss_1/202505/'
    't20250516_33673433.html')
SHENZHEN_EMPLOYMENT_2024 = (
    'https://hrss.sz.gov.cn/gkmlpt/content/12/12004/'
    'post_12004040.html')
CHANGZHOU_2023 = (
    'https://tjj.changzhou.gov.cn/html/tjj/2024/OEJQMFCO_0305/27901.html')
CHANGZHOU_2024 = (
    'https://tjj.changzhou.gov.cn/content/suitable/show?catid=24519&id=28588')
CHANGZHOU_2025 = (
    'https://tjj.changzhou.gov.cn/content/suitable/show?catid=24519&id=29035')
SUZHOU_2024 = (
    'https://tjj.suzhou.gov.cn/sztjj/tjgb/202504/'
    'c77512c90a144784beba4870a6b5cc0d.shtml')
SUZHOU_2025 = (
    'https://tjj.suzhou.gov.cn/sztjj/tjgb/202604/'
    '3dc4b574cabd4e86b36ec5d3280e927c.shtml')
WUXI_2024 = 'https://www.wuxi.gov.cn/doc/2025/04/28/4554447.shtml'
WUXI_2025 = 'https://tj.wuxi.gov.cn/doc/2026/05/09/4772420.shtml'
WUXI_2024_PLAN = 'https://www.wuxi.gov.cn/doc/2025/03/07/4517484.shtml'
CHANGZHOU_WAGE_2024 = (
    'https://tjj.changzhou.gov.cn/html/tjj/2025/OPOEMFCL_0702/28760.html')
CHANGZHOU_WAGE_2025 = (
    'https://tjj.changzhou.gov.cn/html/tjj/2026/OPOEMFCL_0709/29110.html')
SUZHOU_WAGE_2024 = (
    'https://tjj.suzhou.gov.cn/sztjj/rdwd/202506/'
    '67e7a65c402f45f796436d45da431c03.shtml')
SUZHOU_WAGE_2025 = (
    'https://tjj.suzhou.gov.cn/sztjj/rdwd/202606/'
    '026a862b9d5e4acfae7e7d4d06d9d15d.shtml')
WUXI_WAGE_2024 = 'https://tj.wuxi.gov.cn/doc/2025/06/30/4603407.shtml'
WUXI_WAGE_2025 = 'https://tj.wuxi.gov.cn/doc/2026/07/08/4801556.shtml'
SUZHOU_COMMERCE_2024 = (
    'https://commerce.suzhou.gov.cn/szsswj/tjzl/202501/'
    'a99f5b6089344854a184d71b642938bd.shtml')


def _row(city, region_code, indicator_code, value, source_url, source_title,
         source_name, note, data_status='official_preliminary',
         unit='万人', period='2024'):
    return {
        'country_code': 'CN',
        'region_code': region_code,
        'region_name': city,
        'indicator_code': indicator_code,
        'period': str(period),
        'value': value,
        'unit': unit,
        'data_status': data_status,
        'source_name': source_name,
        'source_url': source_url,
        'source_title': source_title,
        'parser_notes': note,
    }


def _bulletin_note(period):
    return (
        f'{period}年城市统计公报直接披露；全市口径。公报年度数据为初步统计数，'
        '不把市本级、区县或省级数据下放到城市。')


_BULLETIN_NOTE = _bulletin_note('2024')


VERIFIED_OFFICIAL_ROWS = (
    _row('北京', '110000', 'resident_population', 2183.2, BEIJING_2024,
         '北京市2024年国民经济和社会发展统计公报',
         '北京市统计局、国家统计局北京调查总队', _BULLETIN_NOTE),
    _row('北京', '110000', 'urban_new_jobs', 29.9, BEIJING_2024,
         '北京市2024年国民经济和社会发展统计公报',
         '北京市统计局、国家统计局北京调查总队', _BULLETIN_NOTE),

    _row('上海', '310000', 'resident_population', 2480.26, SHANGHAI_2024,
         '2024年上海市国民经济和社会发展统计公报',
         '上海市统计局', _BULLETIN_NOTE),
    _row('上海', '310000', 'urban_new_jobs', 62.17, SHANGHAI_2024,
         '2024年上海市国民经济和社会发展统计公报',
         '上海市统计局', _BULLETIN_NOTE),

    _row('广州', '440100', 'resident_population', 1897.80, GUANGZHOU_2024,
         '2024年广州市国民经济和社会发展统计公报',
         '广州市统计局', _BULLETIN_NOTE),
    _row('广州', '440100', 'urban_new_jobs', 34.33, GUANGZHOU_2024,
         '2024年广州市国民经济和社会发展统计公报',
         '广州市统计局', _BULLETIN_NOTE),

    _row('深圳', '440300', 'resident_population', 1798.95, SHENZHEN_2024,
         '深圳市2024年国民经济和社会发展统计公报',
         '深圳市统计局、国家统计局深圳调查队', _BULLETIN_NOTE),

    _row('厦门', '350200', 'resident_population', 535.00, XIAMEN_2024,
         '厦门市2024年国民经济和社会发展统计公报',
         '厦门市统计局', _BULLETIN_NOTE),
    _row('厦门', '350200', 'urban_new_jobs', 16.82, XIAMEN_2024,
         '厦门市2024年国民经济和社会发展统计公报',
         '厦门市统计局', _BULLETIN_NOTE),

    _row('南京', '320100', 'resident_population', 957.70, NANJING_2024,
         '南京市2024年国民经济和社会发展统计公报',
         '南京市统计局', _BULLETIN_NOTE),
    _row('南京', '320100', 'urban_new_jobs', 21.94, NANJING_2024,
         '南京市2024年国民经济和社会发展统计公报',
         '南京市统计局', _BULLETIN_NOTE),

    _row('合肥', '340100', 'resident_population', 1000.2, HEFEI_2024,
         '合肥市2024年国民经济和社会发展统计公报',
         '合肥市统计局、国家统计局合肥调查队',
         _BULLETIN_NOTE + '原文由合肥市统计局、国家统计局合肥调查队发布，'
         '由合肥市瑶海区政府信息公开页托管。'),
    _row('合肥', '340100', 'urban_new_jobs', 21.43, HEFEI_2024,
         '合肥市2024年国民经济和社会发展统计公报',
         '合肥市统计局、国家统计局合肥调查队',
         _BULLETIN_NOTE + '原文由合肥市统计局、国家统计局合肥调查队发布，'
         '由合肥市瑶海区政府信息公开页托管。'),

    _row('长沙', '430100', 'resident_population', 1061.65, CHANGSHA_2024,
         '长沙市2024年国民经济和社会发展统计公报',
         '湖南省统计局（长沙市统计局公报）',
         _BULLETIN_NOTE + '来源为湖南省统计局公开的长沙市统计公报。'),
    _row('长沙', '430100', 'urban_new_jobs', 16.78, CHANGSHA_2024,
         '长沙市2024年国民经济和社会发展统计公报',
         '湖南省统计局（长沙市统计局公报）',
         _BULLETIN_NOTE + '原文措辞为“新增城镇就业人员”，按同义官方指标入库。'),
    _row('深圳', '440300', 'urban_new_jobs', 20.7, SHENZHEN_EMPLOYMENT_2024,
         '去年深圳就业登记人数稳定在1200万人以上 城镇新增就业20.7万人',
         '深圳市人力资源和社会保障局',
         '市人力资源和社会保障局年度工作会议公开报道；全市城镇新增就业，'
         '不是统计公报推算值。', data_status='official'),

    # 常州：统计局官网公报直接给出常住/户籍人口、消费、存款、交通和住房
    # 绝对值。就业部分在这些公报中写作“全年新增就业”，没有擅自映射到
    # “城镇新增就业”字段。
    _row('常州', '320400', 'resident_population', 537.50, CHANGZHOU_2023,
         '2023年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2023'), period='2023'),
    _row('常州', '320400', 'resident_population', 538.60, CHANGZHOU_2024,
         '2024年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2024')),
    _row('常州', '320400', 'registered_population', 389.91, CHANGZHOU_2024,
         '2024年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2024')),
    _row('常州', '320400', 'retail_sales', 2844.4, CHANGZHOU_2024,
         '2024年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2024'), unit='亿元'),
    _row('常州', '320400', 'household_deposits', 8236.5, CHANGZHOU_2024,
         '2024年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2024') + '住户存款余额，亿元。', unit='亿元'),
    _row('常州', '320400', 'trade_total_cny', 3273.9, CHANGZHOU_2024,
         '2024年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2024') + '货物进出口总额，亿元。', unit='亿元'),
    _row('常州', '320400', 'passenger_transport_volume', 6835.8, CHANGZHOU_2024,
         '2024年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2024') + '原文为6835.8万人次，按万人入库。', unit='万人'),
    _row('常州', '320400', 'freight_transport_volume', 17070.7, CHANGZHOU_2024,
         '2024年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2024') + '货运量17070.7万吨。', unit='万吨'),
    _row('常州', '320400', 'housing_under_construction_area', 11942.8, CHANGZHOU_2024,
         '2024年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2024') + '房屋施工面积，万平方米。', unit='万㎡'),
    _row('常州', '320400', 'housing_completed_area', 3959.4, CHANGZHOU_2024,
         '2024年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2024') + '房屋竣工面积，万平方米。', unit='万㎡'),
    _row('常州', '320400', 'new_commercial_housing_filing_area', 387.8,
         CHANGZHOU_2024, '2024年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2024') + '商品房销售备案面积，保留备案口径。', unit='万㎡'),
    _row('常州', '320400', 'medical_institutions', 2225, CHANGZHOU_2024,
         '2024年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2024') + '各级各类医疗卫生机构，个。', unit='个'),
    _row('常州', '320400', 'physicians', 1.9, CHANGZHOU_2024,
         '2024年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2024') + '执业（助理）医师，万人。', unit='万人'),

    _row('常州', '320400', 'resident_population', 541.54, CHANGZHOU_2025,
         '2025年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2025'), period='2025'),
    _row('常州', '320400', 'registered_population', 389.48, CHANGZHOU_2025,
         '2025年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2025'), period='2025'),
    _row('常州', '320400', 'retail_sales', 2918.1, CHANGZHOU_2025,
         '2025年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2025'), unit='亿元', period='2025'),
    _row('常州', '320400', 'household_deposits', 10254.0, CHANGZHOU_2025,
         '2025年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2025') + '住户存款余额，亿元。', unit='亿元', period='2025'),
    _row('常州', '320400', 'trade_total_cny', 3728.1, CHANGZHOU_2025,
         '2025年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2025') + '货物进出口总额，亿元。', unit='亿元', period='2025'),
    _row('常州', '320400', 'passenger_transport_volume', 6745.8, CHANGZHOU_2025,
         '2025年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2025') + '原文为6745.8万人次，按万人入库。', unit='万人', period='2025'),
    _row('常州', '320400', 'freight_transport_volume', 15926.3, CHANGZHOU_2025,
         '2025年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2025') + '货运量15926.3万吨。', unit='万吨', period='2025'),
    _row('常州', '320400', 'housing_under_construction_area', 8574.4, CHANGZHOU_2025,
         '2025年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2025') + '房屋施工面积，万平方米。', unit='万㎡', period='2025'),
    _row('常州', '320400', 'housing_completed_area', 3719.2, CHANGZHOU_2025,
         '2025年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2025') + '房屋竣工面积，万平方米。', unit='万㎡', period='2025'),
    _row('常州', '320400', 'new_commercial_housing_filing_area', 445.6,
         CHANGZHOU_2025, '2025年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2025') + '新建商品房销售备案面积，保留备案口径。', unit='万㎡', period='2025'),
    _row('常州', '320400', 'medical_institutions', 2295, CHANGZHOU_2025,
         '2025年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2025') + '各级各类医疗卫生机构，个。', unit='个', period='2025'),
    _row('常州', '320400', 'physicians', 1.9, CHANGZHOU_2025,
         '2025年常州市国民经济和社会发展统计公报', '常州市统计局',
         _bulletin_note('2025') + '执业（助理）医师，万人。', unit='万人', period='2025'),

    # 苏州：公报给出城镇新增就业，且部分公报字段可与现有一般指标同名对齐。
    _row('苏州', '320500', 'resident_population', 1298.7, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024')),
    _row('苏州', '320500', 'registered_population', 794.9, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024')),
    _row('苏州', '320500', 'urban_new_jobs', 41.75, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '原文为全年城镇新增就业人数。'),
    _row('苏州', '320500', 'household_deposits', 22110.2, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '住户存款余额，亿元。', unit='亿元'),
    _row('苏州', '320500', 'real_estate_investment', 2508.6, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '房地产开发投资，亿元。', unit='亿元'),
    _row('苏州', '320500', 'trade_total_cny', 26193.1, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '货物进出口总额，亿元。', unit='亿元'),
    _row('苏州', '320500', 'passenger_transport_volume', 22000.0, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '公路、水路客运量2.2亿人次，换算为22000万人次。', unit='万人'),
    _row('苏州', '320500', 'freight_transport_volume', 29000.0, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '公路、水路货运量2.9亿吨，换算为29000万吨。', unit='万吨'),
    _row('苏州', '320500', 'housing_under_construction_area', 8768.2, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '房地产开发房屋施工面积，万平方米。', unit='万㎡'),
    _row('苏州', '320500', 'housing_completed_area', 1326.4, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '房地产开发房屋竣工面积，万平方米。', unit='万㎡'),
    _row('苏州', '320500', 'commercial_housing_sold_area', 1617.3, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '商品房销售面积，万平方米。', unit='万㎡'),
    _row('苏州', '320500', 'fixed_phone_subscribers', 178.9, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '年末固定电话用户，万户。', unit='万户'),
    _row('苏州', '320500', 'medical_institutions', 4865, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '各类医疗卫生机构，个。', unit='个'),
    _row('苏州', '320500', 'hospitals', 282, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '医院数，个。', unit='个'),
    _row('苏州', '320500', 'physicians', 4.9, SUZHOU_2024,
         '2024年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2024') + '执业（助理）医师，万人。', unit='万人'),

    _row('苏州', '320500', 'resident_population', 1304.77, SUZHOU_2025,
         '2025年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2025'), period='2025'),
    _row('苏州', '320500', 'registered_population', 798.8, SUZHOU_2025,
         '2025年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2025'), period='2025'),
    _row('苏州', '320500', 'urban_new_jobs', 41.5, SUZHOU_2025,
         '2025年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2025') + '原文为全年城镇新增就业。', period='2025'),
    _row('苏州', '320500', 'retail_sales', 9092.2, SUZHOU_2025,
         '2025年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2025') + '社会消费品零售总额，亿元。', unit='亿元', period='2025'),
    _row('苏州', '320500', 'trade_total_cny', 28119.3, SUZHOU_2025,
         '2025年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2025') + '货物进出口总额，亿元。', unit='亿元', period='2025'),
    _row('苏州', '320500', 'passenger_transport_volume', 19900.0, SUZHOU_2025,
         '2025年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2025') + '公路、水路客运量1.99亿人次，换算为19900万人次。', unit='万人', period='2025'),
    _row('苏州', '320500', 'freight_transport_volume', 31400.0, SUZHOU_2025,
         '2025年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2025') + '公路、水路货运量3.14亿吨，换算为31400万吨。', unit='万吨', period='2025'),
    _row('苏州', '320500', 'fixed_phone_subscribers', 186.2, SUZHOU_2025,
         '2025年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2025') + '年末固定电话用户，万户。', unit='万户', period='2025'),
    _row('苏州', '320500', 'medical_institutions', 5027, SUZHOU_2025,
         '2025年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2025') + '各类医疗卫生机构，个。', unit='个', period='2025'),
    _row('苏州', '320500', 'hospitals', 288, SUZHOU_2025,
         '2025年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2025') + '医院数，个。', unit='个', period='2025'),
    _row('苏州', '320500', 'physicians', 5.02, SUZHOU_2025,
         '2025年苏州市国民经济和社会发展统计公报', '苏州市统计局、国家统计局苏州调查队',
         _bulletin_note('2025') + '执业（助理）医师，万人。', unit='万人', period='2025'),

    # 无锡：2024年就业值来自市发改委公布的计划执行情况，其余来自市统计局
    # 统计公报；2025年直接使用统计局/调查队联合公报。
    _row('无锡', '320200', 'resident_population', 750.50, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024')),
    _row('无锡', '320200', 'registered_population', 522.94, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024')),
    _row('无锡', '320200', 'urban_new_jobs', 14.3, WUXI_2024_PLAN,
         '无锡市2024年国民经济和社会发展计划执行情况', '无锡市发展和改革委员会',
         '市政府公开的年度计划执行情况直接披露“城镇新增就业14.3万人”；全市口径。',
         data_status='official'),
    _row('无锡', '320200', 'retail_sales', 4284.06, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024') + '社会消费品零售总额，亿元。', unit='亿元'),
    _row('无锡', '320200', 'real_estate_investment', 1233.80, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024') + '房地产开发投资，亿元。', unit='亿元'),
    _row('无锡', '320200', 'household_deposits', 13396.20, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024') + '住户存款余额，亿元。', unit='亿元'),
    _row('无锡', '320200', 'college_students', 16.52, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024') + '普通高等教育本专科在校生，万人。', unit='万人'),
    _row('无锡', '320200', 'trade_total_cny', 7709.46, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024') + '货物进出口总值，亿元。', unit='亿元'),
    _row('无锡', '320200', 'passenger_transport_volume', 15100.0, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024') + '客运量1.51亿人次，换算为15100万人次。', unit='万人'),
    _row('无锡', '320200', 'freight_transport_volume', 27100.0, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024') + '货物运输量2.71亿吨，换算为27100万吨。', unit='万吨'),
    _row('无锡', '320200', 'housing_under_construction_area', 4508.01, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024') + '商品房施工面积，万平方米。', unit='万㎡'),
    _row('无锡', '320200', 'housing_completed_area', 793.97, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024') + '商品房竣工面积，万平方米。', unit='万㎡'),
    _row('无锡', '320200', 'medical_institutions', 3596, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024') + '各级各类医疗卫生机构，个。', unit='个'),
    _row('无锡', '320200', 'physicians', 2.95, WUXI_2024,
         '2024年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2024') + '执业（助理）医师，万人。', unit='万人'),

    _row('无锡', '320200', 'resident_population', 753.74, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025'), period='2025'),
    _row('无锡', '320200', 'registered_population', 523.07, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025'), period='2025'),
    _row('无锡', '320200', 'urban_new_jobs', 14.59, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025') + '原文为全年城镇新增就业。', period='2025'),
    _row('无锡', '320200', 'retail_sales', 4418.47, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025') + '社会消费品零售总额，亿元。', unit='亿元', period='2025'),
    _row('无锡', '320200', 'real_estate_investment', 988.74, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025') + '房地产开发投资，亿元。', unit='亿元', period='2025'),
    _row('无锡', '320200', 'college_students', 16.39, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025') + '普通高等教育本专科在校生，万人。', unit='万人', period='2025'),
    _row('无锡', '320200', 'trade_total_cny', 8292.76, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025') + '货物进出口总值，亿元。', unit='亿元', period='2025'),
    _row('无锡', '320200', 'passenger_transport_volume', 15400.0, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025') + '客运量1.54亿人次，换算为15400万人次。', unit='万人', period='2025'),
    _row('无锡', '320200', 'freight_transport_volume', 26700.0, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025') + '货物运输量2.67亿吨，换算为26700万吨。', unit='万吨', period='2025'),
    _row('无锡', '320200', 'housing_under_construction_area', 5173.74, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025') + '房屋建筑施工面积，万平方米。', unit='万㎡', period='2025'),
    _row('无锡', '320200', 'housing_completed_area', 1393.10, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025') + '房屋建筑竣工面积，万平方米。', unit='万㎡', period='2025'),
    _row('无锡', '320200', 'medical_institutions', 3730, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025') + '各级各类医疗卫生机构，个。', unit='个', period='2025'),
    _row('无锡', '320200', 'physicians', 3.00, WUXI_2025,
         '2025年无锡市国民经济和社会发展统计公报', '无锡市统计局、国家统计局无锡调查队',
         _bulletin_note('2025') + '执业（助理）医师，万人。', unit='万人', period='2025'),

    # 三市统计局工资专题发布：统一取城镇非私营单位在岗职工年平均工资。
    _row('常州', '320400', 'avg_wage', 135233, CHANGZHOU_WAGE_2024,
         '2024年常州市城镇单位就业人员年平均工资情况', '常州市统计局',
         '统计局工资专题直接披露；城镇非私营单位在岗职工年平均工资，单位为元；'
         '不与居民人均可支配收入或私营单位工资混用。',
         data_status='official', unit='元', period='2024'),
    _row('常州', '320400', 'avg_wage', 136356, CHANGZHOU_WAGE_2025,
         '2025年常州市城镇单位就业人员年平均工资情况', '常州市统计局',
         '统计局工资专题直接披露；城镇非私营单位在岗职工年平均工资，单位为元；'
         '不与居民人均可支配收入或私营单位工资混用。',
         data_status='official', unit='元', period='2025'),
    _row('苏州', '320500', 'avg_wage', 143611, SUZHOU_WAGE_2024,
         '2024年度苏州市城镇非私营单位在岗职工年平均工资', '苏州市统计局',
         '统计局专题问答直接披露；城镇非私营单位在岗职工年平均工资，单位为元；'
         '不与居民人均可支配收入或私营单位工资混用。',
         data_status='official', unit='元', period='2024'),
    _row('苏州', '320500', 'avg_wage', 148364, SUZHOU_WAGE_2025,
         '2025年度苏州市城镇非私营单位在岗职工年平均工资', '苏州市统计局',
         '统计局专题问答直接披露；城镇非私营单位在岗职工年平均工资，单位为元；'
         '不与居民人均可支配收入或私营单位工资混用。',
         data_status='official', unit='元', period='2025'),
    _row('无锡', '320200', 'avg_wage', 140941, WUXI_WAGE_2024,
         '2024年无锡市城镇单位就业人员年平均工资', '无锡市统计局',
         '统计局公告直接披露；城镇非私营单位在岗职工年平均工资，单位为元；'
         '不与居民人均可支配收入或私营单位工资混用。',
         data_status='official', unit='元', period='2024'),
    _row('无锡', '320200', 'avg_wage', 147293, WUXI_WAGE_2025,
         '2025年无锡市城镇单位就业人员年平均工资', '无锡市统计局',
         '统计局公告直接披露；城镇非私营单位在岗职工年平均工资，单位为元；'
         '不与居民人均可支配收入或私营单位工资混用。',
         data_status='official', unit='元', period='2025'),
    _row('苏州', '320500', 'retail_sales', 10043.7, SUZHOU_COMMERCE_2024,
         '苏州市2024年1-12月商务运行简况', '苏州市商务局',
         '商务局年度运行简况直接披露1—12月全市社会消费品零售总额；单位为亿元；'
         '补齐统计公报只披露增速的2024年水平值。',
         data_status='official_preliminary', unit='亿元', period='2024'),
)


_STATUS_PRIORITY = {
    'official_mirror': 0,
    'official_preliminary': 1,
    'official': 2,
    'official_revised': 3,
}


def _upsert_official_indicator(conn, row):
    """Insert only when the incoming source is at least as authoritative."""
    existing = conn.execute('''SELECT data_status FROM city_indicator_observations
      WHERE country_code=? AND region_code=? AND indicator_code=? AND period=?''',
      (row['country_code'], row['region_code'], row['indicator_code'], row['period'])).fetchone()
    if existing and _STATUS_PRIORITY.get(existing[0], 99) >= _STATUS_PRIORITY[row['data_status']]:
        return 'skipped'
    conn.execute('''INSERT INTO city_indicator_observations
      (country_code,region_code,region_name,indicator_code,period,value,unit,data_status,
       source_name,source_url,source_title,parser_notes,updated_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
      ON CONFLICT(country_code,region_code,indicator_code,period) DO UPDATE SET
        region_name=excluded.region_name,value=excluded.value,unit=excluded.unit,
        data_status=excluded.data_status,source_name=excluded.source_name,
        source_url=excluded.source_url,source_title=excluded.source_title,
        parser_notes=excluded.parser_notes,updated_at=excluded.updated_at''',
      (row['country_code'], row['region_code'], row['region_name'], row['indicator_code'],
       row['period'], row['value'], row['unit'], row['data_status'], row['source_name'],
       row['source_url'], row['source_title'], row['parser_notes']))
    return 'replaced' if existing else 'inserted'


def update_city_bulletin_official(db_path):
    """Idempotently add the directly verified city-bulletin supplement."""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    counts = {'inserted': 0, 'replaced': 0, 'skipped': 0}
    try:
        ensure_city_indicator_table(conn)
        for row in VERIFIED_OFFICIAL_ROWS:
            counts[_upsert_official_indicator(conn, row)] += 1
        conn.commit()
    finally:
        conn.close()
    return {
        'success': True,
        'observations_processed': len(VERIFIED_OFFICIAL_ROWS),
        **counts,
        'cities': sorted({row['region_name'] for row in VERIFIED_OFFICIAL_ROWS}),
        'periods': sorted({row['period'] for row in VERIFIED_OFFICIAL_ROWS}),
        'source': 'city/statistics government bulletins',
    }
