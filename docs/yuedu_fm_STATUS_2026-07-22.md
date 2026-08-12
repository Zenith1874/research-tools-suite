# 悦读FM 本地归档与播放：实现状态

核对日期：2026-07-22（America/Denver）<br>
本地项目：`/mnt/d/claude`（Windows：`D:\claude`）<br>
公开订阅源：`https://feeds.redcircle.com/9e7cc2c9-54c2-431d-9be3-3305ce235d00`

## 目标与边界

新增独立“娱乐 → 悦读FM”功能，把公开 RSS 中的标题、发布时间、作者、节目文字、逐集封面和 MP3 保存到本机，
通过 `/yuedu-fm` 搜索和播放。资料只用于个人本地收听，不重新发布，不写入 `pboc_data.db`，也不进入 Git。
远程设备默认不能读取本地媒体；只有显式设置 `YUEDU_FM_ALLOW_REMOTE=1` 并通过平台写权限检查后才可访问。

## 实现

- `services/yuedu_fm_service.py`：RSS 解析、HTML 转纯文本、稳定单集 ID、原始 feed 快照、逐集 JSON、
  封面/音频下载、SHA-256、HTTP Range 断点续传、响应长度与媒体签名检查；
- `scripts/sync_yuedu_fm.py`：完整同步、`--metadata-only` 和 `--limit N` smoke；
- `scripts/verify_yuedu_fm.py`：逐文件目录、实际大小与 SHA-256 完整性复核；
- `static/yuedu_fm.html`：本地资料统计、同步进度、全文搜索、下载状态筛选、排序、展开节目文字和固定播放器；
- `server.py`：私有 library/status/sync API、封面与音频路由，以及浏览器 seek 所需的单 Range 响应；
- `data/yuedu_fm/`：gitignored 本机目录，含 `raw/`、`manifests/`、`metadata/`、`images/`、`audio/`。

每次 RSS 原文和完成态 manifest 使用带微秒的 UTC 时间戳另存，旧快照不覆盖。下载先写 `.part`，只有最终 HTTP 长度
校验完成后才进入正式媒体路径；若已有异常目标，先改名保留为 `.invalid-<timestamp>`。

## 真实源侦察与全量同步

2026-07-22/23 读取到：

- 472 集，标题、description/content、GUID、发布时间、MP3 enclosure 和逐集图片字段均存在；
- RSS 声明音频合计 `4,620,873,329` bytes（约 4.30 GiB）；
- 日期字段范围为 2024-08-13 至 2025-07-06，但这可能是平台迁移/重发日期，不应解释为作品原始发布日期；
- `--limit 2` 先保存完整 472 集目录与逐集 JSON，并下载前 2 集封面和音频作 smoke；
- 随后完整同步于 2026-07-23 02:34:18–02:49:09 UTC 完成，472/472 音频、472/472 封面、472/472 逐集 JSON 均在本机，
  0 下载错误、0 遗留 `.part`。

真实下载表明 RSS 的 `enclosure length` 不能作为唯一真值：第一集声明 12,545,462、HTTP 实际 12,545,070 bytes；
第二集声明 7,511,144、HTTP 实际 11,258,112 bytes。实现因此同时保存 `declared_bytes` 与 `actual_bytes`，完整性以最终
HTTP `Content-Length`/`Content-Range` 为准，不截断或填充文件。第一集服务器返回的完整对象没有常见 MP3/ID3 文件签名，
已按原字节保存并记录 `signature_valid=false` 警告；第二集为正常 ID3/MP3。该警告是源文件状态，不被伪装成成功可播放。

全量实际结果：

- 音频：`5,123,074,043` bytes（约 4.77 GiB）；
- 封面：`503,297,634` bytes（约 0.47 GiB）；
- 媒体合计：`5,626,371,677` bytes（约 5.24 GiB；文件系统 `du` 约 5.3G）；
- 296 个音频具有常见 ID3/MP3 起始签名；176 个服务器对象长度完整但签名异常，可能无法由浏览器播放；
- 428/472 个音频的实际 HTTP 字节数与 RSS 声明值不同，因此界面和审计以两字段并列保留；
- 472 个音频和 472 张封面均保存 SHA-256。

