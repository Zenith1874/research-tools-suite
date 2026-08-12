# ABDC A* 单篇公开摘要补录状态（2026-08-03）

## 结论

已为以下文章补录 ScienceDirect 出版社公开摘要，并保留可审计来源；未抓取或保存付费全文。

- 文章 ID：`620`
- DOI：`10.1016/j.dss.2026.114683`
- PII：`S0167923626000722`
- 期刊：*Decision Support Systems*（ABDC A*）
- 出版社页面：<https://www.sciencedirect.com/science/article/abs/pii/S0167923626000722>

## 缺失原因核对

核对日期为 2026-08-03（America/Denver）。

| 来源 | 当前结果 | 解释 |
|---|---|---|
| ScienceDirect 公开摘要页 | 有完整摘要 | 可作为本次补录来源 |
| Crossref DOI API | `abstract=null` | DOI 元数据没有存入摘要，仅列出 Elsevier 文本挖掘链接 |
| OpenAlex | `abstract_inverted_index=null` | OpenAlex 无可重建摘要 |
| Semantic Scholar | `abstract=null` | API 明示摘要字段被出版社隐藏（publisher-elided） |
| ScienceDirect 直接自动请求 | HTTP 403 | Cloudflare 阻止普通自动请求；未绕过验证 |
| Elsevier 完整元数据 API | HTTP 401 | 完整 `view=META` 需要 API key；未尝试绕过 |

根因不是前端漏显示，而是原自动链路只使用 OpenAlex、Crossref 和 Semantic Scholar；三者均未返回摘要。出版社公开页面后来已有摘要，但原管道没有“人工核验公开摘要页”的补录通道。

## 本次变更

1. `data/astar_verified_abstract_overrides.json`
   - 保存 DOI、预期标题、公开摘要、ScienceDirect URL、PII、核验时间和来源说明。
2. `scripts/apply_astar_abstract_overrides.py`
   - 支持 `--dry-run`、单 DOI 选择和可选数据库路径。
3. `services/abdc_astar_research_service.py`
   - 新增 `apply_verified_publisher_abstract()`：唯一 DOI/标题校验、拒绝覆盖不同的非空摘要、写入来源记录、重跑单篇分类并写更新日志。
   - 修复后续 OpenAlex/Crossref 返回缺摘要时把已核验摘要状态和分类降级的问题。
4. `static/abdc_astar_research.html`
   - 将“元数据 API 未返回摘要”与“出版社页面不存在公开摘要”明确区分，不再把两者等同。

## 执行与结果

执行命令：

```powershell
python scripts\apply_astar_abstract_overrides.py --doi 10.1016/j.dss.2026.114683 --dry-run
python scripts\apply_astar_abstract_overrides.py --doi 10.1016/j.dss.2026.114683
```

数据库变化：

| 字段 | 补录前 | 补录后 |
|---|---|---|
| `abstract` | `NULL` | 1,223 字符、153 词 |
| `abstract_status` | `missing` | `available` |
| `data_status` | `title_only` | `publisher_metadata` |
| 来源 | OpenAlex / Crossref / Semantic Scholar 均无摘要 | 新增 `ScienceDirect / publisher_page / S0167923626000722` |
| 规则分类 | `uncertain` | `confident` |

摘要规范化文本 SHA-256：

`73d8f185ebe6f6d55471ab05d04080d1fab22f7f74d0f241409269e55508d4f5`

规则分类目前仍为 `relevance_score=20`，方法标签为 `machine_learning`、`theory_paper`；原有语义相关分 `74.7` 保留。本次只补摘要及来源，没有擅自改变“与我研究相关”的构念阈值或人工提高相关分。

## 验证

- 运行接口 `/api/abdc/astar/articles/620` 返回：
  - `abstract_status=available`
  - `data_status=publisher_metadata`
  - 摘要长度 1,223 字符
  - 来源记录含 ScienceDirect URL、PII 和 `full_text_fetched=false`
- 页面内联 JavaScript 通过 `node.exe` 语法校验。
- 全套测试：`python.exe -m unittest discover -s tests -v`
  - **425 tests passed**
- 新探测器通过 `py_compile`；试跑和批次报告均为 JSON 审计输出。
- `/api/health`：HTTP 200，`status=ok`；文章 620 仍返回
  `available / publisher_metadata / 1,223 字符`，新增 Springer 文章也返回
  `available / publisher_metadata` 并带 1 条 `publisher_page` 来源。
- 写入前确认没有运行中的翻译、转录或 A* 更新任务；随后由现有 watchdog 安全重启服务以加载防降级代码。
  - 旧服务 PID：`91632`
  - 新服务 PID：`112192`（watchdog 子进程）
  - `/api/health`：HTTP 200，`status=ok`
  - 重启后再次核对文章 620：`available / publisher_metadata / 1,223 字符 / 1 条 publisher_page 来源`

