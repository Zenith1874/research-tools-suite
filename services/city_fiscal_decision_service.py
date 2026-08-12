# -*- coding: utf-8 -*-
"""城市财政决算直接披露值。

部分财政局只以大表 PDF 发布，且同一文件混有全市、市级和区县口径。这里仅录入
已经逐项核对表名/正文主语的全市值；原始 URL、表名和单位换算均随行保存。
这是可审计的官方决算清单，不从省级值推算，也不把市本级值冒充全市值。
"""
import sqlite3

from services.regional_fiscal_service import ensure_regional_fiscal_table, _upsert


NANJING_2024 = ('https://czj.nanjing.gov.cn/njsczj/202509/'
                 'P020250924616497393160.pdf')
GUANGZHOU_2024 = ('https://czj.gz.gov.cn/attachment/7/7907/7907452/'
                   '10488502.pdf')
SUZHOU_2024 = ('https://czju.suzhou.gov.cn/czj/czyjsxx/202509/'
                '0c2407bec17744d4ab9f8e083a310116/files/'
                'd208955cd2d04d1f8a10d0db227d0553.pdf')
WUXI_2024 = ('https://cz.wuxi.gov.cn/uploadfiles/202510/15/'
             '2025101516244994604889.pdf')
WUXI_2020 = 'https://cz.wuxi.gov.cn/doc/2021/09/10/3422654.shtml'
WUXI_2021 = 'https://cz.wuxi.gov.cn/doc/2022/02/23/3639549.shtml'
SUZHOU_2022 = (
    'https://www.suzhou.gov.cn/szsrmzf/sbjczyjs/202307/'
    '2eea9d5bf20144b7a60cb2f2e65e7dc7/files/'
    '5017674abeb84b99ba6609cb374d0a29.pdf')
SUZHOU_2023 = (
    'https://czju.suzhou.gov.cn/czj/czyjsxx/202409/'
    '31a60c1bd8614934a36ba16f8f4106f0/files/'
    'c6ebea71b62142fd9991bf27a78a9648.pdf')
SHENZHEN_2024_PRELIMINARY = ('https://www.sz.gov.cn/zfgb/2025/1366/'
                              'content/post_12090081.html')
SHENZHEN_2024_FINAL = ('https://szfb.sz.gov.cn/attachment/1/1626/1626809/'
                       '12401906.pdf')
BEIJING_2024_PRELIMINARY = ('https://czj.beijing.gov.cn/zwxx/czsj/czyjs/202501/'
                            'P020250124650364597274.pdf')
BEIJING_2024_FINAL = ('https://czj.beijing.gov.cn/zwxx/czsj/czyjs/202508/'
                      't20250811_4170522.html')
BEIJING_2024_FINAL_TABLES = (
    'https://czj.beijing.gov.cn/zwxx/czsj/czyjs/202508/'
    'P020250818374426796483.pdf')
BEIJING_2021_EXECUTION = (
    'https://czj.beijing.gov.cn/zwxx/czsj/czyjs/202207/'
    'P020220708362698077799.pdf')
BEIJING_2022_EXECUTION = (
    'https://czj.beijing.gov.cn/zwxx/czsj/czyjs/202302/'
    'P020250305548171006010.pdf')
BEIJING_2023_EXECUTION = (
    'https://czj.beijing.gov.cn/zwxx/czsj/czyjs/202402/'
    'P020240202410391761398.pdf')
BEIJING_2022_FINAL = (
    'https://czj.beijing.gov.cn/zwxx/czsj/czyjs/202308/'
    'P020250508598489310570.pdf')
WUHAN_FUND_REVENUE_2024 = (
    'https://czj.wuhan.gov.cn/FBJD/XXGKML/CZGK/CZYJS/202509/'
    'P020250915363469148977.pdf')
WUHAN_FUND_EXPENDITURE_2024 = (
    'https://czj.wuhan.gov.cn/FBJD/XXGKML/CZGK/CZYJS/202509/'
    'P020250915363263249749.pdf')
WUHAN_GENERAL_REVENUE_2024 = (
    'https://czj.wuhan.gov.cn/FBJD/XXGKML/CZGK/CZYJS/202509/'
    'P020250915370207998350.pdf')
WUHAN_DEBT_2024 = (
    'https://www.wuhan.gov.cn/ztzl/yjs/2025/yjsgk/sndjs_37171/202509/'
    'P020250915401855419287.pdf')
WUHAN_DEBT_REPAYMENT_2024 = (
    'https://www.wuhan.gov.cn/ztzl/yjs/2025/yjsgk/sndjs_37171/202509/'
    'P020250915401255703906.pdf')
FUZHOU_2024 = (
    'https://www.fuzhou.gov.cn/zgfzzt/czzj/bjndyjs/zfjsgk/202507/'
    'P020250711511200285357.pdf')
HANGZHOU_2024_PRELIMINARY = (
    'https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/'
    'jcms_files/jcms1/web149/site/attach/0/22d597e448ef42f3912db9c80b730f3c.pdf')
CHANGSHA_DEBT_2024 = (
    'https://czt.hunan.gov.cn/czt/dzqzfwz/202512/33884381/files/'
    '9dd1e8db94fc4293bad7bfb09ee5c904.pdf')
CHENGDU_DEBT_2024_PRELIMINARY = (
    'https://czt.sc.gov.cn/scczt/c102361/2025/2/12/a75ec75444d249629db82cc42c5829b2/'
    'files/4.%E5%9C%B0%E6%96%B9%E6%94%BF%E5%BA%9C%E5%80%BA%E5%8A%A1%E6%83%85%E5%86%B5.pdf')
