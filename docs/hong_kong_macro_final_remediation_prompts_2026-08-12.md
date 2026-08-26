# 香港宏观模块最终修复：新窗口执行提示词

日期：2026-08-12

项目：`/mnt/d/claude`

数据库：`/mnt/d/claude/pboc_data.db`

模块边界：香港宏观保持独立 `/hong-kong-macro`，作为中国对外窗口，不并入“城市经济”

用途：把本轮复核发现的未完成项交给另一个 Codex 窗口继续实现、迁移、验证和收口

---

## 怎么使用

推荐直接在新窗口粘贴下面的“启动提示词 A”。新窗口与当前窗口共享工作区，它会读取本文件中的完整任务书并按顺序执行。

如果希望降低单个窗口的工作量，则依次使用 B、C、D 三个阶段提示词。每一阶段都必须先读取本文件的“共同执行契约”和对应任务，不能只根据聊天摘要动手。

### 启动提示词 A：一次完成全部修复（推荐）

```text
请在 /mnt/d/claude 项目中继续完成香港宏观模块的最终修复。

第一步，请完整读取：
/mnt/d/claude/docs/hong_kong_macro_final_remediation_prompts_2026-08-12.md

然后严格执行其中的：
1. “共同执行契约”；
2. “Prompt A：全量最终修复任务书”；
3. “统一验收门禁”；
4. “最终交付格式”。

这不是只读审计，也不是只给建议。请在保留现有数据和用户改动的前提下，实施必要的增量代码、数据库迁移、语义测试、API/UI 修复和文档收口，并用真实证据逐层验证。不要因为现有测试为绿色就宣布完成。

不要提交、推送或创建 PR，除非我在这个新窗口明确授权。不要使用 git add .，不要清理或重置工作树。
```

### 启动提示词 B：只做 P0 数据语义修复

```text
请在 /mnt/d/claude 项目中执行香港宏观模块的第一阶段修复。

请先完整读取：
/mnt/d/claude/docs/hong_kong_macro_final_remediation_prompts_2026-08-12.md

严格遵守其中的“共同执行契约”，只实施“Prompt B：P0 数据语义修复”，并执行该阶段验收和适用的统一验收门禁。重点是 CSD 人口语义、SAFE 发布日期、HKMA 频率/期间、RVD 2026 年上半年落成量四项。

这不是方案讨论：请实施、迁移、测试、核对数据库与 API，并更新状态记录。不得提交或推送，不得破坏现有原始数据和用户改动。
```

### 启动提示词 C：只做完整性、复现性和 GET 只读性

```text
请在 /mnt/d/claude 项目中执行香港宏观模块的第二阶段修复。

请先完整读取：
/mnt/d/claude/docs/hong_kong_macro_final_remediation_prompts_2026-08-12.md

严格遵守其中的“共同执行契约”，先复核 Prompt B 的四项 P0 是否已经真实完成；若仍未完成，只记录阻塞，不擅自宣称已完成。随后实施“Prompt C：完整性、复现性与 GET 只读性”，并完成相应测试、数据库/API 验证和状态记录。

这不是只做测试补丁：身份等式必须有容差和失败状态，旧 lead-lag 结果必须诚实标注可复现性，mom/qoq 语义必须一致，debug GET 必须真正只读。不得提交或推送。
```

### 启动提示词 D：只做元数据、页面、性能、文档和交付收口

```text
请在 /mnt/d/claude 项目中执行香港宏观模块的第三阶段收口。

请先完整读取：
/mnt/d/claude/docs/hong_kong_macro_final_remediation_prompts_2026-08-12.md

严格遵守其中的“共同执行契约”，先核验 Prompt B 与 Prompt C 的完成证据，再实施“Prompt D：元数据、UI、可访问性、性能、文档与 Git 边界收口”。完成桌面和移动端真实浏览器验收、响应体性能测量、完整测试、状态文档及应跟踪文件清单。

不要点击生产数据库上的 lead-lag 保存按钮；不要提交、推送或创建 PR，除非我在这个窗口明确授权。不得使用 git add .。
```

---

# 共同执行契约

以下规则对 A、B、C、D 全部适用。

## 1. 任务定位

目标不是重新开发一个香港页面，而是在现有实现上完成语义修复和研究级验收。必须保留这些产品边界：

- 香港宏观是独立模块和独立路由 `/hong-kong-macro`。
- 香港是观察中国对外贸易、资金、金融和住房周期的“对外窗口”。
- 暂时不并入 `/city-economy`，也不得把香港数据写入内地城市表。
- 内地正式外汇储备继续使用 SAFE 官方储备资产口径；不得与人民银行资产负债表中的“外汇”、银行结售汇或跨境收付款混为一谈。
- 香港与内地房价的领先/滞后关系只能称为描述性历史关系；不得写成稳定预测规律或因果结论。

## 2. 开工前必须做的只读检查

修改前完整检查并记录：

1. `git status --short`、`git diff --stat`、相关文件的 tracked/untracked 状态。
2. 项目 `README`、相关 changelog/status、服务器路由、服务层、页面和测试。
3. 至少阅读：
   - `/mnt/d/claude/services/hong_kong_macro_service.py`
   - `/mnt/d/claude/services/china_external_service.py`
   - `/mnt/d/claude/server.py`
   - `/mnt/d/claude/static/hong_kong_macro.html`
   - `/mnt/d/claude/tests/test_hong_kong_macro_service.py`
   - `/mnt/d/claude/docs/hong_kong_macro_COMPLETENESS_AUDIT_2026-08-12.md`
   - `/mnt/d/claude/docs/hong_kong_macro_REPAIR_EXECUTION_2026-08-12.md`
   - `/mnt/d/claude/docs/hong_kong_macro_remediation_prompt_2026-08-12.md`
