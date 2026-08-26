# 中美宏观数据宇宙：来源、方法与验证记录

## 目的与范围

- 日期：2026-08-11（America/Denver）
- 目标：在现有 `/china-macro`、`/us-macro`、住房、财政和区域模块基础上，识别下一批值得建设的中国/美国宏观数据专题。
- 输出性质：产品与研究路线图，不是数据下载结果、实证估计、综合指数或预测。
- 写入边界：本轮没有修改业务代码、数据库、模型或既有输出；仅新增本报告目录。

## 本轮检查的项目证据

- `/mnt/d/claude/services/us_macro_service.py`
  - 当前美国底层目录包含 45 条原始序列，重点覆盖劳动力、通胀、增长、财政、利率和金融市场。
- `/mnt/d/claude/docs/china_macro_external_STATUS_2026-08-10.md`
  - 当前中国宏观 API 状态文档记录 143 条序列，覆盖增长/生产、消费/投资、价格/信心、就业/人口、贸易、外资与跨境资金。
  - 同一状态文档明确列出季度 GDP、调查失业、FDI 美元口径和商品价格等现存缺口。
- `/mnt/d/claude/docs/regional_macro_source_plan_2026-07-22.md`
  - 省/州面板已有建设基础；后续应深化而不是重建，并继续避免土地财政、政府层级等伪对称。
- `/mnt/d/claude/docs/us_macro_china_benchmark_2026-08-11/report.html`
  - 前一轮审计已提出质量门禁、来源权威等级、三种中美比较模式和发布/版本层。本报告沿用这些基础，并建议为贸易/资本/供应链增加 `linked` 模式。

较旧的覆盖矩阵和扩展状态文档只用于了解历史演进；当前代码和 2026-08-10/11 状态文档优先。

## 规划方法

候选专题被组织成四层：

1. 共同传导主干；
2. 高频脉搏；
3. 长期结构；
4. 协调口径覆盖。

每个候选专题按五项序数判断评分，每项 1–5 分：

- 研究价值；
- 对现有项目缺口的补充度；
- 中美对标价值；
- 官方来源可得性；
- 近期交付可行性。

`total_score` 为五项简单相加，满分 25。该分数只用于讨论 backlog，不是经济重要性、效应量或预测概率。专题阶段与分数同时由研究问题、现有资产复用程度和实施依赖决定，因此协调数据库即使容易接入，仍安排在本国官方数据之后。

## 官方来源侦察

### 美国

