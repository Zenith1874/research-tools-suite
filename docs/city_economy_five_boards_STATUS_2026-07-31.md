# 城市经济五板块扩展状态（2026-07-31）

## 本轮目标

将 `/city-economy` 从十城混合指标页扩展为十五城、五个可切换研究板块：增长总览、人口就业、产业投资、金融财政、住房与城市承载力。五个板块统一保留多城市同时选择、多指标分别作图、自由期间和每图独立纵轴。现阶段不生成城市综合得分；待十五城关键指标覆盖基本对齐后，再设计公开权重、分项贡献、缺失处理和敏感性结果的“城市经济脉搏指数”。

## 城市与数据边界

- 原十城：北京、上海、广州、深圳、厦门、南京、合肥、常州、苏州、无锡。
- 新增五城：武汉、长沙、成都、杭州、福州。
- 国家统计局主要城市年度数据是本轮人口、工资、投资、商贸、交通、教育、卫生和城市承载力指标的主要来源；采集日为 2026-07-31。
- 国家统计局该目录只覆盖目标十五城中的十二城，不含常州、苏州、无锡。三城相关缺口保持为空，不以江苏省数据替代。
- 城市官网已经存在的 GDP、财政和公报值优先保留；国家统计局在线序列作为可审计的修订序列补空。发现差异时保存来源冲突，不静默覆盖。
- 安居客二手挂牌数据继续只保存在 gitignored 本机独立库，作为非官方参考；未覆盖的新五城不推算、不复制。

## 已实现

- `CITY_CONFIG` 扩至十五城，并加入中部、海西、西南及扩展长三角快捷选择。
- 后端提供 5 个板块、59 个可选指标、逐指标覆盖范围和 7 个透明派生指标。
- 新增的透明派生指标包括：名义 GDP 同比、第三产业占比、财政自给率、房地产开发投资/GDP、人均商品住宅销售面积、平均年工资可购住宅面积、每万户籍人口医师数；仅在同城、同年、所需字段齐全时计算，不跨缺年桥接。
- 五个板块各自记住所选指标；城市与期间选择在板块间共享。
- 每项指标单独作图，并可独立选择可见区间自动、全历史固定、首期=100或自定义纵轴。
- 最新值矩阵逐格显示年份、口径与状态，区分全市、市本级、开发区、统计局修订、公式派生、商业挂牌和镜像数据。
- 覆盖审计页同时提供按城市和按指标的记录数、城市数、起止期；缺失的城市×指标组合显式计数。
- 默认开始期间为 2010 年，用户仍可在下拉框选择更早的已入库年份。
- 保留单城详情、房价情景、城市上市公司和覆盖审计等既有页签。

## 2026-07-31 实测覆盖

- 页面 payload：15 城、5 板块、59 指标。
- GDP：881 行，15/15 城；名义 GDP 2004–2025，名义 GDP 同比 2005–2025。
- 城市财政：853 行；一般预算收入和支出均为 15/15 城，2010–2025；财政自给率同为 15/15 城。
- 国家统计局主要城市年度一般指标：4,419 行；户籍人口为 12/15 城、2010–2019，平均工资、房地产开发投资、普通本专科在校生和医师为 12/15 城、2010–2024。
- 透明派生序列：1,227 行。
- 国家统计局 70 城二手房同比：13/15 城、2011-01–2026-06；常州、苏州不在 70 城名单。
- 安居客月度挂牌价参考：9/15 城、2010-01–2026-07；缺失城市保持为空。
- 来源差异记录：1 条。深圳 2016 年一般预算支出保留城市已发布值 4,178.04 亿元，同时记录国家统计局在线修订值 4,211.04 亿元及相对差异。
- 数据质量：指标复合键重复为 0；新增指标的数值、单位、来源 URL 为空均为 0；每项指标单位一致。

## 更新与复现

本轮只运行约十二个统计局支持城市、2010–2026 年的低频年度目录更新；没有覆盖原始公报或删除旧值：

```bash
PYTHONIOENCODING=utf-8 python.exe -X utf8 -c "from services.city_nbs_service import update_city_nbs; print(update_city_nbs('pboc_data.db', cities=['北京','上海','广州','深圳','厦门','南京','合肥','武汉','长沙','成都','杭州','福州'], start_year=2010, end_year=2026, force=True))"
```

更新结果：抓取 5,507 条目录记录，幂等写入/更新 4,419 条年度一般指标，并刷新 985 条 GDP/财政候选值；保留 103 条优先级更高的城市已发布值，记录 1 条来源冲突，错误列表为空。

## 验证

```bash
node.exe --check static/city-economy.js
python.exe -X utf8 -m unittest tests.test_city_nbs_service tests.test_city_economy_service -v
python.exe -X utf8 -m unittest discover -s tests -q
```

