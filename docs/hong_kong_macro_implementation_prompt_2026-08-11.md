# 香港宏观独立模块与中国外汇储备接入：完整执行提示词

> 使用方法：在新的 Codex 任务中，将本文件作为上下文或直接复制全文发送。  
> 本提示词的目标不是再写一份路线图，而是在审计现有项目后，实际完成数据接入、数据库、API、页面、实证联动分析、测试和状态文档。  
> 项目目录：/mnt/d/claude  
> 编写日期：2026-08-11（America/Denver）

---

## 任务角色

你正在维护一个本地 Python、SQLite 和原生前端组成的研究工具平台。请以“宏观数据工程师 + 研究方法审计者 + 前端产品设计者”的角色完成本任务。

不要只给建议、伪代码、静态 mockup 或空壳页面。只要官方数据源允许，就要把首批数据真正下载、解析、校验、写入数据库，经 API 返回，并在浏览器页面显示。若某个来源被验证、限流、格式变化或网络超时阻断，要保留真实失败状态和证据，完成仍可安全完成的部分，绝不能用搜索结果摘要、手工编造值、商业网站截图值或其他来源的近似值代替。

这是一项实施任务，不是宏观预测任务。所有结论必须区分：

1. 官方原始观测；
2. 项目内派生计算；
3. 描述性相关或领先滞后结果；
4. 解释性假设；
5. 尚未验证的候选关系。

---

## 一、项目背景与已经明确的产品判断

项目当前位于：

    /mnt/d/claude

整体技术栈以现有仓库为准，已知大致结构是：

- Python 标准库 HTTPServer，默认端口 5001；
- services/ 负责数据采集、解析、数据库和 API 逻辑；
- static/ 负责原生 HTML、CSS、JavaScript 页面；
- scripts/ 放置更新、维护、验证和看门狗脚本；
- tests/ 使用 unittest；
- 本地 SQLite 保存观察值、来源和更新状态；
- 不依赖 npm 构建。

现有主要宏观页面包括：

- /china-macro
- /us-macro
- /macro-analytics
- /gdp
- /housing
- /housing-scenario
- /china-rates
- /city-economy
- /fiscal-debt

历史审计曾发现：

- /api/china-macro/data 大约有 6 个板块、143 条序列；
- 项目没有正式的香港宏观模块；
- 现有中国外部板块有海关贸易、商务部投资、外汇局结售汇和跨境收付款，但没有正式接入国家外汇管理局公布的美元外汇储备；
- 央行资产负债表中的“外汇”资产不等于国家外汇管理局公布的外汇储备。

这些是历史审计基线，不是本轮可直接引用的当前事实。实施开始时必须重新从代码、API 和 SQLite 做只读核对，记录实际现状。

已经明确的产品判断如下，除非仓库证据显示存在严重架构冲突，否则不要重新把它变成开放问题：

1. 香港要做成独立宏观模块。
2. 香港暂时不进入“城市经济”，也不作为中国内地十五城、普通城市或省级地区的一个选项。
3. 香港模块的产品定位是“中国的对外窗口、国际金融窗口、贸易转口窗口和资产价格观察窗口”。
4. 香港与内地可以做联动分析，但不能把香港数据简单并入内地全国合计。
5. 内地正式外汇储备应接入 /china-macro 的外部经济板块，同时在香港页面的“中国联动”中提供经过明确口径处理的对照。
6. 商业网站或截图只能作为选题和交互灵感，数据必须回到官方来源；不要抓取 MacroMicro 等商业页面的数据。

建议的新页面和接口：

    /hong-kong-macro
    GET  /api/hong-kong-macro/data
    POST /api/hong-kong-macro/update
    GET  /api/hong-kong-macro/debug

若现有项目对 CSV、任务状态或写权限已有统一路由规范，应复用现有规范。可酌情增加：

    GET /api/hong-kong-macro/export.csv
    GET /api/hong-kong-macro/lead-lag

不要为了追求路由数量而重复现有 API 能力。

---

## 二、最终目标

完成一个可运行、可复现、可审计的“香港宏观”独立页面，并补齐“中国正式外汇储备”。

最终成果至少应包括：

1. 香港独立页面、导航入口和页面说明；
2. 香港住房、综合经济、转口贸易、储备与金融四个首批数据域；
3. 香港与中国内地联动分析页签；
4. 国家外汇管理局正式外汇储备及官方储备资产在中国宏观模块中的清晰接入；
5. 来源登记、原始下载或原始响应留痕、解析、数据库观察层、API、CSV、更新状态；
6. 住房指标的香港—内地领先滞后描述性分析；
7. 数据覆盖、发布日期、最新参考期、修订或暂定值、频率、单位、季调状态和缺失原因；
8. 单元测试、API 检查、数据库核对和浏览器响应式验证；
9. 一份新的状态文档：

    docs/hong_kong_macro_STATUS_2026-08-11.md

如果实施日期已经不是 2026-08-11，状态文档使用实际日期，但不要改本提示词文件的历史日期。

---

## 三、硬性边界

### 3.1 不能做的事情

- 不得把香港放进 /city-economy 的城市选择器。
- 不得把香港当作普通省级行政区与内地省份直接加总。
- 不得抓取、复制或反向工程 MacroMicro 等商业图表的数据。
- 不得从搜索摘要中抄数。
- 不得用新闻稿中的单个最新值伪装成完整历史序列。
- 不得用同名但不同口径的序列静默拼接。
- 不得把人民银行资产负债表“国外资产—外汇”标成国家外汇储备。
- 不得把结售汇、跨境收付款、国际收支、外汇储备互相替代。
- 不得把香港转口出口等同于香港本地生产出口。
- 不得把相关性或领先期写成因果关系或稳定预测规律。
- 不得生成黑箱综合评分来概括“香港经济好坏”。
- 不得删除、覆盖、迁移或清空既有数据库、WAL、SHM、日志和输出。
- 不得因本轮任务顺手重写整个中国宏观或全站前端。
- 不得在未经检查的情况下重启当前服务。
- 不得把“已找到来源”写成“已接入数据”；只有完成下载、解析、入库、API 和页面验证后才能称为已接入。

### 3.2 必须保留的区分

页面、API、代码和文档都必须明确区分以下概念：

**中国内地外汇相关**

- 国家外汇管理局外汇储备，通常以亿美元公布；
- 国家外汇管理局官方储备资产合计；
- 货币黄金、特别提款权、IMF 储备头寸、其他储备资产；
- 人民银行资产负债表中的“外汇”资产，人民币计价；
- 银行结售汇；
- 银行代客涉外收付款或跨境人民币收付；
- 国际收支和国际投资头寸。

**香港外汇与金融相关**

- 香港外币储备资产；
- 外汇基金对应储备；
- 未交收外汇合约及包含该项目的统计口径；
- 货币基础和总结余；
- 港元联系汇率、HIBOR、银行存贷款；
- 人民币存款；
- 外汇储备与货币基础、进口等的覆盖指标，只有官方字段或可审计公式支持时才展示。