## 系统性补录（进行中）

为避免把一篇 ScienceDirect 的处理方式不加区分地套到所有出版社，新增了来源感知的只读探测器：

```powershell
python scripts\probe_astar_publisher_abstracts.py --publisher Springer \
  --limit 100 --delay 1.0 --output data\probe.json --apply
```

默认不写数据库；`--apply` 只把 `status=candidate` 的记录交给同一个
`apply_verified_publisher_abstract()` 审计写回函数。当前自动候选条件是：

- 文章原状态为 `missing`，且 `abstract` 字段确实为空；
- DOI 和标题与出版社页面的 `citation_doi` / `citation_title` 匹配；
- Springer/Palgrave 页面提供完整的 `dc.description` 或 `citation_abstract`；
- 保存页面 URL、解析器、核验时间和 `full_text_fetched=false`。

首轮 Springer 试跑 10/10 通过，随后按 100 篇批次继续；Palgrave 也通过了独立试跑。
截至目前，Springer Nature 补录 265 篇、Palgrave Macmillan 补录 104 篇，另有
ScienceDirect 1 篇；每篇均有 `publisher_page` 来源记录。各批报告保存在
`data/astar_*_probe_*_20260803.json`，包含候选、无摘要字段、标题不匹配和 404 的逐条结果。

另有少量记录虽标成 `missing` 但已有非空文本，已从自动队列排除，避免覆盖未知来源
文本；它们需要单独的数据质量核对。

目前缺摘要总量已由 33,359 降至 32,990；其中 32,663 篇有 DOI，327 篇没有 DOI。
剩余缺失主要集中在
Elsevier（约 2.5 万篇）；对 Elsevier、SAGE、Wiley、UChicago、AOM、APHA、Oxford、
INFORMS、Taylor & Francis 的抽样请求显示 403 或只有 DOI 跳转页，暂无安全的通用
自动摘要字段，因此不会把这些页面描述当成摘要，也不会绕过 Cloudflare、登录或 API
授权。后续会按出版社分别增加经过样本验证的适配器，不能验证的记录进入人工核验队列。

## 全量扫描后台任务

用户于 2026-08-03 明确要求对全部缺摘要记录执行扫描。正式任务已启动：

```powershell
python scripts\run_astar_full_abstract_scan.py \
  --run-dir data\astar_abstract_full_scan_20260803 \
  --delay 1.0 --timeout 20 --status-every 25 --fsync-every 25 \
  --apply --resume
```

冻结快照共 32,990 篇，路由如下：

| 路由 | 数量 | 处理方式 |
|---|---:|---|
| 出版社级访问受阻/无可信适配器 | 30,654 | 每篇写入终态及出版社级抽样证据，不重复制造相同 403 |
| Springer/Palgrave 实页探测 | 1,165 | 单线程、每请求间隔 1 秒，DOI/标题/强摘要字段校验后写回 |
| 其他出版社实页探测 | 415 | DOI 跳转页仅接受 `citation_abstract` / `dc.description` 等强字段，并核对 DOI/标题 |
| 状态为 missing 但已有非空文字 | 429 | 不覆盖，单列数据质量异常 |
| 无 DOI | 327 | 明确记录为不可通过 DOI 定位 |

任务目录：`data/astar_abstract_full_scan_20260803/`

- `manifest.json`：冻结范围、来源路由和网络策略；
- `targets.jsonl`：32,990 篇目标快照；
- `results.jsonl`：逐篇追加式终态，可安全续跑；
- `progress.json`：原子更新的当前进度与心跳；
- `scan.log`：批次日志；任务完成后生成 `summary.json`。

运行中发现通用 `citation_abstract` 可能带 HTML 标签，任务在首次候选后暂停并修复：
所有出版社元数据现在统一转换为纯文本并移除开头的 `Abstract` 标签。首篇候选
`10.3368/jhr.0725-14408r2` 已由 749 字符带标签内容修正为 724 字符纯文本，文章表和
来源记录均再次核对无 HTML；随后从检查点恢复，未重复处理已完成记录。

## ScienceDirect 漏判纠正（2026-08-03 23:18 MDT）

用户以 DOI `10.1016/j.dss.2026.114688`（PII `S0167923626000771`）指出
ScienceDirect 页面已有完整摘要，但系统仍显示缺失。复核确认用户判断正确。

### 根因证据

- 主库文章 ID `616` 在补录前为 `abstract_status=missing`、`data_status=title_only`。
- ScienceDirect 公开页面有完整摘要，DOI、标题、期刊、文章号和 PII 均匹配。
- Crossref、OpenAlex 和 Semantic Scholar 当前仍不返回摘要；Crossref 只给出匹配 PII
  的 Elsevier 文本挖掘链接。