4. 数据库 schema、`PRAGMA user_version`、`PRAGMA quick_check`、WAL 状态、相关表行数和活动行定义。
5. 当前端口、进程、`/api/health`、日志和 watchdog 状态；服务异常时先诊断再决定是否启动或重启。

旧的 `COMPLETENESS_AUDIT` 与 `REPAIR_EXECUTION` 是历史执行记录，不是本轮的事实权威。若与真实代码、数据库或官方来源冲突，以当前证据为准，并在文档中明确“被后续审计纠正/取代”，不要删除历史证据。

## 3. 工作树和文件安全

- 当前工作树有大量用户自己的 tracked 修改和 untracked 文件。
- 不得使用 `git reset --hard`、`git checkout --`、`git clean`、递归删除或任何会丢失用户工作的命令。
- 不得覆盖、移动、重命名或删除现有原始数据、数据库、日志、输出或文档，除非用户明确要求。
- 使用 `apply_patch` 做人工代码和文档修改。
- 只做香港宏观和 SAFE 元数据修复所需的最小增量改动。
- 不得运行 `git add .`。
- 本任务默认不提交、不推送、不创建 PR；只有用户在执行窗口明确授权后才可以进入 Git 发布流程。
- 最终必须列出“本轮实际修改文件”和“仍需纳入版本控制的相关 untracked 文件”，不能用笼统的“改了若干文件”。

## 4. 数据安全和迁移规则

- 原始下载文件必须保留，只能新增，不得覆写。
- 派生/修正记录与原始记录分离；必须保留来源 URL、原始哈希、解析器版本、抓取时间和状态。
- 生产数据库发生任何数据迁移前，先创建一致性备份：识别 `.db`、`-wal`、`-shm`，使用 SQLite online backup 或等价一致性方法，不得只在非空 WAL 情况下裸复制单个 `.db`。
- 备份后运行 `PRAGMA quick_check`；迁移后再次运行。
- 使用可重复、幂等的增量迁移。禁止先删整表再重建来掩盖错误。
- 对错误活动行，优先插入规范的新行并把旧行标记为 `superseded`，写明原因、修复版本和时间。
- 若新增 schema 字段，必须做到老数据库可迁移、新数据库可直接创建、重复启动不重复迁移，并在需要时有意义地提升 `PRAGMA user_version`。
- 不得篡改官方总量来满足身份等式；官方发布值、派生值和修订值必须可区分。

## 5. 官方来源和联网规则

本任务涉及会更新的官方数据和口径，实施时必须浏览并优先引用官方一手来源。禁止仅依赖搜索摘要、二手转载或 MacroMicro 图表作为生产数据。

优先官方来源：

- 香港政府统计处 C&SD / Web Tables / Trade-IDDS
- 香港差饷物业估价署 RVD
- 香港土地注册处 Land Registry
- 香港金融管理局 HKMA API/统计月报
- 国家外汇管理局 SAFE

SAFE 本轮至少核对：

- 官方栏目：`https://www.safe.gov.cn/safe/whcb/`
- 2026 官方储备资产表：`https://www.safe.gov.cn/safe/2026/0206/27116.html`

联网更新应低频、定向、可审计：

- 先检查已有 raw 文件能否完成修复。
- 只有确有必要时才发起目标明确的官方请求。
- 请求前记录来源、目的、预期输入输出和大致规模。
- 保存真实响应和哈希，检查 HTTP 状态、内容长度、文件签名/格式及实际记录数。
- 遇到验证码、验证页、403/429 或登录墙时停止绕过，记录失败类型，不得伪造或补写数据。
- “找到来源”“能访问”“已下载”“已解析”“已入库”“API 可用”“页面可用”是不同阶段，必须分别报告。

## 6. 测试哲学

- 不能只做路由存在、字符串存在或 mock 返回 200 的测试。
- 每个修复至少有一个语义回归测试，使用接近真实官方结构的 fixture。
- 测试必须能在修复前失败、修复后通过，并断言数据含义、单位、频率、期间和状态。
- 不得用不符合真实来源语义的假 fixture 把测试跑绿。
- 对生产数据的验证必须同时使用 SQL、服务函数/API 和页面呈现，不得只检查其中一层。
- 所有“零错误”结论都要给出所用命令、计数和适用范围。

## 7. 服务运行规则

若端口 5001 未运行或页面无法打开：

1. 先检查监听端口、相关 Python 进程、`/api/health`、watchdog 和日志。
2. 不要在不了解现有进程的情况下重复拉起多个服务器。
3. 确需启动时，关闭本任务无关的自动任务，避免浏览器验收触发其他模块更新。可使用项目已经支持的环境变量，例如：

```bash
PBOC_AUTO=0 ASTAR_AUTO=0 FISCAL_AUTO=0 RATES_AUTO=0 BACKUP_AUTO=0 python.exe -X utf8 server.py
```

启动参数以项目真实实现为准，先查代码，不要凭空添加环境变量。

Windows 项目 Python 优先：

```bash
PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest tests.test_hong_kong_macro_service -v
PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest discover -s tests -q
```

只有确认依赖齐全时才用 WSL `python3` 代替。

## 8. 状态记录

每个阶段完成后更新或新增简短但可审计的状态文档，至少包含：

- 日期和执行环境；
- 修改目标；
- 修改文件；
- schema/数据迁移及备份位置；
- 官方来源和获取时间；
- 迁移前后计数；
- 测试命令与结果；
- API、页面和浏览器证据；
- 已完成、部分完成、未完成、阻塞四种状态；
- 已知限制和下一步。

不得把“已发现来源”写成“已接入”，不得把“单元测试通过”写成“浏览器验收完成”。

---

# 已确认的当前基线

以下是 2026-08-12 本轮复核得到的起始基线。新窗口必须重新验证，不能把这些数字机械当成修复后的验收目标；迁移后合理计数可能变化，但每个变化都要解释。

## 数据库和覆盖

