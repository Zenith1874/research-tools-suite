# 研究工具集 · Research Tools Suite

本地运行的个人研究工具集合，用一个 Python 标准库 `HTTPServer`（端口 5001）+ 模块化
`services/` + 暗色风格静态页面托管多个工具，数据存于本地 SQLite。无需 npm 构建。

## 模块

| 页面 | 说明 |
|---|---|
| `/dashboard` | 中国人民银行金融统计监控（M2/M1/贷款/存款/社融/利率，observation 层 + 来源追踪） |
| `/china-macro` | 中国实体经济、人口家庭与外贸七板块：增长生产、消费投资、价格景气、就业收入、人口家庭、海关人民币/美元进出口、商务部外资/对外投资与外汇局跨境资金；支持自由期间、原币种切换、图例显隐、纵轴模式、CSV 和逐序列来源覆盖审计。 |
| `/hong-kong-macro` | 香港独立宏观模块：RVD/土地注册处住房、HKMA 经济与储备金融、Trade-IDDS 转口贸易、CSD 年度补充与中国联动描述性 lead-lag；香港不写入中国城市经济模块。 |
| `/macro-analytics` | 宏观统计分析（中国/美国/中美对照/房价/财政债务五个维度；含 Sahm 规则、收益率曲线、房地产“量-价-地”、付息负担率、地方债借新还旧与中美付息对照；不含预测） |
| `/macro-scenario` | 宏观趋势与情景推演：复用已有中国宏观、央行、利率、房地产数据，提供上行/基准/下行路径、固定种子敏感性模拟、滚动回测和高价值缺口清单；结果标为 `scenario`/`derived`，不冒充官方预测。 |
| `/fiscal-debt` | 财政收支与政府债务监控（2010 年起年度收支、YTD 进度、还本付息三情景、年度借还全景、国债/地方债到期压力，以及央行国债买卖—买断式逆回购—对政府债权时间线） |
| `/debt-ceiling` | 债务限额与时间推演（公开 CAGR/触线/付息公式；国债与地方法定债务限额路径；2023—2024 财政部广义政府债务官方锚点，以及2025隐性债务政策桥接区间）。城投债与隐性债务严格分列；私有库的中国货币网候选债可切换严格/宽关键词口径，展示覆盖率、合同到期墙、三种融资情景、现金偿付和 CSV 明细，但不冒充官方城投债余额，也不并入政府债务合计。 |
| `/abdc` | ABDC 期刊质量列表查询（2010–2025 六个版本，按名称/ISSN/FoR 搜索） |
| `/abdc-astar-research` | **A\* 研究动态（Research Radar）**：追踪 ABDC A\* 期刊最新文章，规则分类 + 个人研究相关性评分 + FT50/UTD24 标签。详见 [docs/abdc_astar_research_PROGRESS.md](docs/abdc_astar_research_PROGRESS.md) |
| `/abdc/research` | **ABDC 商科研究工作台（Phase 2）**：Theory Library、Construct Library、Methods Lab、Paper Workspace 与描述性 Literature Landscape；目录脚手架和文章证据边界见 [docs/business_research_phase2_STATUS_2026-08-15.md](docs/business_research_phase2_STATUS_2026-08-15.md) |
| `/paper-translation` | **学术语言工作台（文档翻译、文章总结与原文问答）**：PDF/DOCX/TXT/Markdown 本机文件处理，通过 SSH 隧道调用校内 GPU 上的开源模型；支持逐节小结、结构化全文摘要、翻译+总结双输出，以及带页码/章节证据的多轮追问，并保留格式与覆盖审计。 |
| `/audio-transcription` | **研究语音工作台**：访谈、会议、讲座和研究录音的逐词转录、匿名说话人区分、可选逐轮翻译；任务在独立结果页直接阅读，同时保留原文/译文/双语 TXT、JSON、SRT、VTT 和 ZIP 导出。 |
| `/ebook-conversion` | **阅读副本工坊**：把本机 PDF 转成手机看的 EPUB 重排本和墨水屏看的裁边分栏 PDF（六种设备比例）。可以填本机目录递归批量、用浏览器选整个文件夹、或直接多选文件；结果支持逐个下载、打包 ZIP、发到 Kindle 邮箱、写入指定文件夹。纯本机 PyMuPDF 完成，**不依赖 GPU，不受论文翻译/语音转写的关闭开关影响**。 |
| `/yuedu-fm` | **悦读FM · 本地听**：从公开 RedCircle RSS 同步标题、节目文字、逐集封面和 MP3 到本机，支持断点续传、搜索与离线播放。 |
| `/cardcookie-monitor` | **CardCookie 按需监控**：默认关闭，手动开启后低频检查 Walmart 与 Best Buy 的库存、折扣和价格；首次检查仅建基线，真实变化才按本机 SMTP 设置发邮件，所有检查与异常保存在独立本地 SQLite。 |
| `/faculty-jobs` | **Academic Career / Faculty Job Market**：美国、加拿大与欧洲公开职位源的低频规范化采集、职位筛选、来源健康、证据字段与 CSV；同域页面还有学校比较、市场分析和本机私有申请追踪。 |
| `/china-rates` | 中国利率与汇率（LPR、SHIBOR、人民币对美元中间价；中国货币网官方接口，每日自动更新） |
| `/us-macro` | 美国宏观（就业、通胀、增长、财政债务、利率金融五组约 46 序列，含美联储总资产/美国 M2/VIX/美元指数/密歇根信心；BLS/劳工部/BEA/财政部/美联储/CBOE 等经 FRED 免 key CSV）。中国实体经济指标继续供给 `/macro-analytics`，完整观察层见 `/china-macro`。 |
| `/gdp` | 中美 GDP 与地方财政：全国历史、BEA 美国州级 GDP、Census ASFIN 州财政；中国31省统计局 GDP/一般预算收支/税收连续覆盖2010–2024，财政部债务覆盖2018–2024，省级决算另补卖地与还本付息。 |
| `/city-economy` | 城市经济十五城多指标视图：北上广深、厦门、南京、合肥、常州、苏州、无锡、武汉、长沙、成都、杭州、福州可任意多选；分为增长总览、人口就业、产业投资、金融财政、住房与城市承载力五个可切换板块，每项指标独立作图、独立纵轴并共享自由期间。上市公司页签另按办公地/注册地汇总家数、最新市值、完整年度营收与城市 GDP 比率，并提供 2021–2025 年平衡/可得样本趋势、头部公司穿透、Top1/Top5、HHI 和双地址口径差异。非直辖市只用城市自身数据，缺失不以省值代替；城市公报补充的消费、外贸、人口、就业、卫生和商品房字段逐格标注镜像/叙述口径；武汉、福州及杭州等城市财政决算补充保留全市/市本级与官方初步状态；在十五城关键口径基本对齐前不生成黑箱综合得分。 |
| `/housing-scenario` | 城市房价推演：可切换统计局70城官方指数，以及安居客月度/年度15城目录；新增武汉、长沙、成都、杭州、福州并提供“后来五城”快捷切换。在原近6/12/36月或约3/5/10年价格动能三档之上，新增人口、收入、全国粗结婚率（登记对数/人口派生）、商品房量供给和5年期LPR的透明结构压力测试，支持0–100%修正强度且0%精确回退纯动能；就业、存款、户籍人口、房地产投资和高校学生只作观察项。另新增“宏观联动”模式，把宏观实验室的GDP、贷款、销售面积、全国人口和LPR轨道按透明系数接入房价路径，并显示组件覆盖与缺口；不重复覆盖原始动能/结构路径。另设独立的2030/2040/2050人口—家庭形成长期层：用UN WPP 2024中方案的20–39岁年龄结构、可调家庭形成倾向和有界城市集聚修正展示十五城容量与固定存量负担，不把人口指数直接换算成房价。只有真实记录才推演，缺失城市明确标记 missing；各口径不拼接，商业挂牌库不入仓库，未来值均为 scenario。 |
| `/housing` | 中国房价（统计局 70 城新房/二手官方指数 + BIS 全国指数 + 全国商品房销售面积/销售额〔年度1991起、月度累计2012-02起〕+ 安居客二手挂牌价参考及历史双口径走势；挂牌数据仅存本机独立库，不入仓库） |

