# 中国宏观、财政、城市与住房

项目 ID：china_macro

该域拥有中国金融与实体经济、财政债务、地区 GDP、城市经济、住房观察和透明情景页面。主要运行代码仍位于根目录 services/、static/、scripts/ 和 tests/，本目录只保存边界说明。

主要页面：

- /dashboard、/china-macro、/macro-analytics
- /gdp、/china-rates
- /fiscal-debt、/debt-ceiling
- /city-economy、/housing、/housing-scenario

公开 Git 可包含官方来源的小型 CSV、解析代码、测试夹具和状态文档。主数据库、城投债库、安居客商业挂牌库、原始页面、WAL/SHM 和历史备份必须进入私有迁移快照。

最低验证：

    python.exe -m unittest discover -s tests -p "test_*macro*.py" -q
    python.exe -m unittest discover -s tests -p "test_*fiscal*.py" -q
    python.exe -m unittest discover -s tests -p "test_*housing*.py" -q