- `PRAGMA quick_check = ok`。
- `PRAGMA user_version = 5`。
- `hong_kong_macro_observations` 总计 28,153 行。
- 主表活动且非 superseded 共 26,903 行：`official=26,456`、`official_revised=99`、`derived=348`。
- `hong_kong_macro_web_table_observations` 总计 175,055 行；活动 85,449；superseded 89,606。
- `hong_kong_macro_trade_dimensions` 共 29,862 行。
- 42/42 个来源的 raw 文件哈希与目录记录一致。
- 41 个来源 current；1 个来源 stale：`HK_CSD_WEB_650-80001`，最新参考期 2026-05。
- 主表、CSD Web Table 和贸易维度表没有活动重复键。
- 内地城市相关四张表中没有香港行：
  - `city_indicator_observations`
  - `housing_city_observations`
  - `housing_national_observations`
  - `regional_fiscal_observations`

## API 和页面

- `/api/hong-kong-macro/data?dashboard=1` 当前约 148 条 series。
- meta 的 observation_count 约 28,364，其中包含 10 条 curated CSD 映射。
- dashboard 实际序列化约 6,343 行，响应约 3.34 MB。
- 本地响应时间观测约 1.4—2.3 秒。
- 单指标过滤仍可能约 700 KB，因为附带完整 catalogs/summaries。
- lead-lag 默认返回 -24 到 +24 共 49 个 lag；滚动窗口结果约 17 个。
- 桌面和移动端目前没有全局横向溢出，浏览器控制台无错误或警告。
- 当前图表约有 445 个数据点可通过 Tab 聚焦，总可聚焦元素约 563 个，键盘负担过高。

## 已正确或基本正确的部分

- SAFE 官方数值已到 2026-07：
  - 外汇储备 34,187.76 亿美元；
  - 储备资产合计 37,916.02 亿美元；
  - 黄金数量 7,608 万盎司。
- SAFE 数值和黄金单位本身已经修正；本轮主要问题是 `release_date` 元数据。
- JSON/CSV 过滤计数基本一致。
- CSD、贸易维度和 lead-lag 端点可用。
- 29 个香港模块测试通过；全套 560 个测试通过。
- Python compile 和页面内联 JavaScript 语法检查通过。

“已有测试全绿”不能抵消下面已经确认的语义错误。

---

# Prompt A：全量最终修复任务书

请按 P0 → P1 → P2 顺序完成。任何 P0 未完成时，不得把整个模块标记为 research-ready。

## P0-1：纠正 CSD 人口指标的构念错误

### 已确认问题

- 官方 C&SD Table `110-01003` 是 `Population growth by component`，不是“按年龄和性别的人口”，也不是人口存量。
- `/mnt/d/claude/services/hong_kong_macro_service.py` 中 `CSD_WEB_TABLES['110-01003']` 当前错误命名为 `Population by age and sex`，约在第 166 行。
- curated mapping `HK_CSD_WEB_POPULATION_SEMIANNUAL` 当前使用：
  - `series_code='freq=H|sv=PG|stat=000'`
  - 名称“CSD 香港人口（半年）”
- 数据库中 2025-H2 的 `PG` 值约为 10.2；这显然是人口增长构件，不是约 750 万的人口存量。
- 页面 CSD explorer 也把表和该值错误展示为人口。

### 必须实施

1. 先用 C&SD 官方表说明和真实维度核对 `110-01003` 的构念、单位、统计项和 `PG` 含义。
2. 将现有 table title、series label、indicator name、category/description 和页面文字全部改为“人口增长/人口增长构成”的准确含义。
3. 不得在没有迁移说明的情况下，静默复用 `HK_CSD_WEB_POPULATION_SEMIANNUAL` 这个旧代码来表示不同构念。
4. 推荐做法：
   - 新增含义准确的新 indicator code，例如以 `POPULATION_GROWTH` 命名；
   - 将旧错误映射标记 deprecated，并迁移/标记旧活动行为 superseded；
   - API catalog 可临时保留兼容别名，但必须明确 deprecated，且不得继续把它显示为人口存量。
5. 如果产品仍需要“香港总人口存量”，再接入官方 Table `110-01001` 或 `110-01002`：
   - 必须先现场核对真实 table、维度、总人口统计项、单位和频率；
   - 不允许根据表号猜字段；
   - 若本轮无法可靠接入，就把“人口存量”明确列为未完成，不得用增长值替代。
6. 修复 CSD explorer、卡片、tooltip、CSV label 和文档中的错误名称。

### 必须新增的测试

- 使用真实形状的 `110-01003` fixture，断言它是 population growth，不是 population stock。
- 断言 `sv=PG|stat=000` 不会映射为“香港人口”存量。
- 对人口存量和人口增长设置不同的合理值域/单位语义检查；不得再用诸如 `Population=6800` 的虚构 PG fixture。
- 断言 deprecated 旧代码不会作为活动的错误构念重复出现。
- API 和 CSV 的 label、indicator code、unit 一致。

### 验收

- 页面上再也不能出现把 10.2 显示为“香港人口”的情况。
- `110-01003` 的 catalog title、API series metadata、CSV 和 UI 使用同一构念。
- 若新增人口存量，能提供官方表、series_code、最新值、单位和原始行证据；否则明确记为未接入。

## P0-2：纠正 SAFE `release_date` 推断

### 已确认问题

- `/mnt/d/claude/services/china_external_service.py` 的 `_safe_release_date` 当前从 URL 路径解析日期。
- 2026 年年度动态页 URL 是 `/safe/2026/0206/27116.html`，这个页面持续更新。
- SAFE 官方栏目显示该 2026 表在 2026-08-07 更新；URL 中的 2026-02-06 不是每个月观测的发布日期。
- 当前数据库因此把 2026 年每个月（包括 2026-07）的 `release_date` 都写成 2026-02-06。
- 官方数值正确，错误在发布元数据。