GUANGZHOU_2024_PRELIMINARY = (
    'https://czj.gz.gov.cn/attachment/7/7778/7778560/10159294.pdf')
NANJING_2024_STATISTICAL_BULLETIN = (
    'https://tjj.nanjing.gov.cn/njstjj/202504/'
    't20250401_5108470.html')
XIAMEN_2024_STATISTICAL_BULLETIN = (
    'https://tjj.xm.gov.cn/zfxxgk/zfxxgkml/tjsjzl/ndgb/202503/'
    't20250326_2924164.htm')
HEFEI_2024_STATISTICAL_BULLETIN = (
    'https://www.hfyaohai.gov.cn/group1/M00/92/B2/'
    'wKgEHmhSjH-AakEtABFDSWCfbvA509.pdf')
XIAMEN_2024_FINAL = (
    'https://cz.xm.gov.cn/zwxx/zfxxgk/zfxxgkml/ysjs/jsbg/202507/'
    'W020250716609893934548.pdf')
CHANGZHOU_2023_FINAL = (
    'https://rd.changzhou.gov.cn/html/rd/2024/OPQFJQAA_0630/34224.html')
CHANGZHOU_2024_BUDGET = (
    'https://rd.changzhou.gov.cn/html/rd/2025/ELPOKPHQ_0113/34580.html')
CHANGZHOU_2020_FINAL = (
    'https://rd.changzhou.gov.cn/html/rd/2021/OPQFJQAA_0625/30103.html')
CHANGZHOU_2021_FINAL = (
    'https://rd.changzhou.gov.cn/html/rd/2022/OPQFJQAA_0630/30843.html')
CHANGZHOU_2025_EXECUTION = (
    'https://rd.changzhou.gov.cn/html/rd/2026/EKPMKPDC_0122/35038.html')
SHANGHAI_2020_FINAL = (
    'https://czj.sh.gov.cn/cmsres/80/80a2043611c6486cb1727c3c996ee082/'
    '5a7fd6b4dfd20dae56a30727dbeb5a7a.pdf')
SHANGHAI_2021_EXECUTION = (
    'https://czj.sh.gov.cn/zys_8908/czsj_9054/zfyjs/yjsbg_9056/'
    '20220127/xxfboswf0000002157.html')
SHANGHAI_2022_EXECUTION = (
    'https://czj.sh.gov.cn/zys_8908/czsj_9054/zfyjs/yjsbg_9056/'
    '20230131/xxfboswf0000002415.html')
SHANGHAI_2023_FINAL = (
    'https://czj.sh.gov.cn/cmsres/c0/c018b52fa53940edb265f88086ee35c9/'
    '760ac7c37c42ebc51ca00b1fbd2f7900.pdf')
SHANGHAI_2024_EXECUTION = (
    'https://czj.sh.gov.cn/zys_8908/czsj_9054/zfyjs/yjsbg_9056/'
    '20250124/xxfboswf0000003119.html')
SHANGHAI_2025_EXECUTION = (
    'https://czj.sh.gov.cn/zys_8908/czsj_9054/zfyjs/yjsbg_9056/'
    '20260211/xxfboswf0000003585.html')
CHENGDU_2023_CHRONICLE = (
    'https://scsqw.org.cn/scdqs/sxdq/cds/content_117434')


def _row(city, region_code, period, indicator_code, value, source_url, source_title,
         note, data_status='official', source_name=None):
    return {
        'country_code': 'CN', 'government_scope': 'city_total',
        'region_code': region_code, 'region_name': city,
        'indicator_code': indicator_code, 'period': period, 'value': value,
        'unit': '亿元', 'frequency': 'annual', 'period_type': 'calendar_year',
        'data_status': data_status, 'source_name': source_name or f'{city}市财政局',
        'source_url': source_url, 'source_title': source_title,
        'parser_notes': note,
    }


