# 香港宏观与中国 SAFE 官方储备资产：最终完整性审计

> **历史记录说明（2026-08-12 final remediation）**：本文保留前一阶段审计证据，部分结论和计数已被 Prompt A 最终执行状态 supersede。请以 [最终执行状态](hong_kong_macro_FINAL_STATUS_2026-08-12.md) 为准，尤其是 CSD 110-01003 的“人口增长”构念、SAFE `release_date` 未提供、RVD `2026-H1` 暂定落成量、HKMA `YYYY-Qn` 期间、identity warning 以及旧 lead-lag 的不可复现标注。本文不删除，以保留审计链。

**项目目录**：`/mnt/d/claude`  
**审计日期**：2026-08-12（America/Denver）  
**对应要求**：`docs/hong_kong_macro_remediation_prompt_2026-08-12.md` 及其引用的香港宏观/SAFE 修复提示词  
**数据库**：`pboc_data.db`（项目根目录；不是 `data/pboc_data.db`）

## 1. 结论

本轮已经把香港独立模块、SAFE 官方储备资产接入、查询/API/CSV、页面交互、lead-lag 门禁、来源审计和回归测试完整复核并修到可运行状态。当前不是“所有来源都是最新”的状态：页面会如实显示 `stale`，原因是 CSD 访客表 `HK_CSD_WEB_650-80001` 的缓存最新期为 2026-05；这不等于把失败来源伪装成成功。

本轮没有启动更新作业、没有调用自动刷新、没有点击保存 lead-lag snapshot、没有做外部写入，也没有清理其他用户改动。受控本地服务使用自动任务关闭的环境运行，收尾时应停止该进程。

## 2. 逐层验收结果

| 层级 | 当前结果 | 证据 |
|---|---|---|
| 项目边界 | 通过 | 香港页面为独立 `/hong-kong-macro`；数据使用 `jurisdiction=HK`，没有并入城市经济页面 |
| SAFE 口径 | 通过 | SAFE 外汇、黄金美元、黄金数量、SDR、IMF、其他储备和官方总额使用独立指标；不写入 PBoC、结售汇或涉外收付款序列 |
| 原始材料 | 通过 | raw 文件保留在 `data/hong_kong_macro_raw/`；debug 的 42 个 source hash 全部 `match` |
| 解析/入库 | 通过 | RVD、Land Registry、HKMA、Trade-IDDS、CSD Web Table 分开解析和入表；schema/user version 为 5 |
| 查询契约 | 通过 | `M/Q/H/Y` period 语义、频率、来源、状态、变换、基期、superseded/missing 参数均有校验 |
| API/CSV | 通过 | 主 API、独立 CSD endpoint、贸易维度 endpoint 和 CSV 现场返回 HTTP 200；JSON/CSV 筛选一致 |
| 页面 | 通过 | Playwright 实际点击标签、筛选、Top N、CSD 维度/latest、lead-lag；控制台 0 errors/0 warnings |
| 统计门禁 | 通过 | lead-lag 状态词汇、最小重叠、lag=0 排除香港领先最佳值、滚动 60/120 窗口均有实现 |
| 可复现性 | 通过 | source URL、retrieved_at、raw SHA-256、parser version、formula、input hash、vintage 字段保留 |

## 3. SAFE 真实数据核对

数据库现场结果：

| 指标 | 总行数 | 非 NULL | 覆盖 | 说明 |
|---|---:|---:|---|---|
| `CN_SAFE_FX_RESERVES_USD` | 139 | 134 | 2015-06—2026-12 | 2026-08—12 为未来空白，保留 `not_released` |
| `CN_SAFE_MONETARY_GOLD_QUANTITY` | 127 | 127 | 2016-01—2026-07 | 官方数量，不把美元值倒推成数量 |
| `CN_SAFE_MONETARY_GOLD_USD` | 139 | 134 | 2015-06—2026-12 | 未来空白保持 NULL |
| `CN_SAFE_OFFICIAL_RESERVE_ASSETS_TOTAL_USD` | 139 | 134 | 2015-06—2026-12 | 独立的官方总额序列 |

2026-01—07 黄金数量（万盎司）严格为：

```text
7419, 7422, 7438, 7464, 7496, 7544, 7608
```

2026-07 现场值：

```text
CN_SAFE_MONETARY_GOLD_QUANTITY            = 7608 万盎司
CN_SAFE_MONETARY_GOLD_USD                 = 3063.54 亿美元
CN_SAFE_OFFICIAL_RESERVE_ASSETS_TOTAL_USD = 37916.02 亿美元
```

