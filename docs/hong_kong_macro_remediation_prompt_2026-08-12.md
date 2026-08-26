# 香港宏观与中国 SAFE 官方储备资产完整修复提示词

> 使用日期：2026-08-12  
> 项目目录：/mnt/d/claude  
> 目标页面：/hong-kong-macro  
> 关联页面：/china-macro  
> 性质：基于独立验收结果的修复、补数、质量提升与浏览器复验任务书  
> 使用方式：把本文件全文交给一个新的 Codex 窗口执行

---

## 一、你的角色与最终目标

你正在维护一个本地 Python HTTPServer、SQLite、services/ 和 static/ 组成的研究数据平台。

本轮不是重新设计一个演示页面，也不是只写方案。你需要在保护现有工作的前提下，真正修复香港宏观独立模块和中国 SAFE 官方储备资产接入中已经被独立验收发现的问题，并逐层验证：

    官方来源
      -> 原始文件或响应
      -> 解析
      -> 规范化与语义
      -> SQLite
      -> API
      -> CSV
      -> 页面
      -> 真实浏览器
      -> 状态文档

最终目标是：

1. 香港继续作为独立统计辖区和“中国的对外窗口”，不进入城市经济模块；
2. 中国 SAFE 官方储备资产继续与 PBoC 资产负债表外汇、银行结售汇、跨境收付款严格分开；
3. 修复当前会产生错误完成状态、错误导出或无效快照的 P0 问题；
4. 补齐研究审计所需的来源、单位、频率、发布日期、修订、季调、价格口径和缺失原因；
5. 将已经下载的 CSD 细表从“行数很多”升级成可解释、可筛选、可绘图的语义数据；
6. 对能合理回填的官方历史执行回填，但不插值、不伪造月频、不把低频值复制到月份；
7. 完成页面时间筛选、转换、tooltip、图例、来源和筛选一致 CSV；
8. 保留香港—内地 lead-lag 的描述性定位，不预设香港领先，不把相关当因果或预测；
9. 用数据库、API、CSV、测试和真实浏览器证据证明完成程度；
10. 对仍受官方源限制或属于后续研究设计的内容明确标记未完成。

不要只给计划。完成侦察后应直接实施安全、增量、可验证的修复。

---

## 二、项目边界与不可违反的约束

### 2.1 香港模块边界

- 香港页面固定为 /hong-kong-macro。
- 香港 jurisdiction 固定为 HK。
- 不把香港加入 city_indicator_observations。
- 不把香港加入 housing_city_observations 的城市选择器。
- 不把香港与内地城市、全国值做加总。
- 香港可以与内地做 aligned、normalized、parallel_only 或 linked 比较，但必须显示比较模式和定义差异。
- 页面定位是中国的外部、贸易、金融和资产价格窗口，不是“内地普通城市”。

### 2.2 SAFE 口径边界

以下概念必须继续使用独立指标代码、单位、来源和说明：

- SAFE 官方外汇储备；
- SAFE 官方储备资产合计；
- SAFE 货币黄金美元价值；
- SAFE 黄金实物数量；
- SAFE SDR 持有；
- SAFE IMF 储备头寸；
- SAFE 其他储备资产；
- PBoC 资产负债表 foreign_exchange；
- 银行结售汇；
- 银行代客涉外收付款。

禁止把 SAFE 外汇储备写入 PBoC foreign_exchange 代码，禁止用 PBoC 外汇资产替代 SAFE 美元储备。

### 2.3 数据安全

- 不删除、覆盖、重命名或移动现有数据库、原始文件、日志、输出和用户未提交改动。
- 不执行 git reset --hard、git checkout --、批量清理或破坏性数据库迁移。
- 当前工作区不是干净 worktree；所有既有修改和未跟踪文件都视为用户工作。
- 修改前先运行 git status --short，并记录与本任务相关的文件。
- 数据库处于 Windows/WSL 混合环境并可能有 WAL；优先使用 python.exe 访问项目数据库。
- 不用 WSL sqlite3 强行操作正被 Windows 服务使用的 WAL 数据库。
- 任何 schema 变化必须使用 CREATE TABLE IF NOT EXISTS、ALTER TABLE 增量迁移或兼容迁移。
- 不 drop 现有香港宏观表。
- 不把 NULL、破折号、空白、n.a.、未发布月份解析为 0。
- 不用线性插值、前向填充或复制季度值制造月度数据。
- 不用搜索引擎摘要、新闻转述或第三方图表值作为正式观察。
- 不绕过验证码、访问限制或网站安全机制。

### 2.4 网络与长任务

- 先做低频、小范围官方探针，再决定是否刷新。
- 每次完整历史回填前，先报告命令、来源、预计写入表、预计时间和磁盘影响。
- 不因为一次成功重试宣称源站永久稳定。
- 不无限重试；有限次数、明确超时、失败留证。
- 如果机器可读官方源可用，不从 PDF 重抄。

### 2.5 Git

- 不创建提交、不推送、不开 PR，除非用户另行要求。
- 只修改本任务必要文件。
- 不格式化或重写无关文件。
- 完成后运行 git diff --check。

---

## 三、开始前必须重新核对的现状

以下是 2026-08-12 独立验收时的基线，不是可跳过重新核对的永恒事实。

### 3.1 运行与测试基线

- 本地服务目标端口为 5001。
- /api/health 当时返回 200。
- 全量 unittest 当时为 542 项通过。
- 香港页面当时可在 1440px 和 390px 打开。
- 两种视口当时都没有横向溢出。
- Playwright 控制台当时为 0 error、0 warning。
- 远程 WSL 地址访问健康接口时为 read_only。
- 从远程地址 POST lead-lag 保存接口当时返回 403 remote_write_forbidden。

### 3.2 SQLite 基线

当时数据库中：

- hong_kong_macro_sources：42 行，全部 status=success；
- hong_kong_macro_observations：26,765 行；
- 其中 value 非空的主观察：25,721 行；
- superseded 且 value 为空的旧记录：1,044 行；
- hong_kong_macro_trade_dimensions：29,862 行；
- hong_kong_macro_web_table_observations：139,741 行；
- 其中 active CSD Web Table 观察：85,449 行；
- superseded CSD 观察：54,292 行；
- hong_kong_macro_lead_lag_results：980 行；
- 主观察、贸易维度、active CSD 唯一键重复数均为 0；
- 42 个来源登记的 raw_path 文件均存在；
- 42 个来源登记的 raw_sha256 均与文件复算一致。

### 3.3 当前已确认正确的功能

不要为了修复而破坏以下能力：

- 香港独立页面和独立 jurisdiction；
- 香港没有进入两个城市数据表；
- RVD 住房观察；
- Land Registry 住宅一手、二手宗数和金额；
- Trade-IDDS 进口、本地出口、转口、总出口、总贸易；
- 贸易来源地、目的地、商品维度；
- HKMA 外币储备；
- SAFE 六个主要金额组件和官方总额；
- PBoC foreign_exchange 与 SAFE 分离；
- GET lead-lag 不写数据库；
- 受保护 POST 的全局远程写限制；
- 原始文件保存与 SHA-256 留痕；
- 更新失败保留旧有效观察；
- lag 符号约定：

    corr_at_lag(k) = corr(HK_t, Mainland_(t+k))

    k > 0 表示香港领先；
    k < 0 表示内地领先；
    k = 0 表示同期。

### 3.4 已验证的恒等式

修复后必须继续满足：

    RVD total sales count
      = primary sales count + secondary sales count

    Land Registry total count
      = primary count + secondary count

    Land Registry total value
      = primary value + secondary value

    total exports
      = domestic exports + re-exports

    total trade
      = imports + total exports

    trade balance
      = total exports - imports

    re-export share
      = re-exports / total exports * 100

