# 香港宏观模块最终执行状态（Prompt A）

**状态**：`complete`（代码、迁移、数据库、API、页面、真实浏览器和文档证据均已完成；“complete”不表示所有官方来源同日更新）
**研究使用判定**：描述性/可审计研究使用 `research-ready`；lead-lag 仍明确为描述性相关，不是因果识别或正式预测。
**执行日期**：2026-08-12（America/Denver；浏览器记录使用 UTC 文件时间）
**项目目录**：`/mnt/d/claude`
**执行依据**：`docs/hong_kong_macro_final_remediation_prompts_2026-08-12.md` 的“启动提示词 A：一次完成全部修复（推荐）”
**Git 边界**：未 `git add`、未提交、未推送、未创建 PR。

## 1. 结论先行

Prompt A 的 P0（4/4）、P1（4/4）和 P2（4/4）均已实施并完成适用验收。香港仍是独立 `jurisdiction=HK` 模块，没有写入城市经济模块；SAFE 储备资产仍位于独立的 `china_macro_observations` 表，不与 PBoC、结售汇或涉外收付款序列混用。

仍需如实保留的状态不是修复阻塞：部分官方来源没有逐观测发布日期，`expected_release_lag_days` 保持 `NULL` 并标为 `not_yet_verified`；CSD 访客表最新缓存期为 2026-05，页面因此可能显示 `stale`；身份等式中的官方舍入差异显示为 `warning`，而不是被伪装成 `pass`。这些都在 API/debug/UI 中披露。

## 2. P0 数据语义修复

| 项目 | 实施结果 | 生产库证据 |
|---|---|---|
| CSD 110-01003 | 表名改为 `Population growth by component`；新增活动 code `HK_CSD_WEB_POPULATION_GROWTH_SEMIANNUAL`；旧 `HK_CSD_WEB_POPULATION_SEMIANNUAL` 只作为 deprecated catalog 项，不再表示人口存量 | 2025-H2 PG=`10.2`、unit=`('000)`、`construct_label=Population growth`、`data_status=provisional`；活动 CSD 空构念数 `0` |
| SAFE `release_date` | URL path 日期、页面创建日期、栏目更新时间、观测发布日期和抓取时间分开存储；没有逐月证据时 `release_date=NULL`、`release_date_not_provided=1` | 2026-07 官方总储备 `37,916.02` 亿美元；`release_date=NULL`；页面创建 `2026-02-06`；页面最近更新 `2026-08-07`；因旧推断留下的 `release_date=2026-02-06` 活动行数 `0` |
| HKMA frequency/period | GDP、实质 GDP、经常账户季度末月转换为 `YYYY-Qn`；政府综合结余保留月度 `YYYY-MM`；`YYYY-00` 不混入活动月/季序列 | 四个指定指标活动 period/frequency 违规数均为 `0`；HKMA 迁移检查 26 条旧行，第二次运行不再 supersede |
| RVD 部分年度落成量 | 读取带 `# Provisional figures (up to 30.06.2026)` 的真实 XLS；新增 `HK_RVD_COMPLETIONS_YTD`，不把部分年度值伪装为 annual | 活动值 `2026-H1=7,914`、`frequency=semiannual`、`data_status=provisional`、`source_period_end=2026-06-30`；活动 annual 2026 落成量 `0`；完整 annual 最新年为 2025 |

## 3. P1 完整性、复现性和只读性

### 3.1 身份等式

debug 输出逐项包含 `checked_periods`、缺失期间、绝对/相对残差、阈值、异常期间和 source/derived 说明。当前生产结果：

- `pass`：贸易余额、转口占比、RVD 数量、Land Registry 数量，共 4 项；
- `warning`：SAFE 总额与构成、贸易总出口、贸易总额、Land Registry 金额，共 4 项；
- `fail`、`insufficient_overlap`、`table_unavailable`：当前为 0 项。

例如 SAFE 2016-09 的最大残差约 `1.45`（亿美元）被保留为舍入 `warning`，没有覆盖官方总量。

### 3.2 旧 lead-lag 结果

没有删除旧的 980 条结果。saved API/UI 将其标为 **2 个 `legacy_unreproducible` result groups、0 个完整可复现 snapshot**；缺失 input hash、source vintage、参数和 computation version 的字段被明确列出。生产数据库未点击“保存当前结果（vintage）”；临时数据库上的保存/元数据测试已在专项回归中覆盖。

### 3.3 变换和 GET 只读

- `difference/diff` 是绝对差；`mom` 是同频百分比变化；`qoq` 是相邻真实季度百分比变化；缺期和零分母返回 `NULL` 及结构化 `missing_reason`，输出 unit/formula 同步进入 JSON/CSV。
- 主 data、debug、lead-lag 和 saved GET builder 使用 SQLite `mode=ro`/`query_only`；未初始化数据库返回明确状态，不在 GET 中建表或刷新 metadata。
- 生产 HTTP GET 前后数据库 SHA、行数、source `updated_at`、snapshot/result 计数未变化；GET 未创建 lead-lag snapshot。