# 所有数值均取“决算数/全市”列；万元表已明确除以 10000 转为亿元。
VERIFIED_OFFICIAL_ROWS = (
    # 北京：2021—2023 为年初预算执行报告中的全市执行数；2022 卖地收入
    # 另取最终决算附表。执行数与最终决算在状态上严格区分。
    _row('北京', '110000', '2021', 'gov_fund_revenue', 2705.7,
         BEIJING_2021_EXECUTION,
         '北京市2021年预算执行情况和2022年预算草案的报告',
         '正文“2021年，全市政府性基金预算收入2705.7亿元”；全市预算执行数。',
         data_status='official_preliminary'),
    _row('北京', '110000', '2021', 'gov_fund_expenditure', 3469.3,
         BEIJING_2021_EXECUTION,
         '北京市2021年预算执行情况和2022年预算草案的报告',
         '正文“全市政府性基金预算支出3469.3亿元”；全市预算执行数。',
         data_status='official_preliminary'),
    _row('北京', '110000', '2022', 'gov_fund_revenue', 2227.5,
         BEIJING_2022_EXECUTION,
         '北京市2022年预算执行情况和2023年预算草案的报告',
         '正文“2022年，全市政府性基金预算收入2227.5亿元”；全市预算执行数。',
         data_status='official_preliminary'),
    _row('北京', '110000', '2022', 'gov_fund_expenditure', 2687.1,
         BEIJING_2022_EXECUTION,
         '北京市2022年预算执行情况和2023年预算草案的报告',
         '正文“全市政府性基金预算支出2687.1亿元”；全市预算执行数。',
         data_status='official_preliminary'),
    _row('北京', '110000', '2022', 'land_transfer_revenue', 2100.7854,
         BEIJING_2022_FINAL, '北京市2022年市级决算（含全市附表）',
         '全市政府性基金收入决算表中国有土地使用权出让收入21007854万元÷10000。'),
    _row('北京', '110000', '2023', 'gov_fund_revenue', 2110.3,
         BEIJING_2023_EXECUTION,
         '北京市2023年预算执行情况和2024年预算草案的报告',
         '正文“2023年，全市政府性基金预算收入2110.3亿元”；全市预算执行数。',
         data_status='official_preliminary'),
    _row('北京', '110000', '2023', 'gov_fund_expenditure', 2737.1,
         BEIJING_2023_EXECUTION,
         '北京市2023年预算执行情况和2024年预算草案的报告',
         '正文“全市政府性基金预算支出2737.1亿元”；全市预算执行数。',
         data_status='official_preliminary'),
    _row('北京', '110000', '2024', 'gov_fund_revenue', 2094.8526,
         BEIJING_2024_FINAL_TABLES, '北京市2024年市级决算（含全市附表）',
         '附表四“北京市2024年政府性基金预算收入决算情况表”收入合计20948526万元÷10000；全市列。'),
    _row('北京', '110000', '2024', 'land_transfer_revenue', 1920.5376,
         BEIJING_2024_FINAL_TABLES, '北京市2024年市级决算（含全市附表）',
         '附表四国有土地使用权出让收入19205376万元÷10000；全市列。'),
    _row('北京', '110000', '2024', 'gov_fund_expenditure', 3034.1,
         BEIJING_2024_PRELIMINARY,
         '北京市2024年预算执行情况和2025年预算草案的报告',
         '全市政府性基金预算支出预计执行数；待完整决算表直接值替换。',
         data_status='official_preliminary'),
    _row('北京', '110000', '2024', 'debt_outstanding', 12579.8,
         BEIJING_2024_FINAL, '关于北京市2024年市级决算的报告',
         '报告正文“截至2024年底，全市政府债务余额12579.8亿元”直接值。'),

    # 上海为直辖市，报告中的“全市”即城市总口径。2021、2022、2024、2025
    # 来自预算执行报告，仍标记为 official_preliminary；2020、2023 为决算。
    _row('上海', '310000', '2020', 'gov_fund_revenue', 3175.0,
         SHANGHAI_2020_FINAL, '关于上海市2020年市级决算及2021年上半年预算执行情况的报告',
         '正文“全市政府性基金预算收入3175亿元”；直辖市全市决算口径。'),
    _row('上海', '310000', '2021', 'gov_fund_revenue', 3769.0,
         SHANGHAI_2021_EXECUTION,
         '关于上海市2021年预算执行情况和2022年预算草案的报告',
         '正文“全市政府性基金预算收入3769亿元”；直辖市全市预算执行数。',
         data_status='official_preliminary'),
    _row('上海', '310000', '2021', 'gov_fund_expenditure', 3568.5,
         SHANGHAI_2021_EXECUTION,
         '关于上海市2021年预算执行情况和2022年预算草案的报告',
         '正文“全市政府性基金预算支出3568.5亿元”；直辖市全市预算执行数。',
         data_status='official_preliminary'),
    _row('上海', '310000', '2022', 'gov_fund_revenue', 4041.5,
         SHANGHAI_2022_EXECUTION,
         '关于上海市2022年预算执行情况和2023年预算草案的报告',
         '正文“全市政府性基金预算收入4041.5亿元”；直辖市全市预算执行数。',
         data_status='official_preliminary'),
    _row('上海', '310000', '2022', 'gov_fund_expenditure', 3736.5,
         SHANGHAI_2022_EXECUTION,
         '关于上海市2022年预算执行情况和2023年预算草案的报告',
         '正文“全市政府性基金预算支出3736.5亿元”；直辖市全市预算执行数。',
         data_status='official_preliminary'),
    _row('上海', '310000', '2023', 'gov_fund_revenue', 3466.7,
         SHANGHAI_2023_FINAL,
         '关于上海市2023年市级决算及2024年上半年预算执行情况的报告',
         '正文披露全市政府性基金预算收入3466.7亿元；直辖市全市决算口径。'),
    _row('上海', '310000', '2023', 'gov_fund_expenditure', 2997.7,
         SHANGHAI_2023_FINAL,
         '关于上海市2023年市级决算及2024年上半年预算执行情况的报告',
         '正文披露全市政府性基金预算支出2997.7亿元；直辖市全市决算口径。'),
    _row('上海', '310000', '2024', 'gov_fund_revenue', 3202.8,
         SHANGHAI_2024_EXECUTION,
         '关于上海市2024年预算执行情况和2025年预算草案的报告',
         '正文“全市政府性基金预算收入3202.8亿元”；直辖市全市预算执行数。',
         data_status='official_preliminary'),
    _row('上海', '310000', '2024', 'gov_fund_expenditure', 2881.1,
         SHANGHAI_2024_EXECUTION,
         '关于上海市2024年预算执行情况和2025年预算草案的报告',
         '正文“全市政府性基金预算支出2881.1亿元”；直辖市全市预算执行数。',
         data_status='official_preliminary'),
    _row('上海', '310000', '2025', 'gov_fund_revenue', 3039.6,
         SHANGHAI_2025_EXECUTION,
         '关于上海市2025年预算执行情况和2026年预算草案的报告',
         '正文“全市政府性基金预算收入3039.6亿元”；直辖市全市预算执行数。',
         data_status='official_preliminary'),
    _row('上海', '310000', '2025', 'gov_fund_expenditure', 4005.1,
         SHANGHAI_2025_EXECUTION,
         '关于上海市2025年预算执行情况和2026年预算草案的报告',
         '正文“全市政府性基金预算支出4005.1亿元”；直辖市全市预算执行数。',
         data_status='official_preliminary'),

    _row('常州', '320400', '2020', 'gov_fund_revenue', 1161.7,
         CHANGZHOU_2020_FINAL, '关于常州市2020年决算草案的报告',
         '正文“全市政府性基金预算当年收入1161.7亿元”；全市口径。'),
    _row('常州', '320400', '2020', 'gov_fund_expenditure', 1298.7,
         CHANGZHOU_2020_FINAL, '关于常州市2020年决算草案的报告',
         '正文“全市政府性基金预算当年支出1298.7亿元”；全市口径。'),
    _row('常州', '320400', '2021', 'gov_fund_revenue', 1467.7,
         CHANGZHOU_2021_FINAL, '关于常州市2021年决算草案的报告',
         '正文“全市政府性基金预算当年收入1467.7亿元”；全市口径。'),
    _row('常州', '320400', '2021', 'gov_fund_expenditure', 1630.7,
         CHANGZHOU_2021_FINAL, '关于常州市2021年决算草案的报告',
         '正文“全市政府性基金预算当年支出1630.7亿元”；全市口径。'),
    _row('常州', '320400', '2023', 'gov_fund_revenue', 1396.2,
         CHANGZHOU_2023_FINAL, '关于常州市2023年决算草案的报告',
         '正文“全市政府性基金预算当年收入完成1396.2亿元”；全市口径。'),
    _row('常州', '320400', '2023', 'gov_fund_expenditure', 1591.0,
         CHANGZHOU_2023_FINAL, '关于常州市2023年决算草案的报告',
         '正文“全市政府性基金预算当年支出1591亿元”；全市口径。'),
    _row('常州', '320400', '2024', 'general_budget_expenditure', 890.0,
         CHANGZHOU_2024_BUDGET, '2024年预算情况和2025年预算草案（摘要）',
         '人大公开摘要正文“全市一般公共预算支出预计完成890亿元”；全市预算执行预计值。',
         data_status='official_preliminary'),
    _row('常州', '320400', '2024', 'gov_fund_revenue', 986.0,
         CHANGZHOU_2024_BUDGET, '2024年预算情况和2025年预算草案（摘要）',
         '人大公开摘要正文“全市政府性基金预算收入预计完成986亿元”；全市预算执行预计值。',
         data_status='official_preliminary'),
    _row('常州', '320400', '2024', 'gov_fund_expenditure', 1023.2,
         CHANGZHOU_2024_BUDGET, '2024年预算情况和2025年预算草案（摘要）',
         '人大公开摘要正文“全市政府性基金预算支出预计完成1023.2亿元”；全市预算执行预计值。',
         data_status='official_preliminary'),
    _row('常州', '320400', '2025', 'gov_fund_revenue', 413.7,
         CHANGZHOU_2025_EXECUTION, '2025年预算执行情况和2026年预算草案的报告',
         '正文“全市政府性基金预算收入413.7亿元”；全市预算执行数。',
         data_status='official_preliminary'),
    _row('常州', '320400', '2025', 'gov_fund_expenditure', 809.8,
         CHANGZHOU_2025_EXECUTION, '2025年预算执行情况和2026年预算草案的报告',
         '正文“全市政府性基金预算支出809.8亿元”；全市预算执行数。',
         data_status='official_preliminary'),

    _row('南京', '320100', '2023', 'gov_fund_revenue', 1254.3009, NANJING_2024,
         '南京市2024年市级决算草案表', '2024年南京市政府性基金预算收入决算表；2023年决算数；12543009万元÷10000。'),
    _row('南京', '320100', '2023', 'land_transfer_revenue', 1126.2739, NANJING_2024,
         '南京市2024年市级决算草案表', '同表国有土地使用权出让收入；2023年决算数；11262739万元÷10000。'),
    _row('南京', '320100', '2024', 'gov_fund_revenue', 937.5926, NANJING_2024,
         '南京市2024年市级决算草案表', '2024年南京市政府性基金预算收入决算表；2024年决算数；9375926万元÷10000。'),
    _row('南京', '320100', '2024', 'land_transfer_revenue', 840.0334, NANJING_2024,
         '南京市2024年市级决算草案表', '同表国有土地使用权出让收入；2024年决算数；8400334万元÷10000。'),

    _row('广州', '440100', '2024', 'gov_fund_revenue', 1281.7, GUANGZHOU_2024,
         '2024年广州市本级政府决算公开', '正文“2024年全市政府性基金预算收支总决算汇编情况”直接值。'),
    _row('广州', '440100', '2024', 'gov_fund_expenditure', 1983.4, GUANGZHOU_2024,
         '2024年广州市本级政府决算公开', '正文“2024年全市政府性基金预算收支总决算汇编情况”直接值。'),
    _row('广州', '440100', '2024', 'debt_outstanding', 6482.8, GUANGZHOU_2024,
         '2024年广州市本级政府决算公开', '正文“2024年我市地方政府债务余额”全市直接值。'),
    _row('广州', '440100', '2024', 'principal_repayment', 313.5, GUANGZHOU_2024,
         '2024年广州市本级政府决算公开', '正文“2024年全市财政偿还地方政府债券本金”直接值。'),
    _row('广州', '440100', '2024', 'interest_expenditure', 186.6, GUANGZHOU_2024,
         '2024年广州市本级政府决算公开', '正文“2024年全市财政支付地方政府债券利息”直接值。'),

    _row('苏州', '320500', '2022', 'gov_fund_revenue', 1735.6769, SUZHOU_2022,
         '2022年苏州市决算表格', '附表5政府性基金预算收入决算数；17356769万元÷10000；全市列。'),
    _row('苏州', '320500', '2022', 'land_transfer_revenue', 1604.7253, SUZHOU_2022,
         '2022年苏州市决算表格', '附表5国有土地使用权出让收入决算数；16047253万元÷10000；全市列。'),
    _row('苏州', '320500', '2023', 'gov_fund_revenue', 1401.1672, SUZHOU_2023,
         '2023年苏州市决算表格', '附表5政府性基金预算收入决算数；14011672万元÷10000；全市列。'),
    _row('苏州', '320500', '2023', 'land_transfer_revenue', 1284.8598, SUZHOU_2023,
         '2023年苏州市决算表格', '附表5国有土地使用权出让收入决算数；12848598万元÷10000；全市列。'),
    _row('苏州', '320500', '2024', 'gov_fund_revenue', 1048.0795, SUZHOU_2024,
         '2024年苏州市决算表格', '附表5全市政府性基金预算收入决算数；10480795万元÷10000。'),
    _row('苏州', '320500', '2024', 'gov_fund_expenditure', 2069.7384, SUZHOU_2024,
         '2024年苏州市决算表格', '附表7全市政府性基金预算支出决算数；20697384万元÷10000。'),
    _row('苏州', '320500', '2024', 'land_transfer_revenue', 942.9578, SUZHOU_2024,
         '2024年苏州市决算表格', '附表5国有土地使用权出让收入决算数；9429578万元÷10000。'),
    _row('苏州', '320500', '2024', 'debt_outstanding', 3657.96, SUZHOU_2024,
         '2024年苏州市决算表格', '附表34/35“2024年末地方政府债务余额决算数”全市列。'),
    _row('苏州', '320500', '2024', 'general_debt_outstanding', 730.40, SUZHOU_2024,
         '2024年苏州市决算表格', '2024年末地方政府债务余额决算数中的一般债务全市列。'),
    _row('苏州', '320500', '2024', 'special_debt_outstanding', 2927.56, SUZHOU_2024,
         '2024年苏州市决算表格', '2024年末地方政府债务余额决算数中的专项债务全市列。'),
    _row('苏州', '320500', '2024', 'interest_expenditure', 67.92, SUZHOU_2024,
         '2024年苏州市决算表格', '附表34“2024年地方政府债务付息决算数”全市列。'),

    _row('无锡', '320200', '2020', 'gov_fund_revenue', 988.0, WUXI_2020,
         '关于无锡市2020年本级财政决算（草案）的报告', '报告正文明确表述“全年政府性基金收入988亿元”；主语为全市。'),
    _row('无锡', '320200', '2020', 'land_transfer_revenue', 960.3, WUXI_2020,
         '关于无锡市2020年本级财政决算（草案）的报告', '报告正文明确表述“其中土地出让收入960.3亿元”；主语为全市。'),
    _row('无锡', '320200', '2021', 'gov_fund_revenue', 1225.8, WUXI_2021,
         '2021年全市财政工作情况',
         '无锡市财政局正文披露全市政府性基金预算收入1225.8亿元。'),
    _row('无锡', '320200', '2021', 'land_transfer_revenue', 1194.2, WUXI_2021,
         '2021年全市财政工作情况',
         '无锡市财政局正文披露土地出让金收入1194.2亿元；与全市基金收入同一主语。'),
    _row('无锡', '320200', '2024', 'gov_fund_revenue', 799.3, WUXI_2024,
         '关于无锡市2024年市级财政决算（草案）的报告',
         '报告正文“全市政府性基金收入完成799.3亿元”；全市口径，官方决算草案叙述值。',
         data_status='official_preliminary'),
    _row('无锡', '320200', '2024', 'gov_fund_expenditure', 706.2, WUXI_2024,
         '关于无锡市2024年市级财政决算（草案）的报告',
         '报告正文“全市政府性基金支出706.2亿元”；全市口径，官方决算草案叙述值。',
         data_status='official_preliminary'),
    _row('无锡', '320200', '2024', 'debt_outstanding', 2609.72, WUXI_2024,
         '关于无锡市2024年市级财政决算（草案）的报告', '债务情况部分“全市地方政府债务余额”直接值。'),
    _row('无锡', '320200', '2024', 'general_debt_outstanding', 615.78, WUXI_2024,
         '关于无锡市2024年市级财政决算（草案）的报告', '全市债务余额中的一般债务直接值。'),
    _row('无锡', '320200', '2024', 'special_debt_outstanding', 1993.94, WUXI_2024,
         '关于无锡市2024年市级财政决算（草案）的报告', '全市债务余额中的专项债务直接值。'),

    # 武汉：2024年全市财政决算公开表，均取“全市/决算数”列，万元除以10000。
    _row('武汉', '420100', '2024', 'gov_fund_revenue', 1485.6051,
         WUHAN_FUND_REVENUE_2024, '武汉市2024年全市政府性基金收入决算表',
         '政府性基金收入决算数14856051万元÷10000；全市列。'),
    _row('武汉', '420100', '2024', 'land_transfer_revenue', 1224.7129,
         WUHAN_FUND_REVENUE_2024, '武汉市2024年全市政府性基金收入决算表',
         '国有土地使用权出让收入决算数12247129万元÷10000；全市列。'),
    _row('武汉', '420100', '2024', 'gov_fund_expenditure', 1934.5645,
         WUHAN_FUND_EXPENDITURE_2024, '武汉市2024年全市政府性基金支出决算表',
         '政府性基金支出决算数19345645万元÷10000；全市列，不含转移性支出合计。'),
    _row('武汉', '420100', '2024', 'tax_revenue', 1223.5595,
         WUHAN_GENERAL_REVENUE_2024, '武汉市2024年全市一般公共预算收入决算表',
         '税收收入决算数12235595万元÷10000；全市列。'),
    _row('武汉', '420100', '2024', 'debt_outstanding', 7806.3971,
         WUHAN_DEBT_2024, '武汉市及市本级2024年政府债务收支决算表',
         '2024年末政府债务余额决算数78063971万元÷10000；全市列。'),
    _row('武汉', '420100', '2024', 'general_debt_outstanding', 2044.6411,
         WUHAN_DEBT_2024, '武汉市及市本级2024年政府债务收支决算表',
         '2024年末一般债务余额决算数20446411万元÷10000；全市列。'),
    _row('武汉', '420100', '2024', 'special_debt_outstanding', 5761.7560,
         WUHAN_DEBT_2024, '武汉市及市本级2024年政府债务收支决算表',
         '2024年末专项债务余额决算数57617560万元÷10000；全市列。'),
    _row('武汉', '420100', '2024', 'principal_repayment', 891.4381,
         WUHAN_DEBT_REPAYMENT_2024, '武汉市2024年地方政府债券还本付息情况表',
         '地方政府债务还本支出决算数8914381万元÷10000；全市列。'),
    _row('武汉', '420100', '2024', 'interest_expenditure', 226.2322,
         WUHAN_DEBT_REPAYMENT_2024, '武汉市2024年地方政府债券还本付息情况表',
         '地方政府债务付息支出决算数2262322万元÷10000；全市列。'),

    # 福州：2024年度全市财政决算公开 PDF，表中“福州市”列，不取“福州市本级”。
    _row('福州', '350100', '2024', 'gov_fund_revenue', 612.2756,
         FUZHOU_2024, '2024年度福州市财政决算公开',
         '政府性基金预算收入决算数6122756万元÷10000；福州市全市列。'),
    _row('福州', '350100', '2024', 'gov_fund_expenditure', 1027.2366,
         FUZHOU_2024, '2024年度福州市财政决算公开',
         '政府性基金预算支出小计决算数10272366万元÷10000；不含支出合计中的转移性支出。'),
    _row('福州', '350100', '2024', 'land_transfer_revenue', 589.2775,
         FUZHOU_2024, '2024年度福州市财政决算公开',
         '国有土地使用权出让收入决算数5892775万元÷10000；福州市全市列。'),
    _row('福州', '350100', '2024', 'tax_revenue', 474.3093,
         FUZHOU_2024, '2024年度福州市财政决算公开',
         '一般公共预算税收收入决算数4743093万元÷10000；福州市全市列。'),
    _row('福州', '350100', '2024', 'debt_outstanding', 2760.74,
         FUZHOU_2024, '2024年度福州市财政决算公开',
         '2024年末地方政府债务余额决算数；福州市全市列。'),
    _row('福州', '350100', '2024', 'general_debt_outstanding', 540.04,
         FUZHOU_2024, '2024年度福州市财政决算公开',
         '2024年末一般债务余额决算数；福州市全市列。'),
    _row('福州', '350100', '2024', 'special_debt_outstanding', 2220.70,
         FUZHOU_2024, '2024年度福州市财政决算公开',
         '2024年末专项债务余额决算数；福州市全市列。'),
    _row('福州', '350100', '2024', 'principal_repayment', 240.48,
         FUZHOU_2024, '2024年度福州市财政决算公开',
         '地方政府债券还本支出决算数；福州市全市列。'),
    _row('福州', '350100', '2024', 'interest_expenditure', 75.26,
         FUZHOU_2024, '2024年度福州市财政决算公开',
         '地方政府债券付息支出决算数；福州市全市列。'),

    # 杭州：公开报告中的2024年执行数，表内全市列；报告非最终决算，标官方初步。
    _row('杭州', '330100', '2024', 'gov_fund_revenue', 1531.0805,
         HANGZHOU_2024_PRELIMINARY,
         '杭州市及市本级2024年政府性基金预算执行情况及2025年预算（草案）',
         '2024年全市政府性基金收入执行数15310805万元÷10000；预算执行报告口径。',
         data_status='official_preliminary'),
    _row('杭州', '330100', '2024', 'gov_fund_expenditure', 1478.6,
         HANGZHOU_2024_PRELIMINARY,
         '杭州市及市本级2024年政府性基金预算执行情况及2025年预算（草案）',
         '2024年全市政府性基金支出执行数1478.6亿元；不含专项债券支出、转移性支出合计。',
         data_status='official_preliminary'),
    _row('杭州', '330100', '2024', 'land_transfer_revenue', 1395.6250,
         HANGZHOU_2024_PRELIMINARY,
         '杭州市及市本级2024年政府性基金预算执行情况及2025年预算（草案）',
         '全市国有土地使用权出让收入执行数13956250万元÷10000。',
         data_status='official_preliminary'),
    _row('杭州', '330100', '2024', 'tax_revenue', 2283.3,
         HANGZHOU_2024_PRELIMINARY,
         '杭州市及市本级2024年预算执行情况和2025年预算（草案）',
         '2024年全市税收收入执行数2283.3亿元；预算执行报告口径。',
         data_status='official_preliminary'),
    _row('杭州', '330100', '2024', 'debt_outstanding', 4464.9054,
         HANGZHOU_2024_PRELIMINARY,
         '杭州市及市本级2024年预算执行情况和2025年预算（草案）',
         '2024年末全市地方政府债务余额=一般债务余额13166144万元+专项债务余额31482910万元，均÷10000。',
         data_status='official_preliminary'),
    _row('杭州', '330100', '2024', 'general_debt_outstanding', 1316.6144,
         HANGZHOU_2024_PRELIMINARY,
         '杭州市及市本级2024年一般债务限额及余额情况表',
         '全市一般债务余额13166144万元÷10000。',
         data_status='official_preliminary'),
    _row('杭州', '330100', '2024', 'special_debt_outstanding', 3148.2910,
         HANGZHOU_2024_PRELIMINARY,
         '杭州市及市本级2024年专项债务限额及余额情况表',
         '全市专项债务余额31482910万元÷10000。',
         data_status='official_preliminary'),
    _row('杭州', '330100', '2024', 'principal_repayment', 470.8,
         HANGZHOU_2024_PRELIMINARY,
         '杭州市及市本级2024年预算执行情况和2025年预算（草案）',
         '2024年全市债务还本支出470.8亿元；预算执行报告口径。',
         data_status='official_preliminary'),
    _row('杭州', '330100', '2024', 'interest_expenditure', 126.8,
         HANGZHOU_2024_PRELIMINARY,
         '杭州市及市本级2024年预算执行情况和2025年预算（草案）',
         '2024年全市债务付息支出126.8亿元；预算执行报告口径。',
         data_status='official_preliminary'),

    # 长沙：湖南省财政厅公布的全省决算表中有长沙市行，属于城市明确列，不是省级值下放。
    _row('长沙', '430100', '2024', 'debt_outstanding', 3211.59,
         CHANGSHA_DEBT_2024, '湖南省2024年地方政府债务限额及余额决算情况表',
         '表内长沙市行：2024年政府债务余额3211.59亿元；数据由市县提供。',
         source_name='湖南省财政厅（长沙市财政局提供）'),
    _row('长沙', '430100', '2024', 'general_debt_outstanding', 774.46,
         CHANGSHA_DEBT_2024, '湖南省2024年地方政府债务限额及余额决算情况表',
         '表内长沙市行：一般债务余额774.46亿元；数据由市县提供。',
         source_name='湖南省财政厅（长沙市财政局提供）'),
    _row('长沙', '430100', '2024', 'special_debt_outstanding', 2437.13,
         CHANGSHA_DEBT_2024, '湖南省2024年地方政府债务限额及余额决算情况表',
         '表内长沙市行：专项债务余额2437.13亿元；数据由市县提供。',
         source_name='湖南省财政厅（长沙市财政局提供）'),

    # 成都：四川省财政厅2025年预算公开表中的“预计执行数”，明确标为官方初步。
    _row('成都', '510100', '2023', 'gov_fund_revenue', 1886.6,
         CHENGDU_2023_CHRONICLE, '成都市2023年财政收支',
         '四川省地方志工作办公室市情资料披露全市政府性基金预算收入1886.6亿元。',
         source_name='四川省地方志工作办公室（成都市地情）'),
    _row('成都', '510100', '2023', 'gov_fund_expenditure', 2387.4,
         CHENGDU_2023_CHRONICLE, '成都市2023年财政收支',
         '四川省地方志工作办公室市情资料披露全市政府性基金预算支出2387.4亿元。',
         source_name='四川省地方志工作办公室（成都市地情）'),
    _row('成都', '510100', '2024', 'debt_outstanding', 6206.6,
         CHENGDU_DEBT_2024_PRELIMINARY, '2024年四川省地方政府债务限额及余额情况表',
         '表内成都市行：2024年债务余额预计执行数6206.6亿元。',
         data_status='official_preliminary', source_name='四川省财政厅（成都市财政局提供）'),
    _row('成都', '510100', '2024', 'general_debt_outstanding', 1374.8,
         CHENGDU_DEBT_2024_PRELIMINARY, '2024年四川省地方政府债务限额及余额情况表',
         '表内成都市行：一般债务余额预计执行数1374.8亿元。',
         data_status='official_preliminary', source_name='四川省财政厅（成都市财政局提供）'),
    _row('成都', '510100', '2024', 'special_debt_outstanding', 4831.8,
         CHENGDU_DEBT_2024_PRELIMINARY, '2024年四川省地方政府债务限额及余额情况表',
         '表内成都市行：专项债务余额预计执行数4831.8亿元。',
         data_status='official_preliminary', source_name='四川省财政厅（成都市财政局提供）'),

    # 深圳这份人大报告明确说明为预计执行数，不能标成决算 official。
    _row('深圳', '440300', '2024', 'gov_fund_revenue', 475.0,
         SHENZHEN_2024_PRELIMINARY,
         '深圳市2024年预算执行情况和2025年预算草案的报告',
         '全市政府性基金预算当年收入预计执行数；待决算后可由决算值替换。',
         data_status='official_preliminary'),
    _row('深圳', '440300', '2024', 'gov_fund_expenditure', 1367.7,
         SHENZHEN_2024_PRELIMINARY,
         '深圳市2024年预算执行情况和2025年预算草案的报告',
         '全市政府性基金预算当年支出预计执行数；待决算后可由决算值替换。',
         data_status='official_preliminary'),
    _row('深圳', '440300', '2024', 'tax_revenue', 3265.7,
         SHENZHEN_2024_FINAL,
         '关于深圳市2024年本级决算的报告',
         '全市地方级一般公共预算税收收入决算数3265.7亿元；不使用来源于辖区的中央级收入。'),

    # 城市统计公报明确给出地方级财政税收收入；它们是官方初步值，
    # 与财政局最终决算若出现差异时由最终决算优先替换。
    _row('南京', '320100', '2024', 'tax_revenue', 1290.71,
         NANJING_2024_STATISTICAL_BULLETIN,
         '南京市2024年国民经济和社会发展统计公报',
         '公报明确披露地方一般公共预算收入中的税收收入1290.71亿元；全市口径，官方初步值。',
         data_status='official_preliminary', source_name='南京市统计局'),
    _row('厦门', '350200', '2024', 'tax_revenue', 653.73,
         XIAMEN_2024_STATISTICAL_BULLETIN,
         '厦门市2024年国民经济和社会发展统计公报',
         '公报明确披露地方级财政收入中的税收收入653.73亿元；全市口径，官方初步值。',
         data_status='official_preliminary', source_name='厦门市统计局'),
    _row('广州', '440100', '2024', 'tax_revenue', 1372.3731,
         GUANGZHOU_2024_PRELIMINARY,
         '广州市2024年预算执行情况和2025年预算草案',
         '全市一般公共预算收入执行表中的税收收入13723731万元÷10000；全市口径，官方初步值。',
         data_status='official_preliminary'),
    _row('广州', '440100', '2024', 'land_transfer_revenue', 1087.1,
         GUANGZHOU_2024_PRELIMINARY,
         '广州市2024年预算执行情况和2025年预算草案',
         '报告明确披露全市国有土地使用权出让收入1087.1亿元；不使用市本级621.6亿元替代全市值。',
         data_status='official_preliminary'),
    _row('合肥', '340100', '2024', 'tax_revenue', 675.21,
         HEFEI_2024_STATISTICAL_BULLETIN,
         '合肥市2024年国民经济和社会发展统计公报',
         '公报披露全市一般公共预算收入中的税收收入675.21亿元；全市口径，官方初步值。',
         data_status='official_preliminary',
         source_name='合肥市统计局、国家统计局合肥调查队'),

    # 厦门：市政府向市人大提交的2024年市本级财政决算报告同时披露全市
    # 政府性基金和全市政府债务；仅录入“全市”主语，市本级基金/债务偿付数不下放。
    _row('厦门', '350200', '2024', 'gov_fund_revenue', 423.7,
         XIAMEN_2024_FINAL,
         '厦门市人民政府关于2024年市本级财政决算的报告',
         '正文“全市政府性基金预算收入”423.7亿元；全市决算口径。'),
    _row('厦门', '350200', '2024', 'gov_fund_expenditure', 868.6,
         XIAMEN_2024_FINAL,
         '厦门市人民政府关于2024年市本级财政决算的报告',
         '正文“全市政府性基金预算支出”868.6亿元；全市决算口径。'),
    _row('厦门', '350200', '2024', 'debt_outstanding', 2639.7,
         XIAMEN_2024_FINAL,
         '厦门市人民政府关于2024年市本级财政决算的报告',
         '正文“截至2024年底，我市地方债务余额”2639.7亿元；全市口径。'),
    _row('厦门', '350200', '2024', 'general_debt_outstanding', 417.7,
         XIAMEN_2024_FINAL,
         '厦门市人民政府关于2024年市本级财政决算的报告',
         '全市地方债务余额中的一般债务余额417.7亿元；全市口径。'),
    _row('厦门', '350200', '2024', 'special_debt_outstanding', 2222.0,
         XIAMEN_2024_FINAL,
         '厦门市人民政府关于2024年市本级财政决算的报告',
         '全市地方债务余额中的专项债务余额2222亿元；全市口径。'),
)


def update_city_fiscal_decisions(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    try:
        ensure_regional_fiscal_table(conn)
        before = conn.execute('SELECT COUNT(*) FROM regional_fiscal_observations').fetchone()[0]
        for row in VERIFIED_OFFICIAL_ROWS:
            _upsert(conn, row)
        conn.commit()
        after = conn.execute('SELECT COUNT(*) FROM regional_fiscal_observations').fetchone()[0]
    finally:
        conn.close()
    return {
        'success': True,
        'observations_processed': len(VERIFIED_OFFICIAL_ROWS),
        'new_rows': after - before,
        'cities': sorted({row['region_name'] for row in VERIFIED_OFFICIAL_ROWS}),
        'data_statuses': sorted({row['data_status'] for row in VERIFIED_OFFICIAL_ROWS}),
    }
