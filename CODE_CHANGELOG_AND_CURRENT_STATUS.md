# 央行金融与财政债务项目代码梳理

> 核对日期：2026-06-17  
> 项目目录：`D:\claude`  
> 旧版对比基线：`server.py.bak-20260616-222434`、`static/dashboard.html.bak-20260616-222434`、`pboc_data.db.bak-20260616-222434`  
> 说明：项目没有 Git 历史，本文的“以前”严格指上述 2026-06-16 备份，不代表更早版本的完整演进记录。

## 1. 结论摘要

当前项目已经从“单文件爬虫 + 单张月度宽表 + 前端种子数据”改造成“旧爬虫保留 + 规范化 observation 表 + 多个独立数据服务 + 来源追踪 + Debug 页面”的结构。

目前完成的是：

- 央行月度金融数据的规范化、来源字段和 Debug 展示。
- 财政部地方政府债务月报抓取和来源记录。
- 央行资产负债表、央行公开市场国债买卖、买断式逆回购逐笔公告及月末存量测算。
- 财政部国债逐只发行明细，区分计划发行额和实际发行额。
- 财政债务页面与两个 Debug 页面。

目前**不能称为全部历史数据已经完整抓取**：

- 央行月度主数据虽覆盖到 2010-03，但月份不连续。
- 社融存量、贷款结构等指标覆盖明显少于 M2。
- 财政部国债发行明细目前只覆盖 2025-11 至 2026-06，2024 及更早旧站数据尚未接入。
- 地方债月报目前只覆盖 2025-09 至 2026-04。
- 国债余额、城投债、财政缺口仍未形成 official 数据集。

## 2. 以前的代码是什么

### 2.1 后端结构

旧版核心逻辑几乎全部集中在 `server.py`：

- 使用 Python 标准库 `HTTPServer` 提供页面和 API。
- 使用 SQLite 数据库 `pboc_data.db`。
- 主要数据表是 `monthly_data`，把一个月份的所有指标放在同一行。
- `raw_pages` 保存抓取过的央行网页原文。
- `scrape_log` 保存旧爬虫运行日志。
- `SEED` 在后端内置种子/人工数据。
- `source_url` 曾同时承担真实 URL、`seed`、`manual` 等多种含义。
- `/api/data` 直接读取 `monthly_data` 并在响应时计算部分月增量。
- `/api/scrape` 调用旧版 `scrape_and_update()`。

旧版主要问题：

1. 单张宽表无法保存“同一个月份不同指标来自不同公告”的来源信息。
2. `seed`、`manual` 和官网抓取数据混在同一字段，来源口径不清晰。
3. 前端含 `SEED_DATA`，API 失败时容易让页面看起来仍有真实数据。
4. 抓取主要依赖少量入口、已知 URL 和季度报告，历史月份不连续。
5. 正则对旧公告中的“货币供应量”“金融机构人民币各项贷款”等写法兼容不足。
6. 没有指标级 Debug、来源覆盖和缺失来源检查。
7. 没有财政债务、央行资产负债表、国债买卖和买断式逆回购模块。

### 2.2 旧前端

旧 `dashboard.html` 是一个较大的单文件 React 页面：

- 内置 `SEED_DATA`。
- 默认 React Context 和页面状态从 `SEED_DATA` 初始化。
- 通过 `/api/data` 替换本地数据。
- 更新按钮调用 `/api/scrape`。
- 表格列较多，但来源、状态和缺失值口径不完整。

### 2.3 旧数据模型

旧版主要数据链路：

```text
央行网页 -> server.py 正则解析 -> monthly_data 宽表 -> /api/data -> dashboard.html
                               -> raw_pages 原文缓存
```

## 3. 修改了什么

### 3.1 央行月度金融数据

新增 `services/financial_data_service.py`，把旧 `monthly_data` 转换为指标级 `financial_observations`。

每条 observation 现在保存：