## 全站信息架构

顶部导航分为六个一级入口：

- **中国宏观**：`/dashboard`、`/china-macro`、`/hong-kong-macro`、`/macro-analytics`、`/macro-scenario`、`/gdp`、`/housing`、`/fiscal-debt`、`/china-rates`、`/city-economy`、`/housing-scenario`
- **美国宏观**：`/us-macro`
- **ABDC 商科研究**：`/abdc`、`/abdc-astar-research`、`/abdc/research`、`/abdc/theories`、`/abdc/constructs`、`/abdc/methods`、`/abdc/landscape`、`/abdc/library`
- **科研工具**：`/ebook-conversion`（“阅读副本工坊”，纯本机始终可用）、`/paper-translation`（“学术语言工作台”）、`/audio-transcription`（“研究语音工作台”，后两者依赖 GPU，默认关闭）
- **娱乐**：`/yuedu-fm`（“悦读FM”，个人本地归档与播放）、`/cardcookie-monitor`（默认关闭的个人价格与库存提醒）
- **学术职业**：`/faculty-jobs`、`/school-explorer`、`/job-market-analytics`、`/my-applications`；前三者提供公开/派生覆盖，最后一个默认仅服务本机可见。

ABDC 研究域下另设 Information Systems、Management、Marketing、OB / HR、计算社会科学五个学科频道。频道链接复用 `/abdc-astar-research?field=...`，直接应用文章筛选，不创建空白占位页面。

## 1 + 6 单仓库项目结构

整个工作台继续使用一个可运行、可测试、可发布的 Git 仓库，并按上述六个一级入口划分六个项目域。项目边界、源码映射、公开 Git 与私有数据规则见 [projects/README.md](projects/README.md)；机器可读清单见 [projects/registry.json](projects/registry.json)。