独立验收时：

- RVD 宗数残差为 0；
- Land Registry 宗数残差为 0；
- Land Registry 金额最大残差为 1 HK$ million；
- Trade-IDDS 总出口、总贸易最大残差为 1 个官方最小单位；
- SAFE 官方总额与组件加总在 134 个重叠月份最大残差约 1.45 亿美元。

这些小残差按官方舍入或估值差异保留，不能静默改写官方总额。

---

## 四、完成状态词与汇报纪律

每条数据链路必须按以下阶段分别汇报：

1. 官方来源已定位；
2. 访问已验证；
3. 原始数据已下载；
4. 解析已完成；
5. schema 和单位已验证；
6. 恒等式或范围校验已通过；
7. 已入库；
8. API 已返回；
9. CSV 已返回；
10. 页面已呈现；
11. 浏览器已验收。

不要把“source status=success”直接写成“历史完整”。

不要把“数据库有 85,449 行”直接写成“CSD 指标已可研究使用”。

不要把“测试通过”直接写成“真实官方 HTML 形状已覆盖”。

不要把“页面能打开”直接写成“筛选、tooltip、来源和 CSV 已完成”。

对未完成项使用明确词语：

- not_attempted；
- blocked；
- failed；
- partial；
- stale；
- unsupported；
- not_released；
- insufficient_sample；
- superseded。

---

## 五、总修复顺序与硬门禁

必须按以下顺序推进：

1. Phase 0：只读侦察与证据冻结；
2. Phase 1：P0-A，修复 SAFE 黄金数量；
3. Phase 2：P0-B，修复 lead-lag 空序列与无效快照；
4. Phase 3：P0-C，修复 API 和 CSV 筛选一致性；
5. Phase 4：P1-A，补齐指标与来源元数据、freshness；
6. Phase 5：P1-B，官方历史回填与无数据指标治理；
7. Phase 6：P1-C，CSD 细表语义化；
8. Phase 7：P1-D，页面交互和研究可读性；
9. Phase 8：P2，增强 vintage 可复现性，但不自动新增批量调度；
10. Phase 9：数据库、API、测试、浏览器和文档总验收。

每个 Phase 完成后先运行该阶段的目标测试和只读核对。前一阶段未过硬门禁时，不得跳过并把整个模块称为完成。

---

## 六、Phase 0：只读侦察与证据冻结

### 6.1 检查项目

先检查：

    pwd
    git status --short
    rg --files

重点阅读：

- README.md；
- projects/README.md；
- projects/china_macro/README.md；
- projects/registry.json；
- server.py；
- services/hong_kong_macro_service.py；
- services/china_external_service.py；
- services/china_macro_dashboard_service.py；
- services/housing_price_service.py；
- static/hong_kong_macro.html；
- static/research-nav.js；
- tests/test_hong_kong_macro_service.py；
- tests/test_china_external_service.py；
- tests/test_research_navigation.py；
- docs/hong_kong_macro_implementation_prompt_2026-08-11.md；
- docs/hong_kong_macro_STATUS_2026-08-11.md；
- docs/hong_kong_macro_P1_AUDIT_2026-08-12.md。

检查是否存在项目级或子目录 AGENTS.md，并遵守其规则。

### 6.2 检查服务而非先重启

依次检查：

- 端口 5001；
- 当前 server.py 进程；
- watchdog；
- /api/health；
- /api/jobs；
- 最近日志；
- 数据库锁和 WAL 状态。

除非服务确实不可用且证据表明需要重启，否则不要重启。

如果必须重启：

- 使用项目现有安全启动方式；
- 不直接杀掉未知进程；
- 记录旧 PID、新 PID、启动命令和日志路径；
- 重启后复测健康接口。

### 6.3 记录修复前基线

用 python.exe 和 PRAGMA query_only=ON 记录：

- 各香港表行数；
- active、superseded、NULL 行数；
- 每个指标的 n、min(period)、max(period)；
- 每个来源状态和最后成功时间；
- 42 个 raw 文件是否存在；
- 42 个 raw hash 是否匹配；
- SAFE 七条指标行数和覆盖；
- 两个城市表中的香港命中数；
- lead-lag 快照数；
- 主表、贸易表、CSD 表重复键；
- 主要恒等式残差。

把修复前数字放入本轮 changelog 或审计记录，便于前后比较。

### 6.4 Phase 0 硬门禁

只有在以下条件满足后才开始改代码：

- 已确认工作区已有用户修改；
- 已确认数据库真实路径；
- 已确认当前服务和访问模式；
- 已记录关键表行数；
- 已确认相关 raw 文件存在；
- 已阅读旧提示词、状态和审计文件；
- 已确认本轮不会覆盖用户工作。

---

## 七、Phase 1：P0-A 修复 SAFE 黄金数量

### 7.1 已知问题

本地当时：

- CN_SAFE_MONETARY_GOLD_QUANTITY 只有 24 条；
- 覆盖 2016-01 至 2017-12；
- 2018-01 至 2026-07 缺失。

但 SAFE 官方 2026 HTML 表已明确给出黄金数量：

- 2026-01：7419 万盎司；
- 2026-02：7422 万盎司；
- 2026-03：7438 万盎司；
- 2026-04：7464 万盎司；
- 2026-05：7496 万盎司；
- 2026-06：7544 万盎司；
- 2026-07：7608 万盎司。

官方入口：

https://www.safe.gov.cn/safe/whcb/

2026 机器可读 HTML：

https://www.safe.gov.cn/safe/2026/0206/27116.html

### 7.2 根因方向

当前 HTML 解析器主要通过行标签中是否含有：

- quantity and gold；
- 黄金数量；

来识别数量行。

真实 SAFE 年度 HTML 的黄金数量可能位于黄金美元价值行之后的独立行，行首标签为空，只包含按月份排列的“xxxx万盎司”值。

现有单元测试 fixture 给数量行人工写了 Gold quantity 标签，因此没有覆盖真实形状。

### 7.3 实施要求

修复 services/china_external_service.py 中 SAFE 年度 HTML 解析，要求：

1. 继续优先锁定官方储备资产表，而不是全页正则；
2. 先识别 Gold / 黄金美元价值行；
3. 在同一表中识别其后紧邻或结构关联的数量行；
4. 数量行即使没有文字标签，也可通过以下组合判定：
   - 位于黄金行之后；
   - 与月份列对齐；
   - 单元格含“万盎司”或 fine troy ounce 语义；
   - 数值数量与已发布月份一致；
5. 不得把任意空标签数值行误认成黄金数量；
6. 保留美元价值和实物数量为两个指标；
7. 黄金数量单位固定为官方“万盎司”，不要转成吨；
8. 不把数量与美元价值相加；
9. 不把未来空白月份写成 0；
10. 如果官方未来月份空白被保留，使用 NULL 和 not_released，而不是 official actual；
11. 继续支持 2015—2017 XLS/XLSX 历史附件；
12. 对 2018—2026 年年度 HTML 进行历史回填；
13. 每条观察保留年度页面 URL、retrieved_at、raw_sha256、parser_version；
14. 如果能从页面元数据获得发布日期，写入 release_date；
15. 失败刷新不得清除已有 2016—2017 数量。

### 7.4 测试要求

新增真实形状 fixture：

- Gold 行有美元和 SDR 值；
- 下一行标签为空；
- 下一行含 7419万盎司、7422万盎司等；
- 断言 2026-01 数量为 7419；
- 断言 2026-07 数量为 7608；
- 断言美元价值仍为 3063.54 亿美元；
- 断言黄金数量不被当成美元；
- 断言空白未来月份不是 0；
- 断言缺少数量行时只缺数量，不影响其他六个系列；
- 断言错误位置的无标签行不会被误认。

