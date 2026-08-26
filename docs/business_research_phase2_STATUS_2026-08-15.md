# ABDC 商科研究 Phase 2 状态

日期：2026-08-15（初版）／2026-08-15 修订版
范围：Theory Library、Construct Library、Methods Lab、Paper Workspace、Literature Landscape，以及与既有 ABDC / A* Research Radar 的连接。

## 结果

Phase 2 已按现有项目架构完成增量实现。项目仍使用 Python 标准库 `ThreadingHTTPServer`、原生 HTML/CSS/JavaScript 和 SQLite，没有引入 React/Next/npm 构建链。

目前新增的是一个可运行的研究工作台和可审计的研究目录脚手架，不把未经核验的理论来源、量表条目、经典论文或研究结论伪装成正式文献综述。

## 修订版修复的问题（2026-08-15 复核）

首版通过了定向测试，但用真实 `pboc_data.db`（131,017 篇）复核时暴露出几类问题，本轮全部修复。

### 1. 页面上的错误学术内容

- **理论概念模型曾对全部 10 个理论硬编码 JD-R 图**。Social Exchange Theory、RBV、TAM 等页面都显示 "Job Demands → Exhaustion"。现在概念模型来自该理论自己的 catalog 记录：有 `conceptual_model.pathways` 就画路径（目前只有 JD-R 有），否则由该理论自己的 antecedents / mechanisms / outcomes 派生，两者都没有就显式留空。视图层不再包含任何理论专有词汇（有测试守卫）。
- **理论/方法计数把上位标签当成自己的证据**。`job_design` 同时覆盖 JD-R 和 Job Characteristics Model，导致两个理论显示完全相同的 357 篇；`survey` 让 SEM 和 Multilevel 都显示 9,874 篇；`causal_inference` 让 DiD/IV/RDD 显示同一批约 5,700 篇。现在 catalog 把标签拆成 `tags`（精确，驱动 "linked papers"）和 `broad_tags`（上位标签，单独计数并在卡片和详情页显式标注），DiD 从 6,915 降到真实的 1,570。
- **TAM / UTAUT 的 0 没有解释**。DB 的 2,219 个 theory tag 里没有任何 technology acceptance 类标签，所以 0 是分类器词表的覆盖限制而不是"没有这类研究"。现在显示 `no classifier tag` 徽章和明确说明；没有为了填数字编造映射。
- **Underexplored Combinations 会在极小语料上出结论**。15 篇语料时把 COR × Burnout 标成"研究得少"。现在语料不足 `MIN_PAPERS_FOR_UNDEREXPLORED = 40` 时整节withheld并说明原因；达标时 0 计数的格子单独归类为"可能是分类器覆盖问题而非文献事实"。

### 2. 显示缺陷

- 年份曾走 `toLocaleString()`，页面显示 "2,020 / 2,026"。新增 `plain()`，年份与计数分开（有测试守卫）。
- 理论 antecedents / outcomes / core constructs 曾直接显示 slug（`employee-voice`、`social-support`）。服务端新增 `_resolve_refs()`，所有展示用引用先解析成名称。
- catalog 有 14 个 dangling reference（`event-study`、`synthetic-control`、`case-study`、`grounded-theory`、`leader-support` 等被引用但不存在），服务端静默过滤成空白区。现在这些实体全部补齐，且有测试断言零 dangling。
- 每页有两个 `<h1>`（shell 占位 + 详情标题），`document.title` 恒为 "Business Research Workspace"。现在详情页只有一个 `<h1>`，标题按路由设置。

### 3. 写了但没接上的功能

- `construct_network.links` 后端算好共现边、前端只画节点 → 现在渲染节点 + 最强共现边列表。
- `business_research_recent_papers_v1` 只写不读 → My Papers 新增"Recently opened"。
- localStorage fallback 只写不读，服务端写失败时数据静默丢失 → `ResearchStore.workspace()` 会把本地待同步的状态和笔记合并回来，并在页面上标注"仅存于本机"。
- 笔记删除/编辑后端有、前端没有 → 已接上，删除走确认弹窗。
- `.br-two-column` / `.br-sidebar` CSS 存在但从不使用 → Paper Workspace 现在是 desktop 70/30（实测 825px / 375px），mobile 堆叠。
- `_distribution` 的 `share` 没显示 → 分布图现在显示计数 + 百分比。

