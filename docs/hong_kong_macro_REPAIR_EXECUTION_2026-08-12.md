# 香港宏观与中国 SAFE 官方储备资产完整修复执行记录

> **历史记录说明（2026-08-12 final remediation）**：本文是前一阶段执行日志，早期“完成/production-ready”等表述不再是当前判定。请以 [最终执行状态](hong_kong_macro_FINAL_STATUS_2026-08-12.md) 为准；该文档修正了 CSD 构念、SAFE 发布日期、RVD 部分年度、HKMA period、identity status、legacy lead-lag 和 debug GET 只读性。本文保留，以便追溯原始执行证据。

**项目目录**：`/mnt/d/claude`  
**执行日期**：2026-08-12  
**执行目标**：按照《香港宏观与中国 SAFE 官方储备资产完整修复提示词》逐项修复、补数、验证，并保留原始数据、历史失败证据和旧 snapshot。

> 说明：本文保留前一阶段的逐项执行证据；最后一轮补丁、live API/CSV、真实浏览器交互、560 项全量回归和当前数据库计数以 [最终完整性审计](/mnt/d/claude/docs/hong_kong_macro_COMPLETENESS_AUDIT_2026-08-12.md) 为准。后续若计数或页面行为与本文早期段落不同，应优先采用最终审计记录。

## 1. 最终结论

本轮 P0、研究使用所需的 P1 关键链路和浏览器验收已经实际落地，不能再把“有数据库行数”当作“可研究使用”的唯一证据。当前链路已经达到：

```text
官方入口/响应
  -> raw 文件或 raw 响应
  -> SHA-256 与 source metadata
  -> parser 与 period/frequency/semantic mapping
  -> active canonical observation
  -> API/CSV 独立筛选
  -> 页面图表、细表 explorer、状态和来源展示
  -> debug、测试、浏览器验收
```

最终状态应表述为：**本轮修复完成，数据状态仍按 source freshness 如实显示为 `stale`，自动 vintage 回测调度、因果识别和正式预测仍是 backlog。** 页面当前的 `stale` 不是成功假装为 `current`，而是由 CSD 访客来源 `HK_CSD_WEB_650-80001` 的最新期 `2026-05` 触发的明确质量提示。

## 2. 本轮保护和备份

- 未删除、覆盖或重命名原始 raw 文件、旧 observation、旧 superseded 行或既有 snapshot。
- SAFE 定向刷新前保留：`backups/pboc_data_safe_pre_20260812.db`。
- Land Registry 回填前保留：`backups/pboc_data_landreg_pre_20260812.db`。
- RVD 回填前保留：`backups/pboc_data_rvd_pre_20260812.db`。
- 数据库 schema 通过增量迁移增加 `missing_reason`，现有表和字段继续可读。
- 现有工作树中的其他用户改动未做 reset、checkout 或清理；本记录只描述本轮香港宏观/SAFE相关变更。

## 3. P0-A：SAFE 官方黄金数量和历史附件

### 3.1 解析和口径

`services/china_external_service.py` 现在把 SAFE 官方储备资产 HTML 与历史 XLS/XLSX 分成明确解析路径：

- HTML 支持真实黄金美元行之后、行首没有标签但每月单元格带“万盎司”的数量行。
- XLS/XLSX 支持 2015 的旧式 `.xls` 和 2016—2017 的 `.xlsx`；兼容一月一列和美元/SDR 成对列，不把 SDR 列当作美元列。
- `CN_SAFE_MONETARY_GOLD_QUANTITY` 只在官方源确实给出数量时写入；2015 官方历史附件未提供可审计数量，因此没有制造 2015 数量。
- 每条 SAFE observation 继续记录 `source_url`、`release_date`（源能推断时）、`retrieved_at`、`raw_sha256`、`parser_version` 和 `missing_reason`。
- SAFE 外汇储备、官方储备资产合计、黄金美元价值、黄金数量、SDR、IMF储备头寸和其他储备资产继续使用独立指标代码；没有写入 PBoC `foreign_exchange`，也没有把结售汇或涉外收付款当作 SAFE 储备资产。

### 3.2 实际数据库结果

