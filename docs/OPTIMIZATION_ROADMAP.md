# 研究工具集 · 优化路线图 / Research Tools Suite · Optimization Roadmap

> 体检日期 / Audit date: 2026-06-30 · 代码量 ~10,100 行(8,690 Python + 1,457 前端) · DB 522MB / 133,297 篇 A\* 文章 / 97 个月央行数据
> 结论:功能层已经很完整,当前短板集中在 **运维兜底、缓存体验、数据缺口、测试覆盖** 四块。
> Verdict: features are mature; the real gaps are **ops resilience, caching/UX, data coverage, and test depth**.

优先级 / Priority:🔴 高(便宜且疼) · 🟡 中(值得排期) · 🟢 低(锦上添花)

---

## ⚡ 状态更新 / Status Update (2026-07-02)

原 21 项中 **除以下几项外全部完成**(含全部 🔴 和绝大部分 🟡)；另新增完成:
中国利率/汇率与美国宏观两个新模块(历史到 2006/1948)、图表悬停十字线、HTML no-cache、
国债还本付息(derived)、财政收支模块、What's New 首页横幅+事件、DB 每周备份、
CSV/BibTeX 导出、每日自动 LLM 精修、A* 语义搜索(bge-small 本地向量+期刊匹配)、
LLM 抽样审计脚本、核心测试 5→26、服务器卡死根治+看门狗。master 与 work 同步。

**仍未完成 / Still open:**
| 项 | 状态 |
|---|---|
| #1 看门狗计划任务注册 | ⏸ 等用户执行一条 PowerShell(命令在 scripts/watchdog.py 末尾) |
| #9 储蓄国债/香港人民币国债 | 🚧 MOF 502 / 需新数据源，外部阻塞 |
| #12 城投债 | 🚧 无免费官方口径，保持诚实 missing(建议不做) |
| #15 LLM 精修存量 backlog | 每日自动精修已上线；老存量(relevance≥40 未过 LLM 的)可一次性排队跑 |
| #20 0.0.0.0 绑定 | 🟡 家用网可接受；公用网络改 127.0.0.1 或加 token |
| 首次分类审计运行 | ⏸ 等 DEEPSEEK_API_KEY(脚本 --dry-run 已验证) |
| SMTP 邮件通知 | ⏸ 可选，配 SMTP_HOST/USER/PASS/NOTIFY_TO 即启用 |

---

## 中文版

### 一、运维与稳定性(最疼,先做)

| # | 项目 | 现状 | 建议 | 优先级 |
|---|------|------|------|--------|
| 1 | **看门狗未注册开机自启** | watchdog.py 已写好、已验证自愈,但是手动启动的——**重启电脑后失效** | 注册 Windows 计划任务(登录自启,命令已写在 watchdog.py 末尾注释) | 🔴 5 分钟 |
| 2 | **master 落后 work 19 个提交** | GitHub 首页(默认 master)显示两周前的代码,已造成一次"代码丢了?"误会 | 合并 PR #3 → master;之后养成小步合并习惯 | 🔴 5 分钟 |
| 3 | **无 requirements.txt** | README 只写了 `pip install requests`;实际还依赖 beautifulsoup4、openpyxl、pypdf 等 | `pip freeze` 精简后写 requirements.txt,README 同步 | 🔴 10 分钟 |
| 4 | **异步更新后前端没跟上** | 更新按钮现在立即返回"已在后台运行",但页面不会自动等结果刷新,用户可能以为没反应 | 前端拿到 `status:started` 后轮询 `/api/jobs`,任务 done 时自动刷新数据并 toast | 🟡 1-2 小时 |
| 5 | **server.stderr.log 无轮转** | 追加写,长期会膨胀 | 看门狗重启时轮转(>5MB 改名归档),或用 RotatingFileHandler | 🟢 |

### 二、缓存与前端体验

| # | 项目 | 现状 | 建议 | 优先级 |
|---|------|------|------|--------|
| 6 | **完全没有缓存头** | send_file 不发 Cache-Control/ETag → 浏览器启发式缓存,已两次让用户看到旧页面(dashboard、fiscal-debt) | HTML 发 `Cache-Control: no-cache`;/vendor/ 发长缓存 `max-age=31536000`(文件不变) | 🔴 30 分钟 |
| 7 | **/api/data 每请求现算** | 532KB payload 每次 0.43s 重建;数据其实一天最多变两次 | 内存缓存 + 写库后失效(更新任务完成时清缓存),响应可到 <10ms | 🟡 1 小时 |
| 8 | **A\* 列表接口分页已做,但 97 个月 dashboard 未做数据窗口** | dashboard 全量返回 97 个月(可接受),fiscal-debt 表格 slice 已限;暂无大问题 | 观察即可,数据破 200 个月再做窗口 | 🟢 |

### 三、数据完整性(fiscal-debt 已知缺口)

