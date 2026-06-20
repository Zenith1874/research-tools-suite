# 政府债务监控模块重构与验收报告

核对日期：2026-06-20  
数据库：`D:/claude/pboc_data.db`  
页面：`/fiscal-debt`、`/fiscal-debt/debug`

## 1. 修改文件

- `server.py`：5-section API、统一更新编排、单模块更新、每周调度、ThreadingHTTPServer。
- `services/fiscal_debt_service.py`：幂等迁移、中央政府债务 PDF、地方债历史分页、scenario 重构。
- `services/fiscal_monitor_service.py`：监控口径聚合、card 契约、更新日志、Debug 汇总。
- `services/mof_treasury_bond_service.py`：国债公告更新改为非破坏式 upsert。
- `services/pboc_gov_bond_omo_service.py`：部分抓取失败时保留旧 observation。
- `services/pboc_buyout_reverse_repo_service.py`：部分抓取失败时保留旧公告、操作和存量。
- `static/fiscal_debt.html`：移除 11 个 Tab，重构为 5 个主板块。
- `static/fiscal_debt_debug.html`：增加导航、覆盖、缺失原因、失败来源和更新日志。
- `scripts/verify_fiscal_debt.py`：数据库覆盖和数据纪律验证脚本。
- `README.md`：手动更新、单模块更新、验证和调度说明。

## 2. API 修改

保留并重构：

- `GET /api/fiscal-debt/data`：只按 5 个 section 返回监控数据。
- `POST /api/fiscal-debt/update`：空 body 更新全部已接入官方来源；传 `module_code` 更新单模块。
- `GET /api/fiscal-debt/debug`：返回覆盖、指标状态、错误、来源、最近 observation 和更新日志。
- `GET/POST /api/fiscal-debt/pboc-balance-sheet[/update]`。
- `GET/POST /api/fiscal-debt/pboc-gov-bond-omo[/update]`。
- `GET /api/fiscal-debt/projection`。
- `POST /api/fiscal-debt/projection/run`。

新增单模块入口：

- `POST /api/fiscal-debt/local-government-debt/update`。
- `POST /api/fiscal-debt/central-government-debt/update`。

每张 API card 均包含：`label`、`value`、`unit`、`period`、`data_status`、`source_name`、`source_url`、`formula`、`parser_notes`。

## 3. 数据库表和字段

`fiscal_debt_observations` 幂等新增：

- `module_code`
- `raw_text`
- `formula`

`fiscal_debt_update_logs` 幂等新增：

- `module_code`
- `source_url`
- `status`
- `http_status`
- `records_inserted`
- `records_updated`

新增 `fiscal_debt_scenario_runs`。scenario 结果只进入该表，不进入 official observation。

中央政府季度债务余额和债券余额复用 `fiscal_debt_observations`，`debt_line=central_government_debt`。

## 4. 页面结构

主页面不再使用十多个 Tab，改为单页 5 个锚点板块：

1. 政府债务总览
2. 发行、还本、付息压力
3. 央行与货币化压力
4. 央行买债压力情景推算
5. 数据来源与 Debug

城投债、财政缺口和完整到期预测没有可靠来源，因此不再作为主 Tab；只在“待接入模块”和 Debug 中说明。

## 5. 返回按钮

`/fiscal-debt` 顶部：

- 返回首页 -> `/`
- Debug -> `/fiscal-debt/debug`
- 刷新数据
- 更新官方数据

`/fiscal-debt/debug` 顶部：

- 返回政府债务监控 -> `/fiscal-debt`
- 返回首页 -> `/`
- 刷新 Debug

全部是可点击链接或按钮。

## 6. 当前覆盖

| 模块 | 记录/期数 | 最早 | 最新 |
|---|---:|---|---|
| 财政债务 observation | 377 条 / 20 个期间 | 2024-03 | 2026-04 |
| 中央政府季度债务 | 4 季度 | 2024-03 | 2024-12 |
| 地方政府债务 | 17 个月 | 2024-12 | 2026-04 |
| 央行资产负债表 | 60 条 / 5 个月 | 2026-01 | 2026-05 |
| 央行公开市场国债买卖 | 10 个月 | 2024-08 | 2025-05 |
| 买断式逆回购公告 | 33 条 | 2024-10-31 | 2026-06-12 |
| 买断式逆回购逐笔操作 | 26 条 / 25 个操作日 | 2025-06-06 | 2026-06-15 |
| 买断式逆回购月末轨迹 | 19 期 | 2025-06 | 2026-12 |
| 财政部国债发行明细 | 239 条 | 2025-11-05 | 2026-06-25 |

地方债已达到“至少回填到 2024”的最低要求，但目前只能从新栏目稳定取得 2024-12；2024-01 至 2024-11 仍需旧栏目/旧站链接发现。

## 7. Official 数据及来源

- 中央政府债务余额：财政部《2024年中央政府月度收支及融资数据和季度债务余额情况》官方 PDF。
- 地方政府债务：财政部债务管理司每月“地方政府债券发行和债务余额情况”具体原文。
- 国债实际发行：财政部债务管理司逐条国债业务公告；主口径只用 `actual_issue_amount`。
- 央行资产负债表：中国人民银行“货币当局资产负债表”官方附件。
- 央行国债买卖：中国人民银行“公开市场国债买卖业务公告”。
- 买断式逆回购逐笔操作：中国人民银行招标公告。