### 必须实施

1. 明确区分以下时间：
   - observation reference period；
   - URL/page creation date（如果保留）；
   - listing/page last updated date；
   - per-observation release date；
   - `retrieved_at`；
   - `vintage_date`。
2. 不得再把稳定年度动态页 URL 的路径日期批量写成每个月的发布日期。
3. 在没有每月独立发布日期证据时，安全默认是：
   - observation `release_date = NULL`；
   - 将页面/栏目最后更新时间存入来源或 vintage 元数据；
   - `release_date_not_provided=1` 或等价明确标记。
4. 如果能从 SAFE 官方历史页可靠获得每月实际发布日期，可以保存，但必须记录抓取逻辑和证据；不能从 URL 猜测。
5. 对现有错误行做幂等迁移/回填，保留原始 raw 文件和来源；不得重写观测值。
6. 页面和 debug 对“参考期”“页面更新时间”“抓取时间”“发布日期未知”使用不同标签。

### 必须新增的测试

- 动态年度页 URL 不会把全年每个月 stamp 成 URL 首次创建日。
- 2026-07 不得得到 2026-02-06 的 release_date。
- `retrieved_at` 不得冒充 release_date。
- 官方栏目 last update 和 observation release date 在 schema/API 中可区分。
- 对旧数据库执行迁移两次仍幂等。

### 验收

- 查询 2026 年 SAFE 月度行，不存在因该 URL 推断得到的统一 2026-02-06 活动 release_date。
- 2026-07 数值仍保持 34,187.76 亿美元，其他官方数值不变。
- 来源元数据显示 2026 表的官方最近更新时间或“未提供逐月发布日期”，不能含混。

## P0-3：修正 HKMA 频率和 period 格式

### 已确认问题

目前至少有 26 条活动行存在 frequency/period 不一致：

- `HK_HKMA_NOMINAL_GDP`：4 条季度值写成 `2025-06`、`2025-09`、`2025-12`、`2026-03`。
- `HK_HKMA_REAL_GDP`：同样 4 条。
- `HK_HKMA_CURRENT_ACCOUNT_BALANCE`：同样 4 条。
- `HK_HKMA_GOV_CONSOLIDATED_BALANCE`：14 条月度值（2025-05 至 2026-06），catalog 却标为 quarterly。
- 同一源中可能还有 `YYYY-00` 年度记录，不能与季度/月度活动序列混用。

### 必须实施

1. 逐字段核对 HKMA 官方 API/统计表的 frequency 和 period 语义。
2. GDP 和经常账户的季度末月份规范化：
   - `YYYY-03 → YYYY-Q1`
   - `YYYY-06 → YYYY-Q2`
   - `YYYY-09 → YYYY-Q3`
   - `YYYY-12 → YYYY-Q4`
3. `HK_HKMA_GOV_CONSOLIDATED_BALANCE` 若官方字段确为月度，则 catalog、indicator metadata、parser 和 UI 都改为 monthly，并保留 `YYYY-MM`。
4. `YYYY-00` 年度行：
   - 继续排除；或
   - 映射为独立 annual indicator code；
   - 不得混入 monthly/quarterly code。
5. 增量迁移现有错误活动行：插入规范行/upsert，旧行标记 superseded 并记录原因。
6. period normalization 必须集中、可测试，不能在 UI 临时替换字符串。

### 必须新增的测试

- 三个季度序列的 quarter-ending month 能准确转换为 `YYYY-Qn`。
- 非季度末月份不得被悄悄转换成季度。
- gov consolidated balance 维持月度 period/frequency。
- 年度 `YYYY-00` 不混入月/季序列。
- 迁移幂等且没有活动重复键。
- qoq 只比较真实相邻季度，不把相邻月份误当季度。

### 验收 SQL 目标

执行前先根据实际 schema 调整字段名，但必须得到等价证据：

```sql
SELECT indicator_code, period, frequency, value, data_status
FROM hong_kong_macro_observations
WHERE indicator_code IN (
  'HK_HKMA_NOMINAL_GDP',
  'HK_HKMA_REAL_GDP',
  'HK_HKMA_CURRENT_ACCOUNT_BALANCE',
  'HK_HKMA_GOV_CONSOLIDATED_BALANCE'
)
AND COALESCE(data_status, '') <> 'superseded'
ORDER BY indicator_code, period;
```

并证明所有活动行满足：

- monthly：`YYYY-MM`
- quarterly：`YYYY-Q1` 至 `YYYY-Q4`
- semiannual：`YYYY-H1` 或 `YYYY-H2`
- annual：`YYYY`

上述四个指标的活动 period/frequency 违规数必须为 0。

## P0-4：修正 RVD 2026 部分年度落成量

### 已确认问题

原始文件：

`/mnt/d/claude/data/hong_kong_macro_raw/HK_RVD_PRIVATE_STOCK_FLOW_20260812T022735353679.xls`

脚注明确写着：`# Provisional figures (up to 30.06.2026).`

当前 parser 把带 `#` 的 7,914 套落成量写为：

- period `2026`
- frequency `annual`
- data_status `official_revised`

这会让 API/UI 把 2026 上半年累计误解为完整 2026 年年度值。

### 必须实施

1. 读取真实 raw 文件、表头、脚注和行结构，保留 provisional 标志。
2. 不得把截至 2026-06-30 的部分年度数字表示为完整 annual 2026。
3. 推荐选择一种语义明确的方案：
   - 新建 YTD/截至期指标，period end 为 2026-06；或
   - 若官方定义允许，使用 `2026-H1` + semiannual；
   - 完整 annual 序列仍只到 2025。
4. 不得仅把 status 从 `official_revised` 改成 `provisional` 而继续保留 annual `2026`；period/frequency 也必须修正。
5. 旧错误行标记 superseded，新增规范活动行，保留脚注和原始哈希。