| # | 项目 | 现状 | 建议 | 优先级 |
|---|------|------|------|--------|
| 9 | **储蓄国债、香港人民币国债** | 卡片单列但 missing;储蓄通知已抓到 3 期但只有计划额且 MOF 正文页间歇 502 | 等 MOF 站点稳定后写储蓄公告金额解析;香港需接新源(金管局/财政部驻港公告) | 🟡 被外部阻塞 |
| 10 | **国债还本付息** | missing 卡片;RQ 是"偿付压力"却缺一半 | 接中债登/财政部兑付公告,或先用"到期分布表 × 票面利率"给 derived 估计并明确标注 | 🟡 半天 |
| 11 | **财政收支/赤字缺口** | missing_modules 里挂着 | 接财政部月度财政收支报告(和现有 MOF 爬虫同模式) | 🟡 半天 |
| 12 | **城投债(LGFV)** | 无免费官方口径,暂不可做 | 保持 missing + 注明原因(现状正确),不要用 Wind 转载数据 | 🟢 保持 |
| 13 | **两个 MOF 502 公告** | 2025-184号、2026-33号持续 502,已记录 update_logs | 每次周更自动重试即可(已有);无需人工干预 | 🟢 已处理 |

### 四、A\* 研究雷达

| # | 项目 | 现状 | 建议 | 优先级 |
|---|------|------|------|--------|
| 14 | **LLM 抽样审计规则分类** | broad_area 曾系统性错 6,798 篇(法学/统计倒进 Management),靠肉眼撞见才修 | 写 `scripts/audit_classification.py`:每个 broad_area 抽 20 篇 → DeepSeek 判"标对没" → 报告不一致率;每月跑一次 | 🔴 半天,防守性极高 |
| 15 | **相关性精修覆盖率** | DeepSeek 精修只跑过部分批次;规则分 ≥40 的候选未全过 LLM | 排队跑完 relevance≥40 的存量(成本低,DeepSeek 便宜) | 🟡 |
| 16 | **摘要覆盖率** | 大量 no_abstract:cap55(评分被封顶) | 继续 Semantic Scholar 批量补摘要(管线已有),按核心刊优先 | 🟡 后台慢慢跑 |

### 五、代码质量与测试

| # | 项目 | 现状 | 建议 | 优先级 |
|---|------|------|------|--------|
| 17 | **测试只有 75 行 / 5 例** | 8,690 行 Python 只测了 PDF 解析和逆回购余额;A\* 分类、财政聚合、卡片纪律全裸奔 | 优先补三块:`classify_article`(含 broad_area 回归防复发)、`_card` 数据纪律(official 无 source_url 必降级)、`build_fiscal_monitor_payload` 契约测试 | 🔴 1 天 |
| 18 | **server.py 1,688 行单文件** | 路由 if/elif 长链 + 业务混杂 | 可拆 routes 表驱动;但**不疼就别动**(重构风险 > 收益) | 🟢 |
| 19 | **abdc_astar_research_service.py 2,071 行** | 单文件承担抓取+分类+LLM+payload | 同上,功能稳定期不动;新功能拆新文件 | 🟢 |

### 六、安全

| # | 项目 | 现状 | 建议 | 优先级 |
|---|------|------|------|--------|
| 20 | **绑定 0.0.0.0 无鉴权** | 局域网内任何设备可访问全部数据和**触发更新/跑情景**的 POST 接口 | 个人机+家庭网可接受;若在公用网络,改绑 `127.0.0.1` 或加最简 token | 🟡 视网络环境 |
| 21 | **API key 走环境变量** | ANTHROPIC/DEEPSEEK key 用 env,正确;.gitignore 已排除 db/bak | 保持;别把 key 写进代码 | 🟢 已达标 |

### 建议执行顺序(如果只做前五件)

1. 🔴 #1 看门狗挂计划任务(5 分钟,彻底告别"又打不开了")
2. 🔴 #2 合并 master(5 分钟,消除"代码在哪"困惑)
3. 🔴 #6 缓存头(30 分钟,告别 Ctrl+Shift+R)
4. 🔴 #14 LLM 抽样审计(半天,防下一个 6,798 篇级别的暗雷)
5. 🔴 #17 核心测试补齐(1 天,守住数据纪律底线)

---

## English Version

### 1. Ops & Stability (highest pain, do first)

