# ABDC A* 研究动态（Research Radar）— 完整进度

> 更新：2026-06-18 · 项目 `D:\claude` · 页面 `/abdc-astar-research` · 端口 5001
> 配套参考文档：[abdc_astar_research.md](abdc_astar_research.md)（API/表/运维细节）

## 1. 这个模块是什么

把现有 ABDC 期刊查询里**当前版本评级为 A\* 的期刊**当作"顶刊雷达"，用 ISSN 经
OpenAlex / Crossref 持续追踪它们最近发表的文章，做主题/理论/方法/数据类型规则分类，
并按个人研究方向（WFH/RTO、AI in orgs、algorithmic management、digital trace/NLP、
burnout/EVLN、JD-R、OB-IS 交叉等）打相关性分。文章级动态追踪，不是期刊查询。

**数据纪律**：只用公开 scholarly metadata API，不抓全文、不绕付费墙、不造 mock；
无摘要标 `abstract_status=missing` 绝不伪造；元数据不足不强行分类。

## 2. 当前数据快照（2026-06-18 实测）

| 指标 | 数值 |
|---|---:|
| 库内文章（去重、去污后） | **126,030** |
| 覆盖期 | **2020-01 → 2026-06** |
| 有摘要 | 81,402（65%） |
| 缺摘要（诚实标记 missing） | 45,749 |
| 有 DOI | 125,657 |
| 有引用数 | 126,030（全量，来自 OpenAlex/S2） |
| **与我研究相关（≥60 分）** | **617** |
| 近 7 天 / 近 30 天新增 | 251 / 1,444 |
| 分类 confident / uncertain | 65,846 / 64,972 |
| 已隐藏的污染文章（JAIS 会议论文） | 4,887 |

**按年份**：2020→19,602｜2021→19,713｜2022→19,171｜2023→18,717｜2024→19,646｜2025→20,209｜2026→8,972（半年）

**期刊覆盖**：追踪 **223 刊**（219 个 ABDC A\* + 4 个 FT50/UTD24 非 A\* 补充），其中 **220 刊有文章**。

## 3. 顶刊清单（FT50 / UTD24）

- **FT50**：Financial Times Research Rank，**2026 版**（移除 Human Relations / J Business Ethics /
  Organization Studies，新增 AoM Annals / American Sociological Review / Psychological Science），50 刊。
- **UTD24**：UT Dallas 24 刊。
- 两者并集 51 刊，ISSN 全部匹配 ABDC 主表。47 刊本身是 A\*；4 刊是 ABDC A（HBR、MIT Sloan
  Mgmt Review、Strategic Entrepreneurship Journal、INFORMS Journal on Computing）已作为
  `prestige_extra` 持久纳入抓取。
- 文章筛选支持 `★ FT50`（26k+ 篇）/ `★ UTD24`（16k+ 篇）chip，卡片显示清单徽章。

## 4. 已完成功能

### 第一阶段（核心四件事）
- ✅ 从最新 ABDC 版本筛 219 个 A\* 期刊（ISSN 覆盖 100%）
- ✅ 文章抓取：OpenAlex 主 + Crossref 兜底，摘要从倒排索引重建
- ✅ 规则分类：broad_area / research_topic / method / data_type / theory + 相关性评分（0-100，≥60 视为相关）
- ✅ Weekly digest（按主题分块，标注 evidence_basis=title only / title+abstract）

### 第二阶段（增强）
- ✅ Semantic Scholar 补全：补摘要（顶刊回填率仅 ~5%，受出版社限制）+ 引用数 + fieldsOfStudy
- ✅ 趋势地图：主题/方法/领域按月迷你柱状图
- ✅ 深度回填：OpenAlex 游标分页 + 多年回填（`backfill_since` / `backfill_one_year`），数据扩到 2020
- ✅ 后台持续抓取：服务器内调度器每 6h 抓最近 14 天增量（`ASTAR_AUTO=0` 可关）

### 第三阶段（清单 + 质量）
- ✅ FT50 / UTD24 清单标签 + 筛选 + 覆盖缺口报告（`/api/abdc/astar/lists`）
- ✅ 把 4 个非 A\* 的 FT50/UTD24 刊纳入追踪（`prestige_extra`，持久、增量也带上）
- ✅ 期刊覆盖页：每刊精确文章数（按 ISSN 统计），点击刊名**下钻**到该刊全部文章

## 5. 页面与 Tab

