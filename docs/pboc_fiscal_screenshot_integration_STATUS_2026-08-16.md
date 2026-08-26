# 截图指标接入与历史联动状态（2026-08-16）

## 1. 本次范围

本次按用户提供的两张截图核对指标含义，并把可复现的官方来源接入现有财政债务监控页：

1. `央行买断式逆回购余额`：截图中的“凭空印钱买国债”是截图/转录的解释性标题，系统不把它当作官方因果结论。系统接入中国人民银行买断式逆回购业务公告和招标公告，逐笔推导尚未到期本金余额。
2. `财政全口径支出逐月演变`：截图中的“全口径支出”按一般公共预算支出 + 政府性基金支出的当期流量简单相加，并增加同一报告窗口同比。

原始截图保留为参照，不把截图数字反写成 official observation，也不使用转录稿或截图中的结论替代官方来源。

## 2. 当前数据结果

### 2.1 买断式逆回购余额

本次官方更新发现并保存：

- 37 条中国人民银行公告：29 条 `tender` 招标公告、8 条 `business` 业务公告；两类公告均进入解析。
- 44 笔逐笔操作，操作日期覆盖 2024-10-31 至 2026-08-14。
- 29 个月末/预测期记录，覆盖 2024-10 至 2027-02。
- 截至 2026-08-16 的已知未到期本金余额：**63,000 亿元（6.3 万亿元）**，9 笔 active operation。
- 最近一个已完成月末（2026-07-31）：**61,000 亿元**。
- 当前月份 2026-08 的月末路径：**63,000 亿元**，是按截至当前已公布操作的到期日推算，不是央行预测；8 月月末前若有新公告，数值会更新。
- 这套逐笔推导序列的历史高点为 2026-02 的 74,000 亿元，随后因到期和操作变化回落。

系统使用的月末公式是：

```text
outstanding_amount(month_end)
  = sum(amount for operation_date <= month_end < maturity_date)
```

到期日若公告明示则使用公告日期；若公告只给期限，则使用操作日期 + 期限推算，并在 `maturity_date_status=derived` 中标记。公告没有完整日的业务公告使用公告月份的可复现月末回退日期，同时保留来源和解析说明。

为纠正本次 7、8 月“看起来没有更新”的问题，页面和月末表现在同时保存第二条截图对照序列：

```text
business 公告：从 operation_month + 1 开始，覆盖 term_months 个自然月
tender 公告：从 operation_month 开始，覆盖 term_months 个自然月
```

因此同一月份现在可以并列查看：

- 2025-07：exact-date **48,000 亿元**；截图月度归集 **60,000 亿元**。
- 2025-08：exact-date **51,000 亿元**；截图月度归集 **60,000 亿元**。截图参考图显示 55,000 亿元，这个差额仍保留为 reference reconciliation，不把 55,000 强行写入官方或 derived 数据。
- 2026-07：exact-date **61,000 亿元**；截图月度归集 **61,000 亿元**。
- 2026-08：截至 2026-08-16 的已知操作月末路径为 **63,000 亿元**；该月尚未结束，所以仍是 projected，不是官方月末观测。

截图中 2025-11 的 66,000 亿元作为 reference anchor 保留；系统同一月份的 exact-date derived 值为 63,000 亿元，而截图月度归集 derived 值为 66,000 亿元。两者不能静默强行相等：截图使用的月度归集/到期日处理口径与逐笔 exact-date 计算不同。页面现在同时展示两条 derived 序列、官方逐笔输入和未来到期路径，便于继续比对。

### 2.1.1 逐笔 × 月份图片矩阵

已把截图式的横向矩阵正式接入 `/fiscal-debt` 页面，不再只是独立 PNG：

- 行：44 笔官方公告解析出的逐笔操作，显示操作日、业务/招标类型、期限和金额。
- 列：2024-10 至当前 2026-08 共 23 个月；业务公告从次月归集，招标公告从操作月归集。
- 合计：底部同时显示 `月度归集合计`、`exact-date 月末余额` 和 `归集 − exact-date`，用于发现口径差异、漏项或日期处理问题。
- 交互：矩阵容器支持横向滚动，页面内提供 CSV 与 PNG 下载；PNG 与 CSV 都由当前 API 数据实时生成。
- 标识：金色列是截图参考 2025-07/08，蓝色列是当前 2026-07/08；颜色之外，表头和行名也直接写明口径，避免只依赖颜色。

当前矩阵合计为：2026-07 月度归集 61,000 亿元、exact-date 61,000 亿元；2026-08 截至 2026-08-16 月度归集和 exact-date 均为 63,000 亿元，差额为 0。2026-08 仍是截至当前已知操作路径，不是已经公布的官方月末统计。

### 2.2 财政全口径支出

已从财政部国库司官方 YTD 报告建立月度流量与同比对象：

```text
general_budget_expenditure_monthly
  = general_budget_expenditure_ytd[current]
  - general_budget_expenditure_ytd[previous_report]

gov_fund_expenditure_monthly
  = gov_fund_expenditure_ytd[current]
  - gov_fund_expenditure_ytd[previous_report]

full_caliber_expenditure_monthly
  = general_budget_expenditure_monthly
  + gov_fund_expenditure_monthly

same_window_yoy
  = full_caliber_expenditure_monthly[current]
  / full_caliber_expenditure_monthly[year_minus_one]
  - 1
```

当前覆盖：