### 4. 真实 bug

- `POST /api/abdc/research/papers/<id>/notes/<note_id>/delete` 用 `path.split('/')[-3]` 取 paper id，实际落在字面量 `notes` 上，`int('notes')` 在 handler 之前抛 ValueError，请求以 `ERR_EMPTY_RESPONSE` 结束。首版没暴露是因为前端从未调用该端点。已改用正则捕获组，并加了回归测试。
- `update_library_state` 的部分更新会重置另一个字段：只传 `favorite` 会把 `reading_status` 打回 `unread`。现在缺省字段保留原值。

### 5. 性能

原实现每次打开目录页都对 131k 行做全表 `LIKE '%…%'` 扫描。新增 `research_paper_links` 派生索引（写在独立的 state DB，不动文章库），启动时后台线程构建、之后增量刷新。

| 调用 | 修复前 | 修复后 |
| --- | ---: | ---: |
| Construct 列表 | 9.96s | 0.00s |
| 统一搜索 | 9.68s | — |
| Overview | 4.84s | 0.37s |
| Theory 列表 | 2.50s | 0.01s |
| Method 列表 | — | 0.04s |
| Landscape（3,294 篇） | 7.7s | 3.1s |

冷启动全量建索引一次约 140s，在后台线程执行，不阻塞请求。

### 6. 可访问性

- Paper Workspace 曾用 `role="tablist"/"tab"` 但没有 `aria-selected`、`aria-controls`、`tabpanel`。现在是完整的 tab 模式，含 roving tabindex 和方向键导航。
- Modal 现在支持 Escape 关闭、焦点陷阱、关闭后焦点归还。
- 矩阵格子按钮有 `aria-label`（"JD-R × Burnout: 3 papers"）。
- 所有输入控件有 label（`.br-visually-hidden`）。
- Emerging topics 不再只靠箭头和颜色，附文字说明（up / up sharply / unchanged）。
- 所有 section 都有 empty state，不再出现空白容器。

### 7. 内容缺口

- Methods 从 15 个扩到 36 个，四类均衡：quantitative 16、experimental 7、computational 7、qualitative 6（原为 9/1/4/1）。
- Constructs 从 12 扩到 17，补齐 `antecedents` / `outcomes` / `mediators` / `moderators`，Construct Network 改为数据驱动。
- Theory Library 搜索现在覆盖 core constructs（搜 "autonomy" 能找到 JD-R）；刻意不覆盖相邻实体名，否则搜 "Job Demands" 会返回所有与 JD-R 相关的理论。
- Landscape 多词短语无结果时自动放宽为 any-term 并在页面标注。修复前 "Return-to-office employee autonomy"（就是输入框 placeholder）返回 0 篇，现在返回 1,597 篇。

## 已实现功能

- 共享 Paper 模型：复用既有 `astar_articles` 和 `astar_article_classifications`，统一提供标题、作者、年份、期刊、ABDC 等级、DOI、摘要状态、来源、分类和证据边界。
- Theory Library：理论列表、搜索/学科筛选、理论详情、核心构念、概念模型、应用论文、边界条件、批评与关联理论。
- Construct Library：构念定义、理论关系、研究角色、数据驱动的构念网络、关键词推断的论文使用情况，以及测量元数据边界。未放入未经许可的完整量表题项。
- Methods Lab：四类方法目录；方法详情含适用场景、假设、工作流、诊断、常见错误和 R/Python/Stata 代码脚手架。
- Paper Workspace：真实文章详情、阅读状态、收藏、APA/BibTeX/纯文本引用、Overview/Theory/Constructs/Method/Findings/Notes 分页、70/30 侧栏，以及带标签的笔记（增删改）。
- Literature Landscape：主题/年份/ABDC 等级/学科筛选，主题、理论、方法、构念分布（含百分比），构念共现网络（节点 + 边）、Theory × Outcome 矩阵、相对低计数组合、近期/前期计数对照和代表性文章。
- 共享入口：首页、ABDC 子导航和 `/abdc/research`、`/research` 别名；既有 `/abdc` 与 `/abdc-astar-research` 保持不变。
- 状态存储：用户状态和派生链接索引放在被 `.gitignore` 忽略的 `data/business_research_state.db`，与大型文章元数据库分离；服务不可写时前端有 localStorage fallback 且会读回。