**香港贸易相关**

- 进口；
- 港产品出口；
- 转口；
- 整体出口；
- 贸易总额；
- 贸易差额；
- 转口占整体出口比重；
- 按货物来源地、出口目的地和商品类别的分解。

**香港住房相关**

- 差饷物业估价署价格和租金指标；
- 土地注册处收到注册的买卖合约宗数和金额；
- 一手与二手；
- 差饷物业估价署的成交、落成、存量、空置和吸纳；
- 实际签约期与送交登记期之间的时间差。

相似概念不得因图表方便而静默合并。

---

## 四、开始前必须完成的只读侦察

先做侦察，再改代码。至少完成以下检查：

1. 查看根目录和相关项目说明：

       pwd
       git status --short
       rg --files -g 'README*' -g 'AGENTS.md' -g 'CHANGELOG*' -g 'docs/**'

2. 阅读：

   - README.md
   - projects/README.md
   - projects/china_macro/README.md
   - projects/us_macro/README.md
   - 最近的中国宏观、美国宏观、住房、城市经济和分析状态文档
   - docs/macro_data_universe_2026-08-11/source_notes.md
   - docs/us_macro_china_benchmark_2026-08-11/ 下的来源和报告

3. 检查现有代码和数据契约：

   - server.py 的页面和 API 路由；
   - services/china_external_service.py；
   - services/pboc_balance_sheet_service.py；
   - 中国宏观、美国宏观、住房和分析模块的服务文件；
   - static/ 下现有导航、主题、图表组件、CSV、来源弹窗和缺失状态实现；
   - tests/ 下相关测试；
   - 数据库初始化、事务、迁移、来源表和更新日志的现有模式。

4. 从当前运行 API 只读核对：

   - /api/health；
   - /api/china-macro/data；
   - 可能相关的 /api/housing/data、/api/macro-analytics/data；
   - 当前 API 中实际有多少组、多少序列、是否已有香港或正式外储。

5. 从 SQLite 只读核对：

   - 找到项目实际使用的数据库路径；
   - 列出表、索引和观察表 schema；
   - 搜索 jurisdiction、region、indicator_code、indicator_name、source_name 中是否已经出现 Hong Kong、HK、香港、外汇储备、official reserve assets；
   - 区分空壳配置、缺失卡片、真实观察记录；
   - 检查数据库是否为 WAL 模式以及是否存在 -wal、-shm。

6. 检查运行服务：

   - 端口是否监听；
   - 哪个 Windows 或 WSL 进程持有端口；
   - 健康接口是否响应；
   - 看门狗是否运行；
   - 最近日志是否有数据库锁、更新任务或长任务。

7. 在开始迁移或写库前：

   - 只在确实需要 schema 变更时做数据库备份；
   - 对 WAL 数据库使用一致性备份方法，不要只复制主 .db；
   - 记录备份位置和时间；
   - 不把大型数据库或原始下载加入公开 Git。

侦察结论要进入状态文档。不要因为已有历史审计就跳过当前核对。

---

## 五、官方来源优先级与来源探针

所有来源先做低频、合规、字段级探针。优先顺序：

1. 官方 JSON/API；
2. 官方 CSV/XLS/XLSX；
3. 官方 HTML 表格；
4. 官方 PDF；
5. 官方新闻稿只作发布日期、口径说明或最新值交叉验证。

只有前一种不可获得或历史覆盖不足时才使用后一种。每个来源都要记录：

- 机构；
- 数据集或表名；
- 官方页面 URL；
- 实际下载 URL 或 API URL；
- 请求参数；
- 文件格式；
- 数据频率；
- 历史起点；
- 单位；
- 是否季调；
- 初值、修订值或最终值状态；
- 最新参考期；
- 官方发布日期或抓取时间；
- 解析器版本；
- 原始内容 SHA-256 或等价哈希；
- 使用限制和脚注。

### 5.1 香港住房

**差饷物业估价署 Rating and Valuation Department**

官方入口：

https://www.rvd.gov.hk/en/publications/property_market_statistics.html

优先接入该页提供的完整历史 XLS：

- Private Domestic - Price Indices by Class (Territory-wide)，历史可追至 1979；
- Private Domestic - Rental Indices by Class (Territory-wide)，历史可追至 1979；
- Domestic Sales，历史可追至 2002；
- Private Domestic - Completions, Stock, Vacancy and Take-up；
- 如资源和结构稳定，再接平均价格、平均租金及分面积等级指标。

**土地注册处 The Land Registry**

官方统计入口：

https://www.landreg.gov.hk/en/monthly/index.htm

住宅一手和二手买卖：

https://www.landreg.gov.hk/en/monthly/agt-primary.htm

开放数据入口：

https://data.gov.hk/en-data/dataset/hk-lr-data5-landreg

优先接入：

- 住宅楼宇买卖合约宗数；
- 住宅楼宇买卖合约金额；
- 一手宗数与金额；
- 二手宗数与金额；
- 全部楼宇买卖合约作为辅助序列；
- 可选：按金额区间和地区分布。

土地注册处统计是“收到注册”的时间口径。官方开放数据说明指出，交易文书执行与送交注册之间通常存在时间差，可能涉及此前数周。必须在元数据、图表来源说明和领先滞后分析中保留该问题；不要把登记月直接描述为实际签约月。

### 5.2 香港综合经济

**香港政府统计处 Census and Statistics Department**

综合统计数据发布系统：

https://www.censtatd.gov.hk/en/page_8000.html

互动数据查询服务：

https://idds.censtatd.gov.hk/

Web Table 页面和 API 的具体表号必须在实施时从官方元数据确认，不能凭记忆硬编码。首批候选：

- 本地生产总值，名义和实际；
- 实际 GDP 同比和经季调环比；
- 私人消费开支；
- 政府消费开支；
- 本地固定资本形成总额；
- 货物和服务进出口；
- 零售业销货价值和数量指数；
- 综合消费物价指数及同比；
- 经季节性调整失业率；
- 就业人数或劳动人口；
- 服务业活动或行业增加值；
- 访港旅客，如有稳定的政府官方表格或政府旅游统计来源；
- 人口和净迁移只作结构层，不应混入月度周期合计。

季度和月度序列不得用线性插值伪造共同月频。跨频对照需保留原频率，或只在明确的季度聚合层比较。

### 5.3 香港转口贸易

**香港政府统计处 Trade-IDDS**

入口：

https://tradeidds.censtatd.gov.hk/

代表性公共表：

https://tradeidds.censtatd.gov.hk/CommonTable/ETR08a03

API 规格：

https://tradeidds.censtatd.gov.hk/MetadataLink/ApiSpec/API_eng.pdf

首批必须争取接入：

- 进口月度金额；
- 港产品出口月度金额；
- 转口月度金额；
- 整体出口月度金额；
- 贸易总额；
- 贸易差额；
- 转口占整体出口比重；
- 中国内地作为货物来源地的转口；
- 中国内地作为目的地的转口或整体出口；
- 主要来源地、目的地和商品类别 Top N。