- v1 全量结果第 655 行把该文标成 `publisher_route_unavailable`，同时明确记录
  `network_request_performed=false` 和 `evidence_scope=publisher_family_preflight`。
  这证明该文章并未逐篇探测；错误来自把“出版社机器访问受限”当成“文章没有摘要”。

### 单篇修复结果

- 文章 ID：`616`
- 摘要：1,142 字符、145 词；SHA-256
  `98eb4821250c4af5c127064e35a0ad150f9b2adc0e352e2e498089bd19639ceb`
- 状态：`available / publisher_metadata / abstract_review_status=resolved`
- 来源：`ScienceDirect / publisher_page / S0167923626000771`
- 页面：<https://www.sciencedirect.com/science/article/abs/pii/S0167923626000771>
- 仅保存公开摘要及来源元数据，没有抓取或保存全文。

### 路由与界面修正

1. `publisher-route-v2.1-2026-08-03` 不再产生文章级
   `publisher_route_unavailable`：受限出版社记录改为
   `publisher_page_review_pending`，并明确
   `article_level_abstract_availability=unknown`。
2. Elsevier 新增官方 Article Retrieval API 的 `view=META` 适配器：强制核对 DOI/标题，
   只接受 `dc:description` 摘要字段，来源单列为 `publisher_api`，不取全文。
   API key 仅从环境变量 `ELSEVIER_API_KEY` 或项目根目录下 gitignored
   `.secrets` 的同名项读取；环境变量优先，值不写日志或审计文件。
3. 2026-08-03 复查时，当前进程、Windows 用户/系统环境变量、项目
   `.secrets` 和标准本地配置位置均未找到 Elsevier API key；这只证明当前扫描
   进程无可用 key，不等于用户从未申请或从未在其他会话中临时配置。
   无 key 时记录保持待复核，不再错误终结；没有绕过
   Cloudflare、登录或 API 授权。Elsevier 官方文档给出的 Article Retrieval 默认配额为
   每周 50,000 次、最高 10 次/秒，足以在取得合规 key 后覆盖现有 Elsevier 队列。
4. 页面缺摘要卡片现在区分“元数据重试待定”和“出版社页面/授权接口待复核”；调试 API
   新增 `articles_without_abstract_checked_metadata_apis` 与
   `articles_without_abstract_publisher_review_pending`，旧字段仅保留兼容别名。
5. 收紧出版社名称匹配：v1 的 `informa` 子串曾把 “Association for Information Systems”
   中的 “information” 误命中 3 篇；v2.1 改为 `Informa UK` 并将这 3 篇转回普通元数据重试。

### 历史全量结果的非破坏性重分类

旧 `results.jsonl` 保留不改。另生成：

- `data/astar_abstract_full_scan_20260803/publisher_review_reclassification_v2_1.jsonl`
  （约 30 MB，30,654 条）；
- `data/astar_abstract_full_scan_20260803/publisher_review_reclassification_v2_1_summary.json`。

v2.1 结果：

| 修正状态 | 数量 |
|---|---:|
| 出版社页面/授权接口待复核 | 30,650 |
| 已通过本次公开页面核验解决 | 1 |
| 普通元数据重试（修复 Informa 子串误命中） | 3 |

先生成的 `publisher_review_reclassification_v2.*` 保留作为审计中间产物，已由 v2.1 明确
supersede，不应作为当前队列使用。重分类过程不联网、不改旧扫描结果、不改数据库摘要。

### Elsevier key 读取修正（2026-08-03）

- 根因：服务进程会读取项目 `.secrets`，但两个摘要扫描命令原先只读取当前进程环境变量；
  即使以后把 key 放入项目本地密钥文件，独立运行的扫描命令也会误报未配置。
- 修正：两个命令现在优先保留环境变量，并在缺失时仅加载 `.secrets` 中指定的
  `ELSEVIER_API_KEY`；不会加载其他密钥，也不会把 key 值写入输出或日志。
- 当前状态：现有 `.secrets` 中仍没有 Elsevier key，因此尚未启动 24,990 条 Elsevier
  缺摘要记录的授权 API 全量请求。
- 验证：相关 14 项单元测试全部通过；1 条 Elsevier 无 key 冒烟返回
  `authorization_required`，候选写入为 0，且没有发起 Elsevier 网络请求。

### Elsevier 授权冒烟（2026-08-04）

- 本地 `.secrets` 已检测到一条非空 `ELSEVIER_API_KEY`；检查和下述输出均未
  显示或记录 key 值。