- `indicator_code`
- `value`、`unit_raw`、`unit_display`、`scale_factor`
- `period`、`frequency`
- `source_name`、`source_type`、`source_url`
- `source_title`、`published_date`、`parser_notes`
- `data_status`、`is_mock`、`is_seed`、`is_cache`
- 存量、累计和月增量等口径标记

同时改进了旧爬虫：

- 增加央行历史链接发现逻辑。
- 复用 `raw_pages` 中的历史公告链接。
- 兼容正文中被插入空格的中文文本。
- 扩展 M2、M1、贷款、存款、拆借和回购利率正则。
- 不再因旧 `manual` 标记而永久阻止官网数据覆盖。
- `/api/data` 改为通过 `build_api_payload()` 从 observation 层生成响应。

### 3.2 前端数据纪律

新版 `static/dashboard.html`：

- 页面启动后只请求 `/api/data`。
- 请求失败时不自动加载演示数据，而是显示后端未连接。
- 缺失值保留为空，不使用 0 填补。
- 详情表增加状态和来源列。
- 具体指标来源通过后端 `indicator_sources` 返回。
- 表格采用固定列宽、横向滚动和首列/表头冻结，减少错位。

当前仍保留 `DEMO_RECORDS` 和“加载演示数据”的显式按钮。它不会自动替代 API 数据，但从严格生产口径看，后续应考虑彻底移除或迁移到独立 demo 页面。

### 3.3 来源追踪和 Debug

新增：

- `financial_source_registry`
- `fiscal_source_registry`
- `/financial/debug`
- `/fiscal-debt/debug`
- `/api/financial/debug`
- `/api/fiscal-debt/debug`

Debug 页面可以查看：

- 指标最新值和最新期数。
- non-null 数量和覆盖范围。
- `source_url`、`source_title`、`published_date`、`parser_notes`。
- 每个原文 URL 解析出的指标。
- 缺少 `source_url` 的记录。
- cache、seed、mock、manual 等状态。
- 最近更新日志和解析错误。

### 3.4 财政债务主模块

新增 `services/fiscal_debt_service.py` 和 `static/fiscal_debt.html`：

- 抓取财政部债务管理司地方政府债券发行和债务余额月报。
- 保存指标级财政 observation 和具体月度原文 URL。
- 区分国债、地方政府债、城投债、财政缺口和情景推算。
- 未接入的数据返回 `missing`，不生成 mock。
- 情景推算单独标记为 `scenario`，不写成 official observation。

### 3.5 央行资产负债表

新增 `services/pboc_balance_sheet_service.py`：

- 从央行官方资产负债表附件解析数据。
- 保存总资产、国外资产、外汇、货币黄金、其他国外资产、对政府债权、对其他存款性公司债权等指标。
- 计算占总资产比例，并将公式和 `derived` 状态一并保存。

### 3.6 央行公开市场国债买卖

新增 `services/pboc_gov_bond_omo_service.py`：

- 只处理“公开市场国债买卖业务公告”。
- 不把逆回购、买断式逆回购或 MLF 混入国债买卖。
- 保存当月是否开展、净买入额、累计净买入额和具体原文。

### 3.7 买断式逆回购

新增 `services/pboc_buyout_reverse_repo_service.py`：

- 抓取栏目两页共 33 条公告。
- 区分招标公告和业务公告，避免重复计入。
- 从招标公告解析操作日期、买入时间、金额、期限和到期日。
- 公告未写明到期日时，用操作日期加期限推算，并标记 `derived`。
- 月末存量公式为：月末仍未到期的逐笔操作本金之和。
- 尚未结束的当前月份只显示预测，不冒充已完成月末值。

### 3.8 财政部国债逐只发行明细

新增 `services/mof_treasury_bond_service.py`：