- 定向测试：20 项通过。
- 全仓测试：377 项通过。
- 本地服务 `/api/health`、`/city-economy`、`/api/city-economy/data` 均返回 HTTP 200。
- 桌面与窄屏完成视觉检查；五板块切换、十五城多选、期间过滤、纵轴自定义、覆盖页签均工作，浏览器控制台 0 errors、0 warnings。
- 页面截图保存在 `output/playwright/city-economy/.playwright-cli/`，仅用于本机视觉审计。

## 仍需后续补齐

- 常州、苏州、无锡的人口就业、产业投资和城市承载力，需要继续从三市统计年鉴/公报按同名口径回填，不能用江苏省值代替。
- 十五城政府性基金、卖地收入和地方债的城市级连续年度覆盖仍不整齐；页面会逐格显示实际年份和空缺。
- 户籍人口目录在 2019 年后停止连续披露，不能冒充常住人口继续延长；后续如接城市公报常住人口，必须保留独立指标和口径标签。
- 只有在核心指标达到预先公开的城市覆盖和时间覆盖门槛后，才进入“城市经济脉搏指数”设计；本轮没有综合得分字段。

## 2026-08-02 数据补充与复核

- 统计公报补充管线扩展为八个缺口城市：常州、苏州、无锡、武汉、长沙、成都、杭州、福州。解析器支持“年末全市常住人口”“年末全市户籍人口”等文字变体，并增加“城镇新增就业”指标；已有国家统计局官方/修订值在同一城市×指标×年份上优先保留。
- 运行 `update_city_bulletin_indicators('pboc_data.db')`：解析 462 条、写入/更新 365 条、因已有更高优先级官方值跳过 97 条、错误 0 条。镜像值统一为 `data_status='official_mirror'`，页面显示“镜像”标签，来源 URL 和公报标题随行保存。
- 新增补充覆盖：常住人口 8 城、54 条（2005–2025，缺年不桥接）；户籍人口 14 城、137 条；城镇新增就业 8 城、36 条（2007–2025，公报披露不连续）；消费、外贸、商品房销售面积、房地产投资、卫生等已有序列继续保留。
- 城市财政决算清单幂等刷新：61 个核验行，新增 35 行；武汉、福州写入 2024 年全市基金收支/卖地/税收/债务及还本付息，杭州写入 2024 年官方预算执行口径，无锡补入 2024 年全市基金收入 799.3 亿元和基金支出 706.2 亿元，长沙写入 2024 年债务余额及一般/专项拆分，成都写入 2024 年官方预计执行债务余额及拆分。杭州、成都以及无锡的决算草案叙述值保留 `official_preliminary`，没有伪装为最终决算。
- 当前十五城 payload 覆盖：城市 15/15、GDP 15/15、一般城市财政 15/15；官方房价 13/15、安居客挂牌 13/15。安居客上海和成都本轮仍因页面返回空挂牌字段而未入库，验证页/空字段不绕过、不硬填。
- 质量检查：`city_indicator_observations` 与 `regional_fiscal_observations` 的复合键重复均为 0；财政清单回跑新增行数为 0；长沙/成都基金收入、基金支出和卖地收入没有找到可核验的全市官方数，继续显示缺口，不用市本级、区县或媒体数字替代。

复现命令：

```bash
PYTHONIOENCODING=utf-8 python.exe -X utf8 -c "from services.city_bulletin_indicator_service import update_city_bulletin_indicators; print(update_city_bulletin_indicators('pboc_data.db'))"
PYTHONIOENCODING=utf-8 python.exe -X utf8 -c "from services.city_fiscal_decision_service import update_city_fiscal_decisions; print(update_city_fiscal_decisions('pboc_data.db'))"
```

本轮仍不将省级值下放到城市；第三方镜像只作明确标注的缺口补充，不改变“城市自身口径优先”的规则。

## 2026-08-03 第二轮官方公报补充与全仓复核