派生恒等式必须明确：

    total_exports = domestic_exports + re_exports
    total_trade = imports + total_exports
    trade_balance = total_exports - imports
    re_export_share = re_exports / total_exports

派生值要标注 derived，并设容忍度检查官方舍入误差。不要把“来自中国内地的货物”与“出口到中国内地”混为一谈。

### 5.4 香港储备与金融

**香港金融管理局 HKMA**

外币储备资产 API 文档：

https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/ef-fc-resv-assets/fc-resv-assests/

API：

https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/ef-fc-resv-assets/fc-resv-assests

货币统计 API 文档：

https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/financial/monetary-statistics/

银行统计 API 文档：

https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/financial/banking-statistics/

贷款分类 API 文档：

https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/loans-by-type-lb/

首批指标：

- 外币储备资产总额；
- 外汇基金外币储备资产；
- 土地基金外币储备资产，如历史字段存在；
- 未交收外汇合约；
- 包含未交收外汇合约的广义展示值，必须使用官方名称；
- 货币基础；
- 总结余；
- M1、M2；
- 港元兑美元；
- 名义有效汇率指数；
- 隔夜和 3 个月 HIBOR；
- 最优惠贷款利率或贴现窗基本利率；
- 银行客户存款；
- 人民币存款；
- 银行贷款及在港使用贷款；
- 贸易融资贷款，如官方分类可稳定取得。

HKMA API 要检查分页、offset、返回状态、datasize、字段缺失、旧新 segment 和重分类脚注。单次网络超时不等于来源不存在；进行有限次数、带超时和间隔的重试，但不要无限轮询。

### 5.5 中国内地正式外汇储备

**国家外汇管理局 SAFE**

外汇储备栏目：

https://www.safe.gov.cn/safe/whcb/

官方储备资产栏目：

https://www.safe.gov.cn/safe/gfcbzc/index.html

首批接入：

- 外汇储备；
- 货币黄金的美元价值；
- 货币黄金实物数量；
- 特别提款权；
- IMF 储备头寸；
- 其他储备资产；
- 官方储备资产合计；
- 如果官方同时给出 SDR 口径，作为独立单位序列保存，不能与美元值拼接。

正式外汇储备优先写入现有中国宏观观察层和“外部经济”板块。页面必须明确：

- SAFE 外汇储备通常是美元价值；
- 人民银行资产负债表“外汇”是人民币资产负债表口径；
- 两者不应画成一条连续序列；
- 结售汇和跨境收付款是流量，储备是存量；
- 黄金实物数量和美元估值是不同变量。

若 SAFE 历史文件分年度、格式不一致，要按年度解析并保留原始来源，不得只接最新年度后声称“完整历史”。

---

## 六、首批指标注册表

实际代码命名应遵循项目现有风格。若没有统一规范，可参考下列稳定、机器可读的 indicator_code。

### 6.1 香港住房

| indicator_code | 中文名 | 频率 | 单位 | 原始或派生 | 首选来源 |
|---|---|---:|---|---|---|
| hk_rvd_private_domestic_price_index | 私人住宅售价指数 | 月 | index | 原始 | RVD |
| hk_rvd_private_domestic_rent_index | 私人住宅租金指数 | 月 | index | 原始 | RVD |
| hk_lr_residential_asp_count | 住宅买卖合约宗数 | 月 |宗 | 原始 | Land Registry |
| hk_lr_residential_asp_value | 住宅买卖合约金额 | 月 | HKD million | 原始 | Land Registry |
| hk_lr_primary_asp_count | 一手住宅买卖合约宗数 | 月 | 宗 | 原始 | Land Registry |
| hk_lr_secondary_asp_count | 二手住宅买卖合约宗数 | 月 | 宗 | 原始 | Land Registry |
| hk_lr_primary_asp_value | 一手住宅买卖合约金额 | 月 | HKD million | 原始 | Land Registry |
| hk_lr_secondary_asp_value | 二手住宅买卖合约金额 | 月 | HKD million | 原始 | Land Registry |
| hk_rvd_private_domestic_completions | 私人住宅落成量 | 年或官方频率 | units | 原始 | RVD |
| hk_rvd_private_domestic_stock | 私人住宅存量 | 年或官方频率 | units | 原始 | RVD |
| hk_rvd_private_domestic_vacancy | 私人住宅空置量或空置率 | 年或官方频率 | units 或 % | 原始 | RVD |
| hk_rvd_private_domestic_take_up | 私人住宅吸纳量 | 年或官方频率 | units | 原始 | RVD |

RVD 和土地注册处都可能出现“销售”统计。两者若定义、日期或覆盖不同，保留不同代码和清晰来源，不要去重为一个指标。

### 6.2 香港综合经济

| indicator_code | 中文名 | 频率 | 单位 | 说明 |
|---|---|---:|---|---|
| hk_real_gdp | 实际 GDP | 季 | 官方链量或指数单位 | 保留价格基期 |
| hk_real_gdp_yoy | 实际 GDP 同比 | 季 | % | 优先官方公布值 |
| hk_real_gdp_qoq_sa | 实际 GDP 经季调环比 | 季 | % | 明确 SA |
| hk_nominal_gdp | 名义 GDP | 季 | HKD million | 不与实际值混轴 |
| hk_private_consumption | 私人消费开支 | 季 | 官方单位 | 标注名义或实际 |
| hk_gross_domestic_fixed_capital_formation | 本地固定资本形成总额 | 季 | 官方单位 | 标注名义或实际 |
| hk_retail_sales_value | 零售销货价值 | 月 | HKD million 或指数 | 遵循官方表 |
| hk_retail_sales_volume_index | 零售销货数量指数 | 月 | index | 保留基期 |
| hk_composite_cpi | 综合消费物价指数 | 月 | index | 保留基期 |
| hk_composite_cpi_yoy | 综合消费物价同比 | 月 | % | 优先官方值 |
| hk_unemployment_rate_sa | 经季调失业率 | 月或移动三个月 | % | 保留官方参考期标签 |
| hk_total_employment | 总就业人数 | 官方频率 | persons | 不伪造月值 |

### 6.3 香港贸易

| indicator_code | 中文名 | 频率 | 单位 | 原始或派生 |
|---|---|---:|---|---|
| hk_trade_imports | 进口 | 月 | HKD million | 原始 |
| hk_trade_domestic_exports | 港产品出口 | 月 | HKD million | 原始 |
| hk_trade_re_exports | 转口 | 月 | HKD million | 原始 |
| hk_trade_total_exports | 整体出口 | 月 | HKD million | 原始或经恒等式核对 |
| hk_trade_total | 贸易总额 | 月 | HKD million | 派生或官方 |
| hk_trade_balance | 贸易差额 | 月 | HKD million | 派生 |
| hk_trade_re_export_share | 转口占整体出口比重 | 月 | % | 派生 |
| hk_trade_re_exports_mainland_origin | 中国内地来源转口 | 月 | HKD million | 原始分解 |
| hk_trade_re_exports_mainland_destination | 输往中国内地转口 | 月 | HKD million | 原始分解 |