## 4. P2 元数据、性能和页面

### 4.1 来源与 CSD 元数据

- 42/42 source hash 为 `match`；活动 CSD 85,449 行均有经验证 `construct_label`，或有结构化 missing reason；活动空构念和空标签无理由均为 `0`。
- Trade-IDDS destination source URL 已纠正为 `https://tradeidds.censtatd.gov.hk/CommonTable/ETR08a03`。
- 没有官方发布日证据的来源仍保留 `release_date_not_provided` 和原因，没有编造 release lag。

### 4.2 响应体和耗时

在本机 Windows Python 3.12、生产数据库、服务在线、每个 endpoint 连续 3 次测量；下列为代表性结果（HTTP 冷/热差异以实际请求为准）：

| endpoint | 结果 |
|---|---:|
| dashboard JSON | 432,068 bytes；约 0.31–0.36 s；小于 1.5 MB |
| 单指标 JSON（RVD price, monthly, mom, 2025-01—2026-07） | 36,323 bytes；约 0.12 s |
| 单指标 CSV | 10,450 bytes；约 0.005–0.007 s |
| debug JSON | 546,971 bytes；约 1.78–1.82 s |
| CSD 110-01003 JSON（limit=100） | 108,963 bytes；约 0.02 s |
| Trade destination latest Top 10 JSON | 5,893 bytes；约 0.06 s |
| lead-lag JSON | 124,235 bytes；约 0.18–0.21 s |

dashboard 明确同时展示数据库活动行、当前筛选行、当前绘图行和“每序列最新 60 条（已截断）”；完整历史仍由显式筛选 API/CSV 提供。贸易维度默认 latest Top N，完整历史保留在独立 endpoint/CSV。

### 4.3 真实浏览器证据

使用 Playwright CLI 的真实浏览器，服务绑定 `127.0.0.1:5001`，自动任务全部关闭（`PBOC_AUTO=0`、`ASTAR_AUTO=0`、`FISCAL_AUTO=0`、`RATES_AUTO=0`、`BACKUP_AUTO=0`、`ANJUKE_AUTO=0`）。

- Desktop：`1440×900`；Mobile：`390×844`。
- 总览、住房、经济、再出口贸易、储备与金融、中国联动均点击并重新载入；筛选、频率、同比、时间范围和 CSV href 联动通过。
- CSD 细表选择 `110-01003` 并点击“读取独立细表”，页面显示 `Population growth by component` 和“不是人口存量”；series code/period/频率/构念表格正常。
- 贸易 Top N 从 10 切换为 5；中国联动计算并显示 full-sample 与滚动 60/120 月窗口，保留“描述性、非因果、非预测”警告。
- debug 展开正常；未点击生产 lead-lag 保存按钮。
- 键盘检查确认焦点可见；图表 SVG 不再逐点进入 Tab stop（当前页面 `svg[tabindex=0]` 为 0；图表提供摘要和下载路径）。
- Desktop 和 Mobile 全局横向溢出为 `false`；移动端仅导航/表格等明确容器内部滚动。在线验收轮次控制台为 `0 errors / 0 warnings`。

代表性截图和快照（未加入 Git）：

- `output/playwright/hong-kong-final/desktop/.playwright-cli/page-2026-08-13T02-24-57-107Z.png`（overview）
- `output/playwright/hong-kong-final/desktop/.playwright-cli/page-2026-08-13T02-32-41-042Z.png`（debug/lead-lag）
- `output/playwright/hong-kong-final/mobile/.playwright-cli/page-2026-08-13T02-32-58-970Z.png`（390×844）

## 5. 数据库迁移、备份和计数

迁移脚本：`scripts/remediate_hong_kong_macro_20260812.py`。它不联网，只消费已经保留并校验过 SHA-256 的本地 raw 文件；调用前已制作一致性备份。

- 备份：`backups/pboc_data_hong_kong_final_remediation_pre_20260812T192259.db`
- 备份大小：`952,057,856` bytes；SHA-256：`ecee269522bb5ac65d943e69bcf517347560800f39513f91a88e1ac5745ce678`
- 备份 `quick_check=ok`、`user_version=5`。
- 最终主库：`pboc_data.db` 大小 `1,037,021,184` bytes；SHA-256 `28d175d9bbddcee994ff472dd1c5dbe1359d02a4d6ef03bce5070373a2f5ef54`；`quick_check=ok`、`journal_mode=wal`、`user_version=6`，关闭服务后无 WAL/SHM 残留。
- 迁移前后：HK active `26,903`、HK superseded `1,277`；CSD active `85,449`、CSD superseded `175,055`；Trade active `29,862`；sources `42/42 success`。
- SAFE 2026-07 值、RVD 7,914、HKMA 规范期间和 CSD 构念标签均在第二次迁移中保持不变。迁移 JSON 证据：`outputs/hong_kong_macro_migration_20260812.json`。
- 服务启动时项目既有的全局初始化会重写 `journal_prestige_lists` 的 SQLite row id/`updated_at`（51 行；字段值不变），所以最终 SHA 是关闭验收服务后的 SHA；这不是香港 GET 写入。启动完成后再重复 data/debug/lead-lag/saved GET，SHA、香港行数、source 更新时间和 snapshot/result 计数均未变化。

