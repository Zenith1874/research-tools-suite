# -*- coding: utf-8 -*-
"""国家统计局 70 城到安居客城市子域的映射。

来源：2026-07-16 抓取的 https://www.anjuke.com/fangjia/ 内嵌
``window.__NUXT__.data[1].filterData.areaFilter``，再与本地主库
``housing_city_observations`` 的 70 个 DISTINCT city 精确匹配。
"""

ANJUKE_CITY_SLUGS = {
    '三亚': 'sanya',
    '上海': 'shanghai',
    '丹东': 'dandong',
    '乌鲁木齐': 'wulumuqi',
    '九江': 'jiujiang',
    '兰州': 'lanzhou',
    '包头': 'baotou',
    '北京': 'beijing',
    '北海': 'beihai',
    '南京': 'nanjing',
    '南充': 'nanchong',
    '南宁': 'nanning',
    '南昌': 'nc',
    '厦门': 'xm',
    '合肥': 'hf',
    '吉林': 'jilin',
    '呼和浩特': 'huhehaote',
    '哈尔滨': 'heb',
    '唐山': 'tangshan',
    '大理': 'dali',
    '大连': 'dalian',
    '天津': 'tianjin',
    '太原': 'ty',
    '宁波': 'nb',
    '安庆': 'anqing',
    '宜昌': 'yichang',
    '岳阳': 'yueyang',
    '常德': 'changde',
    '平顶山': 'pingdingsha',
    '广州': 'guangzhou',
    '徐州': 'xuzhou',
    '惠州': 'huizhou',
    '成都': 'chengdu',
    '扬州': 'yangzhou',
    '无锡': 'wuxi',
    '昆明': 'km',
    '杭州': 'hangzhou',
    '桂林': 'guilin',
    '武汉': 'wuhan',
    '沈阳': 'sy',
    '泉州': 'quanzhou',
    '泸州': 'luzhou',
    '洛阳': 'luoyang',
    '济南': 'jinan',
    '济宁': 'jining',
    '海口': 'haikou',
    '深圳': 'shenzhen',
    '温州': 'wenzhou',
    '湛江': 'zhanjiang',
    '烟台': 'yt',
    '牡丹江': 'mudanjiang',
    '石家庄': 'sjz',
    '福州': 'fz',
    '秦皇岛': 'qinhuangdao',
    '蚌埠': 'bengbu',
    '襄阳': 'xiangyang',
    '西宁': 'xining',
    '西安': 'xa',
    '贵阳': 'gy',
    '赣州': 'ganzhou',
    '遵义': 'zunyi',
    '郑州': 'zhengzhou',
    '重庆': 'chongqing',
    '金华': 'jinhua',
    '银川': 'yinchuan',
    '锦州': 'jinzhou',
    '长春': 'cc',
    '长沙': 'cs',
    '青岛': 'qd',
    '韶关': 'shaoguan',
}

# 用户关注、但不属于统计局 70 城口径的额外挂牌城市。
# 这些城市可展示安居客挂牌参考，但比较层会因缺官方侧而列入 not_comparable。
ANJUKE_EXTRA_CITY_SLUGS = {
    '常州': 'cz',
    '苏州': 'suzhou',
}


def city_market_url(city):
    """返回城市二手挂牌行情页；无映射时诚实返回 None。"""
    slug = ANJUKE_CITY_SLUGS.get(city) or ANJUKE_EXTRA_CITY_SLUGS.get(city)
    return f'https://{slug}.anjuke.com/market/' if slug else None


def city_history_url(city, year):
    """返回安居客年度房价页；年度页统一位于全国 ``/fangjia/`` 路径。"""
    slug = city_slug(city)
    return f'https://www.anjuke.com/fangjia/{slug}{int(year)}/' if slug else None


def city_slug(city):
    return ANJUKE_CITY_SLUGS.get(city) or ANJUKE_EXTRA_CITY_SLUGS.get(city)
