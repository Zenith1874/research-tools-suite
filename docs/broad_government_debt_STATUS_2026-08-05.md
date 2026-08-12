# 广义政府债务与城投债数据审计状态（2026-08-05）

## 结论

- 当前 `pboc_data.db`、两份 2026-07-27 备份和 Git 历史均无城投债数值记录；旧代码只有
  `LGFV_FIELDS` 和 `lgfv_placeholder`，不能视作已有数据。
- 新增“广义政府债务”只使用财政部可复核口径：国债 + 地方政府法定债务 + 地方政府隐性债务。
- 城投债是按发行人名单识别的企业债券，财政部隐性债务是监管认定口径，两者不相等且不得相加。

## 公式

1. 历史复合增速：`g = (X_end / X_start) ^ (1 / calendar_year_span) - 1`。
2. 限额路径：`limit_y = limit_anchor × (1 + limit_growth)^h`。
3. 余额路径：`balance_y = balance_anchor × (1 + balance_growth)^h`；首次
   `balance_y >= limit_y` 仅表示在该假设下需再次提额。
4. 付息压力：`projected_interest / projected_general_budget_revenue`。
5. 广义债务：`treasury_balance + local_legal_balance + residual_hidden_debt`。

## 官方锚点与2025情景

- 2023：财政部披露国债30.0万亿元、地方法定债40.7万亿元、隐性债务14.3万亿元，
  全口径85.0万亿元、负债率67.5%。
- 2024：财政部披露国债34.6万亿元、地方法定债47.5万亿元、隐性债务10.5万亿元，
  全口径92.6万亿元、负债率68.7%。
- 2025法定债务：国债41.231768万亿元 + 地方法定债54.823082万亿元 = 96.054850万亿元。
- 2025隐性债务尚无官方余额。机械区间：
  - 高位：`10.5 - 2.0 = 8.5`万亿元，只扣除2025已确认置换债；
  - 低位：`10.5 - 2.0 - 0.8 = 7.7`万亿元，再假设年度化债资源全部1:1冲减本金；
  - 区间无概率含义，并假设无新增隐性债务。
- 因此2025广义债务情景为103.754850—104.554850万亿元；以国家统计局2025年GDP
  140.1879万亿元计算，约为74.01%—74.58%。

## 来源

- 财政部2023隐性债务与全口径披露：
  https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/202411/t20241109_3947230.htm
- 国务院关于2024年度政府债务管理情况的报告：
  https://zwgls.mof.gov.cn/gzdt/202511/t20251102_3975538.htm
- 2025预算执行与2026预算草案报告（含2025置换债与法定债务余额）：
  https://bgt.mof.gov.cn/zhuantilanmu/rdwyh/czyw/202603/t20260316_3985331.htm
- 国家统计局2025全年GDP：
  https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202601/t20260120_1962349.html

## 实现

- `services/debt_projection_service.py`：新增官方锚点、2025隐性债务区间、广义债务合计、
  债务/GDP及LGFV数据库审计；所有公式与状态进入API。官方锚点已幂等写入
  `fiscal_debt_observations` 的 `broad_government_debt` 模块。
- `static/debt_ceiling.html`：新增算法卡、广义债务堆叠图、明细表、区间与城投数据审计说明。
- `tests/test_debt_projection_service.py`：新增政策桥接区间、官方/情景状态、重复计算与LGFV空库测试。

## 边界

- 2025区间是情景，不是官方余额、置信区间或预测。
- 年度8000亿元政策资源未必在同年1:1冲减隐性债务本金，因此只用于情景低位。
- 真正城投债全量计算需有授权的逐只债券数据、明确发行人分类规则、跨市场去重和存续余额快照；
  在获得这些输入前，系统不生成城投债余额、到期壁或付息数字。

## 验证

- 官方锚点入库12条（2023—2024、6指标），重复执行仍为12条；全部 `official` 且来源URL非空。
- 城投债数值记录实测为0条；没有把隐性债务写入 `lgfv_debt`。
- `python.exe -X utf8 -m unittest tests.test_debt_projection_service tests.test_debt_ceiling_service -v`：32项通过。
- `python.exe -X utf8 -m unittest discover -s tests -q`：443项通过。
- 服务重启后 `/api/debt-ceiling/data` 返回3期广义债务记录、公式、2025区间与LGFV审计。
- Playwright真实页面验证：公式、KPI、堆叠图、明细表和城投边界均渲染；假设改为地方余额增速5%
  后触线结果同步重算，恢复默认成功；控制台0 error / 0 warning。