未来月份不是 0，也没有用插值或最后一期填充；NULL 行的 `missing_reason` 为官方源未来月份空白。黄金美元、外汇储备、SDR、IMF 储备头寸、其他储备与总额仍为不同指标。

主页面总览显示一个明确标注的“中国 SAFE 官方储备资产合计（联动参考）”卡片；它读取中国宏观表，但不加入香港 metrics 或香港 source registry。存在香港指标/日期/频率/来源筛选时，该参考卡会隐藏，避免把未受筛选的中国序列伪装成香港筛选结果。`/api/china-macro/data` 现场返回 SAFE 总额 134 个非 NULL 观测，最新期 2026-07、值 37916.02。

## 4. 数据库、来源和一致性

现场核验命令为：

```text
PRAGMA quick_check                         = ok
PRAGMA user_version                        = 5
主表 active/non-superseded rows            = 26,903
CSD active/non-superseded rows              = 85,449
Trade dimension active rows                 = 29,862
主表 active 重复键组                       = 0
CSD active 重复键组                        = 0
主表年度 period 非 YYYY                    = 0
CSD 年度 period 非 YYYY                    = 0
主表缺 raw_sha256                          = 0
CSD 缺 raw_sha256                          = 0
source hash                                = 42/42 match
source registry status                     = 42/42 success（使用缓存数据时仍显示 freshness/质量状态）
```

身份恒等式 debug 全部为 `ok`：

- SAFE 总储备 = 组件之和；134 个期间，最大绝对残差约 1.45，属于官方显示精度/四舍五入量级。
- 香港总出口 = 本地出口 + 转口；174 个期间。
- 香港总贸易 = 进口 + 总出口；174 个期间。
- 香港贸易差额 = 出口 - 进口；174 个期间。
- 香港转口份额 = 转口 / 总出口；174 个期间。
- RVD 一二手销售宗数合计；294 个期间。
- Land Registry 一二手合约宗数合计；295 个期间。

debug 同时明确记录：42 个香港来源的 `release_date` 和预期 release lag 仍未由来源稳定提供，因此不能把 `retrieved_at` 冒充 `release_date`。页面默认状态为 `stale` 的原因是来源最新期差异，而不是删除旧数据。CSD 表保留官方年度与季度/月份的混合频率；endpoint 返回 `frequency`、语义 period、`period_raw`、statistic、unit 和原始 `dimension_json`，不插值成月度。

此前一次更新运行的 HKMA 8 个接口出现 timeout/502，已保留在 run/source 错误记录中；旧的可用观测没有被清理。当前受控服务自动任务关闭，本轮没有再次对外抓取。

## 5. API 和 CSV 现场验收

### 5.1 主香港 API

```text
GET /api/hong-kong-macro/data?dashboard=1
HTTP 200
dashboard_preview = true
meta.status       = stale
meta.observation_count = 28,364
series rows       = 6,343
response size     ≈ 3.34 MB
```

这里的 API 观测数是主 API 视图的当前筛选数，包含主表和进入主 API 的 curated CSD 映射；它不等同于主表独立存储行数 26,903。仪表盘预览只保留最近 60 个序列观测，显式 API/CSV 查询仍可读取完整历史。

使用同一组筛选：

```text
indicator=HK_RVD_PRICE_INDEX
start=2020-01
end=2020-03
frequency=monthly
transform=difference
```

JSON 返回 3 个观测，CSV 返回 3 个数据行；JSON 的变换值和 CSV 的 `transformation/formula/data_status/source/hash` 字段一致。该筛选 API 不再显示 SAFE 参考卡。

### 5.2 独立 CSD Web Table

- `110-01003?frequency=semiannual&limit=2` 返回 HTTP 200、当前页 2/总计 416，period 为 `2000-H1`，没有被转换为月度。
- `310-31002?dimensions=GDP_COMPONENT:XS&latest=1&limit=2` 返回 HTTP 200、当前总计 4；结果同时覆盖该系列的官方年度/季度统计量，保留 `dimensions`。
- CSD CSV 头部包含 `dimension_json`，CSV 导出强制走全量过滤查询，不受页面 80 行展示限制。

### 5.3 lead-lag

默认现场请求返回 HTTP 200、`status=ok`、49 个 lag、17 个滚动窗口；默认结果的香港领先最佳 lag 为正值。另行核验：