大型 SQLite、原始音频、论文/访谈任务、嵌入、出版社摘要扫描、学术职位缓存/个人申请资料、备份、日志和 .secrets 不进入公开 Git。发布前运行 `python scripts/audit_projects.py`（历史兼容入口 `python scripts/audit_one_plus_five.py`）；完整私有迁移使用 scripts/create_private_migration_snapshot.py 写入仓库外的目的地。

## 运行

```bash
cd <repo>
pip install -r requirements.txt   # requests / beautifulsoup4 / openpyxl / pypdf
python server.py                  # 启动后打开 http://localhost:5001

# 可选：看门狗(只探测本机健康状态,服务器挂了自动重启；默认不连接远端 SSH)
python scripts/watchdog.py --start-if-down
```

启动时自动建表、载入清单、开启后台增量调度器。

### 手动运行与自动启动（Windows）

服务器是普通用户进程。当前登录启动项只恢复本地研究平台；论文翻译和语音转写模块保持关闭，
不会在重启后恢复，也不会触发远端 GPU 连接。

- **看门狗** `scripts/watchdog.py`：默认每 30s 探测 `/api/health`。端口未监听时连失 3 次重启；
  端口仍监听但 HTTP 暂时超时时使用 6 次忙碌容忍窗口，避免 Windows 短时卡顿误杀服务。
  单实例锁会阻止两个看门狗互相重启。它以 `DETACHED_PROCESS` 拉起 `server.py`，自身退出也不影响服务。
  看门狗默认不会自动打开或重连论文翻译 SSH 隧道。
- **本地平台开机自启**：启动文件夹中的 `ClaudeServerWatchdog.vbs` 会启动 watchdog 和 `server.py`，
  但会强制设置两个 GPU 模块为关闭，且不传 `--auto-tunnel`。
- 更强的**计划任务版**（连"看门狗自身崩溃"也每分钟自恢复）需要**管理员** PowerShell：

  ```powershell
  $pyw = "C:\Users\<you>\AppData\Local\Programs\Python\Python312\pythonw.exe"
  $act = New-ScheduledTaskAction -Execute $pyw -Argument "D:\claude\scripts\watchdog.py --start-if-down" -WorkingDirectory "D:\claude"
  $trg = New-ScheduledTaskTrigger -AtLogOn
  $set = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
  Register-ScheduledTask -TaskName "ClaudeServerWatchdog" -Action $act -Trigger $trg -Settings $set -RunLevel Limited
  ```

如需临时自愈，可手动运行 watchdog；它默认只监控本机服务，不会自动连接远端 GPU。

### 环境变量
- `SERVER_HOST` — 服务监听地址；默认 `0.0.0.0`，允许校园网其他电脑查看。只需本机使用时设为 `127.0.0.1`。
- `SERVER_PORT` — 服务端口，默认 `5001`。
- `ALLOW_REMOTE_WRITES=1` — 明确允许远程电脑触发更新、保存和情景运行；默认关闭。
- `ADMIN_TOKEN` — 可选远程管理令牌。远程 API 调用在 `X-Research-Admin-Token` 请求头携带该值后才可执行写操作。
- `CORS_ORIGIN` — 可选的跨站访问来源；默认不开放 CORS。普通浏览器同源访问无需设置。
- `TRUST_CLOUDFLARE_HEADERS=1` — 仅在 Cloudflare Tunnel 是唯一反向代理时启用；把带 `CF-Connecting-IP` 的 loopback 转发按远程请求处理，避免公网 POST 被误判成本机写操作。默认关闭。
- `PAPER_TRANSLATION_ENABLED=0` — 硬关闭论文翻译页面和 API（整站返回 404）；默认 `1` 可用。模块本身不会自动连接 GPU，见下方“GPU 按需连接”。
- `AUDIO_TRANSCRIPTION_ENABLED=0` — 硬关闭语音转写页面和 API；默认 `1` 可用。
- `FACULTY_ASTAR_TIER_SIGNAL=1` — 允许 A* 发表足迹参与商学院 tier 判定。默认关闭：
  足迹是从部分回填的语料里数出来的下限，把它当成 tier 依据是对"tier 代表什么"的判断，
  不该由程序替你决定。关闭时足迹仍然完整展示（Observed A* Publication Footprint，
  含覆盖率与年份窗口），只是不影响 tier。
- `AFFIL_AUTO=0` — 关闭 A* 机构层每日增量回填。默认开启，跟在雷达抓取之后运行，
  只用当日 OpenAlex 预算的剩余部分（免费额度 1000 次/天，UTC 零点重置；雷达自身约需 219 次）。
  预算耗尽时回填自行停止，剩余文章保持 pending，第二天续跑。
