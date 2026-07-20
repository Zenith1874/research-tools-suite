# 研究工具集 · Research Tools Suite

本地运行的个人研究工具集合，用一个 Python 标准库 `HTTPServer`（端口 5001）+ 模块化
`services/` + 暗色风格静态页面托管多个工具，数据存于本地 SQLite。无需 npm 构建。

## 模块

| 页面 | 说明 |
|---|---|
| `/dashboard` | 中国人民银行金融统计监控（M2/M1/贷款/存款/社融/利率，observation 层 + 来源追踪） |
| `/macro-analytics` | 宏观统计分析（中国/美国/中美对照/房价/财政债务五个维度；含 Sahm 规则、收益率曲线、房地产“量-价-地”、付息负担率、地方债借新还旧与中美付息对照；不含预测） |
| `/fiscal-debt` | 财政收支与政府债务监控（2010 年起年度收支、YTD 进度、还本付息三情景、年度借还全景、国债/地方债到期压力，以及央行国债买卖—买断式逆回购—对政府债权时间线） |
| `/abdc` | ABDC 期刊质量列表查询（2010–2025 六个版本，按名称/ISSN/FoR 搜索） |
| `/abdc-astar-research` | **A\* 研究动态（Research Radar）**：追踪 ABDC A\* 期刊最新文章，规则分类 + 个人研究相关性评分 + FT50/UTD24 标签。详见 [docs/abdc_astar_research_PROGRESS.md](docs/abdc_astar_research_PROGRESS.md) |
| `/china-rates` | 中国利率与汇率（LPR、SHIBOR、人民币对美元中间价；中国货币网官方接口，每日自动更新） |
| `/us-macro` | 美国宏观（就业、通胀、增长、财政债务、利率金融五组约 46 序列，含美联储总资产/美国 M2/VIX/美元指数/密歇根信心；BLS/劳工部/BEA/财政部/美联储/CBOE 等经 FRED 免 key CSV）。中国实体经济指标（CPI/PPI/PMI/工业增加值/社零/固投月度 + GDP 季度初步核算，统计局新闻稿与表格解析，2012-2016 起不等）由 `services/china_macro_service.py` 供给 `/macro-analytics` |
| `/housing` | 中国房价（统计局 70 城新房/二手官方指数 + BIS 全国指数 + 安居客二手挂牌价参考及历史双口径走势；挂牌数据仅存本机独立库，不入仓库） |

## 全站信息架构

顶部导航把研究工具固定分为三个一级研究域：

- **中国宏观**：`/dashboard`、`/fiscal-debt`、`/china-rates`、`/housing`
- **美国宏观**：`/us-macro`
- **ABDC 商科研究**：`/abdc`、`/abdc-astar-research`

ABDC 研究域下另设 Information Systems、Management、Marketing、OB / HR、计算社会科学五个学科频道。频道链接复用 `/abdc-astar-research?field=...`，直接应用文章筛选，不创建空白占位页面。

## 运行

```bash
cd <repo>
pip install -r requirements.txt   # requests / beautifulsoup4 / openpyxl / pypdf
python server.py                  # 启动后打开 http://localhost:5001

# 可选：看门狗(健康探测,服务器挂了自动重启)
python scripts/watchdog.py --start-if-down
```

启动时自动建表、载入清单、开启后台增量调度器。

### 保持常驻（Windows，无需管理员）

服务器是普通用户进程，**关机/注销/重启后不会自动回来**。用看门狗 + 登录启动项解决：

- **看门狗** `scripts/watchdog.py`：每 20s 探测 `/api/health`，连失 2 次自动杀掉并重启
  `server.py`（重启前轮转日志）。它以 `DETACHED_PROCESS` 拉起服务，自身退出也不影响服务。
- **开机自启**：登录启动文件夹放了 `ClaudeServerWatchdog.vbs`（隐藏窗口启动看门狗）——
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`。每次登录 Windows 自动拉起看门狗，
  再由看门狗保证服务器在线。**删除该 .vbs 即取消自启。**
- 更强的**计划任务版**（连"看门狗自身崩溃"也每分钟自恢复）需要**管理员** PowerShell：

  ```powershell
  $pyw = "C:\Users\<you>\AppData\Local\Programs\Python\Python312\pythonw.exe"
  $act = New-ScheduledTaskAction -Execute $pyw -Argument "D:\claude\scripts\watchdog.py --start-if-down" -WorkingDirectory "D:\claude"
  $trg = New-ScheduledTaskTrigger -AtLogOn
  $set = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
  Register-ScheduledTask -TaskName "ClaudeServerWatchdog" -Action $act -Trigger $trg -Settings $set -RunLevel Limited
  ```

三层保险：登录启动项 → 看门狗 → server.py（异步更新 + 全局写锁，不自锁死）。

### 环境变量
- `SERVER_HOST` — 服务监听地址；默认 `0.0.0.0`，允许校园网其他电脑查看。只需本机使用时设为 `127.0.0.1`。
- `SERVER_PORT` — 服务端口，默认 `5001`。
- `ALLOW_REMOTE_WRITES=1` — 明确允许远程电脑触发更新、保存和情景运行；默认关闭。
- `ADMIN_TOKEN` — 可选远程管理令牌。远程 API 调用在 `X-Research-Admin-Token` 请求头携带该值后才可执行写操作。
- `CORS_ORIGIN` — 可选的跨站访问来源；默认不开放 CORS。普通浏览器同源访问无需设置。
- `ASTAR_MAILTO` — OpenAlex / Crossref polite-pool 联系邮箱（建议设为你的真实邮箱；默认占位）。
- `ASTAR_AUTO=0` — 关闭 A\* 雷达每天一次的后台增量抓取。
- `FISCAL_AUTO=0` — 关闭政府债务模块每周一次的官方来源检查。
- `RATES_AUTO=0` — 关闭利率/汇率与美国宏观每日一次的自动更新。
- `ANJUKE_AUTO=1` — 开启安居客挂牌价每周低频检查；首次 70 城人工验收完成前默认关闭（验证码页自动跳过，不绕过）。

### 校园网访问安全

默认配置保留局域网查看能力：其他电脑可打开 `http://<本机校园网IP>:5001`，但只能读取页面和数据；更新数据、保存文章、重新分类与运行情景等写操作默认仅允许服务器本机执行。这样无需公开商业挂牌数据库，也避免校园网内其他设备误触发长任务。

