# 研究工具集 1 + 5 迁移状态（2026-08-11）

## 结论

当前工作区采用一个可运行的 monorepo 加五个项目域。此次迁移不移动原有源码、数据库或输出路径，避免破坏 server.py、共享导航、SQLite 和现有看门狗；新增机器可读边界、发布前审计、私有数据一致快照和恢复说明。

五个项目域与当前页面导航一致：

1. 中国宏观、财政、城市与住房；
2. 美国宏观；
3. ABDC 商科研究；
4. 科研语言与语音工具；
5. 个人归档与按需监控。

## 迁移前只读盘点

- 工作区约 9.2 GiB；
- data/ 约 6.3 GiB，tmp/ 约 1.5 GiB，backups/ 约 565 MiB；
- 主数据库约 730 MiB，城投债数据库约 541 MiB，A* 嵌入约 192 MiB；
- 当前 GitHub 远端在 2026-08-11 核对为公开仓库；
- 迁移开始时有 107 个已跟踪文件发生变化、约 1,307 个未跟踪文件和约 3,512 个忽略文件；
- 本机 /api/health 与 /api/jobs 在盘点时不可连接，因此未依赖正在运行的服务状态创建快照。

这些数字是迁移时点快照，不是长期常量。

## 新增边界与工具

- projects/registry.json：五个项目域、页面、源码 glob、公开小型输入和私有数据 glob 的唯一机器可读清单；
- projects/*/README.md：各项目域的责任、数据纪律和最小测试；
- scripts/audit_one_plus_five.py：检查项目数、路由、私有文件是否误跟踪、大型公开文件和高置信敏感信息模式；
- scripts/create_private_migration_snapshot.py：仓库外的可恢复私有快照；在线备份 SQLite，普通文件支持 .part 续传并记录 SHA-256；
- .gitattributes：固定文本换行策略，避免 WSL/Windows 把纯换行变化误报为业务修改；
- .secrets.example：只保存变量名和安全占位符。

## Git 与私有层

Git 保存源码、页面、测试、文档、依赖和小型可复现输入。以下内容不进入公开远端：

- .secrets、token、密码和 SSH 密钥；
- *.db、WAL/SHM、原始数据、备份和日志；
- 悦读FM 音频/封面、论文/访谈原件、译文和转录；
- A* 出版社摘要文本、授权探测报告、全量扫描和嵌入；
- tmp/ 和浏览器/代理运行状态。

## 可复现命令

    python scripts/audit_one_plus_five.py \
      --output docs/migration/one_plus_five_inventory_20260811.json

    python scripts/create_private_migration_snapshot.py \
      --destination <external-private-backup-root>

    python.exe -m unittest discover -s tests -q

## 验证状态

- 公开边界审计：pass，5 个项目域，0 errors，0 warnings；
- Windows Python 全套测试：524 tests passed；
- 迁移工具定向测试（含非空 WAL 恢复）：6 tests passed；
- 运行服务：Windows PID 72852；/api/health 和五个项目域的 17 个页面全部 HTTP 200；
- 私有快照：仓库外的 Windows Documents/research-tools-private-backups/research-tools-private-20260811；
- 私有快照 manifest：2,007 个条目，约 7.6 GiB，默认排除 tmp/；
- 补充私有快照：research-tools-private-supplement-20260811，355 个条目、15.9 MiB；保存本机工具设置、Playwright/导航 QA 证据、运行日志、分类中间文件和旧 HTML 备份；
- 快照复核：1,999 个实际快照文件均存在且大小匹配，6 个 SQLite 快照 quick_check=ok；
- 两个 manifest 合计覆盖 2,362 个私有路径、2,354 个实际文件，0 缺失、0 大小不符；
- 与 Git ignored 文件做差后，除 tmp/、Python 缓存、NUL 和三个明确的临时重复文件外，未留下无法解释的未备份路径；
- Windows ACL：两个快照根目录均仅当前用户、SYSTEM 和 Administrators 具有权限。

Git commit、远端分支和草稿 PR 在发布完成后记录于 PR。
