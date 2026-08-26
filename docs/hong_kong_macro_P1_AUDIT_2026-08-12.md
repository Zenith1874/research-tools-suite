# 香港宏观 P1 续做审计记录（2026-08-12）

## 1. 审计目的与边界

本记录对应用户提供的香港宏观独立模块与中国官方外汇储备接入提示词的 P1 续做。目标是把
HKMA 银行细表、Trade-IDDS 贸易维度、CSD Web Table 细表和内地住房成交联动接入现有
`/mnt/d/claude` 项目的可审计链路；不删除原始数据，不把香港写入中国城市经济表，也不把
香港金融管理局的储备资产当作中国 SAFE 官方储备资产。

提示词副本：
`docs/hong_kong_macro_implementation_prompt_2026-08-11.md`

## 2. 实现范围

### HKMA

新增并登记以下官方 API 数据集：

- banking statistics：认可机构数、资产、外部债权/负债、客户存款、贷款、住宅按揭和质量指标；
- customer deposits by HKD/FC：活期、储蓄、定期、总额及 HKD/FC 分拆；
- customer deposits by CNY：人民币活期/储蓄、定期、总额、认可机构数；
- loans by type：香港贸易融资、非香港商品贸易、香港境内/境外/用途未知及总贷款，含 HKD/FC 贸易融资。
- residential mortgage survey：未偿还按揭、拖欠/重组、新申请、新批/新取用、物业交易类型、LTV、合约期和新批利率参考；
- residential mortgage loans in negative equity：季度负资产贷款宗数、金额、无抵押部分、占比和 LTV。

官方入口：[HKMA banking statistics](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/financial/banking-statistics/)、
[customer deposits HKD/FC](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/customer-deposits-by-type-hkd-fc)、
[CNY deposits](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/customer-deposits-by-type-cny/)、
[loans by type](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/loans-by-type-lb/)、
[residential mortgage survey](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/residential-mortgage-survey/)、
[negative equity loans](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/residential-mortgage-loans-neg-equity/)。

### Trade-IDDS

新增六个独立 dimension source：

| source | 口径 | 结果 |
|---|---|---:|
| `HK_TRADE_IDDS_MAINLAND_ORIGIN` | 中国内地原产地进口 | 66 |
| `HK_TRADE_IDDS_MAINLAND_CONSIGNMENT` | 中国内地寄运地进口 | 66 |
| `HK_TRADE_IDDS_MAINLAND_DESTINATION` | 中国内地目的地出口 | 66 |
| `HK_TRADE_IDDS_TOP_ORIGINS` | 全部进口来源地 Top N；`co=ALL` | 12,096 |
| `HK_TRADE_IDDS_TOP_DESTINATIONS` | 全部出口目的地 Top N；`cc=ALL` | 13,264 |
| `HK_TRADE_IDDS_TOP_SITC2_EXPORTS` | T210 当前定义的 68 个 SITC2 商品代码；官方零记录分类不展示 | 4,304（跨期 67 个有记录代码，最新期 64 个） |

