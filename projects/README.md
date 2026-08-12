# 1 + 5 单仓库结构

本目录定义项目管理边界，不复制或搬动运行代码。根目录仍是唯一可运行、可测试、可发布的 Git 仓库；五个项目域继续共用 server.py、导航、依赖、数据库连接、安全护栏和测试基础设施。

| 项目域 | ID | 主要页面 | 说明 |
|---|---|---|---|
| 中国宏观、财政、城市与住房 | china_macro | /dashboard、/china-macro、/fiscal-debt、/city-economy、/housing-scenario 等 | 中国金融、实体经济、财政债务、城市与住房的一体化观察和情景工具 |
| 美国宏观 | us_macro | /us-macro | 美国就业、通胀、增长、财政债务和金融条件；与 GDP、统计分析共享部分组件 |
| ABDC 商科研究 | abdc_research | /abdc、/abdc-astar-research | 期刊列表、A* Research Radar、分类、语义检索和来源审计 |
| 科研语言与语音工具 | research_tools | /paper-translation、/audio-transcription | 私有文档翻译、总结、原文问答、访谈转录和匿名说话人区分 |
| 个人归档与按需监控 | personal_tools | /yuedu-fm、/cardcookie-monitor | 本地媒体归档、离线播放和默认关闭的低频变化提醒 |

机器可读的唯一边界清单是 registry.json。每个子目录的 README 说明该域的页面、源文件、数据策略和最小验证集合。

## 为什么仍然只有一个 Git 仓库

- 一次跨模块修改可以用一个提交和一个 PR 原子化审阅。
- 根服务器、权限判断、导航和数据库迁移不会在五个仓库间漂移。
- Git 只传输新增提交；修改一个项目域时不需要重新上传其他四个域或私有数据。
- 将来只有在某个域拥有独立运行入口、依赖、数据库迁移和部署周期后，才考虑保留历史地拆仓。

## Git 与私有数据边界

公开 Git 仓库只保存源码、测试、文档、依赖声明和小型可复现输入。以下内容始终留在私有层：

- SQLite 数据库及 WAL/SHM；
- 论文、访谈音频、翻译与转录任务；
- 悦读FM 音频、图片和本地目录；
- A* 出版社摘要文本、授权探测和全量扫描结果；
- 嵌入、备份、日志、临时文件和 .secrets。

发布前运行：

    python scripts/audit_one_plus_five.py

私有数据先查看计划，再复制到仓库外的目的地：

    python scripts/create_private_migration_snapshot.py \
      --destination <external-private-backup-root>

    python scripts/create_private_migration_snapshot.py \
      --destination <external-private-backup-root> \
      --snapshot-name research-tools-private-YYYYMMDD \
      --execute

快照使用 SQLite online backup 生成一致数据库副本；普通文件通过 .part 断点文件复制，并在私有 manifest 中记录 SHA-256。默认不包括 tmp/；只有明确需要保存临时取证或中间产物时才增加 --include-temporary。

## 以后如何提交

每次任务建立短期分支，仅暂存本次实际修改：

    git switch -c codex/<topic>
    git add <explicit paths>
    python.exe -m unittest discover -s tests -q
    git commit -m "<concise change description>"
    git push -u origin codex/<topic>

不要使用未经检查的 git add .。数据变化走私有快照；代码、schema、迁移脚本、来源说明和小型公开输入走 Git。
