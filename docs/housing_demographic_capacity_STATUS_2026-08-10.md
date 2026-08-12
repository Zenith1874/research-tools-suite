# 房地产人口—家庭形成长期层状态（2026-08-10）

## 本次交付

- 在 `/housing-scenario#demographic-capacity` 新增独立的 2030 / 2040 / 2050 长期层。
- 保留既有 2030 城市房价路径原样；长期容量不直接换算房价，也不重复叠加到既有人口、婚姻结构修正。
- 全国图同时展示总人口指数、20—39 岁人口指数和三档家庭形成容量。
- 十五城图可切换年份、乐观/基准/压力、全部/上方已选/本市趋势/全国回退，以及“差异放大”或“0 起点”纵轴。
- 表格固定列出十五城，并逐城披露常住人口样本、近期增速、相对全国修正和回退原因。

## 官方数据与更新方式

公开快照保存在 `data/housing_demographic_capacity_inputs.csv`，共 12 行：

- 来源：United Nations World Population Prospects 2024，Medium variant；
- 原文件：`WPP2024_Population1JanuaryByAge5GroupSex_Medium.csv.gz`；
- 指标：1 月 1 日总人口、20—39 岁人口、60 岁及以上人口；
- 年份：2025、2030、2040、2050；
- 单位：千人；状态：`official_projection`。

可重复执行：

```text
python.exe -X utf8 scripts/update_housing_demographic_capacity.py
```

脚本流式读取约 30 MB 的官方压缩 CSV，只保留中国四个年份并聚合年龄组，不保存或提交整份上游文件。重复执行前后紧凑 CSV 的 SHA-256 均为：

```text
5b755f84c4c2336890a7ab5e9cb17aff2545b8dd50fa3fa74036a0d7a5aafa13
```

全国实际锚点继续读取 `data/housing_structural_drivers.csv` 的国家统计局 2025 年末人口 140489 万人。WPP 是 1 月 1 日口径，绝对总人口路径只使用其相对变化缩放到国家统计局锚点，明确标为 derived；年龄结构指数仍直接使用 WPP 中方案。

## 透明公式

```text
潜在家庭形成容量指数
= (WPP 20—39岁人口 / 2025年20—39岁人口 × 100)
  × 家庭形成倾向情景乘数
  × 城市人口集聚乘数

固定存量负担指数 = 10000 / 潜在家庭形成容量指数
```

- 家庭形成倾向从 2025 年的 1 线性过渡到 2050 年用户设定值；默认乐观 `+10%`、基准 `0%`、压力 `-15%`。
- 默认值只是可调压力测试，不使用视频中的 70% 或 35%，也不声称是估计系数。
- 城市趋势至少需要 3 个近期常住人口增速，且最新期不早于 2022 年；用最近最多 5 个有效增速的中位数减去全国最新人口增速。
- 相对增速限制在 ±2 个百分点，并按 8 年半衰期衰减，避免把短期城市净流入机械复利到 2050 年。
- 常住人口不足时使用全国路径并标记 `national_fallback`；不用户籍人口代替迁移趋势。

## 真实库结果

全国中方案与默认情景：

| 项目 | 2030 | 2040 | 2050 |
|---|---:|---:|---:|
| 国家统计局锚定总人口（百万人） | 1387.596 | 1333.968 | 1253.988 |
| 20—39 岁人口指数（2025=100） | 90.216 | 86.000 | 66.999 |
| 60+ 人口占比 | 25.868% | 32.844% | 39.518% |
| 乐观家庭形成容量 | 92.020 | 91.160 | 73.699 |
| 基准家庭形成容量 | 90.216 | 86.000 | 66.999 |
| 压力家庭形成容量 | 87.510 | 78.260 | 56.949 |
| 基准固定存量负担 | 110.845 | 116.279 | 149.256 |

十五城覆盖：

- 本市趋势可算 8 城：常州、苏州、无锡、武汉、长沙、成都、杭州、福州；
- 全国回退 7 城：北京、上海、广州、深圳、厦门、南京、合肥；这些城市在当前本地库只有 2024 单点，不能据此伪造趋势。
- 2050 基准容量中，杭州约 76.0、长沙约 76.0、苏州约 71.6、常州约 70.1；全国回退城市为 67.0。差异来自有界且衰减的城市人口集聚修正，不是房价排序。

## 解释边界

- WPP 中方案是官方投影，不是实际观测，也不是发生概率。
- 20—39 岁是家庭形成代理，不等于购房人数；结婚、初婚、就业预期、收入分布会改变形成倾向。
- 固定存量负担假设 2025 住房存量不变，未计新建、拆除、空置释放、住房质量和城市内部区位。
- 本层回答“人口侧容量如何变化”，不回答“房价必然跌到哪一年”。后者仍需库存、收入、信贷和政策共同识别。

## 验证

```text
node.exe --check static/housing-scenario.js
python.exe -X utf8 -m py_compile services/housing_demographic_capacity_service.py services/housing_scenario_service.py server.py scripts/update_housing_demographic_capacity.py
python.exe -X utf8 -m unittest tests.test_housing_demographic_capacity_service tests.test_housing_scenario_service -q
# 27 tests: OK

python.exe -X utf8 -m unittest discover -s tests -q
# 495 tests: OK
```

真实 API `/api/housing-scenario/compare` 已核对包含 `demographic_capacity`，十五城覆盖、默认参数与上述锚点一致。Playwright 实测参数更新、年份切换、城市范围切换和差异放大纵轴均正常，浏览器控制台 0 error；验收截图：`output/playwright/housing-demographic-capacity.png`。

## 变更文件

- `data/housing_demographic_capacity_inputs.csv`
- `scripts/update_housing_demographic_capacity.py`
- `services/housing_demographic_capacity_service.py`
- `services/housing_scenario_service.py`
- `server.py`
- `static/housing_scenario.html`
- `static/housing-scenario.js`
- `tests/test_housing_demographic_capacity_service.py`
- `tests/test_housing_scenario_service.py`
- `README.md`