Top N 伙伴和商品明细适合放专门的维度表或 observation 的 dimension_json 中，取决于现有项目模式；不要为每个伙伴硬编码成前端常量。

### 6.4 香港储备和金融

| indicator_code | 中文名 | 频率 | 单位 | 来源 |
|---|---|---:|---|---|
| hk_fx_reserve_assets_total | 外币储备资产总额 | 月 | USD million | HKMA |
| hk_fx_reserve_assets_exchange_fund | 外汇基金外币储备资产 | 月 | USD million | HKMA |
| hk_fx_reserve_assets_land_fund | 土地基金外币储备资产 | 月 | USD million | HKMA |
| hk_fx_unsettled_contracts_total | 未交收外汇合约总额 | 月 | USD million | HKMA |
| hk_monetary_base | 货币基础 | 月 | HKD million | HKMA |
| hk_aggregate_balance | 总结余 | 月 | HKD million | HKMA |
| hk_m2_total | M2 总计 | 月 | HKD million | HKMA |
| hk_hibor_overnight | 隔夜 HIBOR | 月或日后聚合 | % | HKMA |
| hk_hibor_3m | 3 个月 HIBOR | 月或日后聚合 | % | HKMA |
| hk_customer_deposits_total | 客户存款 | 月 | HKD million | HKMA |
| hk_rmb_deposits | 人民币存款 | 月 | RMB million | HKMA |
| hk_loans_total | 贷款及垫款 | 月 | HKD million | HKMA |
| hk_trade_finance_loans | 进出口和转口融资贷款 | 月 | HKD million | HKMA |

### 6.5 中国内地官方储备资产

| indicator_code | 中文名 | 频率 | 单位 | 来源 |
|---|---|---:|---|---|
| cn_safe_fx_reserves_usd | 外汇储备 | 月 | USD 100 million | SAFE |
| cn_safe_monetary_gold_usd | 货币黄金价值 | 月 | USD 100 million | SAFE |
| cn_safe_monetary_gold_quantity | 货币黄金实物量 | 月 | 官方单位 | SAFE |
| cn_safe_sdr_holdings_usd | 特别提款权 | 月 | USD 100 million | SAFE |
| cn_safe_imf_reserve_position_usd | IMF 储备头寸 | 月 | USD 100 million | SAFE |
| cn_safe_other_reserve_assets_usd | 其他储备资产 | 月 | USD 100 million | SAFE |
| cn_safe_official_reserve_assets_total_usd | 官方储备资产合计 | 月 | USD 100 million | SAFE |

指标注册表必须包含中文名、英文名、短说明、频率、单位、币种、季调状态、价格口径、原始或派生、来源、开始期、结束期、最新发布日期和脚注。

---

## 七、数据模型与可审计性

先复用现有观察层、来源表和更新日志。只有现有 schema 无法表达香港的 jurisdiction、维度和版本时，才新增表。

若需要独立表，可参考：

    hong_kong_macro_observations
    hong_kong_macro_sources
    hong_kong_macro_update_runs
    hong_kong_macro_vintages

观察值至少要能表达：

- indicator_code；
- jurisdiction，固定为 HK，但前端显示“香港”；
- category；
- subcategory；
- period_start 或 period_date；
- period_label；
- frequency；
- value；
- unit；
- currency；
- seasonal_adjustment；
- price_basis；
- transformation；
- dimension_key 和 dimension_value，或可审计的 dimension_json；
- status，例如 actual、provisional、revised、derived；
- source_id；
- source_url；
- source_table；
- release_date；
- vintage_date；
- retrieved_at；
- raw_sha256；
- parser_version；
- note。

推荐唯一键包含：

    indicator_code + period + dimensions + vintage

若项目当前只保留最新版本，至少把官方修订状态和抓取时间留下；不要让后一次抓取静默覆盖且无法解释。

原始响应和派生结果分层：

1. raw：官方原始 JSON、XLS、XLSX、HTML 或 PDF 快照；
2. staged：解析后的规范化记录；
3. observation：通过验证的正式观察值；
4. derived：同比、环比、份额、差额、基期化和领先滞后结果。

原始大文件放在项目既有的 gitignored 数据目录中，不要进入公开 Git。若项目没有合适目录，再新增小而清晰的目录，并更新 .gitignore，而不是把二进制塞进 docs。

所有写入采用事务。推荐流程：

    fetch -> raw snapshot -> parse -> schema validation -> algebra checks
          -> staging -> transactional upsert -> update log -> API

任何硬门禁失败时：

- 不覆盖上一版有效数据；
- update run 标记 failed 或 partial；
- 保存错误类型、来源、HTTP 状态、解析阶段和简短消息；
- API 继续返回上一版有效数据，并显著显示 stale 或 partial。

---

## 八、采集与更新实现

### 8.1 网络行为

- 设置明确 User-Agent；
- 设置合理连接和读取超时；
- 采用有限重试；
- 重试间隔有上限；
- 不并发轰炸政府网站；
- 尊重验证码、访问限制和 robots 或站点使用条件；
- 发现验证页立即停止该来源，不尝试绕过；
- 搜索引擎只用于定位官方入口，不用于取数；
- 对 HKMA 和 Trade-IDDS 的分页完整遍历，但先用小页探针验证字段。

### 8.2 格式处理

- XLS/XLSX：保留工作表名、表头行、单位和脚注；合并单元格要显式处理；
- HTML：锁定官方表格语义字段，不用脆弱的全页纯文本正则；
- JSON：验证顶层状态、返回行数、分页、日期和数值类型；
- PDF：只有没有机器可读版本时使用；记录抽取页和表名，并做人工 spot check；
- 中英文双语表：通过字段定义匹配，不能只靠列位置；
- 千位分隔符、括号负数、破折号、空值、暂定值符号和百分号都要规范化；
- 不把 “-”、空白、n.a.、not available 解析成零。

### 8.3 增量更新

每个来源支持：

- 默认增量更新；
- 首次历史回填；
- 明确的起止期；
- dry-run 或 parse-only，如果现有项目已有同类模式；
- force 只允许本机或受管理权限保护的请求；
- 更新任务状态可从 debug API 查看。

POST 更新接口必须复用全站现有的远程写保护，不得因新模块绕过 ALLOW_REMOTE_WRITES 或 ADMIN_TOKEN 规则。

### 8.4 调度

首版不必立即新增后台自动调度。先完成稳定的手动增量更新和可观测状态。只有现有调度器结构非常清晰且测试充分时，才添加低频调度，并提供环境变量关闭开关。

---

## 九、API 契约