### 必须新增的测试

- 使用带 `#` 和 `up to 30.06.2026` 的真实形状 fixture。
- 7,914 不会成为 annual 2026 活动值。
- annual completions 的最新完整年份仍为 2025。
- partial-year 行保留 source period end、provisional 状态和脚注。
- 重复解析不会制造重复活动行。

### 验收

- 页面不能再把 7,914 标为“2026 年全年落成量”。
- API/CSV 能明确区分完整年度与截至 2026-06-30 的暂定累计。

## P1-1：重做身份等式检查状态和容差

### 已确认问题

`_identity_check` 当前只要有 residual 就返回 `status='ok'`，完全不看残差大小。

例如 SAFE 官方 2016-09 的组成项合计与官方总计存在约 1.45 亿美元残差，debug 仍显示 ok。土地注册处金额也可能因为组成项按百万港元发布而有 1 百万港元的舍入差；数量等式通常应精确。

### 必须实施

1. 为每条 identity 明确：
   - absolute tolerance；
   - 如需要，relative tolerance；
   - 单位；
   - 官方舍入规则；
   - pass/warning/fail 判定。
2. 状态至少支持：
   - `pass`
   - `warning`
   - `fail`
   - `insufficient_overlap`
   - `table_unavailable`
3. 输出至少包括：
   - checked_periods；
   - missing_periods；
   - max_abs_residual；
   - max_relative_residual（适用时）；
   - tolerance；
   - offending periods 和 residual；
   - source/derived 区分。
4. 贸易数量/金额、RVD/Land Registry、SAFE 分别配置，不能用一个随意的全局阈值。
5. 不得为了通过 identity 而覆盖官方总量。

### 测试和验收

- 构造超过容差的 residual，状态不能是 pass/ok。
- 构造容许舍入差，得到 warning 或 pass_within_tolerance，具体命名需统一。
- 无重叠数据返回 insufficient_overlap。
- 表缺失返回 table_unavailable。
- debug 页面显示阈值和违规期间，不再用含混的“ok”。

## P1-2：诚实处理旧 lead-lag 结果的复现性

### 已确认问题

- `hong_kong_macro_lead_lag_snapshots` 当前 0 行。
- `hong_kong_macro_lead_lag_results` 当前 980 行，属于两个旧 snapshot_id：
  - `29ff94ce2f1741a1b285da8ee21ccc2d`：490 行；
  - `d7e5286146ee4801a3e855c46264e546`：490 行。
- saved API 能列出两个结果组，但 `input_hash`、`computation_version`、source vintages 等为空。
- 新保存逻辑能为未来结果写完整 snapshot metadata；旧结果不能因此自动变成可复现快照。

### 必须实施

1. 先检查旧结果是否真的能从现有数据、参数和版本唯一重建。
2. 只有证据充分时才回填 metadata，并记录推导方法和迁移日志。
3. 不能可靠重建时，明确标记为 `legacy_unreproducible` 或等价状态。
4. saved list/detail API 和 UI 必须明确区分：
   - reproducible snapshot；
   - legacy result group；
   - metadata incomplete。
5. 不得删除旧 980 行来制造“干净状态”。
6. 只在临时数据库创建一个新 snapshot 做端到端测试；不要在生产数据库点击页面保存按钮或写入测试快照。

### 验收

最终库存必须诚实呈现为以下两种之一：

- 0 个完整可复现旧快照 + 2 个 legacy result groups；或
- 有审计证据支持的迁移快照 + 明确仍不可复现的旧组。

每个 reproducible snapshot 必须有 input hashes、时间范围、观察数、参数、computation version、parser/source vintage 信息。

## P1-3：统一 `difference`、`mom` 和 `qoq` 语义

### 已确认问题

当前 `_transform_rows` 把 `difference`、`diff`、`mom`、`qoq` 全部计算为 `x[t]-x[t-1]`。

UI 把 mom 写成“环比差分”，把 qoq 写成“环比”；现有测试甚至把季度 100→110 的 qoq 断言为 10。这与常见“环比百分比变化”含义不一致。

### 必须实施

推荐语义：

- `difference` / `diff`：绝对差 `x_t - x_{t-1}`；
- `mom`：月度百分比变化 `(x_t/x_{t-1}-1)*100`；
- `qoq`：季度百分比变化 `(x_t/x_{t-1}-1)*100`；
- `qoq_sa` 仅用于有官方季调基础的序列，不得把未季调数据包装成季调环比。

如果出于兼容性决定保留绝对差，则必须把 API/UI 名称改为 `monthly_difference` / `quarterly_difference`，移除误导性的 mom/qoq。无论选择哪一种，都要记录兼容性决策和迁移影响。

还必须明确：

- 缺少相邻期时返回 null，不插值；
- 分母为 0 时返回 null 并说明原因；
- 输出 unit 是 `%`、百分点还是原单位；
- 只使用同 frequency 的规范相邻 period；
- formula 同时进入 API 和 CSV 元数据。

### 测试和验收

- 月度 100→110 的 mom 按选定语义正确返回并带正确 unit/formula。
- 季度 100→110 的 qoq 不再由含混测试定义。
- 缺期、0 分母、跨年季度和半年度序列均有测试。
- UI 选项、API transform 参数、CSV、lead-lag 参数和文档一致。

## P1-4：让 debug GET 真正只读

### 已确认问题

`/api/hong-kong-macro/debug` 调用 `build_hong_kong_macro_debug`，后者调用：

`ensure_hong_kong_macro_tables(conn, refresh_metadata=True)`

即使数据库已初始化，GET 也会做 DML，改变数据库文件哈希或 sources 的更新时间。主 data GET 和 lead-lag GET 在 WAL checkpoint 后基本稳定，但 debug GET 不只读。

### 必须实施