- `AFFIL_AUTO_LIMIT` — 单次回填最多检查的文章数；默认 40000（实际仍受当日预算约束）。
- `TRANSLATION_BASE_URL` — 本地 SSH 隧道后的 OpenAI 兼容地址；默认 `http://127.0.0.1:18001/v1`。
- `TRANSLATION_MODEL` — 论文翻译模型；默认 `Qwen/Qwen3-14B-AWQ`。
- `TRANSLATION_MAX_UPLOAD_BYTES` — 论文文件上限；默认 50 MB。论文任务目录始终 gitignored。
- `TRANSLATION_BATCH_UNITS` — 单批最多翻译单元；默认 10。结构校验失败时自动二分重试。
- `TRANSLATION_MAX_CONCURRENT_JOBS` — 文档任务队列并发数；默认 1，安全范围 1–4。批量文件会排队，不会为每篇论文无限创建推理线程。
- `TRANSLATION_ALLOW_REMOTE=1` — 明确允许非本机访问翻译任务；隐私原因默认关闭，即使普通研究页面可在局域网查看。
- `AUDIO_MAX_UPLOAD_BYTES` — 语音文件上限；默认 1 GiB。服务端按块写入私有任务目录，不把整个请求体读入内存。
- `AUDIO_TRANSCRIPTION_ALLOW_REMOTE=1` — 明确允许非本机访问原始录音、转录和字幕；隐私原因默认关闭。
- `AUDIO_TRANSCRIPTION_HOSTS` — 逗号分隔的语音候选主机；默认固定为 `keller.cs.nmsu.edu`。需要临时扩容时再显式添加其他主机。
- `AUDIO_GPU_WAIT_SECONDS` — Keller 无空闲 GPU 时的最长安全等待；默认 900 秒，不强行共享忙碌 GPU。
- `EBOOK_ALLOW_REMOTE=1` — 显式允许非本机访问阅读副本工坊。该模块能列举本机任意文件夹并把文件写到本机磁盘，隐私与安全原因默认只允许服务器本机访问。
- `EBOOK_MAX_UPLOAD_BYTES` — 上传 PDF 上限；默认 120 MB。用本机路径批量转换不受此限制，因为原件只被读取、不产生副本。
- `EBOOK_MAX_FOLDER_FILES` / `EBOOK_MAX_SCAN_DEPTH` — 单次目录扫描的文件数与递归深度上限；默认 800 与 6，超出时结果标 `truncated` 而不是静默截断。
- `EBOOK_MAX_CONCURRENT_JOBS` — 转换队列并发；默认 2，安全范围 1–4。
- `EBOOK_EMAIL_MAX_BYTES` — 发到 Kindle 的单封附件上限；默认 24 MB，超限的文件明确跳过并给出原因。
- `KINDLE_EMAIL` — 默认的 Send-to-Kindle 收件地址；页面留空即用它。API 只返回遮罩后的地址。
- `EBOOK_SMTP_*` — 阅读副本发信的独立 SMTP 参数（`HOST`/`PORT`/`USER`/`PASS`/`FROM`/`USE_SSL`/`STARTTLS`）。不设置时回落到通用 `SMTP_*`。密码只放在 gitignored 的 `.secrets`，绝不进入任何 API 响应。
- `YUEDU_FM_ALLOW_REMOTE=1` — 显式允许受平台写权限保护的远程设备读取悦读FM本地资料；默认仅服务器本机可访问。
- `CARDCOOKIE_MONITOR_ALLOW_REMOTE=1` — 显式允许受管理权限保护的远程设备读取 CardCookie 监控状态；默认仅服务器本机可访问，开启/停止仍受写权限保护。
- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` — CardCookie 变化通知使用的 SMTP 参数；`SMTP_PASS` 应使用邮箱授权码或应用密码，只放在 gitignored 的 `.secrets`。
- `SMTP_USE_SSL=1` — 端口 465 等直连 SSL SMTP 使用；其他端口默认使用 STARTTLS，可用 `SMTP_STARTTLS=0` 显式关闭。
- `SMTP_FROM` / `NOTIFY_TO` — 发件地址和逗号或分号分隔的收件地址；API 只返回遮罩地址，绝不返回密码。
- `ASTAR_MAILTO` — OpenAlex / Crossref polite-pool 联系邮箱（建议设为你的真实邮箱；默认占位）。
- `ASTAR_AUTO=0` — 关闭 A\* 雷达每天一次的后台增量抓取。
- `PBOC_AUTO=0` — 关闭启动时央行抓取和每日 09:00/14:00 调度；用于只读恢复验证或维护窗口。
- `FISCAL_AUTO=0` — 关闭政府债务模块每周一次的官方来源检查。
- `RATES_AUTO=0` — 关闭利率/汇率与美国宏观每日一次的自动更新。
- `ANJUKE_AUTO=1` — 开启安居客挂牌价每周低频检查；首次 70 城人工验收完成前默认关闭（验证码页自动跳过，不绕过）。
- `FACULTY_JOBS_AUTO_UPDATE=0` — 关闭 Academic Career 公开职位源的每日后台刷新；默认开启，但启动后先等待 15 分钟。
- `FACULTY_JOBS_UPDATE_HOURS` — 职位源刷新间隔，默认 24 小时。
- `FACULTY_JOBS_HTTP_TIMEOUT` / `FACULTY_JOBS_MAX_PAGES_PER_SOURCE` — 单次公开页面请求超时和每来源页数上限；默认 20 秒、1 页。
- `FACULTY_JOBS_ALLOW_REMOTE_PRIVATE=1` — 明确允许远程读取个人 profile/application 数据；默认关闭，即便普通写权限已开启也保持本机隔离。

### 校园网访问安全

默认配置保留局域网查看能力：其他电脑可打开 `http://<本机校园网IP>:5001`，但只能读取页面和数据；更新数据、保存文章、重新分类与运行情景等写操作默认仅允许服务器本机执行。这样无需公开商业挂牌数据库，也避免校园网内其他设备误触发长任务。