- 有值的全口径当期流量：126 个报告窗口，2012-07 至 2026-06。
- 有值的同窗口同比：103 个窗口，2016-02 至 2026-06；覆盖率 81.75%。
- 由于缺少相邻 YTD 或上一年同窗口，保留 23 个同比缺口，不插值、不跨缺口桥接。
- 2025-10：**23,729 亿元，-19.14%**，与截图的 23,729 亿元、-19.1% 可以直接对照。
- 当前本地库最新全口径流量窗口为 2026-06：**37,423 亿元，-11.88%**。这不是 2026-07；库中没有 7 月相邻官方 YTD 报告，因此页面不外推 7 月。

2 月保留财政部的 1—2 月合并报告窗口，不把它伪装成单独 1 月或 2 月流量。

## 3. 代码、接口和页面变更

- `services/pboc_buyout_reverse_repo_service.py`
  - 从只解析招标公告扩展为解析招标公告 + 业务公告。
  - 业务公告没有具体日时使用可复现的月份回退日期，并保存 `announcement_kind`、期限和解析状态。
  - payload 继续区分 official 逐笔输入、derived 月末存量和 projected 到期路径。
  - 月末表新增截图对照字段：`monthly_bucket_outstanding_amount`、归集笔数、归集操作明细和公式；不覆盖 `outstanding_amount`。
- `services/fiscal_budget_service.py`
  - 增加 `build_full_caliber_expenditure_series`。
  - 增加同一报告窗口的 full-caliber expenditure YoY、覆盖统计、缺失原因和公式字段。
- `services/fiscal_monitor_service.py`
  - 将 full-caliber records 接入财政模块的 tables、section 和 API。
  - 修正逆回购 Debug 总览：主覆盖使用月末层记录，同时保留公告、操作、月末三层 breakdown，避免页面误报 0 条。
  - 将 exact-date 与截图月度归集余额同时接入流动性时间线和指标卡。
- `services/pboc_buyout_reverse_repo_service.py`
  - 增加 `build_buyout_reverse_repo_matrix`，在同一个 payload 中返回逐笔行、月度归集合计、exact-date 合计和差额，保留官方输入与 derived 结果分层。
- `scripts/create_pboc_buyout_repo_image.py`
  - 增加可复现的独立图片渲染脚本，输出当前矩阵快照；页面 PNG 导出则直接使用浏览器当前 API 数据。
- `static/fiscal_debt.html`
  - 增加“财政全口径支出逐月演变”金额图、同比图、历史表和来源链接。
  - 逆回购余额、已完成月末、已知操作到期路径继续在“央行与流动性投放”中联动展示。
  - 逆回购表格和图表并列展示 exact-date 与截图月度归集两条 derived 序列。
  - 增加“逐笔操作 × 月份横向展开”矩阵，以及 CSV/PNG 导出按钮；移动端保持容器内横向滚动。
- `tests/test_pboc_buyout_reverse_repo_balance.py`
  - 覆盖业务公告作为 official operation source 的解析和月份回退日期。
  - 覆盖 business/tender 月度归集起算月份不同的规则。
  - 覆盖矩阵行与 exact-date/归集合计分离，防止截图口径覆盖 exact-date。
- `tests/test_fiscal_budget_service.py`
  - 覆盖全口径支出和同窗口同比。
- `tests/test_core_guards.py`
  - 覆盖逆回购三层 coverage 在页面总览中的可显示结构。

## 4. 来源和数据边界

- 中国人民银行买断式逆回购栏目：
  `https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5492845/b0da893b-1.html`
- 财政部国库司财政收支统计入口：
  `https://gks.mof.gov.cn/tongjishuju/index.htm`

官方公告/YTD 报告是输入；余额、当期流量和同比是可审计 derived 结果。买断式逆回购余额不是财政部国债余额、政府债务余额或央行资产负债表“对政府债权”；全口径支出也不是财政部单列的一个官方月度字段。截图和老蛮转录中的解释性表述只作为待验证 reference/hypothesis，不作为事实或因果证据。

本次全历史财政回补有 8 个较早财政部页面返回 HTTP 502；没有用搜索摘要、估计或前后期数填补，已有数据保持不变并在缺口/来源状态中可追溯。最近可用的财政模块更新记录为 success；其他债券模块的历史页面 502 仍按各自 partial 状态保留。

## 5. 验证记录

- Windows Python `py_compile`：通过。
- 专项测试：16/16 通过。
- 全量测试：680/680 通过。
- Windows Python API smoke：`/api/health` 200，`/api/fiscal-debt/data` 200；矩阵返回 23 个月、44 笔操作，当前 2026-08 为 63,000 / 63,000 / 0。
- 桌面浏览器：矩阵、合计行和按钮均已渲染；矩阵内部 `scrollWidth=2186`、可视宽度 1169，页面本身无横向溢出；控制台 0 errors、1 条 Babel warning。
- CSV 和 PNG 按钮均已实际触发下载；PNG 已检查，包含 44 笔操作、参考列、当前列和三行合计。
- 375px 移动视口：矩阵内部 `scrollWidth=2186`、可视宽度 305，页面本身没有横向溢出，仍可横向查看月份。

复现全量测试：

```text
PYTHONIOENCODING=utf-8 C:\Users\cui10\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests
```

## 6. 后续可继续扩展

1. 继续补财政部历史 YTD 页面，使同比缺口减少，但仍逐页保留 blocked/missing 状态。
2. 把全口径支出与房价、土地出让收入、地方债发行、央行流动性模块做可选时间对齐，形成“财政支出—土地—房价—流动性”的情景联动；联动结果应进入 derived/scenario，不覆盖 official。
3. 对截图月度口径单独建立 `reference_reconciliation` 表，把 screenshot/reference、exact-date derived、可能的 month-bucket derived 并列，避免用不同口径直接比较。