现有带显式 Gold quantity 标签的 fixture 继续保留，以保证兼容旧 XLS/HTML 形状。

### 7.5 数据回填与核对

使用最小范围的 SAFE 官方储备资产刷新，不要为修一条序列无条件刷新所有中国宏观来源。

如果现有服务没有目标化 SAFE 刷新入口：

- 优先复用现有函数做本地定向调用；
- 必要时新增内部定向更新函数；
- 不新增暴露到远程的无保护写接口；
- 不写一次性不可复现的手工 SQL。

回填后核对：

- 黄金数量覆盖至少到 2026-07；
- 2026-01 至 2026-07 与官方表逐月一致；
- 七条 SAFE 序列仍使用各自正确单位；
- /api/china-macro/data 能返回新黄金数量；
- /china-macro 黄金数量图能显示 2018 年以后数据；
- PBoC foreign_exchange 行数和指标代码未改变；
- 组件与官方总额残差规则未改变。

### 7.6 Phase 1 硬门禁

以下全部满足才算通过：

- 真实无标签数量行 fixture 通过；
- 2026-07 黄金数量为 7608 万盎司；
- 2018—2026 数量不再整体断档；
- 美元黄金价值没有被覆盖；
- SAFE 总额没有被组件加总覆盖；
- 中国宏观 API 和页面均可见；
- 目标测试通过；
- 原始来源和 hash 可追溯。

---

## 八、Phase 2：P0-B 修复 lead-lag 空序列、样本门禁与无效快照

### 8.1 已知问题

当时以下调用会返回 success=true：

- 香港指标有 0 条观察；
- 香港指标只有 15 条观察；
- 所有 49 个 lag 都是 insufficient_sample；
- best_absolute、best_positive、best_hong_kong_lead 全部为空。

页面只根据 data.success 决定是否开放“保存当前结果”，因此无效结果可能进入 snapshot 表。

此外当前 best_hong_kong_lead 使用 minimum_lag=0，但页面和方法定义明确要求 k>0 才表示香港领先。lag=0 是同期，不能进入“香港领先区间”。

### 8.2 总体结果状态

为 lead-lag payload 增加明确总体状态：

- ok：至少一个全样本 lag 有非空相关且 status=ok；
- hk_no_data：香港序列没有有效观察；
- mainland_no_data：内地序列没有有效观察；
- unsupported_transform：指标不支持请求转换；
- insufficient_overlap：有序列但没有任何 lag 达到最低重叠；
- invalid_request：未知指标、未知变换或非法参数；
- failed：计算异常。

success 只有在总体 status=ok 时才为 true。

HTTP 建议：

- 合法但样本不足可返回 200，success=false，status=insufficient_overlap；
- 未知指标或非法变换返回 400；
- 服务内部错误返回 500；
- 不要用 success=true 包装空结果。

### 8.3 可用指标目录

不要用 INDICATORS 中所有 monthly 定义无条件生成下拉框。

API 应返回每个候选香港指标的：

- indicator_code；
- name_zh；
- unit；
- frequency；
- n_obs；
- start_period；
- end_period；
- supported_transforms；
- eligible_for_lead_lag；
- ineligible_reason；
- source_id；
- latest_status。

eligible_for_lead_lag 至少考虑：

- 有有效观察；
- 频率可与目标月度分析兼容；
- 指标不是 unsupported；
- 指标转换后可能达到最低样本；
- 不把尚无数据的代码提供为可保存分析。

对于只有 15 个月的数据：

- 可以显示，但明确 disabled 或“样本不足 60 月”；
- 或从默认候选列表隐藏；
- 不得让用户误以为可以计算正式 lead-lag。

### 8.4 五个无观察指标

独立验收时注册表中有五个完全无值指标：

- HK_RVD_PRIMARY_SALES_VALUE；
- HK_RVD_SECONDARY_SALES_VALUE；
- HK_RVD_TOTAL_SALES_VALUE；
- HK_HKMA_FC_RESERVE_ASSETS_LF；
- HK_HKMA_UNSETTLED_FX_CONTRACTS_LF。

处理规则：

- 先核对官方源是否真实提供这些字段；
- 如果源不提供，标记 unsupported 或 unavailable_at_source；
- 如果只是历史上已终止，标记 discontinued 并记录覆盖；
- 不删除历史定义；
- 不把它们放进默认图表或 lead-lag 可保存列表；
- 不用 Land Registry 金额冒充 RVD 金额；
- 不用总额减外汇基金值推算土地基金值，除非官方定义明确允许且标为 derived。

### 8.5 转换元数据

转换不能对所有月度指标无条件开放。

建立 supported_transforms，至少按以下逻辑：

- 价格、租金和一般指数：level、yoy、mom、index100；
- 月度金额或宗数流量：level、yoy、mom、rolling_12m、index100；
- 利率、HIBOR、失业率、份额：level、difference；如提供 yoy，必须明确是百分点变化还是百分比变化；
- 已经是同比的序列：level，不再对同比值二次 yoy；
- 存量：level、yoy、index100，不做 rolling sum；
- 季度序列：level、yoy、qoq；qoq_sa 仅限官方季调序列；
- 半年和年度序列不进入月度 lead-lag；
- 不对缺失或 unsupported 指标提供转换。

页面选中指标后动态更新变换选项。

### 8.6 保存门禁

persist_lead_lag_payload 必须拒绝：

- success=false；
- 没有任何 results；
- 所有 corr 都是 NULL；
- 所有 results 都是 insufficient_sample；
- 香港或内地 n_obs 为 0；
- 未知指标；
- unsupported_transform；
- 没有有效全样本曲线而只有空 rolling rows。

页面保存按钮只有在以下条件同时满足时启用：

- data.success=true；
- data.status=ok；
- 至少一个全样本相关非空；
- 当前选项没有在计算后变化；
- 当前用户有写权限。

保存失败时不要显示“已保存 snapshot=失败”一类模糊文本，要显示 HTTP 状态和明确错误。

### 8.7 香港领先区间

修复：

    best_hong_kong_lead

只能在 lag_months >= 1 的行中选择。

lag=0 单独标记“同期”。

全样本曲线仍保留 -24 至 +24 共 49 个 lag。

### 8.8 测试要求

新增：

1. 香港 0 条观察 -> success=false、status=hk_no_data；
2. 内地 0 条观察 -> success=false、status=mainland_no_data；
3. 只有 15 条 -> insufficient_overlap；
4. 所有 lag insufficient -> 保存函数抛出明确 ValueError；
5. 无效 payload 不增加 snapshot 行；
6. GET 计算前后 snapshot 行数相同；
7. lag=0 不会成为 best_hong_kong_lead；
8. 合成香港领先 6 个月 -> 最佳 lag 符号为正；
9. 合成内地领先 6 个月 -> 最佳 lag 符号为负；
10. unsupported transform 返回明确错误；
11. 下拉目录不把 0 条观察指标标为 eligible；
12. 合法默认配对仍产生 49 个全样本 lag；
13. 60 月和 120 月滚动窗口仍返回样本数和状态。

### 8.9 Phase 2 硬门禁

- 空序列不再 success=true；
- 无效结果不能保存；
- lag=0 不再被称为香港领先；
- 默认配对仍可计算；
- GET 保持只读；
- 页面明确显示 no data 或 insufficient sample；
- 新旧目标测试全部通过。

---

## 九、Phase 3：P0-C 修复 API 和 CSV 筛选一致性

### 9.1 已知问题

当时：

- /api/hong-kong-macro/data 不解析筛选参数；
- /api/hong-kong-macro/export.csv?start=2026-01 与无参数导出字节完全相同；
- CSV 导出 26,765 行；
- API 主层有效观察只有 25,721 行；
- CSV 默认包含 1,044 条 superseded 空值旧记录；
- 页面没有全局时间范围和转换状态；
- 下载按钮无法导出“当前看到的数据”。