| # | Item | Current state | Recommendation | Priority |
|---|------|---------------|----------------|----------|
| 1 | **Watchdog not registered for auto-start** | watchdog.py written & self-heal verified, but started manually — **dies on reboot** | Register a Windows Scheduled Task (at-logon; command in watchdog.py footer) | 🔴 5 min |
| 2 | **master is 19 commits behind work** | GitHub landing page (default = master) shows 2-week-old code; already caused one "did we lose code?" scare | Merge PR #3 → master; then merge small and often | 🔴 5 min |
| 3 | **No requirements.txt** | README says `pip install requests` only; actual deps include beautifulsoup4, openpyxl, pypdf | Write a trimmed requirements.txt; sync README | 🔴 10 min |
| 4 | **Frontend not adapted to async updates** | Update buttons now return "running in background" instantly, but pages don't poll for completion — feels unresponsive | On `status:started`, poll `/api/jobs`; auto-refresh + toast when done | 🟡 1–2 h |
| 5 | **No log rotation for server.stderr.log** | Append-only, grows forever | Rotate on watchdog restart (archive >5MB) or RotatingFileHandler | 🟢 |

### 2. Caching & Frontend UX

| # | Item | Current state | Recommendation | Priority |
|---|------|---------------|----------------|----------|
| 6 | **Zero cache headers** | send_file sends no Cache-Control/ETag → heuristic browser caching; users saw stale pages twice | `Cache-Control: no-cache` for HTML; long `max-age` for /vendor/ | 🔴 30 min |
| 7 | **/api/data recomputed per request** | 532KB payload rebuilt in 0.43s each call; data changes ≤2×/day | In-memory cache invalidated on update-job completion; <10ms responses | 🟡 1 h |
| 8 | **Data windowing** | 97 months returned in full — fine for now | Revisit past ~200 months | 🟢 |

### 3. Data Completeness (fiscal-debt known gaps)

| # | Item | Current state | Recommendation | Priority |
|---|------|---------------|----------------|----------|
| 9 | **Savings bonds & HK RMB treasury bonds** | Cards shown as missing (honest); savings notices captured but amounts unparsed & MOF pages intermittently 502 | Parse savings-notice amounts once MOF stabilizes; HK needs a new source | 🟡 externally blocked |
| 10 | **Treasury principal & interest payments** | missing; half of the "rollover pressure" question | Ingest ChinaBond/MOF redemption notices, or derive from maturity table × coupon with explicit `derived` labeling | 🟡 half-day |
| 11 | **Fiscal balance / deficit** | listed in missing_modules | Ingest MOF monthly fiscal revenue-expenditure reports (same crawler pattern) | 🟡 half-day |
| 12 | **LGFV debt** | No free official source | Keep honest `missing` + reason; do not use redistributed vendor data | 🟢 keep |
| 13 | **Two MOF announcements return 502** | Persistent server-side 502s, logged | Weekly auto-retry already covers it | 🟢 handled |

### 4. A\* Research Radar

| # | Item | Current state | Recommendation | Priority |
|---|------|---------------|----------------|----------|
| 14 | **LLM sampling audit of rule-based classes** | broad_area once mislabeled 6,798 articles (law/stats dumped into Management); found by luck | `scripts/audit_classification.py`: sample 20 per broad_area → DeepSeek verdict → disagreement report; run monthly | 🔴 half-day, high defensive value |
| 15 | **LLM refinement coverage** | Only partial batches refined | Queue all relevance≥40 backlog through DeepSeek (cheap) | 🟡 |
| 16 | **Abstract coverage** | Many `no_abstract:cap55` scores capped | Keep Semantic Scholar backfill running, core journals first | 🟡 background |

### 5. Code Quality & Tests

| # | Item | Current state | Recommendation | Priority |
|---|------|---------------|----------------|----------|
| 17 | **Only 75 lines / 5 tests** | 8,690 lines of Python; only PDF parser + repo balance tested | Add: `classify_article` (broad_area regression guard), `_card` data-discipline invariants, `build_fiscal_monitor_payload` contract test | 🔴 1 day |
| 18 | **server.py monolith (1,688 lines)** | Long if/elif routing | Table-driven routes possible — but don't touch while stable | 🟢 |
| 19 | **astar service 2,071 lines** | Crawl+classify+LLM+payload in one file | Same: leave stable code alone; new features go in new files | 🟢 |

### 6. Security

| # | Item | Current state | Recommendation | Priority |
|---|------|---------------|----------------|----------|
| 20 | **Binds 0.0.0.0, no auth** | Any LAN device can read all data and hit update/scenario POST endpoints | Fine on a home network; bind `127.0.0.1` or add a minimal token on shared networks | 🟡 depends on network |
| 21 | **API keys via env vars** | Correct; .gitignore excludes db/backups | Keep as is | 🟢 OK |

### Suggested order (if only five things get done)

1. 🔴 #1 Register watchdog as a Scheduled Task (5 min — never see "site down" again)
2. 🔴 #2 Merge work → master (5 min — kills the "where is my code" confusion)
3. 🔴 #6 Cache headers (30 min — no more Ctrl+Shift+R)
4. 🔴 #14 LLM sampling audit (half-day — prevents the next 6,798-article landmine)
5. 🔴 #17 Core tests (1 day — locks in the data-discipline guarantees)