- [BEA Developer Resources](https://www.bea.gov/resources/for-developers)：国民、国际、区域和行业账户，可支持可支配收入、PCE、企业利润、私人投资、国际收支和 IIP。
- [Census Economic Indicators API](https://www.census.gov/data/developers/data-sets/economic-indicators.html)：住房/建设、贸易、零售、批发、服务、制造、耐用品、库存与企业形成等；页面注明 API key 现为必需。
- [Federal Reserve G.19](https://www.federalreserve.gov/releases/g19/current/default.htm)：消费信贷；另有历史表。
- [Federal Reserve H.8](https://www.federalreserve.gov/releases/h8/h8notes.htm)：商业银行资产负债表与信贷类别；需要保留重分类和修订元数据。
- [Federal Reserve Z.1](https://www.federalreserve.gov/releases/z1/preview/html/table_descriptions.htm)：各部门金融账户与资产负债表。
- [EIA Open Data API](https://www.eia.gov/opendata/index.php/api)：电力、天然气、石油、库存、生产和价格等高频/周期数据。
- [BTS Freight Transportation Services Index](https://www.bts.gov/taxonomy/term/391)：月度货运活动，存在修订与固定发布节奏。
- [Census BTOS](https://www.census.gov/hfp/btos/about)：双周高频企业调查，可覆盖经营状态、远程工作和技术使用；AI 使用应作为技术扩散情境，不直接等同于采用成效。

### 中国

- [中国人民银行调查统计](https://www.pbc.gov.cn/diaochatongjisi/116219/index.html)：金融统计、区域社融，以及银行家、企业家和城镇储户调查。
- [国家外汇管理局统计数据](https://www.safe.gov.cn/safe/tjsj1/)：国际收支、IIP、外债、结售汇、储备和跨境收支。
- [海关总署月度统计](https://english.customs.gov.cn/statics/report/monthly.html)：总额、伙伴和主要商品的月度数量/金额。
- [交通运输部数据](https://www.mot.gov.cn/shuju/)：货运、港口货物与集装箱、跨区域人员流动、城市客运和固定资产投资。
- [国家能源局全社会用电量](https://www.nea.gov.cn/20260519/fdecbf091d654d53a9db438cdc356a5c/c.html)：月度全社会及分产业用电量。
- [工业和信息化部工信数据](https://www.miit.gov.cn/gxsj/)：电信、原材料、装备、消费品、电子信息、软件和互联网行业数据。
- 国家统计局仍是收入、消费、企业利润/库存/应收、投资、住房、人口和研发的首要来源；本轮页面/API 侦察出现访问限制，未尝试绕过。实施时应先使用可访问的官方发布/下载，真实记录缺失和抓取状态。

### 协调口径覆盖

- [OECD Composite Leading Indicator](https://www.oecd.org/en/data/indicators/composite-leading-indicator-cli.html)：适合共同周期和转折信号；指数以长期平均 100 为中心并会修订。
- [IMF data access](https://data.imf.org/en/news/accessing)：IFS 内容已按 CPI、PPI、国际收支、IIP、有效汇率、货币等主题重组。
- [World Bank Indicators API](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392)：适合长历史和年度结构指标，不应替代高频本国来源。
- [BIS total credit](https://www.bis.org/statistics/totcredit/changes.htm)：适合非金融部门信用、房价和有效汇率等协调口径。

## 图表契约

- 位置：`宏观数据专题规划评分`
- 分析问题：哪些专题同时具有较高研究价值、缺口补充度、对标价值、官方可得性和近期可交付性？
- 形式：单序列排序水平条形图；13 个专题，类别粒度一致。
- 字段：`domain`、`total_score`；tooltip 保留五个分项、层级和阶段。
- 尺度：绝对规划分，零基线；满分 25。
- 配色：单一蓝色根系，无冗余图例，不以颜色承担类别识别。
- 限制：规划判断，不可解读为经济效应或预测。
- 最终表面：自包含 HTML 报告；桌面 1440px 与窄屏 390px 均由打包验证器检查。

## Validation Report

### Overall Assessment: Share with caveats

本报告足以支持下一轮研究与产品优先级讨论；它不是实施可行性承诺。真正开始采集前，仍需对每个接口做低频、合规、可复现的字段级探针，并冻结指标定义与版本策略。

### Methodology Review

- 问题对齐：报告回答“还可以搞哪些中美宏观数据，以及先做什么”，没有把问题偷换成宏观预测。
- 来源选择：候选项优先使用两国本国官方发布；协调数据库被限定为 overlay。
- 比较边界：明确使用 `aligned`、`normalized`、`parallel_only` 和建议新增的 `linked`，不把同名当同概念。
- 决策边界：优先级分数是可修改的规划判断，并在图表和 caveat 中显著披露。

### Issues Found

1. **Medium — 分数依赖当前研究目标。** 如果首要目标改成事件研究、房地产、AI 扩散或高频 nowcast，权重和排序应重算。
2. **Medium — 来源入口尚未完成字段级接入验证。** 官方网页证明数据族存在，但不等于当前接口、密钥、下载格式和历史版本已可稳定自动化。
3. **Low — 中美制度边界会限制直接比较。** 该风险已通过比较模式和 caveat 管理，但实施时仍需逐指标登记。

### Calculation Spot-Checks

- 三条 `VALUES` SQL（规划评分、第一波蓝图、数据宇宙）均在内存 SQLite 中成功执行。
- SQL 输出分别为 13、6、13 行，与 `snapshot.datasets` 完全一致。
- 13 个专题的五项分数均在 1–5 范围内；所有 `total_score` 已独立复算并与快照一致；排序为非递增。
- manifest 与顶层来源 ID 顺序一致、均无重复；所有 block/chart/table 的 `sourceId` 均可解析。

### Visualization Review

- 选择水平条形图符合长类别标签的排序比较；没有冗余色彩编码。
- 标题、单位、评分范围和非实证 caveat 均可见。
- portable verifier：`ok=true`；1 张图、2 张表、14 个区块；来源对话框通过；1440px 和 390px 视口通过，无报告级外部请求。

### Required Caveats for Stakeholders

- 优先级分数只用于排 backlog。
- 官方来源存在不代表自动化接入已经完成。
- 高频信号不是 GDP 替代品；情景外推不是正式预测。
- 中国访问限制与两国统计制度差异必须保留为真实缺失或不可比状态。

### Incomplete handoff blockers

- 对本轮“共同脑暴与路线图”没有阻塞项。
- 对后续实施，尚需用户选择第一个专题，并完成具体指标注册表与接入探针。

## 复现方式

Canonical artifact：`/mnt/d/claude/docs/macro_data_universe_2026-08-11/artifact.json`

Portable HTML：`/mnt/d/claude/docs/macro_data_universe_2026-08-11/report.html`

构建脚本：`/mnt/d/claude/docs/macro_data_universe_2026-08-11/build_report.mjs`

使用的 Data Analytics plugin 版本目录：`0.2.8-13ceeea1f599`

```bash
node.exe D:/claude/docs/macro_data_universe_2026-08-11/build_report.mjs \
  --plugin-root C:/Users/cui10/.codex/plugins/cache/openai-curated-remote/data-analytics/0.2.8-13ceeea1f599 \
  --artifact D:/claude/docs/macro_data_universe_2026-08-11/artifact.json \
  --output D:/claude/docs/macro_data_universe_2026-08-11/report.html
```

构建回执：`verification.ok=true`，图表静态语义回退已嵌入，来源交互与桌面/窄屏检查通过。

## Changelog

- 新增一份中美宏观数据宇宙路线图。
- 新增 13 个候选专题的显式规划评分和 6 项第一波专题蓝图。
- 新增官方来源侦察、比较模式、验证记录和可复现构建脚本。
- 未修改任何业务代码或数据库。