- 授权冒烟目录：`data/astar_elsevier_authorized_smoke_20260804/`。选取文章
  ID `135199`、DOI `10.1016/j.tre.2026.105122`；Article Retrieval `view=META`
  返回 HTTP 403 / `Requestor configuration settings insufficient for access to this resource`，
  候选写入为 0，数据库未改动。
- 为排除新文尚未索引，对较 DOI `10.1016/j.euroecorev.2023.104478`：
  Scopus Abstract Retrieval `META` 基础元数据返回 HTTP 200 且 DOI/标题匹配，
  证明 key 有效；包含摘要的 `META_ABS` 返回 HTTP 401 /
  `not authorized to access the requested view or fields`，Article Retrieval 仍返回 HTTP 403。
- Windows 当前未检测到已连接的 VPN 配置或明确的学校 VPN 适配器。结论是
  API key 可用，但当前网络/IP 没有摘要或 ScienceDirect Article Retrieval 权限。
- 为避免将相同的授权错误放大到 24,990 条请求，未启动 Elsevier 授权全量扫描。
  下一步是连接机构校园网/VPN 后重跑单篇冒烟，或由 Elsevier/机构提供与
  API key 配对的 institutional token。
- 用户确认已连接校园网后，于 2026-08-04 重跑较早 DOI 对照；直接 Article
  Retrieval `view=META` 仍返回 HTTP 403 / `AUTHENTICATION_ERROR`，故当前证据更支持
  该 API key 没有开通 Article Retrieval 权限，而非单纯是校园网出口问题。对应报告：
  `data/astar_elsevier_campus_smoke_20260804/report.json`。

### Semantic Scholar 补摘要全量进度（2026-08-04）

- Elsevier 授权路径仍不可用后，先用已有的 Semantic Scholar 公开批量路径补进。
  本次以当时基线缺摘要 32,022 篇、Elsevier 24,990 篇开始；只接受返回的真实
  abstract，不根据标题生成摘要。
- 批处理期间曾观测到新增 162 篇摘要（其中 Elsevier 115 篇）；随后重启前发现旧 UI 后台线程还有 7 条未提交事务，重启时按 SQLite 事务规则回滚。最终稳定状态相对本轮基线净新增 155 篇，其中 Elsevier 112 篇；当前缺摘要总数 31,867，
  Elsevier 缺摘要 24,878。抽查新写入的 Elsevier 摘要长度为 746–2,016 字符，
  来源记录为 Semantic Scholar。
- 对所有有 DOI 但仍缺摘要的记录完成了本轮查验：缺摘要但未查验队列为 0；剩下 327 篇是无 DOI 记录。
- 批处理增加了可配置的批量大小、`429` 后可重试的断点，以及 `No valid paper ids given`
  的负结果审计。本轮日志中记录了批量大小、空结果数和失败批次数，不会把 429 误记为“无摘要”。
- 本次修改后全套测试：439 项通过。
- 同时修正页面的“补全摘要/引用 (S2)”按钮：之后从 UI 触发时也会使用
  500 条/批、只重试未查验队列的断点模式，不会回到旧的 100 条/批全量重请。

### 本地网络继续补全（2026-08-04 10:00 MDT）

- 新增文章使缺摘要数从 31,867 变为 31,889；本次新出的 23 个 DOI 已完成
  Semantic Scholar 查询，没有新摘要，但补了 6 条引用数和 3 条学科字段。
- 本地电脑网络下重试 Elsevier Article Retrieval 仍返回 HTTP 403；本次未发起全量无效请求，数据库未被误写。
- 5001 服务现在返回缺摘要 31,889；Semantic Scholar 未查验队列为 0。剩余缺摘要需要新的公开摘要来源或 Elsevier Article Retrieval 授权，不是扫描尚未运行。

### 服务验证

- 看门狗在确认更新锁为空、无运行中翻译/转录任务后，将旧服务 PID `112192` 替换为
  PID `116388`；`/api/health` 返回 HTTP 200。
- `/api/abdc/astar/articles/616` 返回
  `available / publisher_metadata / 1,142 字符 / resolved`，并带匹配的 ScienceDirect
  来源记录。
- `/api/abdc/astar/debug` 当前返回缺摘要 32,022，出版社页/授权接口动态待复核 31,042。
  该动态数包含 v1 快照之后新增或状态变化的记录，因此可能大于 v2.1 历史队列数。
- 全套回归测试：`python.exe -m unittest discover -s tests -v`，**433 tests passed**。
- v2.1 Elsevier 无密钥烟雾扫描：2/2 为
  `publisher_page_review_pending / availability=unknown / network_request_performed=false`，
  结果在 `data/astar_abstract_full_scan_v2_smoke_elsevier_20260803/`。
