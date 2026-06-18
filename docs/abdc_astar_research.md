# ABDC A* 研究动态（A* Research Radar）

> 模块创建：2026-06-17 · 项目目录 `D:\claude`

## 1. 模块目标

把现有 ABDC 期刊查询里**当前版本评级为 A\* 的期刊**当作"顶刊雷达"，持续追踪这些期刊
最近发表的文章，并自动做主题 / 理论 / 方法 / 数据类型分类，按个人研究方向打相关性分。

它不是期刊查询工具，而是**文章级别的研究动态追踪**：帮助你每天/每周看到顶级期刊最近
在研究什么、用了什么理论和方法、用了什么数据，以及哪些和你的 OB/IS/AI/WFH/RTO 研究相关。

第一阶段只做四件事：
1. A\* 期刊筛选（从最新 ABDC 版本）
2. 最近文章抓取（默认 90 天起步，之后增量）
3. 文章规则分类 + 相关性评分
4. Weekly digest

后续可加：citation network、trend map、LLM 摘要、Semantic Scholar 补全、Unpaywall OA。

## 2. 数据来源

| 来源 | 用途 | 阶段 |
|---|---|---|
| **OpenAlex** | 按 ISSN 查 works，拿 title/authors/date/DOI/abstract(倒排索引重建)/concepts/被引/OA | 主，已接入 |
| **Crossref** | OpenAlex 无结果时按 ISSN 兜底，拿 DOI/title/date/作者/出版商/abstract(JATS) | 兜底，已接入 |
| Semantic Scholar | 用 DOI/title 补 abstract、fieldsOfStudy、引用数 | 可选，未接入 |
| Publisher RSS | 出版社最新文章页补充 | 可选，未接入 |
| Unpaywall | 用 DOI 查 OA 状态和开放版本 | 可选，未接入 |

**数据纪律**：只用公开 scholarly metadata API，不抓全文、不绕付费墙、不用 Sci-Hub/盗版。
没有摘要就标 `abstract_status=missing`，绝不伪造；元数据不足不强行分类；不用 mock 填页面。

## 3. 更新逻辑

- **首次**：读取 A\* 期刊列表 → 对每个有 ISSN 的期刊抓最近 90 天 → 无 ISSN 的列入 missing 报告。
- **每日增量**：抓最近 14 天，按 DOI/title 去重。
- **每周**：抓最近 30 天，生成 weekly digest。
- **历史回填**：支持按单期刊、按今年逐步回填，不一次性暴力请求全历史（避免限流）。

每次抓取在期刊之间有 0.15s 间隔（OpenAlex/Crossref polite pool，带 mailto）。

## 4. API

### 读取
| API | 说明 |
|---|---|
| `GET /api/abdc/astar/journals` | A\* 期刊列表 + ISSN 覆盖统计 |
| `GET /api/abdc/astar/articles` | 文章列表，支持 `q/from_date/to_date/journal/broad_area/topic/method/data_type/theory/related_only/min_relevance/limit/offset/sort` |
| `GET /api/abdc/astar/articles/{id}` | 单篇详情（元数据+摘要+来源+分类+相关文章+DOI/OpenAlex URL） |
| `GET /api/abdc/astar/recent?days=7&related_only=` | 最近新增 |
| `GET /api/abdc/astar/digest?period=this_week&related_only=` | 分块 digest |
| `GET /api/abdc/astar/saved` | 阅读列表 |
| `GET /api/abdc/astar/trends?months=18&related_only=` | 主题/方法/领域按月趋势 |
| `GET /api/abdc/astar/lists` | FT50 / UTD24 清单 + 覆盖缺口报告 |
| `GET /api/abdc/astar/debug` | 覆盖率/来源/失败期刊/分类分布/更新日志 |

文章列表 `GET /api/abdc/astar/articles` 支持 `list=ft50` / `list=utd24` 过滤；每篇文章返回
`is_ft50` / `is_utd24` 标记（运行时按 ISSN 关联 `journal_prestige_lists` 表得到，零大表写入）。

**FT50 / UTD24 清单**（`services/journal_lists.py`）：FT50 取 2026 版（移除 Human Relations /
J Business Ethics / Organization Studies，新增 AoM Annals / American Sociological Review /
Psychological Science）；UTD24 为 UT Dallas 24 刊。ISSN 通过匹配 ABDC 主表解析（51 刊全部匹配）。
其中 **47 刊是 ABDC A\* 已被雷达追踪**；4 刊为 ABDC A（HBR、MIT Sloan Mgmt Review、
Strategic Entrepreneurship Journal、INFORMS Journal on Computing）当前不在 A\* 抓取集中，
点 FT50/UTD24 筛选时不会出现它们的文章（缺口在 `/api/abdc/astar/lists` 的 `not_tracked` 中列出）。