- 从财政部债务管理司“业务公告”发现具体国债公告。
- 建立逐只/逐次发行明细，而不是只保存年度汇总。
- 保存债券名称、类型、发行性质、期限、发行日、起息日、到期日、票面利率、收益率、发行价格等字段。
- 严格区分 `planned_issue_amount` 和 `actual_issue_amount`。
- 只有结果公告才计入实际发行额。
- 只有发行通知时标记 `planned_only`，不把计划额当实际额。
- 支持年度、月度、类型、期限和未来到期年份汇总。

## 4. 增加了哪些文件和模块

| 文件 | 作用 |
|---|---|
| `services/financial_data_service.py` | 央行月度 observation、API payload、Debug |
| `services/financial_dictionary.py` | 金融指标字典和口径 |
| `services/pboc_fetcher.py` | 新服务与旧爬虫的适配 |
| `services/market_fetcher.py` | 市场数据占位；当前未配置真实来源 |
| `services/fiscal_debt_service.py` | 地方债、财政债务来源和情景推算 |
| `services/pboc_balance_sheet_service.py` | 央行资产负债表 |
| `services/pboc_gov_bond_omo_service.py` | 央行公开市场国债买卖 |
| `services/pboc_buyout_reverse_repo_service.py` | 买断式逆回购逐笔操作与月末存量 |
| `services/mof_treasury_bond_service.py` | 财政部国债逐只发行明细 |
| `static/financial_debug.html` | 央行数据 Debug 页面 |
| `static/fiscal_debt.html` | 财政债务主页面 |
| `static/fiscal_debt_debug.html` | 财政债务 Debug 页面 |

## 5. 当前最新代码架构

```text
中国人民银行官网 ----------------------------+
  金融统计报告 -> 旧爬虫/raw_pages ----------+--> monthly_data
  资产负债表附件 -> pboc_balance_sheet_service |
  国债买卖公告 -> pboc_gov_bond_omo_service   |
  买断式逆回购 -> buyout_repo_service         |
                                                  +--> SQLite observation 表
财政部官网 ------------------------------------+         |
  地方债月报 -> fiscal_debt_service             |         +--> API
  国债业务公告 -> mof_treasury_bond_service ----+                |
                                                                  +--> dashboard/debug 页面
monthly_data -> financial_data_service -> financial_observations -+
```

`server.py` 仍然承担：

- HTTP 服务入口。
- 旧央行月度爬虫。
- API 路由。
- 各 service 初始化和调度。

服务已拆分，但旧爬虫尚未完全从 `server.py` 分离。

## 6. 当前数据库真实状态

以下为 2026-06-17 直接查询 `D:\claude\pboc_data.db` 的结果。

### 6.1 央行月度金融数据

- `monthly_data`：97 行。
- `financial_observations`：1,228 条 observation。
- 实际有数据的月份：97 个月。
- 最早：2010-03。
- 最新：2026-05。
- 从 2010-03 到 2026-05 理论应有 195 个月，当前缺 98 个月。
- 当前 `/api/data`：`data_mode = cache`。
- 这批 cache 的直接来源是旧 `monthly_data` 和已归档央行网页，不是 seed/mock；但它是旧数据转换后的缓存层，不等于本次重新抓齐了全部历史月度公告。

主要指标覆盖：

| 指标 | 非空期数 | 最早 | 最新 |
|---|---:|---|---|
| M2 余额 | 97 | 2010-03 | 2026-05 |
| M2 同比 | 97 | 2010-03 | 2026-05 |
| M1 余额 | 94 | 2010-03 | 2026-05 |
| M1 同比 | 97 | 2010-03 | 2026-05 |
| 社融存量 | 9 | 2025-09 | 2026-05 |
| 社融同比 | 11 | 2023-03 | 2026-05 |
| 人民币贷款余额 | 92 | 2010-03 | 2026-05 |
| 人民币贷款同比 | 92 | 2010-03 | 2026-05 |
| 人民币存款余额 | 97 | 2010-03 | 2026-05 |
| 人民币存款同比 | 97 | 2010-03 | 2026-05 |
| 同业拆借加权平均利率 | 96 | 2010-03 | 2026-05 |
| 质押式回购加权平均利率 | 94 | 2010-03 | 2026-05 |