这不满足“CSV 能导出当前筛选”的首版门禁。

### 9.2 查询契约

为香港主数据 API 和 CSV 建立一致的查询参数。

至少支持：

- start：开始参考期；
- end：结束参考期；
- group：housing、economy、re_export、reserves_finance、china_linkage；
- indicators：逗号分隔或重复参数；
- source：一个或多个 source_id；
- transform：level、yoy、mom、qoq、difference、rolling_12m、index100 中受元数据允许的值；
- base_period：index100 所需共同基期；
- status：默认 active；
- include_superseded：默认 false；
- include_missing：默认 false；
- format：如项目已有通用方式可支持 json 或 csv。

要求：

- 未知 group、指标、source、transform 返回 400；
- start > end 返回 400；
- 指标数量设置合理上限；
- 参数不能静默忽略；
- 默认不返回 superseded；
- 默认不返回纯 NULL 历史记录；
- 显式审计请求才包含 superseded，并保留状态和 vintage。

### 9.3 期间处理

支持并验证：

- monthly：YYYY-MM；
- quarterly：YYYY-Q1 至 YYYY-Q4；
- semiannual：YYYY-H1、YYYY-H2；
- annual：YYYY。

不要用字符串排序混合比较不同格式。

实现统一 period parser，将期间映射到：

- period_start；
- period_end；
- frequency；
- canonical_label。

过滤时按规范期间比较。

### 9.4 API 返回字段

每条 series 元数据至少返回：

- indicator_code；
- name_zh；
- name_en；
- description；
- group；
- frequency；
- unit；
- currency；
- seasonal_adjustment；
- price_basis；
- source_id；
- source_name；
- source_url；
- source_table；
- first_period；
- last_period；
- latest_release_date；
- latest_status；
- supported_transforms；
- derived 或 original；
- formula 和脚注。

每条 observation 至少返回：

- period；
- period_start 或 period_end；
- value；
- unit；
- status；
- transformation；
- source_id；
- source_url；
- release_date 或明确为空；
- retrieved_at；
- derived；
- formula；
- missing_reason；
- vintage_date；
- raw_sha256 或安全摘要。

不要把内部绝对路径发送给远程 API。

### 9.5 CSV 行为

CSV 必须与 API 和页面当前筛选一致：

- 同一 start/end；
- 同一 indicators；
- 同一 group；
- 同一 transform；
- 同一 source；
- 默认只导出 active 有效观察；
- 用户显式选择审计模式时才导出 superseded。

CSV 至少包含：

- indicator_code；
- name_zh；
- name_en；
- category；
- period；
- frequency；
- value；
- transformed_value；
- transformation；
- unit；
- currency；
- seasonal_adjustment；
- price_basis；
- data_status；
- derived；
- formula；
- dimension_key；
- dimension_value；
- source_id；
- source_url；
- source_table；
- release_date；
- retrieved_at；
- vintage_date；
- raw_sha256；
- note。

编码：

- 复用项目已有 CSV 约定；
- 至少保证 UTF-8 可无损读取中文；
- 如果为 Excel 添加 BOM，只对该导出明确实现并测试，不要无意改变全站所有 CSV。

### 9.6 性能

当前香港主 API 当时约 7.75 MB。

优化方向：

- 先在 SQL 层过滤；
- 不在主 payload 无条件附带 2,000 条未被页面使用的 CSD preview；
- 大维度继续使用单独端点；
- CSD 细表增加独立筛选端点；
- 主页面只加载当前页签必要数据，或先加载摘要再按需加载；
- 不一次把 85,449 条 CSD active 观察送到浏览器。

不要以牺牲来源和状态字段为代价压缩。

### 9.7 页面筛选状态

页面增加统一 state：

- active tab；
- start；
- end；
- selected indicators；
- transform；
- base period；
- visible series；
- selected sources。

下载链接必须从当前 state 构造 URL。

切换筛选后：

- 图表更新；
- latest 卡片更新；
- CSV URL 更新；
- 来源显示更新；
- 无数据状态更新；
- 不自动执行写入。

### 9.8 测试要求

新增真实服务或函数测试：

1. start 会减少 CSV 行数；
2. end 会减少 CSV 行数；
3. indicators 只返回所选指标；
4. group 只返回所选分组；
5. 默认 CSV 不含 superseded；
6. include_superseded=true 时包含且状态正确；
7. 默认不含 NULL 行；
8. transform=yoy 与已知手工计算一致；
9. 不支持的 transform 返回 400；
10. CSV 和 JSON 对同一筛选的观察数一致；
11. CSV 表头含来源、状态和转换；
12. 中文 UTF-8 往返无损；
13. start>end 返回 400；
14. 未知指标返回 400；
15. 页面下载链接携带当前筛选；
16. 大维度端点仍支持 latest、top_n、start、end。

### 9.9 Phase 3 硬门禁

- 带 start 的 CSV 与全量 CSV 不再相同；
- 默认 CSV 行数与 active、非空筛选一致；
- CSV 不再默认导出 1,044 条 superseded 空值；
- JSON 和 CSV 同筛选结果一致；
- 页面导出当前筛选；
- 非法参数不会静默忽略；
- 目标测试通过。

---

## 十、Phase 4：P1-A 补齐指标、来源、观察元数据与 freshness

### 10.1 已知缺口

当时 42 个 source 记录中，以下字段全部为空：

- download_url；
- request_params；
- file_format；
- history_start；
- unit；
- seasonal_adjustment；
- latest_release_date；
- terms_note。

25,721 条有效主观察中：

- release_date 全部为空；
- seasonal_adjustment 全部为空；
- price_basis 全部为空；
- vintage_date 全部为空；
- currency 约 8,520 条为空。

当前 INDICATORS 主要是五元 tuple：

- 中文名；
- 单位；
- 频率；
- category；
- source_id。

它不足以满足研究语义和页面转换约束。

### 10.2 指标注册表

增量扩展指标元数据。避免一次盲目重写全部调用方。

可以：

- 新建规范 metadata dict；
- 或增加兼容 helper，将旧 tuple 正规化；
- 逐步把核心指标迁移为完整结构。

每个核心指标至少包含：

- indicator_code；
- name_zh；
- name_en；
- short_description；
- category；
- subcategory；
- jurisdiction；
- frequency；
- unit；
- currency；
- seasonal_adjustment；
- price_basis；
- stock_or_flow；
- original_or_derived；
- source_id；
- source_table；
- history_start；
- expected_release_lag；
- supported_transforms；
- formula；
- footnote；
- comparison_mode_hint。

对于无法确认的字段：

- 使用 NULL 或 unknown；
- 提供 missing_reason；
- 不根据常识编造官方定义。

### 10.3 来源登记

为 42 个来源填充真实信息：

- institution；
- dataset_name；
- source_type；
- entry_url；
- download_url 或 API URL；
- request_params 的稳定 JSON；
- file_format；
- frequency；
- history_start；
- unit 或 mixed；
- seasonal_adjustment；
- latest_reference_period；
- latest_release_date；
- last_success_at；
- last_attempt_at；
- raw_sha256；
- raw_path；
- parser_version；
- record_count；
- license 或 terms_note；
- error_type；
- error_message。

API 来源的 request_params 要记录 offset、pagesize、segment 或表号。

RVD 多工作簿来源不能全部只登记同一个首页 raw hash。每个数据集应能追到实际工作簿 raw 文件和 hash。

### 10.4 发布日期与抓取日期

严格区分：

- release_date：官方发布日期；
- retrieved_at：项目抓取时间；
- vintage_date：本项目保存的数据版本时间；
- reference_period：统计参考期。