### 更新
| API | body |
|---|---|
| `POST /api/abdc/astar/update` | `{"mode":"recent","days":30,"abdc_version":"latest"}`；mode 可取 recent / daily_incremental / weekly_incremental / backfill_90_days / backfill_current_year / backfill_one_journal |
| `POST /api/abdc/astar/classify` | 重新分类全部文章（后台线程） |
| `POST /api/abdc/astar/save` | `{"article_id":123,"user_note":"...","reading_status":"to_read"}` |
| `POST /api/abdc/astar/enrich` | Semantic Scholar 补全缺摘要文章（补 abstract/引用/fieldsOfStudy）；`{"limit":500}` 可选 |

**Semantic Scholar 现实**：顶级管理学期刊（AOM、ASQ、AER、APSR 等）几乎不向任何公开 API 提供
摘要，S2 摘要回填率仅约 5%；但它仍能补**引用数**和 **fieldsOfStudy**（作为分类信号）。
未授权调用有 429 速率限制，失败的批次下次 enrich 会自动重试（只针对仍缺摘要的文章）。
CLI：`python scripts\update_abdc_astar.py --enrich-abstracts`。

## 5. 数据库表（启动时自动创建）

- `abdc_astar_journals` — 从 ABDC 列表生成的 A\* 期刊（仅 A\*；保留 print + online ISSN）。
- `astar_articles` — 文章主表（DOI 唯一；`data_status`、`abstract_status` 标记口径）。
- `astar_article_sources` — 每篇文章的来源记录（source_url / raw_id，便于 debug）。
- `astar_article_classifications` — 规则分类 + 相关性评分（每篇一条）。
- `astar_update_logs` — 每次更新的统计与失败记录。
- `astar_saved_articles` — 个人阅读列表。

## 6. 如何手动更新

页面（`/abdc-astar-research`）按钮：更新最近30天 / 更新本周 / 回填90天 / 回填今年 / 重新分类 / 导出CSV / Debug。

命令行：
```powershell
cd D:\claude
python scripts\update_abdc_astar.py --mode backfill_90_days
python scripts\update_abdc_astar.py --mode recent --days 30
python scripts\update_abdc_astar.py --mode backfill_one_journal --journal "Academy of Management Journal"
python scripts\update_abdc_astar.py --classify-only
python scripts\update_abdc_astar.py --debug
```

API：
```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:5001/api/abdc/astar/update -Body '{"mode":"backfill_90_days"}' -ContentType 'application/json'
Invoke-RestMethod http://127.0.0.1:5001/api/abdc/astar/debug
```

## 7. Windows Task Scheduler

创建基本任务 → 触发器：每天 → 操作：启动程序：
- 程序：`python`
- 参数：`scripts\update_abdc_astar.py --mode daily_incremental --days 14`
- 起始于：`D:\claude`

或直接：
```
cd D:\claude
python scripts\update_abdc_astar.py --mode daily_incremental --days 14
```

## 8. 哪些数据不是全量

- 不是 A\* 期刊全历史文章库；第一阶段是 recent + incremental。
- 摘要取决于 OpenAlex/Crossref 是否提供公开 abstract；部分期刊（尤其较早文章）可能无摘要。
- 未接入 Semantic Scholar / Unpaywall / 出版社 RSS。
- 仅追踪**最新 ABDC 版本**的 A\*；切换版本会重建该版本的期刊集合。

## 9. 如何解释 relevance_score

- 0–100，命中越多个人研究方向的主题/方法/数据 → 分越高。
- `is_related_to_my_research = (relevance_score >= 60)`。
- 加权方向：WFH/RTO、AI in orgs、algorithmic management、burnout/EVLN、surveillance/autonomy、
  work-family、platform/gig/logistics、labor market；方法 NLP/text mining/ML；
  数据 Glassdoor/Indeed/job postings/O*NET/BLS/online reviews；领域 OB-HR / IS 交叉加分。
- 多个核心主题共现额外 +15。
- **无摘要时相关分封顶 55**，避免仅凭标题给高分；`classification_notes` 说明加分依据。

## 10. 排查 missing abstract / missing ISSN

- **missing ISSN**：当前最新 ABDC 2025 版 219 个 A\* 期刊全部有 ISSN（覆盖率 100%），无 missing。
  若切换到旧版本出现 missing，会在 `astar_update_logs.warnings` 和 Debug 页「missing_issn」中列出。
- **missing abstract**：`/api/abdc/astar/debug` 的 `articles_without_abstract` 给总数；
  文章卡片会显式标注「无公开摘要」。可后续接 Semantic Scholar/Crossref 补全。
- **失败期刊**：Debug 页 `failed_journals_last_run` 列出期刊名 + 错误（如 API 限流、网络）。
- **分类不确定**：`classification_status` 分布在 Debug 页；`insufficient_metadata` = 标题太短且无摘要无 concepts。