如只在本机使用，可在 `.secrets` 中加入 `SERVER_HOST=127.0.0.1`。不建议在校园网设置 `ALLOW_REMOTE_WRITES=1`；确需远程管理时优先配置随机的 `ADMIN_TOKEN`，并通过受控客户端请求头传递，令牌文件已被 `.gitignore` 排除。

### Cloudflare Tunnel 外网访问

如果需要让不安装 Tailscale 的手机或电脑通过普通浏览器访问，使用 Cloudflare Tunnel + Cloudflare Access：

1. 在 Cloudflare Zero Trust 的 **Networks → Tunnels** 创建 `cloudflared` Tunnel。
2. 添加公开主机名，例如 `research.example.com`，Origin Service 填 `http://127.0.0.1:5001`。
3. 在 **Access → Applications** 创建 Self-hosted 应用，只允许自己的邮箱登录。
4. Windows 启动环境必须设置 `TRUST_CLOUDFLARE_HEADERS=1`；保持 `ALLOW_REMOTE_WRITES=0`，不要把平台写接口公开。

Cloudflare Tunnel 不需要路由器端口转发；Tunnel 的出站连接和 Access 登录是外网入口，域名/DNS 与 Tunnel 凭据只保存在 Cloudflare 和本机受保护配置中。

### GPU 按需连接（两个 GPU 模块共同约束）

这两个模块曾经被整体关闭，原因是**打开页面就会反复联系校内集群**：读取 `/api/translation/config`
会顺手 health-check 模型，而翻译页每 15 秒轮询一次该接口；`/api/audio/config` 更重，会 SSH 登录每台
候选主机跑 `nvidia-smi`。开着标签页就等于全天候占用共享资源，因此被限流。

现在的约束是：

- `config()` 只描述模块，**不产生任何出站连接**——不 HTTP、不 SSH。返回里 `connection_policy` 为
  `on_demand_only`，`model_service.probed` 为 `false`。
- 探活是独立且必须由用户触发的动作：`POST /api/translation/probe`、`POST /api/audio/probe`。
  页面上是“连接并检查”按钮，点击后先弹确认再连。
- **页面没有任何定时探活。**任务列表轮询只读本机 JSON，不碰 GPU。
- 开始任务同样先确认，说明会连接并占用 GPU 直到任务结束。
- 开始按钮不再要求“先探活成功”——那等于强制每次使用都先连一次。模型没起来时任务会失败并提示，
  本机原件和检查点保留，可直接重试。

`tests/test_gpu_on_demand.py` 把这套契约钉死：`config()` 的出站调用次数必须为 0，页面里不允许出现
指向 config/probe 的 `setInterval`，探活与开始任务都必须带确认。需要彻底停用时仍可设
`PAPER_TRANSLATION_ENABLED=0` / `AUDIO_TRANSCRIPTION_ENABLED=0`。

### 学术语言工作台：文档翻译

翻译模块把文件处理和模型推理解耦：PDF/DOCX/TXT/Markdown 原件、检查点和译文只保存在本机
`data/translation_jobs/`；远端 GPU 只接收分段后的文本。vLLM 绑定远端回环地址，通过 SSH 隧道访问，
不向校园网公开模型端口。

总结采用“逐节小结 → 全文结构化摘要”的分层流程。检查点同时绑定源文本 SHA-256、目标语言、领域、
术语表和提示版本；服务重启时遗留的排队/运行任务会标记为“已中断”并保留检查点，用户可安全重试。
DOCX 总结只读取 `word/document.xml`，不会把页眉、页脚、批注、脚注或尾注作为论文正文。多文件批量
默认由单 worker 队列顺序处理，避免同时挤占本机和 Iverson。总结结果同时记录单元完整性、排除项和
目标语言文字占比；缺失正文单元会硬失败，语言占比异常则保留结果并给出可人工复核的警告。
翻译单元若因模型漏回保护占位符或句末截断而失败，会先使用不同 seed 做单元级修复请求；仍失败时，
数字、引用、链接和术语作为本机锚点保留，只翻译锚点之间的文字，不会通过放宽完整性校验来“强行完成”。
PDF 正文分段使用文档级正文字号，不会因回归表或尾注的小字号把正文误切为逐行翻译；
带明确 Table/Figure 标签的复杂版面区域保留原文，出版商软连字符会在送模型前重组。
首页摘要、资助信息等宽栏中的短缩进续行会继承前一宽栏，避免被误分到左栏后与相邻译文叠写。
单栏信件或陈述中的段落短尾行也会继承正文，不再拆成独立“左栏”；姓名后的 `Ph.D.` 等学位缩写
按签名元数据处理，但正文句末完整性校验仍保持严格。
本机 watchdog 在翻译 manifest 仍于最近 10 分钟更新时不会因短暂健康超时强制重启服务；任务进度停止超过
10 分钟后才恢复原有重启逻辑，以兼顾长推理与真实故障恢复。
可靠性加固、检查点 schema 与验证范围见
[docs/paper_summary_reliability_STATUS_2026-07-22.md](docs/paper_summary_reliability_STATUS_2026-07-22.md)。