| 指标 | 行数 | 覆盖 | NULL | 结果 |
|---|---:|---|---:|---|
| `CN_SAFE_FX_RESERVES_USD` | 139 | 2015-06—2026-12 | 5 | 未来空白为 `not_released` |
| `CN_SAFE_MONETARY_GOLD_QUANTITY` | 127 | 2016-01—2026-07 | 0 | 2026-01—07 已回填 |
| `CN_SAFE_MONETARY_GOLD_USD` | 139 | 2015-06—2026-12 | 5 | 未被总额或数量覆盖 |
| `CN_SAFE_OFFICIAL_RESERVE_ASSETS_TOTAL_USD` | 139 | 2015-06—2026-12 | 5 | 官方总额独立保留 |

2026 年 SAFE 黄金数量的实际值为：

| 月份 | 数量（万盎司） |
|---|---:|
| 2026-01 | 7419 |
| 2026-02 | 7422 |
| 2026-03 | 7438 |
| 2026-04 | 7464 |
| 2026-05 | 7496 |
| 2026-06 | 7544 |
| 2026-07 | 7608 |

2026-07 `CN_SAFE_MONETARY_GOLD_USD` 为 `3063.54` 亿美元。2026-08—12 的 SAFE 外汇储备和官方储备资产合计空白行均为：

```text
data_status = not_released
missing_reason = official_source_future_month_blank
```

空白行仍有官方来源 URL、raw hash、parser version 和抓取时间，默认 API 不把它们当成有效观测。

### 3.3 历史格式证据

- 2015：官方 `.xls`，写入外汇储备 7 个月；未发现可审计黄金数量行。
- 2016：官方 `.xlsx`，写入外汇储备 12 个月和黄金数量 12 个月。
- 2017：官方 `.xlsx`，写入外汇储备 12 个月和黄金数量 12 个月。
- SAFE 解析器版本：`safe_reserve_v2`。

## 4. P0-B：lead-lag 状态、样本门禁和 snapshot 保存

lead-lag 总体状态现在固定为：

```text
ok
hk_no_data
mainland_no_data
unsupported_transform
insufficient_overlap
invalid_request
failed
```

只有 `status=ok` 且至少一个全样本 lag 的 `corr` 非空时 `success=true`。具体门禁如下：

- 香港序列为空：`success=false, status=hk_no_data`。
- 内地序列为空：`success=false, status=mainland_no_data`。
- 香港序列不是月度：`invalid_request`。
- 指标不支持转换：`unsupported_transform`；无效 `min_overlap` 也进入 `invalid_request`。
- 有序列但 49 个 lag 都达不到最低重叠：`insufficient_overlap`。
- 计算异常：`failed`，不生成伪造结果。
- `best_hong_kong_lead` 只从 `lag_months >= 1` 选择；`lag=0` 保留在同期曲线中，但不进入香港领先结果。
- 保存函数要求 `success=true`、`status=ok`、全样本曲线中至少一个 `status=ok` 且 `corr` 非空；空曲线、全 NULL 曲线、零观察和失败 payload 都被拒绝。
- GET 计算不写表；只有显式 POST 保存才写入 snapshot。

现场接口核验：

- `HK_RVD_PRIMARY_SALES_VALUE` 请求返回 `success=false, status=hk_no_data`，并保留上游状态 `unavailable_at_source`。
- 非法 `transform=qoq` 返回 HTTP 400 和 `status=unsupported_transform`。
- 非法 `min_overlap=bad` 返回 HTTP 400 和 `status=invalid_request`。
- 默认配对返回 HTTP 200、`success=true`、`status=ok`、49 个 lag；默认最佳绝对相关为 `lag=-17`，香港领先区间最佳为 `lag=12`。

## 5. P0-C：API、CSV 和查询契约

主接口为 `/api/hong-kong-macro/data`，导出为 `/api/hong-kong-macro/export.csv`。当前筛选契约包括：

```text
start, end, group, indicator/indicators, source/source_id,
frequency/freq, status/data_status, base, transform,
base_period, include_superseded, include_missing
```

规则：

- 默认读取 active、非 NULL、非 superseded canonical rows。
- `start`、`end`、频率和 `M/Q/H/Y` period 语义在 SQL/filter 后保持一致。
- 未知指标、未知 source、非法 period、`start>end` 和不支持转换不静默忽略。
- `index100` 使用显式 `base_period`；基期不在序列中时失败，不自动换基。
- API 的 public series 和 CSV 都保留原值、转换值、公式、状态、来源、单位、频率、发布日期/抓取时间、vintage、raw hash、parser 和缺失原因。
- CSV 当前表头为 31 列，含 `source_url`、`data_status`、`raw_sha256` 等审计字段；中文以 UTF-8 输出。