贷款结构、存款结构、社融结构目前没有独立的 `loan_structure`、`deposit_structure`、`tsf_structure` 数据表。贷款结构只从 `financial_observations` 中组合展示，且余额类结构只有 2026-01 至 2026-05 的 5 期；存款结构和社融结构仍未形成完整数据集。

### 6.2 地方政府债务

- `fiscal_debt_observations`：154 条 observation。
- 覆盖 7 个月：2025-09 至 2026-04。
- 最近一次抓取成功，但 2026 年 3 月页面曾返回 HTTP 502，日志保留该 warning。
- 数据来自财政部债务管理司具体月度页面，当前记录缺失 `source_url` 数量为 0。

### 6.3 央行资产负债表

- 60 条指标 observation。
- 5 个报告期：2026-01 至 2026-05。
- 缺失 `source_url`：0。
- 当前不是历史全量资产负债表。

### 6.4 央行公开市场国债买卖

- 10 个月：2024-08 至 2025-05。
- 缺失 `source_url`：0。
- 该模块表示央行二级市场国债买卖，不等同于财政部发行国债。

### 6.5 买断式逆回购

- 公告全集：33 条。
- 招标公告：25 条。
- 业务公告：8 条。
- 逐笔操作：26 笔。
- 操作日期覆盖：2025-06-06 至 2026-06-15。
- 月末存量：19 个期间，2025-06 至 2026-12；未来月份属于基于已知到期日的 derived 轨迹，不是未来真实操作预测。
- 所有记录均保存具体公告 `source_url`。

### 6.6 财政部国债发行

- `mof_treasury_bond_issuances`：204 条。
- official 结果记录：97 条。
- planned_only 记录：107 条。
- 当前发行日覆盖：2025-11-06 至 2026-06-25。
- 缺失 `source_url`：0。
- 2024 年及更早公告尚未通过旧财政部站点补齐，因此页面中的 2024 汇总为空是正确的，不应填 mock。

## 7. 当前 API 和页面

### 页面

| 地址 | 用途 |
|---|---|
| `/dashboard` | 央行金融统计主页面 |
| `/financial/debug` | 央行指标覆盖和来源 Debug |
| `/fiscal-debt` | 财政债务、央行资产和操作页面 |
| `/fiscal-debt/debug` | 财政债务来源和解析 Debug |

### 读取 API

| API | 用途 |
|---|---|
| `GET /api/data` | 央行月度金融数据，当前返回 cache |
| `GET /api/financial/debug` | 央行 observation 覆盖报告 |
| `GET /api/fiscal-debt/data` | 财政债务综合 payload |
| `GET /api/fiscal-debt/debug` | 财政债务 Debug |
| `GET /api/fiscal-debt/pboc-balance-sheet` | 央行资产负债表 |
| `GET /api/fiscal-debt/pboc-gov-bond-omo` | 央行国债买卖 |
| `GET /api/fiscal-debt/pboc-buyout-reverse-repo` | 买断式逆回购 |
| `GET /api/fiscal-debt/mof-treasury-bonds` | 财政部国债发行明细 |

### 更新 API

| API | 当前逻辑 |
|---|---|
| `POST /api/scrape` | 旧 `scrape_and_update()`，仍然存在 |
| `POST /api/financial/update` | 将当前月度宽表同步到 observation；本身不等于重新抓全站历史 |
| `POST /api/fiscal-debt/update` | 更新财政部地方债月报 |
| `POST /api/fiscal-debt/pboc-balance-sheet/update` | 更新央行资产负债表 |
| `POST /api/fiscal-debt/pboc-gov-bond-omo/update` | 更新央行公开市场国债买卖 |
| `POST /api/fiscal-debt/pboc-buyout-reverse-repo/update` | 更新买断式逆回购 |
| `POST /api/fiscal-debt/mof-treasury-bonds/update` | 更新财政部国债发行明细 |