实际字段应尽量与 /api/china-macro/data 和 /api/us-macro/data 保持风格一致。建议响应结构：

    {
      "meta": {
        "module": "hong_kong_macro",
        "jurisdiction": "HK",
        "title": "香港宏观",
        "positioning": "中国的对外窗口",
        "generated_at": "...",
        "latest_reference_period": "...",
        "status": "ok|partial|stale|empty",
        "series_count": 0,
        "observation_count": 0
      },
      "groups": [
        {
          "id": "housing",
          "label": "住房",
          "series": []
        }
      ],
      "source_coverage": [],
      "quality": {
        "warnings": [],
        "missing": [],
        "failed_sources": []
      },
      "derived": {
        "trade_identities": {},
        "lead_lag": {}
      }
    }

每条 series 至少返回：

- indicator_code；
- name_zh；
- name_en；
- description；
- unit；
- frequency；
- currency；
- seasonal_adjustment；
- source_name；
- source_url；
- source_table；
- first_period；
- last_period；
- release_date；
- latest_status；
- transformations_supported；
- observations。

每个 observation 至少返回：

- period；
- value；
- status；
- release_date 或 retrieved_at；
- 是否 derived；
- 缺失时的 reason。

数据接口应支持或复用现有方式支持：

- start；
- end；
- group；
- indicators；
- transform：level、yoy、mom、qoq、index100；
- source；
- format 或 CSV 导出。

不要一次把所有伙伴和商品的全量维度无条件送到前端。如果数据量大，增加明确筛选参数或单独维度端点。

debug API 至少返回：

- 数据库路径的安全摘要，而非暴露私密绝对路径给远程用户；
- 表是否存在；
- 行数、序列数、首末期；
- 各来源最后成功、最后尝试和错误；
- 最新原始哈希；
- 缺失或异常序列；
- 当前是否有更新任务；
- 迁移版本；
- 派生校验结果。

---

## 十、页面信息架构

页面标题：

    香港宏观

副标题建议：

    中国的对外窗口：住房、经济、转口贸易、储备与金融条件

定位说明必须简短但明确：

- 香港是独立统计辖区和国际金融、贸易窗口；
- 页面不把香港并入内地城市合计；
- “中国联动”只做平行、标准化或机制连接分析。

建议页面路径：

    /hong-kong-macro

建议一级页签：

1. 总览；
2. 住房；
3. 经济；
4. 转口贸易；
5. 储备与金融；
6. 中国联动。

导航位置：

- 在“中国宏观”一级导航下增加“香港窗口”或“香港宏观”；
- 不放进“城市经济”的城市列表；
- /china-macro 外部板块可增加一个通往香港页面的说明性链接；
- 香港页回链 /china-macro、/housing、/china-rates 和 /macro-analytics；
- 更新 README.md 和 projects/china_macro/README.md 的模块清单及边界说明。

### 10.1 页面顶部

包含：

- 标题和定位；
- 数据状态：正常、部分、陈旧、无数据；
- 最后成功更新时间；
- 最新参考期；
- 来源覆盖数；
- 手动更新按钮；
- CSV 导出；
- 来源与方法说明入口。

更新按钮必须显示任务状态，避免用户重复提交。远程只读访问时按钮禁用或显示权限说明。

### 10.2 总览页

总览不要堆满所有图。用 5 至 7 张最新卡片和一张“传导地图”建立叙事：

**建议卡片**

- 私人住宅售价指数及同比；
- 住宅买卖合约宗数及同比；
- 实际 GDP 同比；
- 转口金额及转口占比；
- 香港外币储备；
- 3 个月 HIBOR；
- 中国内地外汇储备，可作为联动卡而非香港本地卡。

每张卡必须显示：

- 最新值；
- 参考期；
- 变化口径；
- 单位；
- 来源；
- 暂定、修订或陈旧状态。

**传导地图**

可以使用简洁的 HTML/CSS 流程，而不必上复杂图形库：

    全球需求和金融条件
              ↓
    香港转口贸易与资金条件
       ↙              ↘
    香港实体经济      香港资产价格
              ↓
       与中国内地的贸易、资金和预期联动

这只是页面导航和分析框架，不是因果识别结论。

### 10.3 住房页

建议图组：

1. 私人住宅售价指数与租金指数；
2. 售价同比与租金同比，小多图或可切换；
3. 住宅买卖合约宗数；
4. 住宅买卖合约金额；
5. 一手与二手宗数；
6. 一手与二手金额；
7. 落成、存量、空置和吸纳，保留年度频率；
8. 可选的面积等级或价格区间分布。

不要把指数、宗数和港币金额强塞在同一纵轴。优先使用小多图、切换器或独立图。

页面显著说明：

- 土地注册处按收到注册时间统计；
- 登记与实际交易存在时间差；
- 差饷物业估价署和土地注册处并非完全相同统计口径；
- 月度同比可能受春节、政策和基数影响。

### 10.4 经济页

建议图组：

1. 实际 GDP 同比；
2. 实际 GDP 经季调环比；
3. 私人消费、固定资本形成及主要 GDP 支出项；
4. 零售价值与数量；
5. 综合 CPI；
6. 经季调失业率和就业；
7. 访港旅客或服务业活动，只有官方稳定数据完成接入后再显示。

季度 GDP 与月度指标采用上下排列，不进行虚假月频插值。

### 10.5 转口贸易页

建议图组：

1. 进口、港产品出口、转口和整体出口；
2. 转口占整体出口比重；
3. 贸易差额；
4. 滚动 12 个月总额；
5. 主要货物来源地；
6. 主要出口目的地；
7. 中国内地来源和目的地的两种不同联动；
8. 主要商品类别。

提供：

- 金额、同比、份额切换；
- 月度与滚动 12 月切换；
- 伙伴或商品 Top N；
- 清晰的来源地与目的地区分；
- 恒等式核对状态。

### 10.6 储备与金融页

建议图组：

1. 香港外币储备资产；
2. 外汇基金、土地基金及未交收合约分项；
3. 货币基础和总结余；
4. 隔夜、3 个月 HIBOR、基本利率或最优惠利率；
5. M2、客户存款和贷款；
6. 人民币存款；
7. 贸易融资贷款；
8. 香港与内地储备的标准化平行比较。

香港储备以美元计价，货币基础以港币计价。不要直接用同一数值轴对比。可以：

- 分图；
- 使用双图同步时间；
- 将两条序列统一基期为 100；
- 计算覆盖率时写出公式、汇率来源和单位转换。

### 10.7 中国联动页

该页不是把香港“并入中国合计”，而是回答：

- 香港住房量价是否在某些历史阶段领先内地住房指标；
- 香港转口是否与内地出口、全球需求或制造周期同步；
- 香港金融条件如何与美元利率、人民币汇率和内地流动性平行变化；
- 香港和内地外汇储备在不同制度口径下如何比较。

首版重点做住房领先滞后，贸易和金融先提供配对图与定义，除非数据质量足够再扩展正式分析。

---

## 十一、视觉与交互要求

延续项目现有暗色研究工作台风格，不另起一套设计系统。实现前先观察已有页面的导航、卡片、筛选器、图表、来源弹窗和移动端断点。

要求：