如只在本机使用，可在 `.secrets` 中加入 `SERVER_HOST=127.0.0.1`。不建议在校园网设置 `ALLOW_REMOTE_WRITES=1`；确需远程管理时优先配置随机的 `ADMIN_TOKEN`，并通过受控客户端请求头传递，令牌文件已被 `.gitignore` 排除。

### 财政收支与政府债务数据更新

```powershell
# 更新所有已接入的财政部和央行来源
Invoke-RestMethod -Method Post http://127.0.0.1:5001/api/fiscal-debt/update

# 只更新一个模块
Invoke-RestMethod -Method Post -ContentType application/json `
  -Body '{"module_code":"local_government_debt"}' `
  http://127.0.0.1:5001/api/fiscal-debt/update

# 验证来源、覆盖和更新日志
python scripts/verify_fiscal_debt.py
```

财政收支年度历史来自财政部国库司年度“财政收支情况”原文：一般公共预算覆盖 2010 年起，政府性基金覆盖 2012 年起。页面中的收支差额均为 `收入 - 支出` 的 derived 分析值，不等于法定预算赤字；“两本账”仅作简单相加，未抵销调入调出。未来三年为可切换情景估计，不写入 official observation。

财政债务调度器默认每 168 小时检查一次已接入来源。抓取失败会写入
`fiscal_debt_update_logs`，不会清空或用假数据覆盖旧 observation。

### 房价历史回填

```powershell
# 统计局现行 70 城逐城口径（2011 起，公开来源，可复现）
python scripts/backfill_housing_history.py --source nbs --start-year 2011 --end-year 2026 --nbs-workers 3

# 安居客点名十城年度页（2010 起，低频、本机保存，验证页即跳过）
python scripts/backfill_housing_history.py --source anjuke --start-year 2010 --end-year 2026 --max-requests 90

# 安居客全国历史排名页（独立年度快照层；优先复用本地缓存）
python scripts/backfill_housing_history.py --source anjuke-yearly --no-network
```

统计局 2010 年仍是旧发布制度，不与 2011 年后的逐城序列拼接。安居客挂牌数据和原始页只写入
gitignored 的 `data/housing_listing.db` 与 `data/anjuke_raw/`，不会进入公开仓库。全国历史排名页形成
独立的年度低频快照，城市年度页形成逐月序列；年度点不复制成 12 个月，也不进入与官方二手指数的
月度对比。页面价格为 `-` 时保留缺失，不补零、不用区县均价替代。

## 数据说明

- **数据库 `pboc_data.db` 不入库**（约 500MB 二进制、持续变动，超 GitHub 100MB 单文件上限）。
  两种获取方式：
  - **下载全量快照**（推荐快速上手）：见 [Releases](https://github.com/Zenith1874/research-tools-suite/releases)
    的 `pboc_data_snapshot.db.gz`（压缩 107MB / 解压约 517MB），解压后重命名为 `pboc_data.db` 放到根目录。
  - **自行重建**（数据可由公开 API 再生）：
    ```bash
    python scripts/update_abdc_astar.py --mode backfill_since --since-year 2020
    python scripts/update_abdc_astar.py --enrich-abstracts
    ```
- 不抓取付费全文、不绕过付费墙；缺失字段诚实标记（如 `abstract_status=missing`），不使用 mock 数据。

## 数据来源与致谢

- 文章元数据：[OpenAlex](https://openalex.org)、[Crossref](https://www.crossref.org)、
  [Semantic Scholar](https://www.semanticscholar.org)（均为公开 metadata API）。
- 期刊评级：[ABDC Journal Quality List](https://abdc.edu.au/abdc-journal-quality-list/)（© ABDC）；
  顶刊清单 FT50（Financial Times Research Rank）、UTD24（UT Dallas）。
- 金融/财政数据：中国人民银行、财政部公开发布。

> 期刊清单与评级数据版权归各自机构所有，本项目仅用于个人研究，使用请遵循其各自条款。

## 技术栈

Python 标准库 HTTPServer · SQLite · requests · 前端原生 JS/HTML（A\* 雷达）+ 本地
React/Babel（金融仪表板，`static/vendor/`，离线托管）。