实际一致性核验使用 RVD 季度历史：

- 相同筛选 `1979-Q4—2026-Q2 + index100 + base_period=2000-Q1`，JSON 返回 187 条，CSV 返回 187 条数据行。
- JSON 第一条为 `1979-Q4`，CSV 第一/最后 period 也为 `1979-Q4/2026-Q2`。
- CSV 默认不带 1,044 条 superseded NULL 历史记录。
- 主 payload 的 `csd_web_table_preview=[]`；CSD 不再被无条件塞进 2,000 行 preview。

## 6. P1-A：source metadata、freshness 和缺失状态

### 6.1 数据库当前审计值

```text
PRAGMA quick_check = ok
主表 active/non-superseded non-NULL observations = 26,903
主表 superseded observations = 1,044
CSD active/non-superseded observations = 85,449
CSD superseded observations = 89,606
active 主 observation 重复键 = 0
active CSD 重复键 = 0
source hash status = 42 match
主 observation source_url/retrieved_at/raw_sha256/parser_version 缺失 = 0
CSD source_url/retrieved_at/raw_sha256/parser_version/period_raw/statistic 缺失 = 0
```

主 observation 的 `release_date` 缺失数为 26,903。这个缺失是明确记录的源限制：香港源没有稳定、统一、可复核的发布日期字段；系统使用 `retrieved_at` 记录本次抓取时间，绝不把抓取时间伪装成发布日期。

### 6.2 source freshness

42 个香港 source 当前 `status=success`。source 同时记录 `latest_reference_period`、`last_success_at`、`record_count`、`frequency`、`raw_sha256`、`parser_version` 和 freshness。月度、季度、半年、年度使用不同的新鲜度阈值；混合频率 source 不把字符串排序当作日期排序。

当前页面整体状态为 `stale`，唯一明确的 stale source 为：

```text
HK_CSD_WEB_650-80001
latest_reference_period = 2026-05
```

这会在 meta strip 和 source table 中显示，不阻止历史数据阅读，但阻止页面把整体状态写成“正常最新”。

## 7. P1-B：RVD、Land Registry 和 HKMA 边界

### 7.1 RVD 官方频率历史

RVD 价格/租金指数不再把季度、年度历史复制成月度：

| 指标 | active 行数 | 覆盖 |
|---|---:|---|
| `HK_RVD_PRICE_INDEX` | 402 | 1993-01—2026-06（月度） |
| `HK_RVD_RENT_INDEX` | 402 | 1993-01—2026-06（月度） |
| `HK_RVD_PRICE_INDEX_QUARTERLY` | 187 | 1979-Q4—2026-Q2 |
| `HK_RVD_RENT_INDEX_QUARTERLY` | 184 | 1980-Q3—2026-Q2 |
| `HK_RVD_PRICE_INDEX_ANNUAL` | 46 | 1980—2025 |
| `HK_RVD_RENT_INDEX_ANNUAL` | 45 | 1981—2025 |

季度 period 保留 `YYYY-Qn`，年度 period 保留 `YYYY`；来源 raw hash 与 `hk_macro_v1.1` parser 版本已写入。RVD 的三个金额指标继续是 `unavailable_at_source`，没有用 Land Registry 金额替代。

### 7.2 Land Registry 全历史

已探测并抓取官方六个分段 endpoint：

```text
agt-primary, agt-pri-5, agt-pri-4,
agt-pri-3, agt-pri-2, agt-pri-1
```

最终 raw 文件：`data/hong_kong_macro_raw/HK_LANDREG_PRIMARY_20260812T143217437779.json`  
SHA-256：`1c95aed15382c9325b5a93b43bf1316e3d36a12d8612fd0ef23ae1c657184be9`  
实际解析/写入：`1,770 / 1,770`。

六个 Land Registry 指标各 295 条，全部覆盖 `2002-01—2026-07`：一手/二手/合计的宗数和金额。金额来自官方金额字段；没有用 RVD 成交金额推算。

### 7.3 HKMA 短历史与不可用字段

HKMA 银行统计、客户存款、人民币存款、贷款、按揭、负资产按揭、货币统计和外汇储备端点均记录实际 source status。短 endpoint 的历史起点和 record count 会显示在 source table，不能被称为完整历史。

五个完全无值指标仍保留在注册表并明确标记：