- 桌面 1440 像素正常；
- 窄屏 390 像素无横向溢出；
- 图表标题、单位、参考期和来源可读；
- 不仅靠红绿表示好坏；
- 颜色在各页签保持语义一致；
- 香港使用稳定主色，内地对照使用另一稳定主色；
- 原始、派生、暂定、缺失采用不同视觉状态；
- tooltip 显示值、单位、参考期、状态和来源；
- 图例可显隐；
- 时间范围自由选择；
- 默认范围有研究意义，不只显示最近几个月；
- CSV 导出的时间范围、指标和转换与当前筛选一致；
- 页面加载、无数据、部分失败、陈旧数据和更新中均有明确状态；
- 不显示空白图框冒充“模块已完成”；
- 来源弹窗或抽屉可以逐序列查看官方链接、表名、覆盖期和脚注。

图表选择原则：

- 同单位多序列才适合同图；
- 不同单位优先小多图；
- 指数对标可用共同基期 100，但保留原始值入口；
- 百分比轴与金额轴分开；
- 横截面 Top N 用条形图；
- 结构份额用堆叠条或折线，不用难比较的饼图；
- 领先滞后相关用以零为中心的条形图或折线；
- 滚动领先期用点线图，并显示可用样本数和不稳定状态。

---

## 十二、转换和比较口径

支持的转换必须由指标元数据约束，不是所有指标都无条件支持所有转换。

### 12.1 基础转换

- level：原始水平；
- yoy：与上年同期比较；
- mom：月环比；
- qoq：季环比；
- qoq_sa：仅对官方季调序列；
- rolling_12m：月度流量的滚动 12 月合计；
- index100：共同基期标准化为 100；
- share：分子与分母定义清晰的结构份额。

### 12.2 计算规则

- 同比要求存在准确的上年同期；
- 月环比不对季度序列计算；
- 不对移动三个月失业率再假装成单月点估计；
- 存量通常不做滚动合计；
- 流量和存量不得相加；
- 指数换基要记录基期；
- 季节性明显的月度流量默认展示同比或滚动 12 月；
- 官方已经发布增长率时，优先保留官方增长率，同时可计算一条 audit 值做核对；
- 除非有明确官方方法，不做季调；
- 不用前向填充或线性插值制造缺失观察。

### 12.3 中港比较模式

每个比较必须标记模式：

- aligned：定义、频率和单位高度一致，可直接对照；
- normalized：概念相近但规模或单位不同，统一基期或标准化；
- parallel_only：只能并列观察，不能直接求差；
- linked：贸易、资本或供应链上存在明确连接方向；
- not_comparable：定义差异过大，页面只解释，不画比较结论。

香港与内地外储通常适合 normalized 或 parallel_only；香港转口与内地出口可根据具体来源地、目的地定义使用 linked；住房价格指数必须先说明新房、二手、私人住宅、城市范围和指数方法。

---

## 十三、香港住房领先内地的实证设计

不要预设“香港领先内地 6 个月”或任何固定答案。页面应回答：

1. 在哪些指标配对中，历史最大相关出现在香港领先；
2. 最佳领先期是否随时间变化；
3. 不同内地指标、城市和样本窗口是否一致；
4. 样本是否足够；
5. 结果是否可能来自共同趋势、自相关、登记时差或共同外部冲击。

### 13.1 首批指标配对

至少评估：

- 香港私人住宅售价指数同比 vs 内地一线城市新建商品住宅价格指数同比；
- 香港私人住宅售价指数同比 vs 内地一线城市二手住宅价格指数同比；
- 香港住宅买卖合约宗数同比 vs 内地商品房销售面积同比；
- 香港住宅买卖合约金额同比 vs 内地商品房销售额同比；
- 若全国月度原始量价序列质量不足，分别对北京、上海、广州、深圳做配对，不要用缺失城市均值。

“一线城市指数”若由项目派生，必须公开：

- 城市列表；
- 简单平均还是加权；
- 缺失处理；
- 新房与二手是否分开；
- 是否使用国家统计局 70 城环比指数链式构造；
- 是否因换基或方法调整产生断点。

### 13.2 频率和转换

- 统一到月度时，只使用原本就是月度的序列；
- 主要分析使用同比增长率或对数同比，避免共同趋势制造虚高相关；
- 成交宗数可额外测试对数差分或经季节性稳健的滚动指标；
- 至少保留 level/index100 图作为经济含义背景，但不把水平相关作为主要领先证据；
- 明确排除不完整的最新月份；
- 不插值；
- 最少有效重叠样本建议 60 个月，低于门槛显示 insufficient_sample。

### 13.3 领先期符号

统一定义：

    corr_at_lag(k) = corr(HK_t, Mainland_(t+k))

因此：

- k > 0：香港指标领先内地 k 个月；
- k = 0：同期；
- k < 0：内地领先香港 abs(k) 个月。

代码、API、tooltip、CSV、测试和文档全部使用同一个符号定义。

必须写一个合成数据单元测试：人为构造 Mainland_(t+6) 与 HK_t 同步，验证输出最佳 lag_months = 6。该测试是防止符号反转的硬门禁。

### 13.4 估计范围

- 全样本交叉相关：-24 至 +24 月；
- 滚动窗口：优先 60 月和 120 月；
- 每个窗口记录有效样本数；
- 报告最大绝对相关和最大正相关时要区分；
- 不只显示一个“最佳月数”，必须显示完整相关曲线；
- 对相邻滞后高度接近时显示区间或“不唯一”；
- 对多重滞后搜索不要伪装成单一先验显著性检验；
- 如果不做 block bootstrap 或其他对自相关稳健的区间，明确标记为 descriptive；
- 可选做 block bootstrap，但必须记录 block 长度、重复次数和随机种子，且资源开销可控。

### 13.5 稳定性判定

页面可显示以下描述性指标：

- 全样本最佳领先期；
- 全样本相关系数；
- 滚动窗口最佳领先期中位数；
- 香港领先窗口占比；
- 最佳领先期落在某个相邻区间的占比；
- 正负方向翻转次数；
- 最近窗口是否与历史中位数一致。

只有同时满足下列条件时，才可使用“历史上相对稳定的领先关系”：

- 多个滚动窗口方向一致；
- 最佳滞后不是只由一个异常阶段驱动；
- 至少两个合理的内地对照指标给出近似结果；
- 结果对同比、差分或合理平滑不极端敏感；
- 样本量足够；
- 页面同时显示非因果和登记时差警告。

否则使用：

- “该样本期最大相关出现在……”
- “领先期随窗口变化较大”
- “未发现稳定领先关系”
- “样本不足，暂不估计”

不得使用：

- “香港一定领先内地 X 个月”
- “可据此预测内地房价”
- “香港导致内地房价变化”

### 13.6 领先滞后页面组件

至少包含：

1. 指标配对选择器；
2. 转换选择器；
3. 样本区间；
4. 两条标准化时间序列；
5. -24 至 +24 的相关曲线；
6. 最佳滞后、相关和有效样本卡片；
7. 60 月或 120 月滚动最佳滞后；
8. 方法和符号说明；
9. 数据来源和定义差异；
10. 非因果、修订、登记时差和多重搜索 caveat。