为验证迁移幂等性创建的临时副本目录仍保留在 `tmp_hk_remediation.*`，其中包含约 2–3 份大型数据库副本；它们不是生产数据、未加入 Git，未在未经额外授权的情况下删除。

## 6. 来源验证梯度

| 来源 | source/入口 | raw/解析/存储 | API/页面/浏览器 |
|---|---|---|---|
| C&SD Web Table 110-01003 | [官方细表](https://www.censtatd.gov.hk/en/web_table.html?id=110-01003)；本地 raw 有 SHA | 18 张 CSD 表、`csd_web_v3_constructs`、活动/旧 superseded 分离 | 主 API、独立 CSD JSON/CSV、细表 UI ✅ |
| SAFE | [2026 官方储备页](https://www.safe.gov.cn/safe/2026/0206/27116.html)；栏目更新时间核为 2026-08-07 | 观测值未改写；页面创建/更新/发布日期未知分列 | SAFE card、source metadata、debug、浏览器 ✅ |
| HKMA | [HKMA API 文档](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/financial/economic-statistics/)；保留官方响应 raw | 26 条期间修复；GDP/经常账户季度、政府结余月度 | API/CSV、来源表、浏览器 ✅ |
| RVD | [RVD 官方统计入口](https://www.rvd.gov.hk/en/publications/property_market_statistics.html)；原始 XLS 保留 | partial-year 脚注解析、YTD/semiannual 活动行 | API/CSV、来源表、浏览器 ✅ |
| Land Registry | [官方月度统计](https://www.landreg.gov.hk/en/monthly/monthly.htm) | 独立 source/指标，未并入 RVD | API/CSV、身份等式、浏览器 ✅ |
| Trade-IDDS | [官方 destination 表](https://tradeidds.censtatd.gov.hk/CommonTable/ETR08a03) | 货物贸易与维度表独立存储 | latest Top N、完整 CSV、浏览器 ✅ |

“来源已发现”与“已接入”没有混用：以上各行都有本地 raw/解析/数据库/API 证据；官方发布日或最新期缺失仍明确标注。

## 7. 测试门禁

验收环境处置：第一次从 WSL 启动 Windows `python.exe` 时，前缀环境变量没有跨 Windows 边界传递，项目默认的 PBOC 自动任务短暂启动；我在 HTTP 验收前停止了该进程。与迁移前一致性备份比较，非香港表的行数和非易变字段没有差异；之后所有真实 HTTP/浏览器验收均使用 Windows `cmd.exe` 明确设置所有自动任务为 `0`，且未调用香港 update/save POST。

- Python 静态编译：`PY_COMPILE_OK`。
- 内联 JavaScript：Node `new Function` 对 HTML 两个脚本均通过，`JS_SYNTAX_OK scripts=2`。
- 香港专项：`python.exe -X utf8 -m unittest tests.test_hong_kong_macro_service -q`，`Ran 38 tests ... OK`。
- 全套回归：`python.exe -X utf8 -m unittest discover -s tests -q`，`Ran 569 tests ... OK`。
- SQL：`quick_check=ok`；四个 HKMA 指标 period/frequency 违规 `0`；活动 CSD 空构念/无理由缺口 `0`；SAFE 错误统一 release date `0`；活动 RVD annual 2026 `0`；城市表 Hong Kong probe `0`。
- HTTP：页面、dashboard、单指标 JSON/CSV、debug、CSD JSON/CSV、Trade JSON/CSV、lead-lag、saved 和非法参数均现场验证；非法 indicator 返回 HTTP 400 而非 500/静默回退。

## 8. 相关修改文件和 Git 状态

本轮核心文件（仅报告，不代表已 stage）：

- `services/hong_kong_macro_service.py`
- `services/china_external_service.py`
- `services/china_macro_service.py`
- `server.py`
- `static/hong_kong_macro.html`
- `tests/test_hong_kong_macro_service.py`
- `scripts/remediate_hong_kong_macro_20260812.py`
- `outputs/hong_kong_macro_migration_20260812.json`
- 本状态文档及旧香港文档顶部的 superseding note

工作树同时保留其他用户改动；没有使用 `git add .`、没有 reset/checkout/清理、没有提交或推送。最终交付后仍需由用户决定哪些核心 untracked 文件进入版本控制。

## 9. 明确未宣称的事项

- 未接入香港总人口存量；不能用 110-01003 的 PG 增长量替代人口存量。
- 未把旧 lead-lag 结果升级成不可证明的 vintage snapshot。
- 未把官方舍入差异抹平为全数 `pass`。
- 未因来源发布日期未提供而编造 release lag 或 observation release date。
- 未执行自动刷新、生产 snapshot 保存、提交、推送或 PR。