## API 与页面路由

| 类型 | 路由 |
| --- | --- |
| 总览 | `GET /api/abdc/research/overview` |
| 搜索 | `GET /api/abdc/research/search` |
| 目录 | `GET /api/abdc/research/theories`、`/constructs`、`/methods` 及其 `/<slug>` |
| 文章 | `GET /api/abdc/research/papers`（分页列表）、`/papers/<id>`（工作台） |
| 版图 | `GET /api/abdc/research/landscape` |
| 个人库 | `GET /api/abdc/research/library?recent=<ids>` |
| 状态/笔记 | `POST /api/abdc/research/papers/<id>/state`、`/notes`、`/notes/<note_id>/delete` |
| 页面 | `/abdc/research`、`/abdc/theories`、`/abdc/constructs`、`/abdc/methods`、`/abdc/papers/<id>`、`/abdc/landscape`、`/abdc/library` |

## 数据边界

- `data/research_catalog.json` 明确标为 `demo_catalog`。理论、构念、方法定义是用于导航与研究设计的策划脚手架；来源、起源年份、测量元数据和引用仍需逐项回到 primary source 核验。
- 文章不从目录文件伪造。文章元数据、ABDC 等级、DOI、引用和摘要来自既有 A* Radar 缓存；缺少的研究问题、假设、样本、结果、局限和未来研究继续显示为 unavailable/not structured。
- 理论/方法论文链接复用既有分类标签，并区分精确标签与上位标签；构念链接使用 `title_abstract_keyword_inference`，页面和 API 都显式标注。
- Literature Landscape 是可用缓存的描述性聚合。`Underexplored Combinations` 只表示当前筛选语料中的相对低计数组合，不等于理论 research gap；语料不足 40 篇时整节不出。
- Theory 的 `seminal_works` 记录了作者/年份/篇名/出处；页面按行显示核验状态。当前 105 条中 85 条已由 Crossref 可信匹配（带 `verified_crossref` 与真实 DOI），20 条仍为 `pending_verification`，没有把不确定结果强行填成引用。OpenAlex 有日预算时，核验脚本会自动切换到 Crossref；`key_scholars` 仍为空并显式说明，页面另外显示来源作者，但不把他们冒充 canonical scholar attribution。
- 当前服务消费既有文章缓存的 A* / A 范围，不重新定义或冒充严格的"全体 A*"全集。

## 本轮文件

- 后端：`services/business_research_service.py`、`server.py`
- 前端：`static/business_research.html`、`static/business_research.css`、`static/business_research.js`
- 目录：`data/research_catalog.json`
- 测试：`tests/test_business_research_service.py`、`tests/test_business_research_contract.py`、`tests/test_research_source_verification.py`
- 目录生成：`scripts/build_research_catalog.py`、`scripts/research_catalog_constructs.py`、`scripts/research_catalog_methods.py`、`scripts/verify_research_sources.py`
- 文档：本文件

## 验证记录

```bash
python -m py_compile server.py services/business_research_service.py
node.exe --check static/business_research.js
python -m unittest tests.test_business_research_service tests.test_business_research_contract \
                   tests.test_research_navigation tests.test_astar_title_links
```

结果（基础阶段记录）：定向回归 42/42 通过；扩充目录后全量 `unittest discover` 661/661 通过；Python 编译检查和 Node 语法检查通过。当前全量复核结果见下方“全量修复记录”。

在临时 `SERVER_PORT=5019` 的本地服务上（现有 5001 服务未被停止或覆盖）用真实数据库做了浏览器检查：