- 官方公报补充清单扩展为 94 行，覆盖常州、苏州、无锡 2023–2025 年可从公报正文直接核验的人口、就业、消费、外贸、居民存款、房地产投资、商品房销售面积、住房施工/竣工、医疗和交通等字段。厦门另从 2024 年财政决算报告补入全市政府性基金收入 423.7 亿元、基金支出 868.6 亿元、政府债务余额 2639.7 亿元（一般债 417.7 亿元、专项债 2222.0 亿元）。
- 本轮数据库更新结果：城市公报清单处理 94 行，新增 30 行、替换低优先级镜像 48 行、已有高优先级值跳过 16 行；财政清单处理 72 行，新增 5 行。两条更新管线均保持幂等，未清理旧值或制造重复复合键。
- 常州公报中的“全年新增就业”没有直接映射为 `urban_new_jobs`，因为该指标要求“城镇新增就业”口径；苏州 2024 年社会消费品零售额只公布增速而没有绝对值，所以不从增速倒推水平值。无锡 2024 年城镇新增就业 14.3 万人来自市政府年度计划执行材料，2025 年 14.59 万人来自统计公报，来源和状态分别保留。
- 当前接口核验：15 城、4,829 条城市一般指标、938 条城市财政记录、64 个可选指标；`city_indicator_observations` 和 `regional_fiscal_observations` 复合键重复均为 0，新增字段的数值与来源 URL 空值均为 0。
- 主要来源：常州市统计局 [2023 年公报](https://tjj.changzhou.gov.cn/html/tjj/2024/OEJQMFCO_0305/27901.html)、[2024 年公报](https://tjj.changzhou.gov.cn/content/suitable/show?catid=24519&id=28588)、[2025 年公报](https://tjj.changzhou.gov.cn/content/suitable/show?catid=24519&id=29035)；苏州市统计局 [2024 年公报](https://tjj.suzhou.gov.cn/sztjj/tjgb/202504/c77512c90a144784beba4870a6b5cc0d.shtml)、[2025 年公报](https://tjj.suzhou.gov.cn/sztjj/tjgb/202604/3dc4b574cabd4e86b36ec5d3280e927c.shtml)；无锡市政府/统计局 [2024 年公报](https://www.wuxi.gov.cn/doc/2025/04/28/4554447.shtml)、[2024 年计划执行材料](https://www.wuxi.gov.cn/doc/2025/03/07/4517484.shtml)、[2025 年公报](https://tj.wuxi.gov.cn/doc/2026/05/09/4772420.shtml)；厦门市财政局 [2024 年财政决算报告](https://cz.xm.gov.cn/zwxx/zfxxgk/zfxxgkml/ysjs/jsbg/202507/W020250716609893934548.pdf)。
- 验证：定向新增测试 7 项通过；全仓 `python.exe -X utf8 -m unittest discover -s tests -q` 共 414 项通过；`/api/city-economy/data` 返回 HTTP 200。仍未找到全市官方绝对值的字段继续留空，尤其是常州“城镇新增就业”、苏州缺失的 2024 年零售额水平，以及各城市基金/卖地/地方债的连续年度细项；不以省级、市本级、区县、媒体或商业数据库替代。

复现命令：

```bash
PYTHONIOENCODING=utf-8 python.exe -X utf8 -c "from services.city_bulletin_official_service import update_city_bulletin_official; print(update_city_bulletin_official('pboc_data.db'))"
PYTHONIOENCODING=utf-8 python.exe -X utf8 -c "from services.city_fiscal_decision_service import update_city_fiscal_decisions; print(update_city_fiscal_decisions('pboc_data.db'))"
PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest discover -s tests -q
```

## 2026-08-03 官方来源补充与覆盖复核

- 新增 `services/city_bulletin_official_service.py`，把可直接核验的城市/统计部门来源单独列为官方补充清单。2024 年新增 16 行：北京、上海、广州、深圳、厦门、南京、合肥、长沙的常住人口或城镇新增就业；深圳就业行来自深圳市人力资源和社会保障局年度工作总结，长沙行来自湖南省统计局公开的长沙市统计公报。官方补充优先替换同键 `official_mirror`，不覆盖 `official`/`official_revised`。
- 财政清单新增 3 行：广州全市税收收入 1372.3731 亿元、全市土地出让收入 1087.1 亿元，合肥全市税收收入 675.21 亿元。广州来源为广州市财政局预算执行报告，合肥来源为合肥市统计局/国家统计局合肥调查队统计公报 PDF；均按全市口径保留为 `official_preliminary`。
- 本地库幂等更新结果：官方公报清单处理 16 行，首次本轮新增 2 行、替换镜像 1 行、已存在高优先级行跳过 13 行；财政清单处理 67 行，新增 3 行。重复运行不会增加复合键行数。
- 当前 payload：15 城、64 个可选指标、城市年度一般指标 4,799 行、财政行 932 行。人口就业关键覆盖变为：常住人口 15/15 城（61 行，2005–2025，仍有缺年）；城镇新增就业 15/15 城（44 行，2007–2025，披露不连续）。税收收入为 13/15 城；政府性基金收入 10/15 城；政府性基金支出 9/15 城；土地出让收入 9/15 城。
- 质量检查：`city_indicator_observations` 与 `regional_fiscal_observations` 复合键重复均为 0；值或来源 URL 为空均为 0。直辖市的人口/就业行同时兼容 110000、310000 省级行政区代码，避免把北京、上海官方全市行错误过滤掉。
- 尚未补齐的主要缺口：合肥、长沙、成都等城市的全市基金收支/土地出让连续年度；厦门、南京、合肥、长沙、成都的基金细项；成都税收；以及常州、苏州、无锡的连续年鉴级人口就业、产业投资和承载力。没有找到全市官方值的字段继续留空，不用市本级、区县、评级报告或商业数据库替代。

复现命令：

```bash
PYTHONIOENCODING=utf-8 python.exe -X utf8 -c "from services.city_bulletin_official_service import update_city_bulletin_official; print(update_city_bulletin_official('pboc_data.db'))"
PYTHONIOENCODING=utf-8 python.exe -X utf8 -c "from services.city_fiscal_decision_service import update_city_fiscal_decisions; print(update_city_fiscal_decisions('pboc_data.db'))"
```

## 2026-08-03 第三轮官方数据补充

- 城市指标新增 7 条：常州、苏州、无锡 2024–2025 年城镇非私营单位在岗职工年平均工资 6 条；苏州 2024 年社会消费品零售总额 10043.7 亿元 1 条。工资字段明确标注为“城镇非私营单位在岗职工”，不与居民收入或私营单位工资混用。
- 城市财政新增 5 条：常州 2023 年政府性基金收入 1396.2 亿元、支出 1591.0 亿元；常州 2024 年一般公共预算支出 890.0 亿元、政府性基金收入 986.0 亿元、支出 1023.2 亿元。2024 年三项来自人大公开的预算执行预计值，状态保留 `official_preliminary`，等待最终决算值时可按优先级替换。
- 更新结果：公报补充清单处理 101 行，新增 7 行、其余 94 行按已有更高优先级跳过；财政清单处理 77 行，新增 5 行。新增后 payload 为 4,836 条城市一般指标、944 条财政记录；平均工资已覆盖 15/15 城、2010–2025，苏州零售额 2024 年缺口已补齐。
- 来源：常州统计局 [2024 年工资](https://tjj.changzhou.gov.cn/html/tjj/2025/OPOEMFCL_0702/28760.html)、[2025 年工资](https://tjj.changzhou.gov.cn/html/tjj/2026/OPOEMFCL_0709/29110.html)；苏州统计局 [2024 年工资](https://tjj.suzhou.gov.cn/sztjj/rdwd/202506/67e7a65c402f45f796436d45da431c03.shtml)、[2025 年工资](https://tjj.suzhou.gov.cn/sztjj/rdwd/202606/026a862b9d5e4acfae7e7d4d06d9d15d.shtml)；无锡统计局 [2024 年工资](https://tj.wuxi.gov.cn/doc/2025/06/30/4603407.shtml)、[2025 年工资](https://tj.wuxi.gov.cn/doc/2026/07/08/4801556.shtml)；苏州市商务局 [2024 年 1—12 月商务运行简况](https://commerce.suzhou.gov.cn/szsswj/tjzl/202501/a99f5b6089344854a184d71b642938bd.shtml)；常州市人大 [2023 年决算报告](https://rd.changzhou.gov.cn/html/rd/2024/OPQFJQAA_0630/34224.html)、[2024 年预算执行摘要](https://rd.changzhou.gov.cn/html/rd/2025/ELPOKPHQ_0113/34580.html)。
- 质量复核：两张表复合键重复均为 0，值或来源 URL 为空均为 0；全仓 414 项测试通过，`/api/city-economy/data` 返回 HTTP 200。仍不填常州“全年新增就业”到“城镇新增就业”，也不把常州 2024 预算预计值写成最终决算。

## 2026-08-10 官方源刷新复核

- 运行城市经济组合更新并强制刷新国家统计局城市数据。NBS 抓取 16,243 行，刷新 3,040 行，保留 211 条已发布优先值；发现 11 条官方修订冲突，按来源优先级保留已发布值，未静默覆盖。
- 城市公报指标本轮解析 462 行、写入/更新 316 行、已有官方值跳过 146 行；城市财政决算清单处理 77 行，新增 0 行，保持幂等。当前 `/api/city-economy/data` 为 15 城、城市一般指标 4,836 行、GDP 887 行、财政 944 行、5 个板块、64 个可选指标；官方房价 9,672 行，安居客挂牌 2,505 行。
- `city_indicator_observations` 当前 13,409 行，`regional_fiscal_observations` 当前 8,156 行；城市指标和财政复合键重复组均为 0。缺失城市财政细项、缺失年份和安居客空字段继续保持缺失，不以前月、邻城、区县或省级值替代。
