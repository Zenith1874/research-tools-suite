# 研究工具集 · Research Tools Suite

本地运行的个人研究工具集合，用一个 Python 标准库 `HTTPServer`（端口 5001）+ 模块化
`services/` + 暗色风格静态页面托管多个工具，数据存于本地 SQLite。无需 npm 构建。

## 模块

| 页面 | 说明 |
|---|---|
| `/dashboard` | 中国人民银行金融统计监控（M2/M1/贷款/存款/社融/利率，observation 层 + 来源追踪） |
| `/fiscal-debt` | 政府债务监控（国债、地方债、央行资产负债表、国债买卖、买断式逆回购、国债发行明细） |
| `/abdc` | ABDC 期刊质量列表查询（2010–2025 六个版本，按名称/ISSN/FoR 搜索） |
| `/abdc-astar-research` | **A\* 研究动态（Research Radar）**：追踪 ABDC A\* 期刊最新文章，规则分类 + 个人研究相关性评分 + FT50/UTD24 标签。详见 [docs/abdc_astar_research_PROGRESS.md](docs/abdc_astar_research_PROGRESS.md) |

## 运行

```bash
cd <repo>
pip install requests        # 仅 A* 雷达需要；其余模块用标准库
python server.py            # 启动后打开 http://localhost:5001
```

启动时自动建表、载入清单、开启后台增量调度器。

### 环境变量
- `ASTAR_MAILTO` — OpenAlex / Crossref polite-pool 联系邮箱（建议设为你的真实邮箱；默认占位）。
- `ASTAR_AUTO=0` — 关闭 A\* 雷达每天一次的后台增量抓取。

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