- `/abdc/theories`：卡片显示解析后的构念名、精确/上位计数分列、TAM/UTAUT 带 `no classifier tag` 徽章、JCM 带 `broad tag only`。
- `/abdc/theories/job-demands-resources`：双路径概念模型来自 JD-R 自己的记录；单个 `<h1>`；标题为 "Job Demands–Resources Theory · Business Research"。
- `/abdc/theories/social-exchange-theory`：显示 SET 自己的 derived 模型，不再是 JD-R 图。
- `/abdc/methods/difference-in-differences`：5 个 related methods 全部解析；treatment/control before-after 设计示意；R/Python/Stata 代码页签带正确 ARIA。
- `/abdc/papers/31`：ARIA tab 模式完整；桌面 825/375 双栏；笔记保存/编辑/删除全流程通过；Modal Escape 与焦点归还通过。
- `/abdc/landscape?topic=algorithmic management`：分布带百分比、共现边渲染、矩阵格子有 aria-label、年份显示为 2020/2026。
- 375px 移动视口：`document.documentElement.scrollWidth === window.innerWidth === 375`，无横向溢出；侧栏堆叠；矩阵表格在 `overflow-x:auto` 容器内横向滚动。


## 目录扩充与来源（2026-08-15 第三轮）

### 规模

| | 之前 | 现在 |
| --- | ---: | ---: |
| 理论 | 10 | **60** |
| 构念 | 17 | **39** |
| 方法 | 36 | 36 |

理论按学科分布：Management / Strategy 34、OB / HR 24、Marketing 16、Information Systems 16、Computational Social Science 6（一个理论可归属多个学科）。

补入的高价值理论此前完全缺失，而它们在缓存中的覆盖量很大：Signaling Theory 3,007 篇、Transaction Cost Economics 658 篇、Sensemaking 329 篇、Agency Theory 270 篇。这些是先挖 `astar_article_classifications` 的标签词表、再据此选题补入的，不是凭印象罗列。

60 个理论里有 18 个在当前缓存中没有任何对应分类标签（如 TAM、UTAUT、LMX、组织支持理论）。页面显示 `no classifier tag` 徽章并说明这是分类器词表的覆盖限制，而不是"没有这类研究"。

### 中英对照

理论、构念、方法都新增 `name_zh` 与 `definition_zh` / `description_zh`。页面在英文名下方以较弱的视觉层级显示中文名与中文释义——英文保持权威地位，因为来源文献是英文的。

中文进入搜索索引，实测 `信号` → Signaling Theory、`社会交换` → Social Exchange Theory。搜索框 placeholder 也提示支持中文。

### 来源

每个理论新增 `seminal_works`（作者、年份、篇名、出处、类型），共 105 条。

这些来源首先写自领域知识，是"待核查的线索"，不是自动生成的文献综述。核验前为 `pending_verification`；核验后才写入来源特定的 DOI 与元数据。

`scripts/verify_research_sources.py` 负责把它们解析成真实记录：优先查询 OpenAlex；如果账户日预算耗尽或没有可信命中，则查询 Crossref。命中后写入真实 DOI、来源、年份与来源可提供的元数据，并把状态改为 `verified_openalex` 或 `verified_crossref`。匹配要求标题重合度 ≥ 0.6，且必须有作者姓氏或年份佐证——只靠标题命中正是错误记录被标成"已核验"的典型原因。

`tests/test_research_source_verification.py` 用桩数据离线验证了匹配逻辑：同名不同作者不同年份会被拒绝、无关标题会被拒绝、多个候选中取最优、作者对但年份差一年仍接受（重印/在线优先常见）。

本轮实际运行时 OpenAlex 账户余额为 0（`Insufficient budget … Resets at midnight UTC`）。脚本识别后没有空转重试，而是切换到 Crossref；最终 105 条中 85 条可信匹配，20 条保留 pending。若未来 OpenAlex 恢复余额，脚本仍可用 `--all` 对已核验记录重新核对：

```bash
python scripts/verify_research_sources.py
```

需要注意：**A\* Research Radar 依赖同一个 OpenAlex 配额**；Crossref fallback 只覆盖本目录的来源核验，不会替代 A* Radar 的文章抓取。

### 顺带修掉的问题

`business_research_state.db` 原为回滚日志模式，全量重建索引时会独占写锁约 140 秒，期间所有目录页报 `database is locked`。已改为 WAL 并将写入按批提交，重建期间页面可正常读取部分索引而不报错。

### 生成方式

catalog 不再手写 JSON，改为脚本生成，便于后续维护：

```bash
python scripts/build_research_catalog.py     # 生成 data/research_catalog.json
```

