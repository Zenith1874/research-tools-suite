"""Market data placeholder.

No authenticated or reviewed live market source is configured for this local app.
The dashboard must show missing status instead of fabricating real-time quotes.
"""

def get_market_data():
    return {
        'latest_date': None,
        'data_status': 'missing',
        'records': [],
        'warnings': ['暂无已配置的真实市场数据源，未展示模拟行情。'],
    }