---

## 十四、数据质量门禁

### 14.1 通用检查

每条序列检查：

- 指标代码存在且在注册表中；
- 日期可解析且属于合理范围；
- 频率与日期一致；
- 数值可解析；
- 单位不为空；
- 观察值按期排序；
- 无重复唯一键；
- 不把缺失转为零；
- 没有意外未来参考期；
- 首末期与来源声明一致；
- 最新期没有因表格中的空白未来月份写成零；
- 原始行数、有效行数、拒绝行数可追踪；
- hash 和 retrieved_at 存在；
- 来源 URL 指向官方页面或文件。

### 14.2 住房检查

- 一手宗数 + 二手宗数约等于总宗数；
- 一手金额 + 二手金额约等于总金额；
- 宗数为非负整数；
- 金额为非负；
- 价格和租金指数基期记录完整；
- 年度存量、落成、空置、吸纳不被伪装成月度；
- RVD 与 Land Registry 不静默混表。

### 14.3 贸易检查

- 港产品出口 + 转口约等于整体出口；
- 进口 + 整体出口约等于贸易总额；
- 贸易差额等于整体出口减进口；
- 转口占比在 0 至 100% 合理范围；
- 伙伴或商品分项不超过总额的异常情况要记录舍入、未分类或定义差异；
- 来源地与目的地字段不可互换；
- HKD million 与其他单位不混用。

### 14.4 香港储备和金融检查

- 外汇基金和土地基金分项与总额按官方适用期核对；
- 未交收外汇合约保持独立；
- USD million、HKD million、RMB million 不混轴或静默转换；
- 新旧 segment 重分类断点有元数据；
- API datasize 与实际分页记录数一致；
- 利率单位是百分比年率，不乘错 100。

### 14.5 中国内地储备检查

- 外汇储备、黄金、SDR、IMF 头寸、其他资产与官方储备总额按官方舍入容忍度核对；
- 美元和 SDR 两套口径独立；
- 黄金数量与价值独立；
- SAFE 与 PBOC 序列代码、名称、单位和来源完全不同；
- 逐年度来源拼接前做重叠月份一致性检查；
- 最新年度的尚未发布月份保持缺失。

### 14.6 发布和新鲜度

每个指标计算：

- latest_period；
- latest_release_date；
- expected_frequency；
- expected_next_release，只有可由官方日历或稳定规则支持时；
- freshness_days；
- freshness_status：current、due、stale、unknown；
- missing_reason。

不要仅用抓取时间判断数据新鲜度。

---

## 十五、测试与验证

先识别现有测试命名和 fixture 方式，再新增最小而完整的测试。

建议新增或扩展：

- tests/test_hong_kong_macro_service.py
- tests/test_hong_kong_macro_routes.py
- tests/test_hong_kong_macro_parsers.py
- tests/test_hong_kong_macro_lead_lag.py
- tests/test_china_external_reserves.py
- 现有导航或页面测试

至少覆盖：

1. RVD XLS 解析；
2. Land Registry HTML、JSON 或 XLS 解析；
3. Trade-IDDS JSON 解析和分页；
4. HKMA JSON 解析和分页；
5. SAFE 年度 HTML/XLS/XLSX/PDF 中实际采用格式的解析；
6. 缺失、破折号、括号负数、百分号、暂定值；
7. 重复期和重复唯一键；
8. 住房一手加二手恒等式；
9. 贸易恒等式；
10. SAFE 官方储备合计；
11. 更新失败不覆盖上一版有效数据；
12. 数据接口 schema；
13. debug 接口状态；
14. CSV 内容、编码、字段和筛选；
15. 远程写保护；
16. 合成数据领先期符号测试；
17. 不足 60 个月返回 insufficient_sample；
18. 页面路由和导航链接；
19. 页面无数据和 partial 状态；
20. 现有中国宏观、住房和全站路由不回归。

优先使用 Windows Python 环境：

    cd /mnt/d/claude
    PYTHONIOENCODING=utf-8 python.exe -m unittest discover -s tests -p "test_*hong_kong*.py" -v
    PYTHONIOENCODING=utf-8 python.exe -m unittest discover -s tests -p "test_*macro*.py" -v
    PYTHONIOENCODING=utf-8 python.exe -m unittest discover -s tests -q

根据实际环境调整引号，但要记录最终可复现命令。

另做：

    python.exe -m py_compile <所有本轮修改的 Python 文件>
    git diff --check
    git status --short

### 15.1 数据库验证

通过只读 SQL 核对：

- 表、索引和唯一键；
- 每个来源行数；
- 每条序列首末期；
- 最新值和来源；
- 重复记录数；
- NULL 与零；
- 香港记录没有进入城市经济表；
- SAFE 正式外储没有被写成 PBOC foreign_exchange；
- 失败更新没有造成行数异常下降。

### 15.2 API 验证

在不破坏现有服务的前提下检查：

- /api/health；
- /api/hong-kong-macro/data；
- /api/hong-kong-macro/debug；
- /api/hong-kong-macro/export.csv；
- /api/china-macro/data 中 SAFE 外储；
- update 接口的本机权限和任务状态。

WSL 调 Windows localhost 时优先使用 curl.exe。保存关键响应摘要，不要把超大 JSON 全部贴进状态文档。

### 15.3 浏览器验证

先检查当前服务、端口、进程、健康、看门狗和日志，再决定是否需要重启。若必须重启，使用项目已有安全方式，不能直接杀掉未知进程。

浏览器至少验证：

- 页面能打开；
- 导航入口正确；
- 香港不在城市经济选择器；
- 6 个页签正常；
- 图表有真实数据或明确缺失状态；
- 时间筛选、转换、图例、来源、CSV 正常；
- 更新按钮状态清晰；
- 1440 像素桌面布局；
- 390 像素窄屏布局；
- 无横向溢出；
- 控制台无关键错误；
- 网络请求无 404 或 schema 错误；
- 领先滞后符号说明与输出一致。

可以使用项目现有浏览器测试或 Playwright。保留关键截图到 gitignored 的测试输出或 docs 下的小型验证资源，遵循现有项目惯例。

---

## 十六、实施顺序

按以下阶段推进。每一阶段都要有可验证产出。

### Phase 0：侦察和设计冻结

- 完成代码、页面、API、数据库、运行状态和来源探针；
- 确定复用哪些现有抽象；
- 冻结首批指标注册表；
- 明确 schema 是否需要迁移；
- 记录官方源的真实字段、频率和历史覆盖。

### Phase 1：中国内地正式外汇储备

优先完成 SAFE：

- 历史回填；
- 观察层；
- API；
- /china-macro 外部板块；
- 与 PBOC 外汇资产的定义区分；
- 测试和来源覆盖。

这是范围明确、研究价值高的首个可交付切片。

### Phase 2：香港储备与金融

- HKMA 外币储备；
- 货币基础和 HIBOR；
- 必要的银行存贷款；
- API 和页面储备页签；
- 与内地外储的 normalized 或 parallel_only 对照。