## 验证

```bash
python.exe -m py_compile services/yuedu_fm_service.py scripts/sync_yuedu_fm.py server.py
python.exe -m unittest tests.test_yuedu_fm tests.test_research_navigation tests.test_server_access_security -v
python.exe scripts/sync_yuedu_fm.py --limit 2
python.exe scripts/sync_yuedu_fm.py
python.exe scripts/verify_yuedu_fm.py
```

聚焦测试共 31 项通过。全量 `verify_yuedu_fm.py` 重新计算 944 个媒体 SHA-256，结果 `ok=true`、0 failure。
临时端口 HTTP smoke 验证 `/yuedu-fm` 为 200、library 报告 472/472、标准音频 `Range: bytes=0-31` 返回
`206 Partial Content`、`Content-Range: bytes 0-31/11258112` 和 ID3 起始字节。
仓库完整回归 `python.exe -m unittest discover -s tests -v` 共 255 项通过，0 failure、0 error。
确认文档与语音队列均无运行任务后，5001 服务由既有 watchdog 安全重启；正式地址再次返回 health 200，
`/yuedu-fm`、472/472 library 与标准音频 206 Range 响应均在正式端口复核通过。

## 微信公众号与新浪补档

补充日期：2026-07-23（America/Denver）

新浪媒体页 `https://www.sina.cn/media/2035970661` 的公开静态页只暴露 99 条动态，资料页声称总量 774 条；
其中 91 个短链可解析，7 个指向 `mp.weixin.qq.com` 文章，84 个指向旧 `yuedu.fm/article/<id>/`。旧站文章 URL
目前返回旧站首页，无法直接恢复正文和音频；不把首页内容误当作节目数据。

新增 `scripts/sync_yuedu_fm_wechat.py`：

```bash
python.exe scripts/sync_yuedu_fm_wechat.py --metadata-only --discover-related --pause-seconds 0.2
python.exe scripts/sync_yuedu_fm_wechat.py --discover-related --pause-seconds 0.3 --max-images 8
python.exe -m unittest tests.test_yuedu_fm -v
python.exe -m py_compile services/yuedu_fm_service.py scripts/sync_yuedu_fm.py scripts/sync_yuedu_fm_wechat.py server.py
```

实现边界：

- 只处理本机可直接打开的微信公众号文章 URL；
- 递归跟随文章正文中的 `mp.weixin.qq.com/s...` 往期作品链接，保留 `__biz/mid/idx/sn/chksm/scene` 等公开访问所需参数；
- 公众号 profile history 入口会返回验证/客户端限定页，未使用公众号后台、微信客户端历史接口、登录态或验证码绕过；
- 原始 HTML、逐篇 JSON、M4A 音频、正文图片和合并审计均保存在 `data/yuedu_fm/wechat/`，与 RedCircle 原库分开；
- `data/yuedu_fm/library.json` 保持 RedCircle 原库不变，合并播放器库写入 `data/yuedu_fm/library_combined.json`。

本次结果：

- 从新浪 7 个微信种子和正文往期链接共访问 13 篇微信公众号文章，0 抓取错误；
- 下载 13 个微信 M4A/MP4 音频和 29 张正文图片，`data/yuedu_fm/wechat/` 约 86 MiB，0 `.part` 残留；
- 合并策略按规范化标题+时长、音频 SHA-256 去重：8 集作为新增节目加入播放器，5 集跳过；
- 合并后 `/api/yuedu-fm/library` 返回 480 集，其中 RedCircle 472 集、微信新增 8 集，480/480 音频可本地读取；
- 微信音频接口复核：`/api/yuedu-fm/episodes/98e623a299a60c077e573a63/audio` 的 `Range: bytes=0-31` 返回
  `206 Partial Content`、`Content-Range: bytes 0-31/5153686`，起始字节为 `ftypisom`。

仍不可称为“公众号全量”：桌面公开 profile 入口返回验证/客户端限定页，当前只能保证“已知公开入口 + 文章内往期链接”穷尽到 13 篇。
若后续提供公众号后台导出、微信客户端内可分享链接列表，或更多新浪/网页入口 URL，可用同一脚本继续追加并重新生成合并库。