```text
min_overlap=99999              -> status=insufficient_overlap, success=false
transform=not_a_transform      -> HTTP 400, status=unsupported_transform
GET 前后 snapshot 数量         -> 0 -> 0（GET 不写表）
```

状态词汇固定为：`ok`、`hk_no_data`、`mainland_no_data`、`unsupported_transform`、`insufficient_overlap`、`invalid_request`、`failed`。保存需要显式成功结果和本机写权限；本轮没有点保存按钮。

## 6. 页面真实浏览器验收

使用 Playwright 对 `http://127.0.0.1:5001/hong-kong-macro` 实际操作，而不是只读取 HTML：

1. 首屏加载总览，显示 42/42 来源、`stale` 状态、SAFE 参考卡和 RVD SVG 图表 tooltip 点。
2. 点击“经济”，URL 变为 `group=economy&tab=economy`；经济图表、Trade Top N 和 CSD explorer 均出现。
3. Trade Top N 切换到 20 后出现三个维度各自的最新 Top 20 条形项。
4. CSD 选择 `310-31002`，填写 `GDP_COMPONENT:XS`，勾选“每系列最新”，读取到 4 行，并更新 CSV 链接。
5. 应用 RVD 2020-01—03 差分筛选，状态栏显示“当前筛选观测 3 条”，CSV 链接携带相同筛选，SAFE 卡隐藏。
6. 点击“中国联动”，URL 变为 `group=china_linkage&tab=china_linkage`，香港序列下拉框有 74 个候选；运行 lead-lag 后显示全样本曲线、滚动 60/120 窗口、滚动最佳 lag 图、逐 lag 表，保存按钮按成功/权限状态管理。
7. 浏览器 console：`Errors: 0, Warnings: 0`。关键网络请求均返回 HTTP 200。

本轮还修复了一个会阻塞真实浏览器的 `MutationObserver` 自触发循环：保存按钮现在只有 disabled 状态确实改变时才写属性；首次 API 加载延后到 window load 后的零延迟任务，避免 SVG/大载荷阻塞导航。

现场截图（lead-lag 页面视口）：[Playwright screenshot](/mnt/d/claude/.playwright-cli/page-2026-08-13T00-12-58-966Z.png)

## 7. 本轮代码和文档补丁

- [services/hong_kong_macro_service.py](/mnt/d/claude/services/hong_kong_macro_service.py)：SAFE 参考卡边界、china linkage 候选序列、dashboard 预览上限、CSD dimension/latest/full CSV、来源缺口、period/frequency/filter 契约。
- [static/hong_kong_macro.html](/mnt/d/claude/static/hong_kong_macro.html)：分区重新加载、Top 5/10/20、CSD 维度过滤、SAFE 展示、rolling best-lag SVG、来源/tooltip 和保存按钮门禁。
- [tests/test_hong_kong_macro_service.py](/mnt/d/claude/tests/test_hong_kong_macro_service.py)：SAFE、RVD、CSD、API/CSV、dashboard preview、china linkage group 和 snapshot 契约测试。
- [docs/hong_kong_macro_REPAIR_EXECUTION_2026-08-12.md](/mnt/d/claude/docs/hong_kong_macro_REPAIR_EXECUTION_2026-08-12.md)：前一阶段执行记录；本文件是最后一轮完整性审计。

## 8. 回归验证

```text
PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest discover -s tests -q
Ran 560 tests in 10.913s
OK

py_compile: server.py + Hong Kong/China services + Hong Kong tests -> OK
inline JavaScript node --check -> OK
git diff --check -> OK（仅有工作树既有的换行符提示，无 whitespace error）
```

## 9. 明确保留的 backlog

以下事项不是本轮假装“已完成”的内容：

1. HKMA 部分 endpoint 的 timeout/502 需要在允许的低频、session-based 条件下重新验证；当前缓存数据保留，页面明确显示质量状态。
2. 没有设置自动更新/自动 vintage 调度；需要人为显式触发更新并复核来源、raw hash、parser、入库和浏览器链路。
3. lead-lag 仍是描述性相关，不是因果识别、预测或显著性结论；没有新增多重比较校正或正式推断层。
4. CSD 混频数据保持官方频率，后续研究必须按频率和 statistic 明确选择，不能把年度/季度值当作月度流量。
5. 本轮验证的是本机受控服务和本地真实浏览器；没有把它表述成已经部署的公共远程页面。

本文件与代码、数据库、raw 文件和测试结果共同构成当前交付证据；若后续更新数据，应新建运行记录和新的审计时间点，不覆盖本次证据。