1. GET debug 只查询，不执行 schema migration、metadata refresh、upsert 或 update。
2. schema 初始化在应用启动/显式迁移路径完成。
3. 如确需刷新 metadata，移动到显式 POST update/maintenance 路由，遵守写权限和审计日志。
4. debug 中可以在内存计算 freshness/identity，不把结果写回数据库。
5. 对未初始化数据库，GET 应返回明确的 `not_initialized/table_unavailable`，而不是悄悄建表。

### 测试和验收

在一个已初始化、无未 checkpoint WAL 的临时数据库上，重复调用：

- main data GET builder；
- debug GET builder；
- lead-lag GET builder；

前后对比：

- 数据库文件 SHA-256；
- 相关表行数；
- `hong_kong_macro_sources.updated_at`；
- `PRAGMA data_version` 或等价写入证据。

上述 GET 不得产生持久化变化。POST update/save 不在这个只读约束内。

## P2-1：补齐来源和 CSD 元数据

### 已确认问题

- 42 个来源的 `expected_release_lag_days` 目前全部 NULL。
- 5,349 条活动 CSD 行的 `construct_label` 为空。
- 贸易 destination 来源 URL 有拼写错误：
  - 当前：`tradeidds.censtat.gov.hk`
  - 正确域名应核为：`tradeidds.censtatd.gov.hk`

### 必须实施

1. `expected_release_lag_days` 只在官方日历/发布说明有证据时填值。
2. 没有官方证据时保留 NULL，并使用 `release_date_not_provided`、reason 或等价字段明确“未提供/未核实”，不得编造。
3. `construct_label` 使用已验证的 CSD `sv` 字典或官方维度映射补齐；未知值保持 unknown + 原始代码，不能靠自然语言猜测。
4. 修复 Trade-IDDS URL，并测试链接域名。
5. API/debug 应能区分：missing、not provided、not applicable、not yet verified。

### 验收

- 所有活动 CSD 行要么有经验证的 construct_label，要么有结构化 missing_reason；不能悄悄留空。
- 来源 freshness/lag 元数据有证据引用或明确空缺原因。
- 页面和 CSV 不把未知标签伪装成已知构念。

## P2-2：降低 dashboard 响应体和页面初载开销

### 已确认问题

- dashboard 响应约 3.34 MB、6,343 行，本地约 1.4—2.3 秒。
- 单指标过滤仍约 700 KB，主要因为附带完整 catalog/summaries。
- 图表只显示最新 60 个 observation，但页面 status 显示全部 observation_count，披露不清楚。

### 必须实施

1. 用真实测量分解响应体：series rows、catalogs、source metadata、CSD catalog、summaries 各占多少。
2. 设计最小兼容改动，例如：
   - dashboard 仅返回首屏需要的数据；
   - catalog/CSD/来源元数据拆成按需 endpoint；
   - 支持 limit/pagination；
   - 单指标请求不重复携带无关大目录；
   - 明确 latest-N 与 total count。
3. 不得为减小响应而删除历史数据库记录。
4. UI 明确展示：数据库/筛选总观测数、当前图表绘制数、时间范围、是否截断。
5. 兼容现有 CSV 全量导出和筛选逻辑。

### 性能目标

优先目标：

- dashboard 初始 JSON < 1.5 MB；
- 本地 warm response < 1 秒；
- 单指标响应不携带无关全量 catalog。

如果在保持功能和兼容性的前提下无法达到，必须记录测试机器、命令、冷/热缓存、P50/多次测量、瓶颈和合理预算，不能虚报。

## P2-3：修复图表键盘焦点和完成浏览器验收

### 已确认问题

当前 overview 约 445 个图表数据点逐个可聚焦，总 focusable 元素约 563，键盘用户要按数百次 Tab。

### 必须实施

1. 不让每个 SVG/data point 默认成为独立 Tab stop。
2. 可选做法：
   - 每张图仅一个可聚焦容器；
   - roving tabindex；
   - 键盘方向键在点之间移动；
   - 视觉 tooltip 与屏幕阅读器摘要并存。
3. 保留数据可访问性：chart title、单位、时间范围、最新值和可下载数据。
4. 确保 focus visible、按钮 label、表单 label、颜色之外的状态提示、移动端触控大小。

### 真实浏览器验收矩阵

至少检查：

- desktop：1440×900 或 1440×1000；
- mobile：390×844；
- overview 和每个 group；
- 指标筛选、频率、transform、时间范围；
- CSV 链接随筛选变化；
- CSD table explorer；
- 贸易 Top N 和维度切换；
- 图例显示/隐藏；
- lead-lag 运行和滚动窗口；
- debug 展开；
- keyboard-only 主流程；
- 控制台 error/warning；
- 全局横向滚动和组件内滚动。

不得在生产数据库点击“保存当前结果（vintage）”。需要测试保存时使用临时数据库和测试服务器。

截图可保存到 `/mnt/d/claude/output/playwright/` 或独立审计输出目录，但不要未经授权把大量截图加入 Git。

## P2-4：文档和 Git 边界收口

### 必须实施

1. 新建本轮最终审计/执行状态文档，或在旧文档顶部加入 superseding note 并链接新审计。
2. 纠正旧文档中以下过早结论：
   - “模块全部完成/production-ready”；
   - `110-01003` 被称为人口存量；
   - SAFE release_date 已完整；
   - 2026 落成量为 annual；
   - 旧 lead-lag 是完整 vintage snapshot；
   - debug GET 只读；
   - identity checks 均 ok。
3. 不删除旧文档，以保留审计链；用日期、状态和替代文档说明修正。
4. 生成精确的相关文件清单，特别注意这些核心文件当前可能是 untracked：
   - `/mnt/d/claude/services/hong_kong_macro_service.py`
   - `/mnt/d/claude/static/hong_kong_macro.html`
   - `/mnt/d/claude/tests/test_hong_kong_macro_service.py`
   - `/mnt/d/claude/docs/` 下多份香港宏观文档