## 8. 当前仍存在的问题

按优先级排序：

1. **央行历史月份不连续。** 目前 97 个实际月份，不是 2010-03 至今的连续 195 个月。
2. **社融历史覆盖不足。** 社融存量只有 9 期，需要独立抓取社融存量报告历史页。
3. **结构数据不完整。** 贷款结构只有近期少量余额数据；存款结构、社融结构没有独立表和完整历史。
4. **财政部国债旧站未接入。** 2024 及更早数据需要从旧国库司/国债管理路径发现和解析。
5. **地方债只有 7 个月。** 需要继续翻页和处理历史栏目迁移。
6. **央行资产负债表只有 5 个月。** 当前只验证了近期附件，没有历史全量。
7. **国债余额、城投债、财政缺口未接入。** 现在返回 missing 是正确行为。
8. **前端仍保留显式 demo 数据。** 不会自动使用，但生产版最好删除。
9. **`server.py` 仍偏大。** 旧爬虫、HTTP 路由和调度还在一个文件中。
10. **没有自动化测试。** 当前验证以数据库查询、API 200 和人工页面检查为主。
11. **没有 Git 仓库。** 只能依靠 `.bak` 文件追踪改动，后续回归和审计风险较高。

## 9. 如何运行和验证

启动：

```powershell
cd D:\claude
python server.py
```

检查服务：

```powershell
Invoke-RestMethod http://127.0.0.1:5001/api/health
Invoke-RestMethod http://127.0.0.1:5001/api/financial/debug
Invoke-RestMethod http://127.0.0.1:5001/api/fiscal-debt/debug
```

触发更新：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:5001/api/scrape
Invoke-RestMethod -Method Post http://127.0.0.1:5001/api/financial/update
Invoke-RestMethod -Method Post http://127.0.0.1:5001/api/fiscal-debt/update
Invoke-RestMethod -Method Post http://127.0.0.1:5001/api/fiscal-debt/pboc-balance-sheet/update
Invoke-RestMethod -Method Post http://127.0.0.1:5001/api/fiscal-debt/pboc-gov-bond-omo/update
Invoke-RestMethod -Method Post http://127.0.0.1:5001/api/fiscal-debt/pboc-buyout-reverse-repo/update
Invoke-RestMethod -Method Post http://127.0.0.1:5001/api/fiscal-debt/mof-treasury-bonds/update
```

注意：`/api/scrape` 是后台线程，返回 started 不代表已经抓取完成；需轮询 `/api/status`。随后再调用 `/api/financial/update`，把新的 `monthly_data` 同步到 `financial_observations`。

数据库覆盖检查：

```sql
SELECT COUNT(*) AS observations,
       COUNT(DISTINCT period) AS periods,
       MIN(period) AS earliest_period,
       MAX(period) AS latest_period
FROM financial_observations;

SELECT indicator_code,
       COUNT(value) AS non_null_count,
       MIN(period) AS earliest_period,
       MAX(period) AS latest_period,
       GROUP_CONCAT(DISTINCT source_type) AS source_type,
       GROUP_CONCAT(DISTINCT data_status) AS data_status
FROM financial_observations
GROUP BY indicator_code
ORDER BY indicator_code;

SELECT data_status,
       COUNT(*) AS records,
       COUNT(actual_issue_amount) AS actual_records,
       COUNT(planned_issue_amount) AS planned_records
FROM mof_treasury_bond_issuances
GROUP BY data_status;
```

## 10. 对“当前最新”的准确表述

当前代码版本可以表述为：

> 已完成前后端数据来源追踪、指标级 observation、央行及财政债务多个专项模块和 Debug 能力；近期数据已能从官方原文抓取、缓存和展示。央行月度金融主数据最新到 2026-05，财政部国债公告抓取到 2026-06，但历史数据仍不完整，不能称为全量历史数据库。

不应表述为：

> 已完成央行和财政部所有历史数据的全量抓取。