来源模块：`scripts/build_research_catalog.py`（理论）、`scripts/research_catalog_constructs.py`（构念）、`scripts/research_catalog_methods.py`（方法）。生成时强制校验交叉引用全部可解析、id 无重复、精确标签与上位标签无重叠，任一不满足即构建失败。

## 2026-08-15 全量修复记录

- `Signaling Theory` 的 catalog 关系补为 `information-asymmetry`；moderator 没有证据支持时保持空，并在页面显示 `No catalog relationship recorded`，不把缺口写成事实。
- Theory detail API 增加 `source_authors`。它只转录目录经典文献中的作者及其逐行核验状态；独立的 `key_scholars` 列表仍为空，避免把来源作者误称为 canonical scholars。
- `scripts/verify_research_sources.py` 增加 OpenAlex→Crossref fallback、来源标记、Crossref DOI/年份/出处及保守匹配逻辑；`scripts/build_research_catalog.py` 会在重建脚手架时保留已核验字段。105 条来源当前为 `verified_crossref=85`、`pending_verification=20`。
- 本轮离线回归：

```bash
python3 scripts/build_research_catalog.py
python3 -m py_compile scripts/verify_research_sources.py scripts/build_research_catalog.py services/business_research_service.py
python3 -m unittest tests.test_research_source_verification tests.test_business_research_service tests.test_business_research_contract
"/mnt/c/Program Files/nodejs/node.exe" --check static/business_research.js
```

结果：目录构建成功并报告 `85 verified fields preserved`；定向测试 41/41 通过；Windows Python 全量 `unittest discover` 665/665 通过；Python 与 JavaScript 语法检查通过。

## 2026-08-15 界面一致性复核

- Business Research 页面不再自行重复渲染 `Overview / Journals / Constructs ...` 页面内导航。只要共享 `research-nav.js` 已挂载，就由全局的主 tab + ABDC 子导航负责；独立运行时才保留本地 fallback。Theory、Construct、Method、Paper 详情页会按父级路由保持对应子导航高亮。
- `business_research.css` 统一到既有 `/abdc` 的视觉框架：全局导航仍使用深色应用 chrome，内容区改为 `#f0f2f5` 浅灰背景、`#1a3a5c` 蓝色页面标题带、白色卡片/筛选区、统一边框与按钮状态。Construct 列表和详情都经过同一套壳层处理。
- Windows 浏览器临时服务 `SERVER_PORT=5017` 上核验了 `/abdc/research`、`/abdc/theories`、`/abdc/constructs`、`/abdc/methods`、`/abdc/landscape`、`/abdc/library`、`/abdc/constructs/autonomy` 和 `/abdc/papers/509`：每页 `globalNav=1`、`localNav=0`、单一 `<h1>`、无页面错误；详情页的父级 tab 也保持高亮。
- 截图证据：`output/playwright/construct-after-active.png`、`output/playwright/construct-list-after.png`、`output/playwright/abdc-reference-after.png`。
- 375px 移动视口复核：`scrollWidth === window.innerWidth === 375`，共享导航仍存在、Construct Library 仍高亮，详情卡片左右边距为 14px。
- 本轮回归：定向契约测试 24/24 通过；Windows Python 全量 `unittest discover` 667/667 通过；`business_research.js` 与 `research-nav.js` Node 语法检查通过；`git diff --check` 通过。

## 后续工作

1. UTC 零点后运行 `python scripts/verify_research_sources.py`，把 105 条经典文献从 pending 升级为带真实 DOI 的 verified；同时处理 OpenAlex 预算问题，A* Radar 依赖同一配额。
2. Landscape 的主题匹配仍是 `LIKE '%term%'` 全表扫描（大语料 2–6s）。若要进一步提速，下一步是给标题/摘要建 FTS5 索引（同样放在派生的 state DB 里）。
3. 在有授权的结构化来源或全文抽取链完成后，再增加文章级研究问题、假设、样本、发现、局限和未来研究字段；不要从标题/摘要自动补写事实。
4. 分类器词表本身是覆盖瓶颈：36 个方法里有 5 个精确计数为 0，10 个理论里有 2 个完全没有对应标签。补 classifier 词表比补 catalog 更能提升这四个模块的实际可用性。
