# 财政赤字与财政汇总补充状态（2026-08-17）

## 本次完成

- 在 `fiscal_budget_observations` 中增加 `official_national_fiscal_deficit` 年度官方补充字段，覆盖 2009—2025 年 17 个完整年度；补充函数是幂等的，并在财政预算更新任务结束时自动执行。
- 新增“历年财政汇总”：将财政部年度报告公布的法定赤字，与财政部 12 月 YTD 收入/支出计算的账面缺口并列展示。
- 新增“当前年度财政汇总”：将最新 YTD 实际、YTD 账面缺口和年度预算安排拆开；预算计划标记为 `official_plan`，不冒充全年实际赤字。
- 新增历史赤字对账图、当前年度 YTD 收入/支出/账面缺口图、独立数据表和 CSV 导出列。

## 口径边界

1. 法定财政赤字：来自财政部年度预算执行报告，单位为亿元。它包含预算平衡所需的调入资金、结转结余、预算稳定调节基金等安排，不应直接用月度“收入−支出”替代。
2. 一般预算账面缺口：`一般公共预算支出 − 一般公共预算收入`，由财政部 12 月 YTD 观测计算，状态为 `derived`。
3. 两本账账面缺口：一般公共预算与政府性基金分别计算后简单相加，未抵销调入调出或跨账本转移，只用于系统内压力和量级对照。
4. 当前年度截至 2026-06 的法定全年实际赤字尚不存在；2026 年 58900 亿元只是预算安排，单独标记为 `official_plan`。

## 当前接口结果（单位：亿元）

### 最新完整年度：2025

| 指标 | 数值 | 状态 |
|---|---:|---|
| 财政部法定财政赤字 | 56600 | official |
| 一般预算账面缺口 | 71350 | derived |
| 政府性基金账面缺口 | 55170 | derived |
| 两本账账面缺口 | 126520 | derived |
| 法定赤字 − 一般预算账面缺口 | -14750 | derived 对账 |

### 当前年度：2026-06 YTD

| 指标 | 数值 | 状态 |
|---|---:|---|
| 一般公共预算账面缺口 | 22282 | derived |
| 政府性基金账面缺口 | 23461 | derived |
| 两本账账面缺口 | 45743 | derived |
| 2026 年预算安排财政赤字 | 58900 | official_plan |
| 2026 年全年法定实际赤字 | — | not_available |

## 主要官方来源

- [2009 年中央决算报告](https://www.mof.gov.cn/gkml/caizhengshuju/201006/t20100628_324488.htm)
- [2010 年中央和地方预算执行报告](https://m.mof.gov.cn/czsj/201103/t20110317_505087.htm)
- [2012 年中央和地方预算执行报告](https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/201303/t20130319_782332.htm)
- [2016 年中央和地方预算执行报告](https://www.mof.gov.cn/gkml/caizhengshuju/201703/t20170317_2559812.htm)
- [2018 年中央和地方预算执行报告](https://www.mof.gov.cn/gp/xxgkml/bgt/201904/t20190402_3210848.htm)
- [2019 年中央和地方预算执行报告](https://m.mof.gov.cn/czsj/202005/t20200530_3523307.htm)
- [2020 年中央和地方预算执行报告](https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/202103/t20210314_3670203.htm)
- [2021 年中央和地方预算执行报告](https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/202203/t20220314_3794760.htm)
- [2022 年中央和地方预算执行报告](https://www.mof.gov.cn/gkml/caizhengshuju/202303/t20230316_3872867.htm)
- [2023 年中央和地方预算执行报告](https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/202403/t20240314_3930581.htm)
- [2024 年中央和地方预算执行报告](https://m.mof.gov.cn/czxw/202503/t20250314_3959885.htm)
- [2025 年执行与 2026 年预算草案报告](https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/202603/t20260316_3985331.htm)
- [2026 年上半年财政收支情况](https://gks.mof.gov.cn/tongjishuju/202607/t20260722_3993943.htm)

## 验证记录

- 财政预算专项测试：29/29 passed。
- 全量 Windows Python 测试：683/683 passed。
- API：`/api/fiscal-debt/data` 返回历史 17 年、官方赤字 17 个点、当前 2026-06 汇总。
- 浏览器：`/fiscal-debt` 桌面端和 375px 移动端检查通过；新增表头、数据值、官方链接存在；无运行时 JavaScript 错误；移动端页面无 body/document 横向溢出。