不能用 retrieved_at 假装 release_date。

官方未提供发布日期时：

- release_date 保持 NULL；
- source metadata 写 release_date_not_provided；
- 页面显示“抓取于”，不要显示“发布于”。

### 10.5 修订、暂定和派生

规范 data_status：

- official；
- provisional；
- revised；
- official_revised；
- derived；
- not_released；
- unavailable；
- superseded。

解析：

- RVD P、*、Z 等官方标记；
- HKMA 脚注或重分类状态；
- SAFE 空白未来月份；
- CSD 官方增长率与项目计算增长率。

派生观察必须带：

- derived=true；
- formula；
- input indicator codes；
- calculation_version；
- 不覆盖官方原始指标。

### 10.6 mixed-frequency latest period

禁止继续使用：

    max(period_string)

来比较 YYYY-MM、YYYY-Qn、YYYY-Hn 和 YYYY。

实现规范 parser，并在 meta 中返回：

- latest_monthly_period；
- latest_quarterly_period；
- latest_semiannual_period；
- latest_annual_period；
- latest_release_date；
- latest_reference_period 的明确选择规则。

页面顶部优先显示：

- 最新成功更新时间；
- 最新月度参考期；
- 最新季度参考期；
- 来源覆盖数。

不要因为字符串 Q 大于连字符而显示错误“最新参考期 2026-Q2”。

### 10.7 stale 状态

增加 freshness 规则，但不要一刀切。

每个来源或指标记录：

- expected_frequency；
- expected_release_lag_days；
- latest_reference_period_end；
- last_success_at；
- freshness_status；
- freshness_reason。

状态至少：

- current；
- delayed_but_expected；
- stale；
- source_failed_using_cached_data；
- not_released；
- unknown。

页面总状态：

- ok：核心来源 current 且无硬失败；
- partial：部分核心来源失败、缺失或历史不足；
- stale：数据可用但超过来源预期更新窗口；
- empty：无有效观察。

不要只因 42 个 source status 都是 success 就显示“正常”。

### 10.8 debug API

debug 至少增加：

- 数据库 quick_check；
- 表和迁移版本；
- active、superseded、NULL；
- 每个指标首末期和 n；
- 0 条指标；
- 少于最低样本指标；
- mixed-frequency period 异常；
- source metadata 缺失数；
- observation metadata 缺失数；
- raw 文件缺失和 hash mismatch；
- 重复键；
- 恒等式残差；
- 当前更新任务；
- stale 来源；
- 最近失败 run；
- 安全的数据库标识，不暴露私密绝对路径。

### 10.9 Phase 4 硬门禁

- 核心指标拥有完整语义元数据；
- source 表不再八个关键字段全部为空；
- release_date 与 retrieved_at 不混淆；
- currency 缺失显著减少且有解释；
- mixed-frequency latest period 正确；
- 页面支持 partial 和 stale；
- debug 能列出元数据缺口；
- 相关测试通过。

---

## 十一、Phase 5：P1-B 官方历史回填与无数据指标治理

### 11.1 RVD 完整历史

官方入口：

https://www.rvd.gov.hk/en/publications/property_market_statistics.html

官方页面说明：

- Private Domestic Price Indices 完整序列自 1979；
- Private Domestic Rental Indices 完整序列自 1979；
- Domestic Sales 自 2002。

当前主价格、租金序列当时从 1993-01 开始。

要求：

1. 检查官方工作簿中 1979—1992 是年度、季度还是月度；
2. 保留官方真实频率；
3. 不把年度或季度值复制成月度；
4. 如同一官方指标跨年代频率变化，明确选择：
   - 每行保留原频率；
   - 或拆分 monthly、quarterly、annual 指标代码；
5. 页面默认月度图可以从 1993 开始；
6. 另提供完整历史入口或低频图；
7. 记录工作表、表头、基期、修订标记和脚注；
8. 价格和租金指数基期必须显示；
9. 不把平均价格、平均租金与指数混为同一序列；
10. 回填前后记录行数和覆盖变化。

### 11.2 Land Registry 完整历史

官方入口：

https://www.landreg.gov.hk/en/monthly/index.htm

当前数据库当时从 2012-01 开始，但代码已有 2002—2026 文件路径。

要求：

- 检查 full_history=True 是否确实读取全部历史文件；
- 定向回填 2002—2011；
- 一手和二手宗数、金额分别保留；
- 总计继续通过官方字段或恒等式核对；
- 登记月份不解释为签约月份；
- 页面和 lead-lag 保留登记时滞警告；
- 不用 RVD 销售金额替代 Land Registry 金额；
- 不把注册宗数与 MacroMicro 第三方口径混用。

### 11.3 HKMA 短历史

当前使用的 HKMA financial/economic-statistics 端点只返回近期 20 条汇总记录。

当时主层：

- 名义 GDP：4 个季度点；
- 实质 GDP：4 个季度点；
- CPI：14 个月；
- 失业率：14 个月；
- 货币基础和 HIBOR：15 个月；
- 外币储备：318 个月，2000-01 至 2026-06。

处理规则：

- 不把该 20 条端点描述为完整历史；
- 保留它作为近期 HKMA 汇总或交叉核验来源；
- 经济历史优先从 CSD 官方细表映射；
- 金融历史优先检查 HKMA 具体表端点；
- 不因为 summary endpoint 短就循环 offset 制造不存在的页；
- 验证 datasize 和 records 长度；
- 页面显示真实覆盖，不隐藏只有 4 或 14 条的事实。

### 11.4 无数据指标

对五个 0 条指标逐一给出结论：

- source provides field；
- historical only；
- discontinued；
- parser bug；
- unsupported。

不得保留为“看起来可用”的普通指标。

如果 source 不提供 RVD 销售金额：

- 将其标记 unsupported；
- 默认页面和下拉隐藏；
- Land Registry 金额继续作为独立官方序列；
- 不删除代码以免破坏旧引用，但 metadata 明确。

如果土地基金字段只在早期存在：

- 历史回填实际存在的期间；
- 没有历史就标记 unavailable；
- 不从总额反推。

### 11.5 Phase 5 硬门禁

- RVD 完整历史频率事实已确认；
- 1979—1992 不再被无说明遗漏，或明确记录为何不入月度主序列；
- Land Registry 2002—2011 已回填，或有官方阻断证据；
- HKMA 短端点不再被称为完整历史；
- 0 条指标不再出现在可用分析列表；
- 回填没有制造重复键；
- 恒等式仍通过；
- 目标测试通过。

---

## 十二、Phase 6：P1-C 将 CSD 细表变成可研究语义层

### 12.1 已知问题

当前 active CSD Web Table 有 85,449 条，但：

