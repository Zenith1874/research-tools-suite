# 城市上市公司图表与年度口径修正（2026-07-29）

## 问题证据

- 原“营收/GDP”把多数公司的 2026 年一季度累计营收与 2025 全年 GDP 相除，少数公司又已披露半年报，流量期间混杂。
- 原证券化率/营收比使用对数轴分组柱。柱形图失去线性零基准后，柱长不再能直观表达倍数差。
- 原双对数散点只有十个点，城市文字容易碰撞；旁注实际讨论的是“总市值/营业收入”，可直接画成排名图。
- 页面口径说明仍把财务三表写成巨潮 official，但当前落库记录的三表来源实际为东方财富 third_party。

## 增量修改

- 利润表采集只选择最新完整年度（12 月 31 日）；资产负债表仍选最新报告期，市值仍为最新行情快照。
- 聚合层忽略季度累计营收/净利润；只有城市内采用的营收均为同一完整年度且与 GDP 年份一致时，才计算营收/GDP。
- payload 新增每个指标的 `report_periods`，表格显示覆盖家数和报告期，来源说明与实际落库状态一致。
- 上市公司页新增由“排名指标”控制的全宽主图；证券化率、完整年度营收/GDP、市销率拆成三张线性零基准横向排名图，条末显示精确值。
- 原对数分组柱和双对数散点删除；精确汇总表与行业表保留。

## 数据回填

- 目标：办公地属于北京、上海、广州、深圳、厦门、南京、合肥、常州、苏州、无锡的 2,227 家公司。
- 命令：`update_financials(..., include_balance=False, include_headstrip=False, resume=True)`。
- 输出：仅新增/更新东方财富 F10 最新完整年度营收与归母净利润，不删除原季度记录；聚合层继续保留原始记录但不再采用季度流量。
- 审计日志：`logs/listed_annual_backfill_2026-07-29.log` 及并行断点续跑的
  `logs/listed_annual_backfill_2026-07-29_A.log`、`_B.log`。
- 实测结果：十城 2,227 家公司中，2025 完整年度营收覆盖 2,118 家（95.1%）；
  两组断点任务分别处理 980/998 家，错误均为 0。未返回年报字段的公司保持缺失。
- 十城采用的营收期均为 `2025-12-31`，与城市 `2025` GDP 对齐；常州覆盖
  57/68 家、苏州 89/104 家、北京 543/570 家。

## 验证

- `python.exe -X utf8 -m unittest tests.test_listed_company_service -v`：9 项通过。
- `python.exe -X utf8 -m unittest tests.test_listed_company_service tests.test_research_navigation -q`：19 项通过。
- `node.exe --check static/city-economy.js`：语法检查通过。
- `python.exe -X utf8 -m unittest discover -s tests -q`：364 项通过。
- 服务重启后 `/api/health` 返回 200；`/api/listed-company/data` 返回 10 城、
  `report_periods`、同年年度比率及修正后的来源说明。
- 新增测试覆盖：最新完整年度选择、季度累计值不替代年度值、营收/GDP 同年约束、报告期元数据。

## 页面核验边界

- 服务与 payload 已验证，浏览器截图级的视觉验收仍需用户允许使用 Playwright；
  在获得允许前不擅自控制用户浏览器。
