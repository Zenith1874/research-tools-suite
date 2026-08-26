# 香港宏观独立模块与中国官方储备资产状态（2026-08-11；续做更新至 2026-08-12）

## 1. 交付边界与当前结论

本轮按用户提供的执行提示词实施，提示词副本保存在
`docs/hong_kong_macro_implementation_prompt_2026-08-11.md`，与附件
`/mnt/c/Users/cui10/.codex/attachments/d34202b5-c7a3-461f-99ed-2c34603c1689/pasted-text.txt`
的 SHA-256 均为 `930d472f0a4727bcc5e76a973fd6d155abd86440cf4a79d5ca034a31c8ab2a1b`。

香港已作为独立 jurisdiction 接入 `/hong-kong-macro`，没有写入
`city-economy` 城市选择器，也没有与内地全国或城市数据加总。中国正式外汇储备
已接入 `/china-macro` 的外部经济板块，并与 PBoC 资产负债表
`foreign_exchange`、银行结售汇、银行代客涉外收付款分别保存。

首版目前是“真实数据已接入、部分刷新状态仍需如实显示”，不是“所有候选指标全部完成”。
首轮全域刷新曾因 HKMA 的 `ReadTimeout/ConnectionError` 产生部分失败；本次续做已对这 8 个
端点执行定向重试并成功入库。历史失败 run 和 raw/错误证据仍保留，不会被成功重试覆盖。

## 1A. 2026-08-12 P1 续做结论

本次续做已把提示词中明确要求的 P1 链路落到“源目录—raw—解析—SQLite—API—页面—测试”
闭环：

- HKMA 银行统计、客户存款（港元/外币）、人民币存款、贷款按用途/贸易融资、住宅按揭调查和
  负资产按揭已完成官方字段探针、parser、源目录和入库链路；定向重试 run
  `337b032b595a44388e0787acf9572b8a` 将此前 8 个失败/阻断端点全部恢复为 `success`，解析/写入
  `11,461 / 11,461`，0 error。此前全域 run 的 `partial` 状态仍作为历史审计记录保留。
- Trade-IDDS 已增加中国内地进口来源地、进口寄运地、出口目的地、全部来源地 Top N、全部出口目的地
  Top N 和 SITC2 商品维度；六个维度共 29,862 条 observation，并提供页面、JSON、筛选 API 和 CSV
  导出。SITC2 请求覆盖官方当前定义的 68 个代码，因官方零记录分类不展示，当前跨期有 67 个代码、
  最新期有 64 个代码；来源地/目的地页面和默认 API 只返回最新期 Top 10，全量仍可通过筛选 API/CSV 获取。
- CSD Web Table 已接入 17 个官方细表。首次解析审计发现官方响应同时含年/季/月频率和多种
  `svDesc` 统计量，原有键会折叠合法记录；已改用 `freq + sv + svDesc + dimension` 稳定键，
  85,449 条 canonical observation 全部入库，旧派生行保留为 `superseded`。