5. 只报告 Git 状态，不 stage/commit/push，除非用户明确授权。

---

# Prompt B：P0 数据语义修复

如果使用启动提示词 B，只执行下列内容：

1. 完成“共同执行契约”的开工检查、数据库一致性备份和基线记录。
2. 完整实施 P0-1 CSD 人口构念修复。
3. 完整实施 P0-2 SAFE release_date 修复。
4. 完整实施 P0-3 HKMA frequency/period 修复。
5. 完整实施 P0-4 RVD 2026 partial-year 修复。
6. 为四项都增加语义回归测试和幂等迁移测试。
7. 运行香港专项测试、相关 SAFE 测试和全套测试。
8. 用 SQL、API/CSV 和页面逐层验证。
9. 更新阶段状态文档，列明 P1/P2 仍未执行，不得把模块整体标为完成。

阶段 B 的硬门禁：

- 页面不再把 PG=10.2 当人口存量。
- 2026-07 SAFE 不再继承 URL 的 2026-02-06 发布日期。
- 四个 HKMA 指标活动 period/frequency 违规数为 0。
- RVD annual completions 最新完整年份为 2025，7,914 明确是截至 2026-06-30 的 provisional/partial-year 值。
- 四类旧错误行有可审计 superseded/migration 记录，没有活动重复键。
- `PRAGMA quick_check=ok`。

---

# Prompt C：完整性、复现性与 GET 只读性

如果使用启动提示词 C，只执行下列内容：

1. 先用 B 的硬门禁复核 P0；不接受只看测试名或旧文档。
2. 完整实施 P1-1 identity tolerance/status。
3. 完整实施 P1-2 legacy lead-lag reproducibility inventory。
4. 完整实施 P1-3 transform semantics。
5. 完整实施 P1-4 debug GET read purity。
6. 使用临时数据库验证 snapshot save；不得污染生产数据库。
7. 对 GET builder 做文件哈希、行数、updated_at 和写入行为比较。
8. 更新阶段状态文档，明确 P2 是否仍未执行。

阶段 C 的硬门禁：

- 超容差 residual 不可能显示 pass/ok。
- 两个旧 result group 的可复现性被诚实标注。
- mom/qoq/difference 的公式、单位、API、UI 和测试完全一致。
- debug/main/lead-lag GET 在初始化完成的临时数据库上不产生持久化写入。
- 所有生产历史行得到保留，没有为了测试删除旧结果。
- `PRAGMA quick_check=ok`。

---

# Prompt D：元数据、UI、可访问性、性能、文档与 Git 边界收口

如果使用启动提示词 D，只执行下列内容：

1. 复核 B/C 的硬门禁并记录证据。
2. 完整实施 P2-1 来源/CSD 元数据。
3. 完整实施 P2-2 dashboard 性能和截断披露。
4. 完整实施 P2-3 可访问性和浏览器验收。
5. 完整实施 P2-4 文档与 Git 文件清单。
6. 运行香港专项测试和全套测试。
7. 完成下面的统一验收门禁和最终交付格式。

阶段 D 的硬门禁：

- 未知 release lag/construct 不被伪造。
- Trade-IDDS 链接正确。
- 页面明确总观测数与实际绘图数。
- 图表不再制造数百个 Tab stop，同时保留可访问摘要。
- 桌面/移动无全局横向溢出，控制台 0 error；warning 必须逐条解释或修复。
- 响应体和耗时有可复现测量；达到目标或如实说明差距。
- 新审计替代旧的 false-complete 声明，但保留历史链。
- 只生成应跟踪文件清单，不擅自 stage/commit/push。

---

# 统一验收门禁

不论使用 A 还是分阶段执行，都要按适用范围完成。Prompt A 必须全部完成。

## 1. 静态检查

```bash
cd /mnt/d/claude
python.exe -X utf8 -m py_compile services/hong_kong_macro_service.py services/china_external_service.py server.py
```

使用项目现有 JS 语法检查方式验证 `/mnt/d/claude/static/hong_kong_macro.html` 内联脚本。不得只靠浏览器“看起来能打开”。

运行：

```bash
git diff --check
```

并检查所有新文件的换行、编码和意外绝对路径。

## 2. 专项测试

至少运行：

```bash
cd /mnt/d/claude
PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest tests.test_hong_kong_macro_service -v
```

如果 SAFE 测试位于其他模块，定位并一起运行。报告测试数和耗时，不要只说“passed”。

## 3. 全套回归

```bash
cd /mnt/d/claude
PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest discover -s tests -q
```

起始基线是 560 tests；增加测试后总数应合理上升。若因环境依赖跳过或失败，逐项报告，不能隐藏。

## 4. 数据库完整性

在生产库和迁移测试临时库上分别检查：

```sql
PRAGMA quick_check;
PRAGMA user_version;
PRAGMA journal_mode;
```

活动重复键目标为 0：

```sql
SELECT indicator_code, period, dimension_key, dimension_value, vintage_date, COUNT(*) AS n
FROM hong_kong_macro_observations
WHERE COALESCE(data_status, '') <> 'superseded'
GROUP BY indicator_code, period, dimension_key, dimension_value, vintage_date
HAVING COUNT(*) > 1;
```

```sql
SELECT table_id, period, series_code, COUNT(*) AS n
FROM hong_kong_macro_web_table_observations
WHERE COALESCE(data_status, '') <> 'superseded'
GROUP BY table_id, period, series_code
HAVING COUNT(*) > 1;
```

```sql
SELECT source_id, dimension_type, trade_type, period, dimension_code, statistic, COUNT(*) AS n
FROM hong_kong_macro_trade_dimensions
WHERE COALESCE(data_status, '') <> 'superseded'
GROUP BY source_id, dimension_type, trade_type, period, dimension_code, statistic
HAVING COUNT(*) > 1;
```