当前所有 official observation 缺失 `source_url` 数量为 0。

## 8. Derived 数据及公式

- 同期显性政府债务合计：`central_government_debt_balance + local_debt_balance_total`。
- 央行资产占比：对应资产项目除以 `total_assets`。
- 央行国债累计净买入：`sum(net_purchase_amount for parsed official months)`。
- 买断式逆回购月末存量：月末尚未到期的逐笔操作本金合计。
- 地方债当月还本缺正文值时：当月 YTD 还本减同年上月 YTD 还本。

derived observation 缺失 `formula` 数量为 0。

## 9. 仍然 Missing

- 国债完整到期还本序列：发行明细不等于完整存量兑付表。
- 国债完整付息序列：待接财政部兑付公告或中债登公开统计。
- 城投债统一余额：没有财政部官方统一口径，不纳入地方政府显性债务。
- 财政缺口：需要先定义测算口径，不能冒充官方赤字。
- 2025 年以前完整国债发行历史：当前新栏目只稳定覆盖 2025-11 以后。
- 2024-01 至 2024-11 地方债月报：新栏目未提供全部旧链接。
- 2025 年以后中央政府季度债务 PDF：当前发现并接入的是 2024 年官方文件。

missing 卡片不显示大数字，只显示“待接入可靠来源”。

## 10. Mock、Seed、Math.random、Fallback

财政债务模块数据库检查结果：

- mock：0
- seed：0
- scenario 混入 official observation：0
- official 标记为 cache：0
- `Math.random`：财政债务两个前端页面中不存在
- 前端硬编码金融数值：不存在
- 缺失值默认补金融数字：不存在

注意：`server.py` 仍保留另一个 `/dashboard` 央行金融统计模块的历史 `SEED` 常量；它不进入 fiscal-debt API 或 observation。

## 11. 更新机制

手动更新全部：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:5001/api/fiscal-debt/update
```

手动更新单模块：

```powershell
Invoke-RestMethod -Method Post -ContentType application/json `
  -Body '{"module_code":"local_government_debt"}' `
  http://127.0.0.1:5001/api/fiscal-debt/update
```

默认启动每 168 小时检查一次。设置 `FISCAL_AUTO=0` 可关闭。每个模块有独立“更新此模块”按钮。

更新逻辑改为非破坏式 upsert。本次没有有效解析结果或部分 URL 失败时，保留旧数据，并写入更新日志和来源错误。

## 12. 最近 update_logs

最近国债发行单模块更新：

- `module_code=treasury_issuance`
- `status=partial`
- `http_status=502`
- 成功解析 195 条；数据库保留 239 条历史/现有明细
- 2 个具体公告失败
- `error_message=2 source fetch/parse errors`

最近完整更新中，地方债、中央政府债务、央行资产负债表、央行国债买卖和买断式逆回购均成功。国债发行因具体公告 502 为 partial。

## 13. 主页面现在可见内容

- 中央政府债务余额、中央政府债券余额、地方政府债务余额。
- 2024-12 同期中央 + 地方显性政府债务 derived 合计。
- 地方一般债务、专项债务、发行、还本、付息、利率和期限。
- 国债实际发行月度汇总与逐条来源。
- 央行资产负债表和占比。
- 央行国债买卖月度 official 0/非 0 数据。
- 买断式逆回购月末未到期本金测算。
- 用户显式运行的 scenario 表单和结果。
- 来源覆盖和待接入模块。

## 14. Debug 页面现在可见内容

- 每个模块和指标的 earliest/latest/count/status。
- source_url 缺失数。
- parser errors。
- last update/success/error。
- 最近 20 条 source、observation 和 update_logs。
- missing 模块、原因和下一步候选来源。
- mock/seed/cache 状态分布。

## 15. 本次抓取失败

| source_url | HTTP | 错误 |
|---|---:|---|
| `https://zwgls.mof.gov.cn/ywgg/202511/t20251112_3976291.htm` | 502 | HTTP 502 |
| `https://zwgls.mof.gov.cn/ywgg/202603/t20260305_3984711.htm` | 502 | HTTP 502 |

两条失败均已进入 `fiscal_debt_sources` 和 `fiscal_debt_update_logs`。旧国债明细未被删除。

## 验证结果

- `/fiscal-debt`：HTTP 200。
- `/fiscal-debt/debug`：HTTP 200。
- `/api/fiscal-debt/data`：5 个 section，card 契约字段无缺失。
- 页面 JSX：Babel 编译通过。
- Python：`py_compile` 通过。
- `git diff --check`：通过。
- 隔离 scenario 测试：2 个季度结果，全部标记 scenario，不写 official observation。
- 应用内浏览器在首次本地导航时进程崩溃，重连后被崩溃页策略阻断，因此本轮未完成截图级视觉验收；HTTP、静态编译和数据/API 验收均已完成。
