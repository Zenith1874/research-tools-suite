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
| `/paper-translation` | **学术语言工作台（文档翻译与文章总结）**：PDF/DOCX/TXT/Markdown 本机文件处理，通过 SSH 隧道调用校内 GPU 上的开源模型；支持逐节小结、结构化全文摘要及翻译+总结双输出，并保留格式与覆盖审计。 |
| `/audio-transcription` | **研究语音工作台**：访谈、会议、讲座和研究录音的逐词转录、匿名说话人区分、可选逐轮翻译；任务在独立结果页直接阅读，同时保留原文/译文/双语 TXT、JSON、SRT、VTT 和 ZIP 导出。 |
| `/china-rates` | 中国利率与汇率（LPR、SHIBOR、人民币对美元中间价；中国货币网官方接口，每日自动更新） |
| `/us-macro` | 美国宏观（就业、通胀、增长、财政债务、利率金融五组约 46 序列，含美联储总资产/美国 M2/VIX/美元指数/密歇根信心；BLS/劳工部/BEA/财政部/美联储/CBOE 等经 FRED 免 key CSV）。中国实体经济指标（CPI/PPI/PMI/工业增加值/社零/固投月度 + GDP 季度初步核算，统计局新闻稿与表格解析，2012-2016 起不等）由 `services/china_macro_service.py` 供给 `/macro-analytics` |
| `/housing` | 中国房价（统计局 70 城新房/二手官方指数 + BIS 全国指数 + 安居客二手挂牌价参考及历史双口径走势；挂牌数据仅存本机独立库，不入仓库） |

## 全站信息架构

顶部导航分为四个一级入口：

- **中国宏观**：`/dashboard`、`/fiscal-debt`、`/china-rates`、`/housing`
- **美国宏观**：`/us-macro`
- **ABDC 商科研究**：`/abdc`、`/abdc-astar-research`
- **科研工具**：`/paper-translation`（“学术语言工作台”）、`/audio-transcription`（“研究语音工作台”）

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
- `ASTAR_MAILTO` — OpenAlex / Crossref polite-pool 联系邮箱（建议设为你的真实邮箱；默认占位）。
- `ASTAR_AUTO=0` — 关闭 A\* 雷达每天一次的后台增量抓取。
- `FISCAL_AUTO=0` — 关闭政府债务模块每周一次的官方来源检查。
- `RATES_AUTO=0` — 关闭利率/汇率与美国宏观每日一次的自动更新。
- `ANJUKE_AUTO=1` — 开启安居客挂牌价每周低频检查；首次 70 城人工验收完成前默认关闭（验证码页自动跳过，不绕过）。

### 校园网访问安全

默认配置保留局域网查看能力：其他电脑可打开 `http://<本机校园网IP>:5001`，但只能读取页面和数据；更新数据、保存文章、重新分类与运行情景等写操作默认仅允许服务器本机执行。这样无需公开商业挂牌数据库，也避免校园网内其他设备误触发长任务。

如只在本机使用，可在 `.secrets` 中加入 `SERVER_HOST=127.0.0.1`。不建议在校园网设置 `ALLOW_REMOTE_WRITES=1`；确需远程管理时优先配置随机的 `ADMIN_TOKEN`，并通过受控客户端请求头传递，令牌文件已被 `.gitignore` 排除。

### 学术语言工作台：文档翻译

翻译模块把文件处理和模型推理解耦：PDF/DOCX/TXT/Markdown 原件、检查点和译文只保存在本机
`data/translation_jobs/`；远端 GPU 只接收分段后的文本。vLLM 绑定远端回环地址，通过 SSH 隧道访问，
不向校园网公开模型端口。

总结采用“逐节小结 → 全文结构化摘要”的分层流程。检查点同时绑定源文本 SHA-256、目标语言、领域、
术语表和提示版本；服务重启时遗留的排队/运行任务会标记为“已中断”并保留检查点，用户可安全重试。
DOCX 总结只读取 `word/document.xml`，不会把页眉、页脚、批注、脚注或尾注作为论文正文。多文件批量
默认由单 worker 队列顺序处理，避免同时挤占本机和 Iverson。总结结果同时记录单元完整性、排除项和
目标语言文字占比；缺失正文单元会硬失败，语言占比异常则保留结果并给出可人工复核的警告。
可靠性加固、检查点 schema 与验证范围见
[docs/paper_summary_reliability_STATUS_2026-07-22.md](docs/paper_summary_reliability_STATUS_2026-07-22.md)。

PDF 模式面向带可提取文本层的论文：保留原页尺寸、图片、矢量线条、双栏和链接，在原段落矩形内写入中文；
表格内部、参考文献、页眉页脚和竖排版权文字默认保留原文。它是高保真阅读副本，不是字节级无损替换。
扫描型 PDF 在本地 OCR/VLM 尚未配置时会明确失败，不生成缺页或假完成文件。

```bash
# 1. 默认使用记录中的主机，否则固定 Iverson；只有显式 --host auto 才会多机选择
python scripts/manage_translation_vllm.py start

# 2. 隧道由看门狗自动维护:只要模型状态文件在(manage start 后),隧道断了(如重启电脑)
#    会在 20s 内自动重建;也可手动 scripts/start_translation_tunnel.sh

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