PDF 模式面向带可提取文本层的论文：保留原页尺寸、图片、矢量线条、双栏和链接，在原段落矩形内写入中文；
表格内部、参考文献、页眉页脚和竖排版权文字默认保留原文。它是高保真阅读副本，不是字节级无损替换。
扫描型 PDF 在本地 OCR/VLM 尚未配置时会明确失败，不生成缺页或假完成文件。

```bash
# 1. 默认使用记录中的主机，否则固定 Iverson；只有显式 --host auto 才会多机选择
python scripts/manage_translation_vllm.py start

# 2. 隧道不由看门狗自动建立；需要翻译时由用户显式打开并保持这个终端
scripts/start_translation_tunnel.sh
#    如确有明确需求，可手动运行 watchdog.py --auto-tunnel；失败后会指数退避，
#    但不建议把它放进登录启动项或计划任务。

# 3. 启动本研究平台，访问 http://127.0.0.1:5001/paper-translation
python server.py
# 等页面右上角显示“本地模型可用”后再上传论文

# 4. 翻译完成后先 Ctrl-C 关闭隧道，再按启动记录释放远端 GPU
python scripts/manage_translation_vllm.py stop

# 只想查看全部允许主机而不启动时
python scripts/check_translation_hosts.py
```

允许的通用主机检查列表仅包含 `iverson / keller / lovelace / newton / riemann`；simurgh 与 kaiju 已从默认候选中移除。
Qwen 正常启动固定使用 Iverson，只有手工传入 `--host auto` 才会在允许列表内选择。远端重启会终止 vLLM 与 SSH 隧道；
再次使用翻译前按上面的第 1、2 步恢复，页面会显示未连接状态而不会静默改用其他机器。

检查、管理和隧道脚本会在 WSL 中自动发现 Windows 用户目录下的 SSH 配置、密钥和 `known_hosts`；
私钥只临时复制到 mode 0600 的 `/tmp`，退出即清理。也可用 `--ssh-config`、`--identity`、
`--known-hosts` 或对应的 `TRANSLATION_SSH_*` 环境变量显式覆盖。详细架构、模型参数、验证范围和格式边界见
[docs/paper_translation_STATUS_2026-07-21.md](docs/paper_translation_STATUS_2026-07-21.md)。

### 研究语音工作台：转录、说话人区分与翻译

页面：`http://127.0.0.1:5001/audio-transcription`。原始音频和本机输出保存在 gitignored 的
`data/audio_jobs/<job_id>/`。音频会经 SSH 加密暂存到 Keller；远端 worker 使用本地缓存的
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) medium 权重生成逐词时间戳，再用
[pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) 的 exclusive diarization
对齐匿名说话人。结构化结果必须通过输入 SHA-256 校验才能复制回本机，随后删除该任务的精确远端目录。

说话人标签只有 `SPEAKER_00`、`SPEAKER_01` 等匿名聚类含义；系统不推断姓名、性别、年龄、情绪或身份。
知道访谈人数时建议填写准确人数；不确定时可给最小/最大范围。重叠发言、噪声、极短发言和串音仍需人工抽查。
翻译继续复用 Iverson 上的 Qwen、论文模块结构校验与检查点，原文、译文和双语字幕共用完全相同的起止时间。也可以先完成纯转录，
待 Qwen 可用后在任务卡点击“追加翻译”，不会再次上传音频或重跑 ASR/diarization。

任务创建后会打开 `/audio-transcription/results/<job_id>` 独立查看页；排队和运行阶段自动刷新，完成后可切换原文、
译文或双语视图，并按匿名说话人筛选或搜索。任务卡也始终保留“打开查看结果”，下载文件作为归档和字幕编辑入口继续保留。
查看 API 只返回轮次级文本与时间，不把逐词概率、原始 diarization 片段、本机路径或私有诊断日志送到浏览器。
语音页面每次打开或点击“重新检查服务”都会新建一次只读 SSH 检查，显示 Keller 当前是空闲、繁忙还是无法连接；
正式语音任务还会重新建立独立 SSH/SCP 会话，因此 Keller 重启后不依赖旧连接。

```bash
# 首次/升级部署：脚本只写模块目录，不修改共享 reddit_env；key 值不会打印
python scripts/deploy_audio_transcription.py \
  --host keller.cs.nmsu.edu --install-dependencies --migrate-key

# 只复核部署、模型快照、导入和私有 key 权限
python scripts/deploy_audio_transcription.py --host keller.cs.nmsu.edu --check-only

# 查看 Keller；生产任务只在显存 <= 1 GiB 且利用率 <= 10% 时启动
python scripts/check_translation_hosts.py --hosts keller.cs.nmsu.edu

# 只读检查全部允许主机；不会启动模型或占用 GPU
python scripts/check_translation_hosts.py

# 可复现的合成双说话人 smoke（默认只转录；加 --translate 会继续调用本地 Qwen）
python scripts/run_audio_transcription_smoke.py \
  data/audio_smoke/two_speaker_smoke.wav --num-speakers 2 \
  --host keller.cs.nmsu.edu
```

