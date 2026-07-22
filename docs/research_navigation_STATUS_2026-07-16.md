# 全站研究导航状态 · 2026-07-16

## 本次改动

- 将首页从七个并列工具卡片重组为“中国宏观 / 美国宏观 / ABDC 商科研究”三个一级研究域。
- 新增共享顶部标签导航，一级标签直接切换各研究域默认页面；当前研究域在第二行显示全部子页面，接入全部 8 个主要页面。
- 新增全站页面搜索，可按页面名称、研究域和学科频道定位。
- ABDC 研究域新增 Information Systems、Management、Marketing、OB / HR、计算社会科学入口。
- 学科入口通过 `/abdc-astar-research?field=...` 复用现有 A* 文章列表；Management 映射到 `Management / Strategy`，计算社会科学映射到现有 NLP 方法筛选。
- 调整 A* 页面和财政债务页的 sticky 偏移，避免与全站导航遮挡。

## 文件

- 共享导航：`static/research-nav.css`、`static/research-nav.js`
- 首页：`static/index.html`
- A* 学科筛选：`static/abdc_astar_research.html`
- 静态契约测试：`tests/test_research_navigation.py`
- 本地视觉 QA：`design-qa.md`；截图存于 gitignored 的 `outputs/research-navigation-qa/`

## 验证方法

```powershell
python -m unittest tests.test_research_navigation
python -m unittest discover -s tests
```

浏览器核验范围：桌面首页、三个顶部标签的页面切换、当前域二级导航、全站搜索、A* 学科落地筛选、窄屏导航换行，以及控制台错误。

## 未改变

- 未更改任何数据库、抓取逻辑或历史数据。
- 未增加新的后端页面路由；所有现有 URL 保持兼容。
- Debug 页面仍通过各模块内部入口访问，不列为一级研究工具。
