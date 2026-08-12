# 宏观统计分析层状态（2026-07-17）

## 交付范围

- 新增 `/macro-analytics`，含中国、美国、中美对照三个标签页。
- 新增 `/api/analytics` 及 `/api/analytics/china|us|cross`，10分钟内存缓存；任一更新任务结束后失效。
- 新增纯 `numpy` 统计原语：历史分位、滚动Z、几何年化变化、日历感知同比、Pearson近似p值、领先滞后相关、滚动相关。
- 新增 `USREC` 与 `QUSR628BIS` 两个FRED原始序列；数据库不写入分析派生结果。
- 明确不含预测、VAR、Granger、协整，也不使用因果措辞。

## 数据与统计护栏

- 相关分析只对同比或差分序列计算，不对趋势水平值直接计算。
- 月频相关至少24个共同观测、季频至少16个，否则返回 `insufficient_sample`。
- 每个分析项均包含 `method`、`sample_start`、`sample_end`、`n_obs`、`data_status`、`caveats`。
- 中国债务可持续性差只有1个同口径年度增长观测，因此拒绝方向判断；没有降低门槛硬算。
- 社融存量同比当前库中只有12个非空观测，可做描述性定位但不进入相关分析。

## Sahm Rule验收

- 本地公式：UNRATE最近3月均值减去当前及前11个月的3月均值最低点，结果四舍五入到0.01个百分点。
- 2026-06本地结果 `0.07`，FRED `SAHMREALTIME` 官方值 `0.07`，当前值误差 `0.00`。
- 历史整段不能宣称逐月复现 `SAHMREALTIME`：FRED说明该系列使用每个月当时可获得的失业率实时版本，而本地 `UNRATE` 是当前修订历史。798个共同月份的当前修订版对实时版平均绝对差约0.089个百分点，不能把这种版本差异误报为公式错误。

## 验证

- 新增9项纯函数/契约测试；全套88项测试通过。
- 真实库全量payload约1.1秒，缓存后直接复用。
- 新增FRED系列更新成功；更新任务无错误。
- 桌面浏览器完成三个标签切换；390×844移动视口通过；控制台0错误（仅既有Babel开发模式警告）。

## 复现

```powershell
python -m unittest tests.test_macro_analytics
python -m unittest discover -s tests
Invoke-RestMethod http://127.0.0.1:5001/api/analytics
```