还要核对：

- source raw_sha256 与实际 raw 文件哈希；
- 迁移前后活动/ superseded 行数；
- 频率和 period 格式；
- CSD 构念映射；
- SAFE 日期字段；
- RVD full-year/partial-year；
- legacy snapshot inventory；
- identity failure/warning 期间。

## 5. 城市模块隔离

再次证明香港没有被写入以下内地城市表：

- `city_indicator_observations`
- `housing_city_observations`
- `housing_national_observations`
- `regional_fiscal_observations`

查询条件要覆盖 `city/name/jurisdiction/region/code` 等真实字段；先查看 schema，不能假设所有表都有同一字段。

## 6. API 验收

至少验证并记录 HTTP status、content type、响应大小、耗时、meta 和关键计数：

- `/api/hong-kong-macro/data?dashboard=1`
- `/api/hong-kong-macro/data` 的单指标/频率/transform/时间筛选
- `/api/hong-kong-macro/export.csv` 的同条件筛选
- `/api/hong-kong-macro/debug`
- `/api/hong-kong-macro/csd-web-table/{table_id}`
- `/api/hong-kong-macro/csd-web-table/{table_id}.csv`
- `/api/hong-kong-macro/trade-dimensions`
- `/api/hong-kong-macro/trade-dimensions.csv`
- `/api/hong-kong-macro/lead-lag`
- `/api/hong-kong-macro/lead-lag/saved`

验证 JSON 和 CSV 同筛选的 observation 数值/计数一致。确认错误参数得到清楚的 4xx，而不是 500 或静默回退。

## 7. GET 只读性

在临时初始化数据库上对 main/debug/lead-lag GET builder 或真实 HTTP GET 做调用前后比较。必须记录：

- db SHA-256；
- `-wal` 是否产生/增长；
- 表行数；
- source `updated_at`；
- 快照/结果表行数。

如果 SQLite 只因只读连接产生瞬态文件但无持久数据变化，要如实说明测试条件；不能只看主 `.db` hash 得出武断结论。

## 8. 真实浏览器验收

用 Playwright 或项目可用的真实浏览器工具打开 `/hong-kong-macro`，完成 P2-3 的矩阵。保存代表性截图和控制台记录。

特别核对页面文字：

- 香港是独立模块；
- 人口增长与人口存量不混淆；
- 2026 H1/YTD 落成不显示为全年；
- SAFE 参考期、页面更新时间、抓取时间和发布日期未知可区分；
- lead-lag 明示描述性、非因果、非稳定预测；
- latest 60 plotted 与 total observations 同时披露；
- legacy results 不显示为完整可复现 vintage。

## 9. 性能和可访问性证据

- 至少重复测量 3 次 dashboard JSON 大小和响应时间，区分 cold/warm 或说明无法区分。
- 记录初始 DOM/focusable 数量和修复后数量。
- 键盘从页头走到主要控制区，不应经过数百个数据点。
- 检查 390×844 和桌面视口的 `scrollWidth <= clientWidth`，若组件内有意滚动要单独说明。

## 10. 最终状态判定

使用以下严格定义：

- `complete`：代码、迁移、数据、API、页面、浏览器和文档证据齐全。
- `partial`：已经实施但某一层未验证或仍有已知缺陷。
- `blocked`：有明确外部阻塞，已经记录重现步骤和不绕过的原因。
- `not started`：未实施。

任何 P0 为 partial/blocked/not started，整个香港宏观模块只能标为 partial，不能标为 complete 或 research-ready。

---

# 最终交付格式

最终回答必须以结论开头，并包含以下内容：

## 1. 总结

- 最终状态：complete / partial / blocked。
- P0、P1、P2 各完成多少项。
- 是否达到 research-ready；若没有，最短缺口是什么。

## 2. 实际修改

逐文件列出：

- 绝对路径；
- 修改内容；
- 为什么需要；
- 是否 tracked/untracked。

## 3. 数据和迁移

- 备份绝对路径和校验结果；
- schema/user_version 变化；
- 活动、superseded、derived 行数变化；
- 四项 P0 的迁移结果；
- raw 数据是否新增以及哈希。

## 4. 来源验证梯度

按来源分别报告：

`source found → access verified → downloaded → parsed → stored → API → page → browser accepted`

没有达到的阶段写明原因，不得跳级。

## 5. 测试和验收

- 精确命令；
- 专项测试数量；
- 全套测试数量；
- quick_check；
- 重复键；
- GET 只读；
- API/CSV；
- 浏览器视口、控制台、溢出；
- 性能和 focusable 计数。

## 6. 尚未完成

按严重性列出剩余项、影响、原因和建议下一步。没有证据时不要写“无”。

## 7. Git 状态

- 当前分支；
- 精确相关 dirty/untracked 文件；
- 是否 stage、commit、push、PR（默认均为否）；
- 如用户后续授权发布，建议的最小 stage 清单。

最终回答要提供可点击的绝对文件链接，尤其是新状态报告、核心服务、页面和测试。不要只给相对路径。

---

# 明确禁止的完成方式

- 只改 label，不迁移错误数据。
- 只补 mock 测试，不验证真实 raw/数据库/API。
- 用 URL 路径日期冒充每月 SAFE 发布日期。
- 把 2026 H1/YTD 落成量继续存成 annual 2026。
- 把 residual 非空就判定 identity ok。
- 给旧 lead-lag 结果虚构 input hash/vintage。
- 把 mom/qoq 继续保持含混而只改中文说明。
- GET debug 内部继续 refresh/upsert。
- 为补齐元数据而猜 release lag 或 construct label。
- 删除历史行、raw 或旧审计以掩盖错误。
- 只看单元测试绿色就宣布 production-ready。
- 未经授权执行 `git add .`、commit、push、PR、reset 或 clean。
