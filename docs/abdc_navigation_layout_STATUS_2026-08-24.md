# ABDC 导航布局修复状态 · 2026-08-24

## 本次修复

- 修复 `/abdc` 期刊列表页的旧版全局 `header` CSS 污染共享研究导航的问题。
- 旧页头现在使用 `.abdc-page-header` 作用域；共享导航继续由 `research-nav.css` / `research-nav.js` 统一渲染。
- 未修改 ABDC 数据、API、SQLite、筛选逻辑或其他页面导航。

## 根因证据

- `/abdc` 的动态 `.research-nav-shell` 是一个 `<header>`。
- 旧页面的 `header { display:flex; padding:18px 24px; gap:16px; }` 让共享导航的主导航和二级导航变成同一行。
- 修复前真实浏览器测得共享 shell 为 `display:flex; flex-direction:row`，二级导航从视口外延伸到 `scrollWidth=2222`（视口宽 `1251`）。

## 验证

- `python3 -m unittest tests.test_research_navigation`
- `git diff --check`
- Playwright：`/abdc` 桌面与 375px；对照 `/abdc/research`；检查导航激活态、二级导航、页面数据加载、控制台和横向溢出。

## 仍需注意

- 全站临时服务器启动的完整 `init_db()` 受到另一个 Faculty Jobs SQLite 进程持锁影响；本次浏览器验收使用现有 `Handler` 的只读静态/API 路由，未终止该进程，也未触碰数据库。