### Phase 3：香港住房

- RVD 售价、租金；
- Land Registry 宗数、金额、一手、二手；
- 住房页面；
- 登记时差和口径说明；
- 数据恒等式。

### Phase 4：香港转口贸易

- 进口、港产品出口、转口、整体出口；
- 转口占比、贸易差额；
- 中国内地来源和目的地；
- 伙伴和商品 Top N；
- 贸易页面和恒等式。

### Phase 5：香港综合经济

- GDP；
- 消费和投资；
- 零售；
- CPI；
- 就业失业；
- 经济页面。

### Phase 6：中国联动

- 配对定义；
- 住房全样本与滚动领先滞后；
- 贸易和金融配对图；
- 方法说明、CSV 和测试。

### Phase 7：全站整合与交付

- 导航；
- README；
- 状态文档；
- 全套测试；
- 数据库、API、浏览器验收；
- 最终差异和未完成项说明。

若某一官方来源被阻断，不要让整个项目停在空白页。将该来源标成 failed 或 pending，继续完成其他独立来源；但不得用替代数据伪装完成。

---

## 十七、文件修改原则

- 使用 apply_patch 做手工代码和文档编辑；
- 不覆盖用户现有未提交改动；
- 如果工作树已有脏文件，先识别归属，避开无关修改；
- 不进行 git reset --hard、checkout -- 或批量删除；
- 不提交、不推送、不建 PR，除非用户随后明确要求；
- 不把数据库、WAL、SHM、原始大文件或密钥加入 Git；
- 新增代码保持清晰英文注释和可读变量名；
- 复用现有 CSS、组件和 API 工具；
- 避免无关格式化造成巨大 diff；
- 若新增 schema，迁移应幂等；
- 若新增环境变量，更新 README 和示例配置，但不写入真实密钥；
- 修改管线后必须更新状态文档。

---

## 十八、状态文档要求

创建：

    docs/hong_kong_macro_STATUS_<实际日期>.md

至少包含：

1. 任务目标；
2. 实施前审计；
3. 产品边界：香港独立、不是城市经济；
4. 修改文件；
5. 数据库表和迁移；
6. 指标清单；
7. 每个指标的来源、覆盖期、频率、单位、最新参考期；
8. 实际下载和解析结果；
9. 质量门禁和恒等式结果；
10. API 路由和示例响应摘要；
11. 页面与交互；
12. 领先滞后方法和符号；
13. 测试命令与精确结果；
14. 浏览器验证尺寸和结果；
15. 服务是否重启以及如何重启；
16. 已知缺口、被阻断来源和错误证据；
17. 后续 P1/P2；
18. 数据与研究解释限制；
19. Changelog。

不要写“全部完成”这种无法审核的笼统表述。逐项说明 downloaded、parsed、stored、served、rendered、verified 的状态。

---

## 十九、完成标准

只有同时满足以下条件，才可称首版完成：

- /hong-kong-macro 是真实独立页面；
- 香港没有进入 /city-economy；
- 至少香港住房、转口贸易、储备金融和综合经济四域中，每域都有真实官方观察，或对被官方访问阻断的域提供清晰 partial 状态和证据；
- SAFE 正式外汇储备在 /china-macro 可见；
- SAFE 外储与 PBOC 资产负债表外汇明确分开；
- 土地注册处住宅宗数和金额真实入库；
- RVD 私人住宅售价指数真实入库；
- Trade-IDDS 转口真实入库；
- HKMA 外币储备真实入库；
- 数据有来源、单位、频率、首末期和最新参考期；
- API 返回真实 observation；
- CSV 能导出当前筛选；
- 来源覆盖和失败状态可查；
- 更新失败不会覆盖有效数据；
- 住房领先滞后分析没有预设答案；
- lag_months 符号有合成测试；
- 页面显示完整相关曲线和滚动稳定性，而非只报一个月数；
- 目标测试通过；
- 全量测试没有因本轮变化新增失败；
- 数据库只读核对通过；
- 页面在桌面和窄屏验证通过；
- README、项目边界文档和状态文档已更新。

如果由于外部阻断无法满足某条：

- 明确列出未满足项；
- 给出官方 URL、探针方式、HTTP 或解析错误；
- 说明有没有入库；
- 保留有效旧数据；
- 不把它标成完成。

---

## 二十、建议的 P1 与 P2，不要挤占首版

首版稳定后再考虑：

**P1**

- 香港写字楼、零售物业和工业物业价格租金；
- 住宅按面积等级；
- 住宅按地区和金额区间；
- 负资产住宅按揭贷款；
- 新批按揭、按揭利率和拖欠比率；
- 服务贸易；
- 国际收支和国际投资头寸；
- 外债；
- 人民币存款和跨境人民币更细分；
- 港口吞吐、航空货运、旅客和酒店；
- 中国内地经香港的贸易融资和金融渠道。

**P2**

- 高频 nowcast；
- 房地产周期转折识别；
- 贸易网络；
- 香港—内地—美国三方金融条件；
- 数据 vintage 和修订回测；
- 事件注释；
- 可复现研究 notebook；
- 对领先滞后的稳健统计推断。

这些是 backlog，不应以空卡片方式混入首版。

---

## 二十一、最终回复格式

完成后，向用户先报告结果，不要先写过程流水账。最终回复至少包含：

1. 香港是否已成为独立页面；
2. 实际接入了哪些官方数据；
3. 中国内地正式外储是否已接入，如何与 PBOC 外汇区分；
4. 页面有哪些页签和核心交互；
5. 住房领先滞后得出了什么描述性结果，或为什么尚不能得出；
6. 数据覆盖、最新参考期和主要缺口；
7. 测试、API、数据库和浏览器验证结果；
8. 服务是否重启；
9. 状态文档和主要文件的可点击绝对路径；
10. 未完成项和建议下一步。

对于每个数据域，使用以下准确状态词：

- 已定位官方来源；
- 已完成字段探针；
- 已下载；
- 已解析；
- 已校验；
- 已入库；
- API 已返回；
- 页面已渲染；
- 浏览器已验证；
- 被阻断；
- 尚未实施。

不得将前四个状态混为“已完成”。

---

## 二十二、现在开始

现在请直接开始实施，不要只重复这份提示词。

第一步先给用户一个简短进度说明，然后完成只读侦察和官方字段探针。若侦察发现：

- 工作树有用户未提交改动；
- 数据库有活跃 WAL；
- 服务正在执行长任务；
- 某个建议表或路由已存在；
- 官方来源字段与本提示词示例不同；

应以当前仓库和官方字段为准，做最小、安全、可审计的调整，并在状态文档解释。只有会显著改变产品边界或需要破坏性操作时才停下来询问。

不要声称“香港领先内地多少个月”，直到真实数据、符号测试、全样本相关曲线和滚动稳定性全部完成。不要声称“数据已接入”，直到它经过下载、解析、入库、API、页面和浏览器逐层验证。

最终要交付的是一个真实可用的研究模块，而不是一张看起来完整的空页面。

