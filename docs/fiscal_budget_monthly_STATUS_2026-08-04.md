# 财政收支月度流量与完整性审计（2026-08-04）

## 结论

当前财政库原始值是财政部国库司报告的年初至今累计（YTD），不是财政部直接发布的单月流量。原库不能称为“按月完整”。

- 一般公共预算收入/支出：各 130 个截止期，2010-06 至 2026-06。
- 政府性基金收入/支出：各 113 个截止期，2012-06 至 2026-06。
- 两本账 YTD 简单相加：从 2012-06 起有 113 个共同截止期。
- 月度流量层：由相邻 YTD 差分得到；现有观测跨度内 158 个候选月份，两本账收入与支出同时可差分的期数为 98 个。
- 最新共同可差分期为 2026-06：两本账当期总收入 23,308 亿元、总支出 37,423 亿元、差额 -14,115 亿元。

## 口径与缺失纪律

- `YYYY-02` 表示财政部的 1—2 月合并报告，保留为两个月窗口，不拆出 1 月。
- 3 月以后只有在同年相邻两期 YTD 都存在时才做 `current_ytd - previous_ytd`。
- 缺少相邻 YTD 时保持 `missing`，不以前值、插值或跨缺月差分。
- “两本账总收入/总支出”是一般公共预算与政府性基金的简单相加，是 derived 分析视图，不是财政部另行公布的法定综合财力。

## 本次改动

- `services/fiscal_budget_service.py`
  - 新增不跨缺月的 YTD→当期流量转换与覆盖审计。
  - 新增两本账总收入、总支出、差额的月度 derived 字段。
  - 财政部主站“全国财政收支情况”归档作为索引发现备用入口；实测 8 页发现 165 个链接，其中 153 个标题可解析为报告期，覆盖 2010-03 至 2026-06。
- `services/fiscal_monitor_service.py`
  - 将月度流量、月度卡片和完整性审计接入 `/fiscal-debt` payload。
- `static/fiscal_debt.html`
  - 新增月度实际流量图、总收入/总支出卡、缺月说明和 CSV 表。
- `tests/test_fiscal_budget_service.py`
  - 覆盖 1—2 月合并、跨年重置、缺月不桥接、月度覆盖和归档链接解析。

## 数据源限制

财政部主站归档可访问，但报告链接多数仍指向 `gks.mof.gov.cn`；当前运行环境直接请求该域名返回 502。因此本次没有用搜索摘要或其他非官方来源填充缺失原文，历史缺口仍如实保留，后续可在能访问国库司正文的网络环境执行 `full_history=True` 回填。

## 验证

- `python.exe -m py_compile services/fiscal_budget_service.py services/fiscal_monitor_service.py`：通过。
- `python.exe -m unittest tests.test_fiscal_budget_service -v`：18 项通过。
- `build_fiscal_monitor_payload('pboc_data.db')`：成功生成 payload，月度行 158 条，最新月度卡为 2026-06。
