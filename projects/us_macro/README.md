# 美国宏观

项目 ID：us_macro

该域拥有 /us-macro，并作为共享消费者使用 /gdp 和 /macro-analytics 的中美比较能力。核心文件包括 services/us_macro_service.py、static/us_macro.html 及对应测试。

FRED、BLS、BEA、美国财政部等公开来源的解析逻辑和来源元数据可进入 Git；运行数据库和缓存留在私有层。缺失数据必须保留缺失状态，不以演示值或零替代。

最低验证：

    python.exe -m unittest discover -s tests -p "test_macro_analytics.py" -q
    python.exe -m unittest discover -s tests -p "test_gdp_service.py" -q