页面 `/abdc-astar-research`（暗色风格，原生 JS）：
- 顶部 KPI + 操作按钮（更新最近30天/本周/回填90天/回填今年/补全摘要S2/重新分类/导出CSV/Debug）
- Tab：最新文章 · 与我相关 · 本周 Digest · 主题地图 · 趋势 · **期刊覆盖（可下钻）** · 已保存 · Debug
- 筛选 chip：All A\* / 与我相关 / ★FT50 / ★UTD24 / AI / WFH-RTO / NLP / OB-HR / IS / OM / Marketing / Job postings

## 6. 排查并修复的问题（本轮重点）

| 问题 | 根因 | 处理 |
|---|---|---|
| 多次出现服务多实例 | Windows 下 HTTPServer 允许多进程绑同端口 | 端口守卫，已在跑则退出 |
| dashboard 白屏 | unpkg CDN 国内加载失败 | React/Babel 本地化到 `static/vendor/`（Babel **7.x**，非 8） |
| 期刊覆盖满屏 0 | 只读 debug 前 40 名 + 按刊名匹配（大小写不符） | 改为**按 ISSN 全量统计** |
| 下钻点不动 | 行内 onclick 用 JSON.stringify 双引号与属性引号冲突 | 改 `openJournalIdx(i)` 索引调用 |
| 高产刊旧文章缺失 | 1500/窗口上限截断（EJOR 漏 ~988 等） | 定向重抓 cap=8000；默认上限调高 |
| JAIS 文章虚高（5273） | OpenAlex 把 AIS 会议论文错并入 JAIS 的 ISSN | DOI 过滤只认 `10.17705/1jais`，砍回 387；一次性清理+抓取拦截+启动自检 |

## 7. 数据库表

`abdc_astar_journals`（追踪期刊，含 prestige_extra）· `astar_articles`（文章主表）·
`astar_article_sources`（来源记录）· `astar_article_classifications`（分类+相关性）·
`astar_update_logs`（运行日志）· `astar_saved_articles`（阅读列表）·
`journal_prestige_lists`（FT50/UTD24 清单，运行时按 ISSN 关联）。全部启动时自动创建。

## 8. 已知限制 / 未做

- 摘要回填受出版社限制：AOM/ASQ/AER/APSR 等顶刊几乎不向公开 API 提供摘要，仍有 45,749 篇缺摘要。
- 3 个 A\* 刊真实 0 文章：Advances in Experimental Social Psychology（书系）、Australian Tax Forum
  （OpenAlex 未收录）、Environment and Planning B（ABDC 刊号过期）。
- 分类是**规则法**，非 LLM/embedding；method/data 标签靠关键词，可能漏判（标 uncertain）。
- 未接入：Unpaywall（OA 链接）、出版社 RSS、引用网络、LLM 摘要、embedding 分类。
- Semantic Scholar 未授权调用有 429 限流，缺摘要的会分多轮慢慢补。

## 9. 新增 / 改动文件

- `services/abdc_astar_research_service.py` — 核心服务（抓取/分类/评分/清单/payload/清理）
- `services/journal_lists.py` — FT50 / UTD24 清单数据
- `static/abdc_astar_research.html` — 页面（暗色，8 个 tab）
- `scripts/update_abdc_astar.py` — 命令行更新
- `scripts/run_astar_phase3.py` — 一次性编排（S2→回填→S2）
- `docs/abdc_astar_research.md`、`docs/abdc_astar_research_PROGRESS.md`（本文）
- 改动：`server.py`（import/路由/建表/调度器/清单与清理初始化）、`static/index.html`（首页卡片）

## 10. 如何运行 / 持续更新

```powershell
cd D:\claude
python server.py                 # 启动（自动建表、载清单、清理污染、开 6h 调度器）
# 浏览器打开 http://localhost:5001/abdc-astar-research

# 手动更新（CLI）
python scripts\update_abdc_astar.py --mode recent --days 30
python scripts\update_abdc_astar.py --mode backfill_since --since-year 2018   # 继续往前挖
python scripts\update_abdc_astar.py --enrich-abstracts                        # 补摘要/引用
python scripts\update_abdc_astar.py --debug
```

Windows 计划任务（每日增量）：`python scripts\update_abdc_astar.py --mode daily_incremental --days 14`

## 11. 下一步候选

1. 给剩余 45,749 篇缺摘要的再轮 S2 补全（受限流，分多轮）
2. 继续往前回填（2018/2015）扩历史
3. 接 Unpaywall 拿 OA 开放版本链接
4. 期刊覆盖加学科/清单筛选
5. 引用网络 / trend map 进阶 / LLM 摘要