每条记录保留 `dimension_code`、官方 label、贸易类型、期间、统计量、单位、source URL、
raw hash、原始 dimension JSON 和说明。请求参数依据 [Trade-IDDS API specification](https://tradeidds.censtat.gov.hk/MetadataLink/ApiSpec/API_eng.pdf)
和官方 [T057](https://tradeidds.censtat.gov.hk/CommonTable/T057)、
[ETR08a03](https://tradeidds.censtat.gov.hk/CommonTable/ETR08a03)、
[T210](https://tradeidds.censtat.gov.hk/CommonTable/T210) 核对。

### CSD Web Table

接入 17 张官方 Web Table：

`310-31002`, `310-31003`, `310-31007`, `310-33041`, `310-33042`, `620-67001`,
`620-67002`, `620-67003`, `620-67021`, `650-80001`, `650-80005`, `110-01003`,
`315-37001`, `315-37003`, `315-37004`, `315-37021`, `315-37031`。

CSD 响应同时包含不同 `freq` 和 `svDesc`。canonical `series_code` 显式保留频率、统计量
和动态维度；年、季、月期间分别保存为 `YYYY`、`YYYY-Qn`、`YYYY-MM`。官方 Web Table
字典见 [WT_data_dict_en.pdf](https://www.censtat.gov.hk/datagovhk/WT_data_dict_en.pdf)。

## 3. 数据库与更新结果

- 数据库：`/mnt/d/claude/pboc_data.db`
- 写库前备份：`backups/pboc_data_hong_kong_preflight_20260811.db`
- CSD 系列键维护备份：`backups/pboc_data_csd_key_migration_pre_20260812T011333.db`
- 续做写库前备份：`backups/pboc_data_monthly_flow_pre_20260812.db`、`backups/pboc_data_hkma_retry_pre_20260812.db`
- 最近在线 run（HKMA 定向 retry）：`337b032b595a44388e0787acf9572b8a`
- 定向 retry 状态：`completed`
- 定向 retry 解析/写入：`11,461 / 11,461`，`error_count=0`
- 历史全域更新 run：`e297ef25b3f34991af5db3bdd976a339`，`partial`，`128,102 / 128,102`
- 数据库 `PRAGMA quick_check`：`ok`

当前计数：

| 层 | active/canonical | superseded | 备注 |
|---|---:|---:|---|
| `hong_kong_macro_observations` | 25,721 | 1,044 | 134 个实际有值指标；注册指标 139 个 |
| `hong_kong_macro_trade_dimensions` | 29,862 | 0 | 6 个维度 source；来源地 12,096、目的地 13,264、SITC2 4,304 条 |
| `hong_kong_macro_web_table_observations` | 85,449 | 54,292 | 17 张 CSD Web Table |
| `hong_kong_macro_sources` | 42 sources | — | 42 success（定向 retry 后） |

此前全域刷新中 HKMA 8 个 source 受网络影响；本次定向 retry 已重新取得并写入全部 8 个 source，
旧版有效观测和历史失败证据均未删除。当前相关记录为：

- `HK_HKMA_FC_RESERVE_ASSETS`、`HK_HKMA_ECONOMIC`、`HK_HKMA_MONETARY`、
  `HK_HKMA_BANKING_STATS`、`HK_HKMA_CUSTOMER_DEPOSITS`、`HK_HKMA_RMB_DEPOSITS`、
  `HK_HKMA_LOANS_BY_TYPE`、`HK_HKMA_MORTGAGE_SURVEY`：定向 retry 后均为 `success`；
- `HK_HKMA_NEGATIVE_EQUITY` 仍提供可用的季度观察，不把季度插值为月度。

## 4. 数据质量门禁

已运行以下检查：

- Trade dimension 唯一键重复：`0`；关键字段空值：`0`；
- CSD active 行逐表满足 `COUNT(*) = COUNT(DISTINCT period, series_code)`；重复：`0`；关键字段空值：`0`；
- 17 张 CSD 表 raw 解析数合计 `85,449`，canonical active 入库数合计 `85,449`；逐表 source `record_count` 与 active 入库数一致；
- 主 observation 的 active 行中 source URL、unit、raw hash 缺失：`0`；
- `housing_national_observations` 的 `sales_area_monthly_derived`、`sales_value_monthly_derived` 各 `109` 条，
  覆盖 `2015-03—2026-06`；只使用同一年度相邻官方累计值差分，缺失上月的 `14` 个期间不推断，负差分 `0`。
- 当前 `hong_kong_macro_lead_lag_results` 有 `2` 个显式 snapshot、`980` 行；每个 snapshot `490` 行，
  保存后按 `snapshot_id` 读回行数一致。
- 数据库 `quick_check=ok`；raw 文件未被覆盖或删除。

第一次 CSD 解析审计确认：只使用 `period + sv/dimension` 会把年度、季度、月度或不同统计量
折叠。修复后采用 `freq + sv + svDesc + dimension`；原已写入的错误派生键保留在同表并标记
`data_status='superseded'`，API、debug 摘要和页面查询均排除这些行。

## 5. API、页面和测试

实现/更新文件：

- [hong_kong_macro_service.py](/mnt/d/claude/services/hong_kong_macro_service.py)
- [server.py](/mnt/d/claude/server.py)
- [hong_kong_macro.html](/mnt/d/claude/static/hong_kong_macro.html)
- [test_hong_kong_macro_service.py](/mnt/d/claude/tests/test_hong_kong_macro_service.py)

新增/确认接口：

- `/api/hong-kong-macro/data`
- `/api/hong-kong-macro/debug`
- `/api/hong-kong-macro/export.csv`
- `/api/hong-kong-macro/trade-dimensions?dimension_type=origin_top&latest=1&top_n=10`
- `/api/hong-kong-macro/trade-dimensions.csv`
- `/api/hong-kong-macro/lead-lag`
- `/api/hong-kong-macro/lead-lag/save`
- `/api/hong-kong-macro/lead-lag/saved`
- `/api/hong-kong-macro/retry-hkma`
- `/hong-kong-macro`

测试命令：

```text
PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest tests.test_hong_kong_macro_service -v
PYTHONIOENCODING=utf-8 python.exe -m py_compile services/hong_kong_macro_service.py server.py tests/test_hong_kong_macro_service.py
git diff --check
```

本次局部测试：新增的月度流量、snapshot 持久化、接口契约和页面派生序列测试均通过。全量回归共
542 项通过；`py_compile` 通过；5001 API 和 Playwright 页面验收均通过，控制台错误/警告为 0，
国家住房 YTD 动态警告与 derived 月度流量定义均在结果区显示。1440px 和 390px 视口均无横向溢出。

## 6. 本轮逐项修复结果

本节为提示词执行后的复核补充，前面的审计结论仍保留作为独立验收基线。

### 7.1 P0-A SAFE

- SAFE 黄金数量已经使用真实官方 HTML 数量行解析；2026-01—07 为 `7419, 7422, 7438, 7464, 7496, 7544, 7608` 万盎司。
- 2026-07 黄金美元价值为 `3063.54` 亿美元，未被数量或总额覆盖。
- 2015 `.xls`、2016—2017 `.xlsx` 历史附件分别有兼容解析路径；2015 官方源没有可审计黄金数量，不填造值。
- SAFE 外汇储备与官方储备资产合计未来空白月份标记为 `not_released`，并带 `official_source_future_month_blank`；SAFE 与 PBoC `foreign_exchange`、结售汇、涉外收付款保持独立。

### 7.2 P0-B lead-lag

lead-lag 总体状态统一为：`ok`、`hk_no_data`、`mainland_no_data`、`unsupported_transform`、`insufficient_overlap`、`invalid_request`、`failed`。只有 `ok` 才 `success=true`。空香港、空内地、15 月短样本、未知指标和不支持转换均有测试；`lag=0` 不进入香港领先候选；无效或无有效全样本曲线不能写 snapshot。

### 7.3 P0-C API/CSV

主 API 和 CSV 共享 start/end/group/indicator/source/frequency/status/base/transform/base_period/include flags。默认 active、非 NULL、非 superseded；RVD 季度 `1979-Q4—2026-Q2` 同筛选 JSON/CSV 均为 187 条，CSV 为 31 列且含 source/status/hash/parser 等字段。CSD preview 为空，CSD 细表通过独立分页 endpoint 读取。

### 7.4 P1、页面和最终回归

- RVD 月/季/年频率分开；Land Registry 六个指标各 295 条，覆盖 2002-01—2026-07；HKMA 42 个 source 当前 hash 全部 match。
- CSD 17 表 active canonical 85,449 条，M/Q/H/Y 与 `freq+sv+stat+dimension` 语义键保留；主 API 有 10 条 curated mapping；CSD explorer 返回 `n_rows/total_rows/has_more`。
- 页面六个页签、全局筛选、动态转换、CSV、tooltip/图例、source/freshness、真实 CSD 图、Trade Top N、lead-lag 49 lag/滚动曲线和 no-data/stale 状态均已验收。
- 1440×900 与 390×844 document 无横向溢出，Playwright console errors/warnings 为 0。
- 全量回归：`551` 项通过；定向香港宏观：`22` 项通过；`py_compile` 和 `git diff --check` 通过。

### 7.5 当前限制

页面整体当前显示 `stale`，原因是 CSD 访客表最新期为 2026-05；香港 source 多数不提供稳定 release_date，保持 NULL 并以 retrieved_at 记录抓取时间。自动 vintage 回测、多重比较校正、因果/预测、市级官方月度销售面积或销售额仍是明确 backlog。

## 7. 仍需后续处理

1. 后续全域刷新仍可能受 HKMA 源站网络波动影响；本次定向 retry 已成功，但不能据此假设永久可用。
2. 如研究问题需要市级住房销售面积/销售额，仍需另找/接入可审计的官方月度源；当前国家层面
   derived 流量来自官方累计值差分，不是官方单独发布的月度流量，YTD 序列只作敏感性配对。
3. lead-lag 已支持显式 snapshot 保存/检索；尚未做自动化批量 vintage 回测调度，需要先定义配对集合、
   窗口版本和保存策略。