```text
HK_HKMA_FC_RESERVE_ASSETS_LF       unsupported_field
HK_HKMA_UNSETTLED_FX_CONTRACTS_LF  unsupported_field
HK_RVD_PRIMARY_SALES_VALUE         unavailable_at_source
HK_RVD_SECONDARY_SALES_VALUE       unavailable_at_source
HK_RVD_TOTAL_SALES_VALUE           unavailable_at_source
```

它们不进入默认图表、API 有效序列或可保存 lead-lag 候选；没有使用总额减项推算 Land Fund，也没有使用其他机构字段冒充 RVD 金额。

## 8. P1-C：CSD Web Table semantic layer

### 8.1 17 张细表重解析结果

当前 active canonical 总计 `85,449` 条；旧键折叠行没有删除，而是 `superseded`。逐表结果如下：

| table_id | active rows |
|---|---:|
| 110-01003 | 416 |
| 310-31002 | 3,275 |
| 310-31003 | 3,275 |
| 310-31007 | 1,680 |
| 310-33041 | 3,930 |
| 310-33042 | 2,870 |
| 315-37001 | 1,965 |
| 315-37003 | 7,989 |
| 315-37004 | 9,703 |
| 315-37021 | 4,390 |
| 315-37031 | 5,389 |
| 620-67001 | 1,384 |
| 620-67002 | 20,825 |
| 620-67003 | 13,775 |
| 620-67021 | 1,034 |
| 650-80001 | 3,492 |
| 650-80005 | 57 |

### 8.2 语义规则

- 期间规范为 `M=YYYY-MM`、`Q=YYYY-Qn`、`H=YYYY-H1/H2`、`Y=YYYY`。
- stable `series_code` 保留 `freq`、`sv`、`stat` 和实际维度；不同统计量、单位或维度不再折叠。
- `series_label` 与 `unit` 分开；没有可用变量名时保留真实 `sv/svDesc`，不把纯单位当成变量名。
- observation 保留 `period_raw`、`statistic`、`construct_label`、`dimension_json`、`parser_version` 和 `missing_reason`。
- 110-01003 的人口精选映射使用半年频率，页面显示 `2000-H1` 等官方 period，不插值为月度。

### 8.3 curated mappings

主 API 接入 10 条可解释精选序列：GDP 当期价格季度、实质 GDP 季度、实质 GDP 同比季度、私人消费季度、固定资本形成季度、经常账户季度、零售总额月度、零售价值指数同比月度、内地访港旅客月度、人口半年。每条 mapping 记录 table、stable series code、名称、unit、frequency、statistic、category、note 和 `mapping_version=csd_curated_v1`。

CSD 独立 endpoint：

```text
/api/hong-kong-macro/csd-web-table/{table_id}
```

支持 `start`、`end`、`series_code`、`frequency`、`statistic`、`include_superseded`、`include_missing`、`limit`、`offset`，返回 `n_rows`、`total_rows`、`has_more` 和 frequency summary。现场请求 `110-01003?limit=2` 返回 2/416 行，period 为 `2000-H1`，frequency 为 `semiannual`；没有把 85,449 条送到浏览器。

## 9. P1-D：页面和浏览器验收

页面文件：`static/hong_kong_macro.html`。已确认：

- 六个页签：总览、住房、经济、再出口贸易、储备与金融、中国联动。
- 全局 start/end、frequency、indicator、source、transform、base_period 状态；CSV link 随当前 state 构造。
- 选择指标后动态约束 transform；半年、季度、年度不伪装成月度 lead-lag。
- 卡片、SVG chart tooltip、可点击图例、source table、freshness、stale/partial/no-data 提示可用。
- 经济页绘制真实 curated CSD GDP、消费、固定资本形成、经常账户、零售等历史。
- CSD explorer 独立分页，不展示巨型 preview。
- Trade-IDDS Top N 使用有限页面结果，完整维度仍由独立 API/CSV 读取。
- lead-lag 有完整 -24—+24 曲线、标准化共同月份序列和 60/120 月滚动曲线。
- 更新按钮和 snapshot 保存都是明确写操作；读取和 GET 计算不自动写入。

最终浏览器运行态：

```text
URL: http://127.0.0.1:5001/hong-kong-macro
desktop: 1440 x 900
mobile: 390 x 844
desktop documentScrollWidth = 1425 = documentClientWidth
mobile documentScrollWidth = 375 = documentClientWidth
console errors = 0
console warnings = 0
```