- 内地住房联动新增国家新建商品房销售面积/销售额累计同比选项，并在 API/页面明确标注：
  这是 NBS YTD 同比敏感性配对，不是月度成交流量，不能直接解释为月度领先滞后。另新增
  `sales_area_monthly_derived` 和 `sales_value_monthly_derived`：仅对同一年度相邻月份的官方累计值
  做差分，面积与金额各 109 条（2015-03—2026-06），缺少上月的 14 个期间不推断，1—2 月合并发布
  不拆分。国家统计局当前公告仍按累计口径发布销售面积/销售额，见
  [2026 年 1—6 月全国房地产市场基本情况](https://www.stats.gov.cn/sj/zxfbhjd/202607/t20260715_1964126.html)。
- lead-lag 结果新增显式 vintage 写入/检索：只有 POST `/save` 或页面按钮会写入，GET 保持只读；
  当前已保存 2 个相同配对的 snapshot，每个 490 行（全样本 49 lag + 滚动窗口）。
- 5001 运行态已加载最新 server；390px 手机宽度的 12px 横向溢出已修复，桌面/手机均通过复测。

截至本次验收，源登记表 42 条（42 success）；香港主 observation
层有 134 个实际有值指标（代码注册 139 个），25,721 条 active observation 和 1,044 条
可审计 `superseded` 行；Trade dimensions 29,862 条，其中全部来源地 12,096 条、全部目的地
13,264 条、SITC2 4,304 条；CSD Web Table
有 85,449 条 active observation 和 54,292 条 `superseded` 行。最近一次是 HKMA 定向重试 run
`337b032b595a44388e0787acf9572b8a`，写入 11,461 条并完成；全域 run
`e297ef25b3f34991af5db3bdd976a339` 的 128,102 条/`partial` 仍保留为历史记录。

## 2. 实施前审计

- 复核了根目录、项目说明、宏观/住房/城市经济/分析状态文档、服务代码、路由、导航、SQLite schema 和测试；工作树原有未提交修改及用户文档均保留。
- 重新核对了现有 API、数据库路径、WAL/SHM、端口和进程；续做时先确认任务锁为空，再精确替换
  5001 上旧的 `pythonw.exe D:\\claude\\server.py` 进程，最后确认新进程命令行和新增路由已生效。
- 写库前建立一致性备份：`backups/pboc_data_hong_kong_preflight_20260811.db`，大小 765,566,976 bytes，`PRAGMA quick_check=ok`。
- 续做写库前另建：`backups/pboc_data_monthly_flow_pre_20260812.db` 和
  `backups/pboc_data_hkma_retry_pre_20260812.db`；两次写入后数据库 `PRAGMA quick_check=ok`。
- 当前数据库仍为 WAL 模式，写入后再次 `PRAGMA quick_check=ok`；未删除、迁移或清空既有数据。
- 备份和 raw 下载目录均不加入 Git；raw 快照分别位于 `data/hong_kong_macro_raw/` 和 `data/china_macro_raw/`。

## 3. 真实数据接入状态

状态词按以下层级使用：已定位官方来源、已完成字段探针、已下载、已解析、已校验、已入库、API 已返回、页面已渲染、浏览器已验证、被阻断、尚未实施。

### 香港

| 数据域 | 官方来源 | 当前覆盖/记录 | 状态与限制 |
|---|---|---:|---|
| 价格、租金指数 | [RVD property market statistics](https://www.rvd.gov.hk/en/publications/property_market_statistics.html) | 2012-01—2026-06；价格指数、租金指数各 174 期 | 已定位、字段探针、下载、解析、校验、入库、API 返回、页面渲染、浏览器验证；官方修订值保留 `official_revised`。 |
| 平均价格、平均租金 | 同上 | 15 个面积类别×地区维度，约 2,583/2,604 条有效观察 | 已接入维度字段；不做无权重总平均。旧版缺维度审计行保留为 `superseded`，不进入绘图序列。 |
| RVD 住宅销售 | 同上 | 2012-01—2026-06；一手/二手/合计的宗数和金额 | 已下载、解析、入库；一手+二手合计恒等式通过。 |
| 土地注册处住宅注册买卖合约 | [Land Registry monthly statistics](https://www.landreg.gov.hk/en/monthly/monthly.htm) 及官方 JSON `t1/t2` | 2012-01—2026-07；宗数和金额六条序列各 175 期 | 已补齐提示词中遗漏的金额表；注册月份不等于实际签约月份。金额恒等式按 HK$ million 四舍五入容忍度校验。 |
| 综合经济与就业 | [HKMA economic statistics API](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/financial/economic-statistics/)、[CSD-IDDS](https://idds.censtat.gov.hk/) | HKMA 2025-05—2026-06；CSD Web Table 年/季/月细表 | 已完成字段探针、上一版官方快照解析、入库、API/页面验证；HKMA 8 个端点已由定向 retry 成功刷新，历史全域 `partial` 错误证据仍保留。CSD 频率和统计量纳入 series key，未插值、未把季度改写为月度。 |
| 外币储备及金融条件 | [HKMA foreign currency reserve assets](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/ef-fc-resv-assets/fc-resv-assests/)、[HKMA monetary statistics](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/financial/monetary-statistics/) | 外币储备/未交收合约约 2000-01—2026-06；货币与利率字段 2025-05—2026-07 | 已补齐原始响应中此前漏掉的未交收外汇合约、总结余、HIBOR、最优惠贷款利率、贴现窗基本利率、港元兑美元、名义有效汇率、M1/M2/M3 等字段；定向 retry 已成功，旧快照和历史失败证据仍可追溯。 |
| HKMA 银行统计、存款与贷款 | [HKMA banking statistics](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/financial/banking-statistics/)、[customer deposits HKD/FC](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/customer-deposits-by-type-hkd-fc)、[CNY deposits](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/customer-deposits-by-type-cny/)、[loans by type](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/loans-by-type-lb/) | 2026-06/07 最新期；定向 retry 写入 11,461 条 | 已完成字段映射、保存 raw hash、入库和页面分组；此前 5 个相关 HKMA 端点的 timeout/502 已通过定向 retry 恢复，失败 run 不删除。 |
| HKMA 住宅按揭与负资产 | [residential mortgage survey](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/residential-mortgage-survey/)、[negative equity loans](https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/residential-mortgage-loans-neg-equity/) | 按揭调查 2,760 条、最新 2026-06；负资产 203 条、最新 2026-Q2 | 已完成官方字段探针、parser、指标注册、金融页分组和来源状态；定向 retry 成功后页面来源为 `success`，季度负资产序列仍不插值为月度。 |
| 转口贸易 | [Trade-IDDS API specification](https://tradeidds.censtat.gov.hk/MetadataLink/ApiSpec/API_eng.pdf) | 总量 2012-01—2026-06；内地专门三类各 66 期；全部来源地 12,096、全部目的地 13,264、SITC2 4,304 | 已完成 session/cookie 合规流程、下载、解析、入库、API/页面/CSV 验证；不绕过验证页。页面/默认 JSON 取最新期 Top 10，筛选 API 和 CSV 保留全量；SITC2 覆盖 T210 当前 68 个有效代码。 |
| CSD 年度及细表补充 | [CSD Web Table dictionary](https://www.censtat.gov.hk/datagovhk/WT_data_dict_en.pdf)、[CSD Monthly Digest table list](https://www.censtat.gov.hk/en/hkmds_ctable.html) | 17 个 Web Table；active 85,449 条，最新期按表为 2025-12—2026-06 | GDP 支出/生产、零售、国际收支、国际投资头寸、外债、访客、人口/出生死亡等细表已下载、解析、入库；按官方 `freq` 和 `svDesc` 保留年/季/月及统计量差异。 |

注：RVD 年度库存/竣工/空置/吸纳表的 `2026-12` 是官方年度期末标签；当前文件只发布到 2026 年 6 月，相关值标为临时/截至期内观察，不代表已经实现的 2026 年全年事实或预测。CSD Web Table 的年频率统一保存为 `YYYY`，季度保存为 `YYYY-Qn`，月频率保存为 `YYYY-MM`，不跨频率拼接。

当前香港主 observation 层有 134 个实际有值指标、25,721 条 active 观察；另有 1,044 条早期解析版本的可审计 `superseded` 行。Trade dimensions 29,862 条，CSD Web Table 85,449 条 active、54,292 条 `superseded`；来源登记表 42 条且当前全为 `success`。最近 HKMA 定向 retry 写入 11,461 条并完成；此前全域更新写入 128,102 条并标为 `partial`，其 8 个 HKMA 网络错误仍作为历史证据保留。

### 中国 SAFE 官方储备资产

官方入口为 [SAFE 外汇储备栏目](https://www.safe.gov.cn/safe/whcb/)；当前年度官方储备资产页面为
[SAFE 2026 official reserve assets](https://www.safe.gov.cn/safe/2026/0206/27116.html)。

已接入 `china_macro_observations` 的七条独立指标：外汇储备、货币黄金美元价值、黄金数量、SDR、IMF 储备头寸、其他储备资产、官方储备资产合计。美元值使用官方“亿美元”口径，不把 SDR 换算成美元；黄金数量与黄金美元价值分开。历史来源包含年度 HTML 及 2015—2017 年官方 XLS/XLSX，不能只称为最新年度快照。

- 组成指标及合计覆盖 2015-06—2026-07；每条表内保留 2026-08—2026-12 的官方尚未发布缺失行，不把空白月份写成零。
- 最新已发布期为 2026-07：外汇储备 34,187.76 亿美元，官方储备资产合计 37,916.02 亿美元，货币黄金 3,063.54 亿美元；这些是官方观察，不是预测。
- 黄金数量历史可解析覆盖为 2016-01—2017-12，共 24 期；没有用黄金美元金额反推缺失数量。
- 数据库中 PBoC 资产负债表 `foreign_exchange` 仍为单独的 47 行；SAFE 官方外储未写入该代码，也未替代结售汇或跨境收付款。

## 4. 数据模型与审计层

香港新增并幂等初始化：

- `hong_kong_macro_observations`：含 jurisdiction、频率、单位、维度、状态、来源、版本、raw hash、解析器版本、公式和说明；唯一键含指标、期间、维度和 vintage。
- `hong_kong_macro_sources`：机构、数据集、入口、raw path/hash、覆盖、最后成功/尝试和错误状态。
- `hong_kong_macro_update_runs`：逐源更新状态、解析/写入计数和错误信息。
- `hong_kong_macro_lead_lag_results`：保存显式请求的 lead-lag vintage；`snapshot_id` 将全样本 49 lag
  与滚动窗口结果绑定。GET 计算和读取均不写库，只有 POST 保存接口或页面按钮显式写入。
- `hong_kong_macro_trade_dimensions`：保存 Trade-IDDS 来源地、寄运地、目的地和 SITC2
  商品维度；唯一键含来源、维度、贸易类型、期间、维度代码和统计量。
- `hong_kong_macro_web_table_observations`：保存 CSD Web Table 的官方频率、统计量、维度、
  series key、原始 JSON 和 raw hash；旧解析键不删除，标为 `superseded`。

原始层采用 `data/hong_kong_macro_raw/`；解析后通过事务 upsert 进入 observation 层。当前有效香港观察的 `source_url`、`unit`、`raw_sha256` 缺失数均为 0。失败刷新不会覆盖上一版有效观察；最新 HKMA 阻断只更新来源/更新日志状态。

## 5. API、页面和交互

已实现：

- `GET /api/hong-kong-macro/data`
- `POST /api/hong-kong-macro/update`
- `GET /api/hong-kong-macro/debug`
- `GET /api/hong-kong-macro/export.csv`
- `GET /api/hong-kong-macro/trade-dimensions.csv`
- `GET /api/hong-kong-macro/lead-lag`
- `POST /api/hong-kong-macro/lead-lag/save`
- `GET /api/hong-kong-macro/lead-lag/saved`
- `POST /api/hong-kong-macro/retry-hkma`
- 页面 `/hong-kong-macro`

数据 API 当前返回 `meta`、`groups`、`metrics`、`series`、`cards`、`coverage`、`sources`、`quality`、
`trade_dimensions`、`csd_web_table_summary/preview` 和方法警告；debug 不暴露本机绝对 raw 路径，只返回
`data/hong_kong_macro_raw/` 安全摘要。页面包含 Trade-IDDS 维度和 CSD Web Table 细表摘要/最新行。

页面包含：总览、住房、经济、再出口贸易、储备与金融、中国联动六个页签；手动更新、调试、CSV 下载、来源状态、空数据/部分失败状态、RVD 维度数据和 Trade-IDDS 派生贸易差额/转口占比。

## 6. 贸易与住房质量门禁

- RVD 一手+二手销售宗数合计：0 个不一致期。
- 土地注册处一手+二手宗数：0 个不一致期；金额差异最大为 1 HK$ million，按官方金额四舍五入容忍度后 0 个超限期。
- Trade-IDDS 本地出口+转口=整体出口、进口+整体出口=贸易总额：最大差异为 1 HK$ '000，按官方整数单位容忍度后 0 个超限期。
- 派生贸易差额严格使用 `total_exports - imports`；转口占比使用 `re_exports / total_exports * 100`，当前均在 0—100% 范围内。
- SAFE 官方总额不被组件加总结果覆盖。134 个重叠发布期的组件残差最大为 1.45 亿美元（2016-09），保留官方合计并在研究解释中视为官方舍入/估值残差，而不是静默修正。
- 国家统计局销售面积/销售额累计值的月度流量派生仅使用同一年度相邻官方累计观察；面积和金额各 109 条，
  2015-03—2026-06，缺失上月的 14 个期间未填补，负差分为 0；这些行标记为 `derived`，不冒充官方单独发布的月度流量。
- 当前 lead-lag 有 2 个显式 snapshot、共 980 行；每个 snapshot 490 行，按 snapshot ID 读回与写入数一致。
- Trade-IDDS 六类维度分别为内地专门 66、66、66，全部来源地 12,096，全部目的地 13,264，SITC2 4,304 条；最新期全部来源地/目的地/SITC2 分别有 183/199/64 个有记录代码；维度唯一键重复组 0，维度关键字段空值 0。
- CSD Web Table 17 表 raw 解析 85,449 条，active 入库 85,449 条；逐表 `COUNT(*) = COUNT(DISTINCT period,series_code)`，重复 0，关键字段空值 0。
- CSD 首轮旧键折叠的 54,292 条派生行均保留为 `superseded`，页面/API 只读取 canonical 行，raw 文件未被覆盖。
- 唯一键重复组 0；有效主 observation 缺来源 URL、单位和 raw hash 均为 0；数据库 `quick_check=ok`。

## 7. 香港—内地领先滞后设计

默认配对已经改为香港 RVD 私人住宅价格指数同比 vs 一线城市新建商品住宅价格指数同比。内地序列不是黑箱全国指数：从现有 `housing_city_observations` 的北京、上海、广州、深圳官方月环比指数，按月对有值城市等权平均后链式累计为 base=100 的派生比较序列；缺月不桥接。另提供一线城市二手住宅版本，以及 CPI、PPI、出口同比和 SAFE 官方储备资产等平行选项。

统一约定：`corr_at_lag(k)=corr(HK_t, Mainland_(t+k))`，所以 `k>0` 才表示香港领先，`k<0` 表示内地领先。全样本报告 -24—+24 共 49 个滞后；滚动窗口为 60/120 个月、12 个月步长，最低有效重叠 60 个月；同时返回 z-score 标准化共同月份序列、最大绝对相关、最大正相关和滚动窗口摘要。

基于当前数据库的默认描述性结果：新房同比全样本最大绝对相关出现在 `lag=-17`，`r≈0.613`；二手房版本约为 `lag=-16`，`r≈0.531`。60 个月窗口中最佳滞后从负值到正值变化，120 个月窗口也不应解读为固定结构；因此当前结论是“样本期内存在若干较强的同步/滞后相关，但未形成可据此预测或因果解释的稳定香港领先关系”。页面明确标注多重滞后搜索、共同趋势、自相关、指数链式构造和登记时差限制。

本次新增 `CN_NATIONAL_SALES_AREA_YTD_YOY` 和 `CN_NATIONAL_SALES_VALUE_YTD_YOY` 两个国家层面
内地住房敏感性配对。它们来自国家统计局新建商品房销售面积/销售额累计同比口径；由于是 YTD 同比，
页面明确警告不能与香港月度成交宗数/金额当作同频月度流量，也不将该配对结果称为月度预测或因果证据。
另提供 `CN_NATIONAL_SALES_AREA_MONTHLY_DERIVED` 和 `CN_NATIONAL_SALES_VALUE_MONTHLY_DERIVED`，
由官方累计值差分得到研究用月度流量；1—2 月合并发布期不拆分，缺少上月不插值。

## 8. 测试和验证

- `python.exe -X utf8 -m unittest tests/test_hong_kong_macro_service.py tests/test_china_external_service.py tests/test_research_navigation.py -q`：31 项通过；其中包含 RVD、Land Registry 宗数/金额、Trade-IDDS、HKMA 新金融字段、SAFE HTML、schema、raw hash/debug、派生住房序列、领先滞后符号、滚动窗口和不足样本测试。
- `PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest discover -s tests -q`：542 项通过。
- `python.exe -m py_compile services/hong_kong_macro_service.py services/china_external_service.py services/china_macro_dashboard_service.py server.py`：通过。
- API 运行态验证：`/api/health`、`/api/hong-kong-macro/data`、`/api/hong-kong-macro/debug`、`/api/hong-kong-macro/lead-lag`、`/api/hong-kong-macro/lead-lag/saved`、`/api/hong-kong-macro/export.csv`、`/api/hong-kong-macro/trade-dimensions.csv` 和 `/hong-kong-macro` 均返回 200；保存接口写入后按 snapshot ID 读回 490 行。
- 5001 浏览器验证使用 Playwright：页面标题、共享导航、六个页签、真实图表、Trade-IDDS 维度、CSD Web Table 细表、来源表、derived 月度流量、lead-lag 计算/保存结果和国家住房 YTD 警告均检查；1440px 与 390px 均无横向溢出，控制台错误/警告均为 0。
- 续做时先核对任务锁和端口，再精确替换旧 pythonw 进程并确认新进程命令行；当前 `5001` 的 health、数据 API、lead-lag 新旧接口和浏览器入口均返回/渲染正常。

## 9. P1 完成情况与剩余遗漏

已完成：

- HKMA 银行统计、客户存款、人民币存款、贷款及贸易融资的源目录、字段映射、raw/hash、
  parser、upsert、金融页分组和失败保留逻辑；当前在线刷新是否成功由来源状态如实决定。
- Trade-IDDS 中国内地来源地、寄运地、出口目的地和 SITC2 商品维度；含 API、页面摘要和独立 CSV。
- CSD 17 个官方 Web Table 细表；保留年/季/月频率和 `svDesc` 统计量，不把同一期间不同频率/统计量折叠。
- 国家新建商品房销售面积/销售额累计同比选项及 UI/API 的 YTD/non-monthly 警告。

仍明确未完成或不宜假装完成：

- HKMA 八个端点的定向 retry 已成功；后续全域刷新仍可能受源站网络波动影响，历史失败 run 和
  成功 retry 的 raw/hash/计数均保留，不能把一次成功重试推断为永久可用。
- 没有新增市级住房销售面积/销售额月度流量；当前提供的是国家层面 NBS 官方累计值差分 derived
  序列，不能替代官方单独发布的月度成交量，也没有拆分 1—2 月合并值。
- lead-lag 已支持显式 snapshot 保存/检索；尚未做自动化的批量 vintage 回测调度，这仍需另行定义。
  配对集合、窗口版本和保存策略。
- CSD Web Table 已接入提示词范围内的 17 张候选细表，但未把所有表的每一个官方 series 都
  再复制成单独顶层 indicator；它们通过细表 observation/API/UI 访问，避免把多频多统计量强行
  伪装成月度主序列。

## 10. 主要文件与 changelog

主要实现文件：

- `services/hong_kong_macro_service.py`
- `services/china_external_service.py`
- `services/china_macro_dashboard_service.py`
- `server.py`
- `static/hong_kong_macro.html`
- `static/research-nav.js`
- `tests/test_hong_kong_macro_service.py`

文档和导航同步更新：`README.md`、`projects/README.md`、`projects/china_macro/README.md`、`projects/registry.json`、`static/index.html`、`.gitignore`。

## 11. 2026-08-12 完整修复复核（以本节为当前状态）

本节是 2026-08-12 按完整修复提示词再次运行数据库、API、测试和浏览器验收后的当前结果；前文的阶段性计数和历史描述保留作过程记录，不覆盖本节。

### 11.1 当前数据库门禁

```text
PRAGMA quick_check = ok
主表 active/non-superseded non-NULL = 26,903
主表 superseded = 1,044
CSD active/non-superseded = 85,449
CSD superseded = 89,606
active 主 observation 重复键 = 0
active CSD 重复键 = 0
42 个 source raw hash = 42 match
主 observation source_url/retrieved_at/raw_sha256/parser_version 缺失 = 0
CSD source_url/retrieved_at/raw_sha256/parser_version/period_raw/statistic 缺失 = 0
```

主 observation 的 `release_date` 缺失数为 26,903。香港多个官方源没有稳定发布日期字段，系统保留 NULL，并单独记录 `retrieved_at`；没有把抓取时间伪装为发布日期。

当前 42 个 source 均为 `success`。页面整体仍为 `stale`，唯一触发 stale 的来源为 `HK_CSD_WEB_650-80001`，其最新期为 `2026-05`。这是质量提示，不是失败，也不是把历史数据标为最新。

### 11.2 SAFE 最终结果

- `CN_SAFE_MONETARY_GOLD_QUANTITY`：127 条，2016-01—2026-07；2026 年 1—7 月实际值为 `7419, 7422, 7438, 7464, 7496, 7544, 7608` 万盎司。
- `CN_SAFE_MONETARY_GOLD_USD`：2026-07 为 `3063.54` 亿美元。
- 2015 官方 `.xls`、2016—2017 官方 `.xlsx` 已有对应历史解析路径；2015 官方附件未提供可审计黄金数量，未制造数量值。
- SAFE 外汇储备和官方储备资产合计的 2026-08—12 空白行均为 `data_status=not_released`、`missing_reason=official_source_future_month_blank`，仍有 URL、hash、parser 和 retrieved_at。
- SAFE 继续与 PBoC `foreign_exchange`、银行结售汇和涉外收付款分开。

### 11.3 香港历史和语义层

- RVD 月度价格/租金各 402 条；季度价格 187 条（1979-Q4—2026-Q2）、季度租金 184 条（1980-Q3—2026-Q2）；年度价格 46 条、年度租金 45 条。季度和年度没有复制成月度。
- Land Registry 六个官方分段 endpoint 已完成全历史回填：1,770/1,770 条，六个指标各 295 条，覆盖 2002-01—2026-07；金额来自官方金额字段。
- CSD 17 张细表重新解析并 canonical 入库 85,449 条，M/Q/H/Y period、`freq+sv+stat+dimension` series key、`period_raw`、`statistic`、`construct_label`、source/hash/parser 均保留；旧键行标记 superseded。
- 主 API 有 10 条可解释 curated CSD 序列；CSD 细表通过 `/api/hong-kong-macro/csd-web-table/{table_id}` 独立分页，默认不把 85,449 条送进浏览器。

### 11.4 API、lead-lag 和保存门禁

- 同一筛选下 RVD 季度 API/CSV 均返回 187 条；CSV 当前为 31 列，含来源、状态、转换、hash、parser 和缺失原因。
- 默认读取 active、非 NULL、非 superseded；`include_superseded`/`include_missing` 需要显式请求。
- lead-lag 总体状态已统一为 `ok`、`hk_no_data`、`mainland_no_data`、`unsupported_transform`、`insufficient_overlap`、`invalid_request`、`failed`；只有 `ok` 才 `success=true`。
- `lag=0` 保留在同期曲线但不进入 `best_hong_kong_lead`；默认配对仍返回完整 -24—+24 共 49 个 lag。
- 空结果、只有 NULL 相关、样本不足、非法 transform 或无效 payload 均不能写入 snapshot。

### 11.5 最终测试和浏览器

```text
PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest discover -s tests -q
Ran 551 tests ... OK

定向香港宏观测试：22 项通过
py_compile：通过
git diff --check：通过（无 whitespace error）
```

运行态 `/api/health` 为 `200/status=ok`；debug `quick_check=ok`；source hash `42 match`；浏览器 Playwright 在 1440×900 和 390×844 视口均无 document 横向溢出，控制台 errors/warnings 均为 0。最终截图在 `output/playwright/hong-kong-macro-desktop-final.png` 和 `output/playwright/hong-kong-macro-mobile-final.png`。

详细逐项记录见：[hong_kong_macro_REPAIR_EXECUTION_2026-08-12.md](/mnt/d/claude/docs/hong_kong_macro_REPAIR_EXECUTION_2026-08-12.md)。

### 11.6 仍然明确保留的 backlog

自动批量 lead-lag vintage 回测、多重比较校正、因果识别、正式预测、高频 nowcast、市级官方商品房销售面积/销售额月度流量和后台定时更新没有伪装为已完成。CSD 访客表 stale、香港 source 多数没有 release_date、2015 SAFE 没有官方黄金数量也均在当前状态中明确记录。

### Changelog

- 2026-08-11：完成只读侦察、官方字段探针、WAL 一致性备份和香港独立 observation/source/update-run schema。
- 2026-08-11：接入 RVD、土地注册处 t1/t2、HKMA、Trade-IDDS、CSD；补齐土地注册处金额、Trade-IDDS 贸易差额/转口占比派生层。
- 2026-08-12：按 T210 官方有效代码全集分批抓取 SITC2，成功刷新 4,304 条商品维度；阶段性 run `483e4c0ccf864ae08e3e3857cd1ce8f5` 写入 107,306 条，保留 5 个 HKMA 源的网络失败证据。
- 2026-08-12：补齐 Trade-IDDS 全体来源地/出口目的地 Top N，增加筛选维度 API；本轮 run `e297ef25b3f34991af5db3bdd976a339` 写入 128,102 条，Trade dimensions 达 29,862 条，页面/默认 JSON 限制为最新期 Top 10，CSV 保留全量。
- 2026-08-11：接入 SAFE 官方储备资产历史 HTML/XLS/XLSX，保留与 PBoC `foreign_exchange`、结售汇和跨境收付款的口径边界。
- 2026-08-11：补齐 HKMA 未交收合约、总结余、HIBOR、政策利率、港元汇率/NEER、M1—M3 等已在官方响应中出现的字段。
- 2026-08-11：补齐 raw hash 追踪、部分失败状态、debug 安全摘要、一线城市住房派生比较、完整 lead-lag 曲线/标准化序列/滚动摘要和浏览器验收。
- 2026-08-12：完成 HKMA 银行统计/客户存款/人民币存款/贷款贸易融资字段、Trade-IDDS 六类维度和 17 个 CSD Web Table 的 raw—解析—入库—API—页面链路；新增 trade-dimensions 筛选 API/CSV、国家住房 YTD 敏感性配对和质量审计记录。
- 2026-08-12：修复 CSD Web Table 多频率/多统计量系列键折叠；canonical 行纳入 `freq + sv + svDesc + dimension`，旧派生行保留为 `superseded`，逐表完成解析数/入库数/唯一键门禁。
- 2026-08-12：根据 HKMA 官方文档补齐住宅按揭调查与负资产按揭的字段映射、季度/月度频率和金融页分组；本轮按揭调查写入 2,760 条、负资产按揭写入 203 条，失败源仍按阻断规则保留旧观测。
- 2026-08-12：在任务锁为空的前提下对 HKMA 8 个失败/阻断端点做定向 retry；run `337b032b595a44388e0787acf9572b8a` 完成，42/42 source 当前为 `success`，解析/写入 11,461/11,461。
- 2026-08-12：由国家统计局官方累计销售面积/销售额相邻月份差分生成两条研究用月度流量；面积与金额各 109 条，缺失上月不推断，并新增 3 个解析/schema/配对测试。
- 2026-08-12：lead-lag 增加显式 `snapshot_id`、保存/检索 API 和页面 vintage 按钮；当前两个测试 snapshot 各 490 行，GET 计算保持只读。
- 2026-08-12：修复香港页面手机端 linkage 控件的固定宽度，1440px/390px 浏览器验收均无横向溢出；全量测试更新为 542 项通过。