- 页面只显示表号、系列数、行数和覆盖；
- 主 payload 带 2,000 条 preview，但页面不使用；
- 5,349 条 series_label 与 unit 完全相同；
- 例如 series_label 可能只是 ('000) 或 (%)；
- freq=H 的半年人口观察回退为 annual；
- CSD quarterly 使用 YYYY-MM，而主表 quarterly 使用 YYYY-Qn；
- svDesc 有时是单位，有时是 Year-on-year % change，不是构念名称；
- 行数很多，但没有稳定的中文/英文指标语义。

### 12.2 频率映射

明确支持官方频率代码：

- M -> monthly；
- Q -> quarterly；
- H -> semiannual；
- Y -> annual。

未知频率：

- frequency=unknown；
- data_status=partial 或 metadata_unknown；
- debug 列出；
- 不回退成表级默认频率后静默入库。

规范期间：

- M：YYYY-MM；
- Q：YYYY-Q1 至 YYYY-Q4；
- H：YYYY-H1 或 YYYY-H2；
- Y：YYYY。

保留原始 period 字段用于审计。

### 12.3 series_code 和 label

series_code 必须稳定包含：

- table_id；
- 官方 sv；
- 官方 freq；
- statistic；
- 维度代码；
- 必要的分类版本。

series_label 必须优先包含：

- 官方变量或项目；
- 统计量；
- 维度标签；
- 单位。

如果 API 只给 sv 代码：

- 先从 CSD 元数据或 CTT 表定义查找真实变量名；
- 找不到时显示 sv code + statistic + dimension；
- 不把单位单独当作标签；
- 不编造中文名称。

将以下概念拆开：

- construct label；
- statistic type；
- unit；
- transformation；
- dimension label。

例如：

    construct = Total retail sales
    statistic = Year-on-year change
    unit = %
    frequency = monthly

而不是：

    series_label = Year-on-year % change
    unit = Year-on-year % change

### 12.4 旧记录迁移

不删除 54,292 条 superseded。

对新 parser：

- 增加 parser_version；
- 旧 canonical key 标为 superseded；
- 新 key 幂等 upsert；
- 保存 raw_sha256；
- migration 可重复运行；
- 重跑后 active 唯一键仍为 0 重复；
- 不无限累积同一版本的重复 superseded。

### 12.5 curated 主指标映射

不要把每个 CSD series 都复制成顶层指标。

建立一个明确、人工审核的 curated mapping，优先覆盖：

#### GDP

- 名义 GDP；
- 实质 GDP；
- 实质 GDP 同比；
- 实质 GDP 经季调环比；
- 私人消费开支；
- 政府消费开支；
- 固定资本形成总额；
- 货物和服务进出口。

#### 消费与就业

- 零售销货价值；
- 零售销货价值同比；
- 零售销货数量指数；
- 综合 CPI；
- 综合 CPI 同比；
- 经季调失业率；
- 就业人数或劳动人口。

#### 外部经济

- 服务出口；
- 服务进口；
- 经常账户；
- 国际收支；
- 国际投资头寸；
- 外债。

#### 结构层

- 访港旅客；
- 人口；
- 净迁移，如官方表稳定。

每条 curated mapping 必须记录：

- table_id；
- series_code 条件；
- 官方字段；
- frequency；
- unit；
- seasonal adjustment；
- price basis；
- source URL；
- mapping version；
- 选择理由。

不确定的 series 不进入主图，只留在细表 explorer。

### 12.6 CSD API

增加或完善独立细表端点，支持：

- table_id；
- series_code；
- frequency；
- statistic；
- dimensions；
- start；
- end；
- latest；
- limit；
- cursor 或分页；
- format=csv。

主 /api/hong-kong-macro/data 不再无条件返回 2,000 条 preview。

### 12.7 页面

经济页至少真实绘制：

- 一条有充分历史的实质 GDP 指标；
- 一条 CPI 或零售指标；
- 一条失业率；
- 一条消费或固定资本形成；
- 一条访港旅客或服务贸易，如语义验证通过。

CSD 细表 explorer 可以：

- 选表；
- 选 series；
- 选 statistic；
- 选维度；
- 看覆盖、单位和来源；
- 导出当前筛选。

不能只显示“85,449 条”作为完成。

### 12.8 测试要求

新增：

1. freq=H -> semiannual；
2. 202506 H -> 2025-H1；
3. 202512 H -> 2025-H2；
4. Q 期间规范化；
5. Y 期间规范化；
6. unknown freq 不回退 annual；
7. series_label 不等于纯单位；
8. svDesc 为同比时 unit 为 %、statistic 为 yoy；
9. 两个相同 sv 但不同 statistic 不冲突；
10. 维度不同不冲突；
11. 重跑 parser 不产生 active duplicate；
12. curated mapping 命中正确官方 series；
13. 未审核 series 不进入顶层；
14. CSD endpoint 分页和筛选正确；
15. 主 payload 不再携带无用大 preview。

### 12.9 Phase 6 硬门禁

- H 不再被标成 annual；
- period 格式统一；
- 核心 series label 可解释；
- curated 经济指标进入主 API；
- 页面绘制真实 CSD 历史，而非只显示表行数；
- 细表仍保留原始维度和 hash；
- active duplicate 为 0；
- 目标测试通过。

---

## 十三、Phase 7：P1-D 页面筛选、图表、来源和浏览器体验

### 13.1 设计边界

- 延续现有暗色研究工作台；
- 不另起一套设计系统；
- 复用研究导航、颜色变量、卡片和移动断点；
- 香港和内地使用稳定、可区分颜色；
- 不只靠红绿表达状态；
- 保持 1440px 和 390px 响应式。

### 13.2 顶部信息

顶部至少显示：

- 香港宏观；
- 中国的对外窗口定位；
- jurisdiction=HK；
- 数据状态 ok、partial、stale 或 empty；
- 最后成功更新时间；
- 最新月度参考期；
- 最新季度参考期；
- 来源成功数 / 总数；
- active 指标数；
- 更新任务状态；
- 当前访问模式 manage 或 read_only；
- CSV 导出；
- 来源与方法入口。

远程 read_only 时：

- 更新按钮禁用；
- 保存 vintage 禁用；
- 显示只读说明；
- 不等用户点击后才报 403。

### 13.3 全局筛选

增加：

- 开始期；
- 结束期；
- 指标；
- transform；
- index100 基期；
- 来源；
- 图例选择；
- 重置筛选。

筛选状态与：

- API；
- 图表；
- 卡片；
- CSV；
- URL query 或可复现页面状态

保持一致。

### 13.4 卡片

总览使用 5 至 7 张有数据卡片，不用空卡：

- 私人住宅价格指数与同比；
- 住宅买卖宗数与同比；
- 实质 GDP 同比；
- 转口金额与占比；
- 香港外币储备；
- 3 个月 HIBOR；
- 中国 SAFE 外储作为联动卡。

每张卡显示：

- 值；
- 单位；
- 参考期；
- status；
- 同比或变化定义；
- source；
- 是否 derived；
- freshness。

### 13.5 图表交互

普通图表至少支持：

- hover 或 keyboard tooltip；
- tooltip 显示 period、value、unit、status、source、release/retrieved；
- 图例点击显隐；
- 当前可见序列不参与隐藏后的 y 轴计算；
- 时间范围选择；
- 无数据明确状态；
- partial 或 stale 状态；
- 原始、派生、暂定、修订视觉区分；
- 来源按钮或抽屉；
- 图表标题、单位、首末期和来源可读。

不要继续只用静态 polyline 加首末期文本充当完整交互图。

如果项目已有图表库或组件，优先复用；没有时可增量增强 SVG，不要引入重量级依赖而没有必要。

### 13.6 来源抽屉

逐图或逐序列显示：

- 中文名；
- 英文名；
- 定义；
- source institution；
- 官方 URL；
- table；
- frequency；
- unit；
- currency；
- seasonal adjustment；
- price basis；
- first/last period；
- release date；
- retrieved_at；
- status；
- footnote；
- formula；
- raw hash 安全摘要。

### 13.7 Trade Top N

来源地、目的地和 SITC2 Top N：

- 使用横向条形图；
- 显示最新月份；
- 显示金额单位；
- 支持 Top 5、10、20；
- 支持 origin、consignment、destination 明确定义；
- 不把来源地和寄运地混为一谈；
- 完整历史仍通过独立端点和 CSV 获取。

### 13.8 CSD 页面

不要只显示表号统计。

至少提供：

- curated 核心经济图；
- 细表 explorer；
- 表号、series、statistic、维度筛选；
- 当前筛选 CSV；
- 单位与脚注；
- 原始频率；
- 不进行跨频插值。

### 13.9 lead-lag 页面

保留：

- 香港指标；
- 内地指标；
- transform；
- min overlap；
- 符号说明；
- 描述性、非因果警告；
- 保存有效 vintage。

新增或完善：

1. 两条标准化共同样本时间线；
2. -24 至 +24 的相关曲线；
3. 以 lag=0 为中心的零线；
4. 正 lag 和负 lag 清晰标注；
5. 60 月滚动最佳 lag 点线图；
6. 120 月滚动最佳 lag 点线图；
7. 每个窗口 n_obs；
8. 不稳定方向警告；
9. 完整表格放在可展开区域，兼顾可访问性；
10. 无效配对显示 no data 或 insufficient sample；
11. 无效配对不开放保存。

“全样本相关曲线”不能继续只有 49 行长表。

“滚动窗口稳定性”不能继续只有最佳 lag 表。

### 13.10 传导地图

总览可增加小型传导地图：

    香港住房
      -> 银行按揭与金融条件
      -> 居民财富和消费

    内地生产与出口
      -> 香港转口
      -> 港口、贸易融资和服务业

    美元利率
      -> HIBOR 与港元金融条件
      -> 香港资产价格
      -> 与内地金融条件平行比较

它是叙事导航，不是因果估计。

### 13.11 更新状态

更新按钮：

- 本机 manage 才可用；
- 显示 queued、running、completed、partial、failed；
- 轮询 /api/jobs 或项目已有任务状态；
- 防止重复提交；
- 显示每个 source 的结果；
- 不在任务刚提交 1.2 秒后无条件当成完成；
- 刷新失败保留旧数据并显示 cached。

### 13.12 Phase 7 硬门禁

- 时间筛选可用；
- 转换按指标约束；
- tooltip 可用；
- 图例可显隐；
- 来源可逐序列查看；
- CSV 与当前筛选一致；
- CSD 不再只有行数；
- lead-lag 有真实相关曲线和滚动图；
- 无数据指标不出现空白图；
- 1440px 正常；
- 390px 无横向溢出；
- 控制台无关键错误或警告；
- 网络无 404 或 schema 错误；
- read_only 按钮状态正确。

---

## 十四、Phase 8：增强 lead-lag vintage 可复现性

### 14.1 当前边界

已有：

- 显式 POST 保存；
- GET 计算只读；
- snapshot_id；
- pair_code；
- 49 个全样本 lag；
- rolling rows；
- computed_at。

缺少：

- 输入香港序列 hash；
- 输入内地序列 hash；
- 输入首末期；
- 输入有效样本数；
- source/vintage 标识；
- parser_version；
- computation_version；
- transform 详细参数；
- lag 范围；
- rolling 窗口规格；
- 代码版本或 git commit，在工作区可合理取得时；
- 数据修订前后对比。

### 14.2 增量增强

不 drop 现有表。

可以新增 snapshot metadata 表，或兼容 ALTER：

- snapshot_id；
- pair_code；
- hk_indicator_code；
- mainland_indicator_code；
- hk_input_hash；
- mainland_input_hash；
- hk_start；
- hk_end；
- mainland_start；
- mainland_end；
- hk_n_obs；
- mainland_n_obs；
- transform；
- min_overlap；
- lag_min；
- lag_max；
- rolling_windows_json；
- source_vintages_json；
- parser_versions_json；
- computation_version；
- code_revision；
- computed_at；
- note。

输入 hash 应根据实际用于计算的规范 period/value/status 序列确定，排序稳定。

### 14.3 保存与读取

- 保存前通过 Phase 2 有效性门禁；
- transaction 同时写 metadata 和 rows；
- 失败不产生半个 snapshot；
- saved endpoint 返回 metadata 摘要；
- 页面可选择一个 snapshot 查看；
- 不自动覆盖同 snapshot；
- 对相同输入和参数可标记 duplicate candidate，但不要静默丢弃。

### 14.4 本轮不自动新增调度

不要在本轮无条件实现自动批量 vintage 回测调度。

原因：

- 配对集合尚需研究定义；
- 保存频率尚需定义；
- 多重比较和修订窗口尚需定义；
- 自动任务可能快速膨胀数据库。

只需：

- 让单次 snapshot 真正可复现；
- 在状态文档保留“自动批量调度未完成”；
- 给出未来所需设计问题。

### 14.5 Phase 8 硬门禁

- 无效结果不能保存；
- 新 snapshot 有输入 hash 和参数；
- 写入事务完整；
- saved endpoint 能还原定义；
- 老 snapshot 仍可读取；
- GET 仍不写；
- 自动批量调度明确留在 backlog。

---

## 十五、测试策略

### 15.1 环境

优先：

    PYTHONIOENCODING=utf-8 python.exe -X utf8

不要因为 WSL python3 缺少项目依赖就把环境问题报成代码失败。

### 15.2 目标测试

至少覆盖：

- SAFE 真实无标签黄金数量 HTML；
- SAFE 2018—2026 回填；
- SAFE 与 PBoC 边界；
- lead-lag 空序列；
- lead-lag 样本不足；
- lead-lag 符号；
- lag=0 不属于香港领先；
- 无效 snapshot 拒绝；
- GET 不写；
- API start/end/group/indicator/source；
- CSV 同筛选；
- 默认不含 superseded；
- transform 元数据约束；
- mixed-frequency period parser；
- latest period；
- CSD H 频率；
- CSD label 和 unit 分离；
- CSD curated mapping；
- RVD 历史频率；
- Land Registry 历史回填；
- source metadata；
- stale/partial；
- remote write protection；
- 页面 no data、partial、stale；
- 导航和城市边界。

### 15.3 不要只做字符串测试

当前部分页面契约测试只是：

- 读取 HTML；
- 断言 URL 字符串存在；
- 读取 server.py；
- 断言路由字符串存在。

保留这些轻量测试，但必须补：

- 实际函数输出；
- 实际 HTTP；
- 实际 CSV；
- 实际 SQLite 前后变化；
- Playwright 交互。

### 15.4 推荐测试命令

先目标：

    PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest \
      tests.test_hong_kong_macro_service \
      tests.test_china_external_service \
      tests.test_research_navigation -v

再按新增测试模块运行。

最后全量：

    PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest discover -s tests -q

语法：

    PYTHONIOENCODING=utf-8 python.exe -X utf8 -m py_compile \
      server.py \
      services/hong_kong_macro_service.py \
      services/china_external_service.py \
      services/china_macro_dashboard_service.py

格式：

    git diff --check

### 15.5 数据库核对

用 query_only 检查：

- PRAGMA quick_check；
- 重复键；
- NULL；
- superseded；
- source metadata；
- raw hash；
- 各指标覆盖；
- SAFE 七条序列；
- 五个 0 条指标状态；
- CSD frequency；
- CSD label=unit；
- 恒等式；
- snapshot 行数。

不要只相信 debug API 自己的汇总。

### 15.6 API 验收

至少真实请求：

- GET /api/health；
- GET /api/jobs；
- GET /api/hong-kong-macro/data；
- 带 start/end/indicators 的 data；
- GET /api/hong-kong-macro/debug；
- GET /api/hong-kong-macro/export.csv；
- 带筛选的 export.csv；
- GET trade-dimensions；
- GET lead-lag 默认配对；
- GET lead-lag 空指标；
- GET saved；
- GET /api/china-macro/data。

核对：

- HTTP 状态；
- Content-Type；
- Content-Disposition；
- 字节数；
- CSV 行数；
- JSON 行数；
- 筛选是否真实生效；
- GET 是否写数据库。

### 15.7 远程只读

从非 loopback 地址验证：

- /api/health 显示 read_only；
- POST update 返回 403；
- POST save 返回 403；
- GET data 正常。

使用安全、无副作用的请求。不要为了测试远程写保护真的触发更新。

---

## 十六、真实浏览器验收

使用 Playwright，并遵守项目可用 skill 的浏览器流程。

### 16.1 桌面 1440px

验证：

- 页面标题；
- 独立香港定位；
- 6 个页签；
- 5—7 个卡片；
- 时间筛选；
- transform；
- tooltip；
- 图例；
- 来源抽屉；
- CSV；
- update 状态；
- 住房；
- 经济；
- 转口；
- 储备金融；
- 中国联动；
- CSD explorer；
- no data；
- stale 或 partial；
- console；
- network。

### 16.2 窄屏 390px

验证：

- document scrollWidth 等于 clientWidth；
- 导航可用；
- 筛选控件不溢出；
- 下拉框不超宽；
- tooltip 可触达；
- 来源抽屉可滚动；
- lead-lag 图不被压扁到不可读；
- 49 行表格放在可控滚动或展开区域；
- 没有按钮被截断；
- 没有横向页面溢出。

### 16.3 lead-lag 交互

实际操作：

1. 默认配对；
2. 计算；
3. 检查 49 lag；
4. 检查 correlation curve；
5. 检查 rolling chart；
6. 检查 k>0 说明；
7. 检查 best_hong_kong_lead 不为 0；
8. 选择样本不足指标；
9. 确认显示 insufficient；
10. 确认保存按钮禁用；
11. 回到有效配对；
12. 仅在本机明确需要验收保存时保存一个测试 snapshot，并记录如何清理；若不需要写入，验证函数和按钮即可。

不要为了验收污染正式快照表。

### 16.4 保存证据

关键截图放到现有 gitignored 浏览器输出目录。

不要无必要把大截图提交进 Git。

记录：

- viewport；
- 页面 URL；
- console 数；
- network 失败数；
- overflow 数；
- 关键交互结果。

---

## 十七、状态文档、README 与 changelog

更新：

- docs/hong_kong_macro_STATUS_2026-08-11.md，或新建实际日期的状态文件；
- docs/hong_kong_macro_P1_AUDIT_2026-08-12.md，追加修复结果或新建修复审计；
- README.md；
- projects/README.md；
- projects/china_macro/README.md；
- projects/registry.json，如路由或说明改变。

状态文档必须按来源到浏览器阶段写，不得只列代码文件。

至少记录：

- 修复日期；
- 修复前后行数；
- SAFE 黄金数量覆盖；
- lead-lag 门禁；
- CSV 筛选；
- metadata 完整度；
- RVD 和 Land Registry 历史；
- CSD semantic mapping；
- 页面功能；
- 目标测试；
- 全量测试；
- 浏览器；
- 未完成；
- 外部阻断；
- 文件列表。

自动批量 vintage 调度继续列为 backlog，除非用户另行授权和定义。

---

## 十八、最终完成门禁

只有以下全部满足，才可称本轮修复完成：

### 18.1 P0

- SAFE 黄金数量到 2026-07；
- 2026-07 为 7608 万盎司；
- 空 lead-lag 不 success；
- 无效结果不能保存；
- lag=0 不属于香港领先；
- CSV 默认不含 superseded 空值；
- CSV 支持并执行当前筛选；
- JSON 与 CSV 同筛选一致。

### 18.2 数据

- 42 个 raw hash 继续一致；
- 主、贸易、CSD active 重复为 0；
- 恒等式继续通过；
- source metadata 不再关键字段全空；
- 核心 observation 有来源、单位、频率、抓取时间和状态；
- release_date 未提供时明确缺失，不伪造；
- latest period 不再字符串误判；
- stale/partial 可表达；
- 五个无观察指标有明确状态。

### 18.3 历史

- RVD 1979 起完整历史频率已处理或解释；
- Land Registry 2002 起已回填或有阻断证据；
- HKMA 短 summary 不再称为完整历史；
- CSD 为经济历史提供可解释的 curated 指标。

### 18.4 CSD

- H 正确映射 semiannual；
- 期间规范统一；
- 主要 label 不再只是单位；
- 主 API 有 curated CSD 指标；
- 页面有真实 CSD 图；
- 细表有筛选端点；
- 主 payload 不再带无用大 preview。

### 18.5 页面

- 6 个页签；
- 时间筛选；
- 指标约束转换；
- tooltip；
- 图例显隐；
- 来源抽屉；
- 当前筛选 CSV；
- correlation curve；
- rolling stability chart；
- no data、partial、stale；
- 1440px；
- 390px；
- 无横向溢出；
- console 无关键错误；
- network 无关键失败；
- 远程只读按钮正确。

### 18.6 测试与文档

- 目标测试通过；
- 全量测试不低于修复前 542 项，且无新增失败；
- py_compile 通过；
- git diff --check 通过；
- debug 与独立 SQL 结果一致；
- README 和状态文档更新；
- 未完成项如实保留。

---

## 十九、仍允许明确留在 backlog 的内容

以下不阻挡本轮完成，但必须明确未实施：

- 自动批量 lead-lag vintage 回测调度；
- 领先滞后的稳健统计显著性和多重比较校正；
- 因果识别；
- 正式预测模型；
- 高频 nowcast；
- 香港—内地—美国三方金融条件模型；
- 事件注释系统；
- 完整研究 notebook；
- 港口、航空货运和酒店等新增专题；
- 市级商品房销售面积或销售额官方月度流量。

不要用空卡片表示这些已经完成。

---

## 二十、最终汇报格式

最终回复以结果开头，不要先叙述过程。

按以下结构：

### 1. 最终结论

- 完成；
- 部分完成；
- 被阻断。

说明为什么。

### 2. 已修复

按 Phase 列出：

- 问题；
- 根因；
- 修改；
- 验证证据。

### 3. 数据前后对比

表格至少包含：

- 指标或表；
- 修复前；
- 修复后；
- 首期；
- 末期；
- 状态。

### 4. SAFE

单列：

- 外汇储备；
- 黄金美元价值；
- 黄金数量；
- SDR；
- IMF；
- 其他；
- 总额；
- 与 PBoC 区分。

### 5. lead-lag

单列：

- 空样本门禁；
- 保存门禁；
- lag 符号；
- 默认结果；
- rolling；
- vintage metadata；
- 未实现的自动调度。

### 6. API 与 CSV

列出：

- 新参数；
- 默认 active 规则；
- superseded 规则；
- 同筛选行数；
- Content-Type 和文件名。

### 7. 页面与浏览器

列出：

- 1440px；
- 390px；
- overflow；
- console；
- network；
- 交互。

### 8. 测试

给出真实命令和真实结果：

- 目标测试数；
- 全量测试数；
- py_compile；
- git diff --check。

### 9. 文件

列出所有修改和新增文件。

### 10. 未完成

只列真实未完成，不把失败写成完成。

如果某个官方源失败，必须给出：

- 官方 URL；
- 探针时间；
- HTTP 或解析错误；
- raw 是否保存；
- 数据是否入库；
- 旧数据是否保留；
- 下一步。

---

## 二十一、执行时的最后提醒

- 先侦察，后修改。
- 最小安全修复优先。
- 不破坏已通过的 542 项基线。
- 不把香港并入城市。
- 不把 SAFE 与 PBoC 混用。
- 不把 search snippet 当数据。
- 不把来源 success 当历史完整。
- 不把 85,449 行当语义完成。
- 不把空相关曲线保存成 vintage。
- 不把 lag=0 称为香港领先。
- 不把 superseded 空值默认导出。
- 不把低频历史伪造成月频。
- 不把抓取日期伪造成发布日期。
- 不把相关当因果或预测。
- 不删除用户已有工作。
- 不提交 Git，除非用户另行要求。

现在开始：先完成 Phase 0 的只读侦察和修复前基线，然后按 Phase 1 至 Phase 9 逐层实施与验证。