截图：

- `output/playwright/hong-kong-macro-desktop-final.png`
- `output/playwright/hong-kong-macro-mobile-final.png`

移动端顶部导航自身保留水平滚动容器，这是导航的响应式行为；页面 document/body 没有横向溢出。

## 10. P2：snapshot、vintage 和可复现性

`hong_kong_macro_lead_lag_snapshots` 和 `hong_kong_macro_lead_lag_results` 保留：

- snapshot_id、pair_code、香港/内地指标、transform、min_overlap、lag 范围和窗口；
- 香港/内地样本数、input_start/input_end、input_hash；
- source vintages JSON（raw hash、retrieved_at）；
- parameters JSON、computation version、code revision、computed_at、status、note；
- 每个 lag 的 corr、n_obs、window、status。

现有两个测试 snapshot 和 980 条结果仍可按 snapshot_id 读取；本轮最终浏览器只验证保存按钮门禁，没有额外写入正式 snapshot。保存采用事务，失败不保留半个 snapshot；GET 前后行数不改变。

自动批量 vintage 回测尚未实现，避免在没有定义 pair 集合、窗口版本和调度权限前擅自引入后台写入。

## 11. 测试、命令和输出

最终测试结果：

```text
PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest discover -s tests -q
Ran 551 tests ... OK

python3 -m py_compile services/hong_kong_macro_service.py server.py tests/test_hong_kong_macro_service.py
OK

git diff --check
OK（仅保留 Git 的 CRLF 转换提示，无 whitespace error）
```

定向香港宏观测试：`22` 项通过。测试覆盖 SAFE HTML、RVD 月/季/年、Land Registry、CSD H 频率、CSD endpoint 分页、查询/CSV、transform/base_period、lead-lag 状态、snapshot 保存门禁、Trade-IDDS 和 derived 序列。

运行态命令：

```text
GET /api/health                                  -> 200, status=ok
GET /api/hong-kong-macro/data                    -> 200, 42/42 source success
GET /api/hong-kong-macro/debug                   -> quick_check=ok
GET /api/hong-kong-macro/csd-web-table/110-01003 -> 200, bounded pagination
GET /api/hong-kong-macro/export.csv              -> 200, current filters
GET /api/hong-kong-macro/lead-lag                -> 200 when status=ok/no-data
GET invalid transform/min_overlap                -> 400
```

## 12. 明确保留的限制和 backlog

这些内容没有被空卡片或成功状态掩盖：

1. CSD 访客表最新期为 2026-05，页面整体显示 `stale`；需要源端发布新期后再刷新。
2. 香港多数 source 不提供统一 release_date；该字段保持 NULL，retrieved_at 单独记录抓取时间。
3. 2015 SAFE 历史附件未提供可审计黄金数量，因此黄金数量从 2016-01 开始；没有凭外汇储备或黄金美元价值反推数量。
4. HKMA 短端点的历史覆盖由 source metadata 如实展示；不能称为完整历史。
5. 自动 lead-lag vintage 批量回测、多重比较校正、稳健显著性、因果识别、正式预测、高频 nowcast 尚未实施。
6. 市级官方商品房销售面积/销售额月度流量仍未接入；当前国家层面月度流量是由官方累计值差分得到的 derived 序列，1—2 月合并发布期不拆分、不插值。
7. 本轮没有引入定时任务或后台自动写入；后续若要调度，需单独定义权限、频率、失败重试和 vintage 策略。

## 13. 主要实现文件

- [services/hong_kong_macro_service.py](/mnt/d/claude/services/hong_kong_macro_service.py)
- [services/china_external_service.py](/mnt/d/claude/services/china_external_service.py)
- [services/china_macro_dashboard_service.py](/mnt/d/claude/services/china_macro_dashboard_service.py)
- [server.py](/mnt/d/claude/server.py)
- [static/hong_kong_macro.html](/mnt/d/claude/static/hong_kong_macro.html)
- [tests/test_hong_kong_macro_service.py](/mnt/d/claude/tests/test_hong_kong_macro_service.py)
- [hong_kong_macro_P1_AUDIT_2026-08-12.md](/mnt/d/claude/docs/hong_kong_macro_P1_AUDIT_2026-08-12.md)
- [hong_kong_macro_STATUS_2026-08-11.md](/mnt/d/claude/docs/hong_kong_macro_STATUS_2026-08-11.md)