远端 ASR 使用 CPU INT8，避免当前 CUDA 13 环境与 CTranslate2 的 CUDA 12 运行库冲突；Community-1 使用所选 GPU。
Keller GPU 忙时任务保持等待，超时后如实失败并保留本机原件；不会把语音任务自动挤到运行 Qwen 的 Iverson。远端已缓存模型以离线路径加载，HF key 只供授权模型
刷新使用，保存在 `/home/simurghnobackup/zcui/audio_transcription/.secrets/hf_token`（mode 0600），不会进入进程日志、
API 或仓库。详细架构、版本、验证结果和限制见
[docs/audio_transcription_STATUS_2026-07-21.md](docs/audio_transcription_STATUS_2026-07-21.md)。

### 阅读副本工坊：PDF 转 Kindle 与手机格式

页面：`http://127.0.0.1:5001/ebook-conversion`。同一次解析产出两种阅读副本：**EPUB 重排**给手机和支持
EPUB 的 Kindle（正文重排、字号可调，表格与图形渲染成图片原样插入，保留原文页码作为 EPUB 页标记方便引用）；
**裁边分栏 PDF** 给墨水屏（切白边、双栏按栏切开、按设备屏幕比例重排页面，公式图表 100% 保真）。
两者共用 `services/pdf_translation_service.py` 里的版面引擎，通过 `extract_reading_layout()` 取得
与翻译路径相反的取舍：保留参考文献、把表格与图形当作可渲染区域、扫描件只交几何不抛异常。

**这个模块只用本机 PyMuPDF，不连任何远端 GPU**，因此不套 `PAPER_TRANSLATION_ENABLED` /
`AUDIO_TRANSCRIPTION_ENABLED` 那类开关，即使那两个模块被硬关闭也照常可用。

三种选文件方式：填本机目录递归批量（原件只读，不产生副本）、浏览器选整个文件夹、多选文件。
三种投递方式：逐个下载或打包 ZIP、发到 Kindle 邮箱、写入指定本机文件夹（同名默认跳过不覆盖）。

模块能列举本机任意目录并往磁盘写文件，因此**默认只允许服务器本机访问**，不跟随普通局域网只读策略；
确需远程使用时才设 `EBOOK_ALLOW_REMOTE=1`。扫描件没有文本层，EPUB 会明确标为跳过而不是产出空书，
裁边分栏 PDF 仍然可用。详细设计取舍、几何算法与已知不足见
[docs/ebook_conversion_STATUS_2026-08-15.md](docs/ebook_conversion_STATUS_2026-08-15.md)。

### 悦读FM：本地归档与播放

页面：`http://127.0.0.1:5001/yuedu-fm`。RSS 原始快照、逐集 JSON、封面和音频保存在
gitignored 的 `data/yuedu_fm/`，不会进入研究数据库或公开仓库。网页可启动完整同步；命令行也可断点续传：

```bash
# 先同步完整目录、节目文字和全部封面（不下载 MP3）
python scripts/sync_yuedu_fm.py --metadata-only

# 下载全部音频；RSS 在 2026-07-22 声明约 4.30 GiB，可中断后重跑
python scripts/sync_yuedu_fm.py

# 只处理前 2 集资源，用于网络与字段 smoke test
python scripts/sync_yuedu_fm.py --limit 2

# 完整同步后逐文件复核大小与 SHA-256
python scripts/verify_yuedu_fm.py

# 追加同步已知且可公开访问的微信公众号文章、M4A 音频和正文图片，
# 并生成 data/yuedu_fm/library_combined.json 供本地播放器读取
python scripts/sync_yuedu_fm_wechat.py --discover-related
```

下载采用单连接低频请求、有限超时、`.part` 临时文件和 HTTP Range；完整文件按最终 HTTP 响应长度校验后才进入本地播放器，
RSS 声明长度另存作审计（本源多数声明值与实际响应不同）。2026-07-23 全量同步的 472 个音频约 4.77 GiB、472 张封面约 0.47 GiB。
每次 RSS 原文和完成态 manifest 均另存时间戳快照，保留来源与字段变化证据。微信公众号导入只处理从新浪公开短链和文章正文“往期作品”
能直接打开的文章；不使用公众号后台、微信客户端历史接口或验证码绕过。2026-07-23 已可归档 13 篇微信文章，其中 8 集作为 RedCircle
之外的新增本地节目合并进播放器，5 集按标题+时长或音频哈希判为重复后跳过。版权归节目方与原作者所有，本模块只面向个人本地收听，
不重新发布音频或文字。

### CardCookie：默认关闭的按需监控

