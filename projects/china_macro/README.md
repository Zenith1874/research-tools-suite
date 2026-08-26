# 中国宏观、财政、城市与住房

项目 ID：china_macro

该域拥有中国金融与实体经济、财政债务、地区 GDP、城市经济、住房观察和透明情景页面。主要运行代码仍位于根目录 services/、static/、scripts/ 和 tests/，本目录只保存边界说明。

主要页面：

- /dashboard、/china-macro、/hong-kong-macro、/macro-analytics
- /gdp、/china-rates
- /fiscal-debt、/debt-ceiling
- /city-economy、/housing、/housing-scenario

中国宏观页面将“就业与收入”和“人口与家庭”分为两个独立页签；后者含出生人口、
结婚登记、协议离婚、法院判决/调解离婚、出生人口官方绝对数与单独标注的出生人口历史估算、按年派生的离婚合计及同年离婚/结婚登记流量比。详细覆盖、来源和缺口见
`docs/china_demography_macro_STATUS_2026-08-13.md`。

公开 Git 可包含官方来源的小型 CSV、解析代码、测试夹具和状态文档。主数据库、城投债库、安居客商业挂牌库、原始页面、WAL/SHM 和历史备份必须进入私有迁移快照。

香港宏观保持独立 jurisdiction，不并入城市经济模块；其 SAFE 联动、来源 freshness、CSD 细表、API/CSV 和浏览器验收的最新完整性记录见：

    docs/hong_kong_macro_COMPLETENESS_AUDIT_2026-08-12.md

最低验证：

    python.exe -m unittest discover -s tests -p "test_*macro*.py" -q
    python.exe -m unittest discover -s tests -p "test_*fiscal*.py" -q
    python.exe -m unittest discover -s tests -p "test_*housing*.py" -q
