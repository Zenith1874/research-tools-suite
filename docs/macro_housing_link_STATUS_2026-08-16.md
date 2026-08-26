# 宏观情景—房价联动状态（2026-08-16）

## 已完成

- 新增 `services/macro_housing_link_service.py`：读取现有宏观情景实验室的 GDP、贷款余额同比、商品房销售面积、全国人口增速和 5 年期 LPR；为每个组件生成 upper/base/lower 轨道。
- 新增 `macro_linked_scenarios`，原始 `scenarios` 和现有 `structural_scenarios` 均保留；宏观联动不覆盖、不改写原始历史或数据库。
- 默认方向：增长/信用/销售/人口上行、LPR 下行对应房价乐观；压力情景反向；基准全部使用基准轨道。逐项固定轨道可用于敏感性检查。
- 接入 `/api/housing-scenario/data` 与 `/api/housing-scenario/compare`，参数为 `macro_link=1` 及 `macro_growth`、`macro_credit`、`macro_sales`、`macro_population`、`macro_lpr`。
- 房价页面新增“宏观联动”模型、五个组件选择器、组件覆盖表、期末年化调整图和纯动能对照线。
- 年度挂牌源明确标为 `not_applicable`，不把年点伪装成月度宏观联动；缺失/历史不足组件保留状态并减少覆盖。

## 本机数据库冒烟结果

使用 Windows Python 3.12 直接读取 `D:\claude\pboc_data.db`，厦门、官方二手房、24 个月：

| 组件 | 状态 | 连续点 | 说明 |
|---|---|---:|---|
| GDP实际增速 | ok | 35 | 2017-12—2026-06 |
| 人民币贷款余额同比 | ok | 32 | 2023-12—2026-07 |
| 商品房销售面积累计同比 | insufficient_sample | 11 | 少于 18 点门槛，不生成轨道 |
| 全国人口增速 | ok | 15 | 2011—2025，CSV 年度推导 |
| 5年期LPR | ok | 84 | 2019-08—2026-07 |

因此当前联动覆盖为 4/5。默认 auto 方向下，厦门二手房 24 个月期末相对当前的本地冒烟
结果为：乐观约 +2.08%、基准约 −10.65%、压力约 −16.95%；纯动能路径仍在 API 中保留。
这些是当前数据快照下的条件情景，不是预测，也不是概率。

## 验收记录

- `tests/test_macro_housing_link_service.py`：4/4 通过。
- Windows Python 全量测试：675/675 通过。
- `server.py`、服务模块 `py_compile` 通过；`static/housing-scenario.js` 使用 Node `--check` 通过。
- 真实 API：`/api/housing-scenario/data?...&macro_link=1` 返回 3 条联动路径；比较接口 2 城冒烟通过。
- Playwright：已验证宏观模型初始加载、组件选择器改变路径、切回纯动能隐藏联动卡、切换年度挂牌自动禁用联动；桌面和 375px 移动视口截图保存在 `output/playwright/housing_macro_linked_desktop.png` 与 `output/playwright/housing_macro_linked_mobile.png`。

## 方法边界

系数是公开、可调整的压力测试假设，不是回归估计。GDP/季度和人口/年度路径以阶梯方式
展开到房价月份；组件缺失不以 0 或文字稿数字填充。联动只改变未来情景速度，不改变历史
观测、官方/挂牌源定义，也不把老蛮文字稿中的未经核验数字写入数据库。