页面：`http://127.0.0.1:5001/cardcookie-monitor`。模块只检查 CardCookie 的 Walmart 与 Best Buy
公开页面，支持 1/2/3/5 分钟及更长间隔，每轮每个商家一次请求；遇到验证页或 HTTP 403/429 自动退避
15 分钟，不会绕过登录、验证码或访问限制。首次成功结果仅作为
本机基线，不发送邮件；以后有货/缺货、折扣、面值、售价或页面卡片数量发生变化时才记录事件并按 SMTP
设置通知。连续三次检查失败才发送一次异常提醒，失败不会覆盖上次有效状态。

运行开关不持久化：服务器每次启动后均为关闭，只有在本机页面明确点击“开启监控”才开始自动查询。
关闭状态下的“立即检查一次”只更新本机记录，不发送邮件。记录保存在 gitignored 的
`data/cardcookie_monitor.db`。现有 `C:\Workplace\Cardcookie` 笔记本保持原样，仅作为历史参考；其中若曾
保存明文邮箱授权码，应先在邮箱后台撤销并生成新授权码，不要复制到代码或仓库。

页面内有本机邮件配置表单，保存时只更新 gitignored 的 `.secrets`，不会发送测试邮件。CardCookie 使用
独立的 `CARDCOOKIE_SMTP_HOST/PORT/USER/PASS/FROM`、`CARDCOOKIE_NOTIFY_TO`、
`CARDCOOKIE_SMTP_USE_SSL/STARTTLS` 参数，避免与其他模块混用；旧版通用 `SMTP_*` 参数仅作兼容回退。
已从旧笔记本导入 QQ SMTP 服务器、端口、发件人与收件人，但旧明文授权码被明确跳过。正式启用前应在
QQ 邮箱后台撤销旧授权码，在本机页面填入新授权码；密码不会进入 API、数据库、页面回显或日志。

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

财政收支历史来自财政部国库司“财政收支情况”原文：一般公共预算覆盖 2010 年起，政府性基金覆盖 2012 年起；原始值是 YTD 累计，页面另提供不跨缺月的相邻 YTD 差分流量（1—2 月保留合并窗口），并显示月度覆盖审计。页面中的收支差额均为 `收入 - 支出` 的 derived 分析值，不等于法定预算赤字；“两本账”仅作简单相加，未抵销调入调出。全年推演自动锚定最新非 12 月官方累计月，按历史同截止月/全年比例重算；上半年口径保留为回测对照。未来三年同时展示最可能、较好、较坏三种透明点估计，并以固定种子的 5,000 次年度联合冲击抽样给出 P10/P50/P90 模型敏感性区间；全部标记为 scenario，不写入 official observation。

财政债务调度器默认每 168 小时检查一次已接入来源。抓取失败会写入
`fiscal_debt_update_logs`，不会清空或用假数据覆盖旧 observation。

`/debt-ceiling` 的广义口径为“国债 + 地方政府法定债务 + 财政部披露的地方政府隐性债务”。
2023、2024 为官方隐性债务锚点；2025 因尚无官方隐性债务余额，仅按已确认置换债和年度化债资源
给出无概率含义的情景区间。城投债是基于发行人名称关键词代理识别的企业债券，不等于隐性债务；
私有 `data/lgfv_bond.db` 可单独计算已回填样本的存续发行额上限与偿付情景；当前页面另以用户
指定的15万亿元作为透明的市场基准情景，并按候选债条款结构缩放到期/付息路径。该基准不是官方
观测，不会写入公开快照，也不会把市场代理数字混入官方总量。

### 房价历史回填

```powershell
# 统计局现行 70 城逐城口径（2011 起，公开来源，可复现）
python scripts/backfill_housing_history.py --source nbs --start-year 2011 --end-year 2026 --nbs-workers 3

# 统计局全国商品房销售面积/销售额（月度累计自2012-02；年度长历史自1991）
python scripts/backfill_housing_history.py --source nbs-sales --start-year 2012 --end-year 2026 --nbs-workers 3

# 安居客关注十五城年度页（2010 起，低频、本机保存，验证页即跳过）
python scripts/backfill_housing_history.py --source anjuke --start-year 2010 --end-year 2026 --max-requests 90

# 安居客全国历史排名页（独立年度快照层；优先复用本地缓存）
python scripts/backfill_housing_history.py --source anjuke-yearly --no-network
```

统计局全国商品房年度销售面积与销售额从 1991 年起单独保存；月度累计仅从可连续核验的
2012 年 1—2 月合并发布期起回填，不把年度值拆成月份。统计局 2010 年仍是旧价格发布制度，
不与 2011 年后的逐城价格序列拼接。安居客挂牌数据和原始页只写入
gitignored 的 `data/housing_listing.db` 与 `data/anjuke_raw/`，不会进入公开仓库。全国历史排名页形成
独立的年度低频快照，城市年度页形成逐月序列；年度点不复制成 12 个月，也不进入与官方二手指数的
月度对比。页面价格为 `-` 时保留缺失，不补零、不用区县均价替代。
全国销售区的“当年销售面积累计/当年销售额累计”指统计局年初至今的官方月度 YTD；
“历史累计销售面积/历史累计销售金额”则是覆盖期内各年度官方总量之和，1991—2004 与
2005 年以后统计范围存在阶段变化，因此只作规模汇总。

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
