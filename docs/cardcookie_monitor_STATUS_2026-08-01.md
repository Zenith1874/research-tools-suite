# CardCookie 按需监控状态说明（2026-08-01）

## 目标与边界

- 将 `C:\Workplace\Cardcookie` 中 Walmart / Best Buy 的历史监控思路接入研究工具集，而不直接运行或改写旧笔记本。
- 监控运行态默认关闭；服务器重启后仍为关闭。只有服务器本机页面的明确点击才会开启自动查询。
- 只访问 CardCookie 的公开商品页；不登录、不处理验证码、不绕过访问限制。验证页、HTTP 403/429 和未知页面都记为失败，不覆盖上次有效状态。
- 本次未开启生产监控，也未发送测试邮件。邮件非敏感参数已迁移到 gitignored 的 `.secrets`；旧明文授权码未迁移。

## 已实现

页面：`http://127.0.0.1:5001/cardcookie-monitor`

- Walmart 与 Best Buy 可分别选择；默认每 10 分钟，可选 1/2/3/5 分钟及更长间隔，每轮每个商家只请求一次。
- 1–3 分钟用于短时抢卡监控；遇到验证页或 HTTP 403/429 时自动退避 15 分钟，页面显示退避原因和下次检查时间。
- “立即检查一次”只建立/更新本机记录，永不发邮件。
- “开启监控”立即检查一次，之后按间隔运行；停止后不再安排下一轮。当前正在返回的请求可以写完日志，但停止后不会再发邮件。
- 首次成功结果是基线，不发送邮件。后续有货/缺货、面值、折扣、售价或同类卡数量变化才生成变化事件。
- 连续 3 次失败才生成一次异常通知；单次失败在检查明细中可见。恢复后生成本机恢复记录，不额外发送恢复邮件。
- 邮件配置存在时，页面只显示遮罩后的发件人/收件人，并要求用户在开启前再次勾选确认。邮件密码不会进入 API、数据库或页面。
- 邮件未配置时仍可运行“仅记录”模式。
- 页面新增本机邮件配置表单：QQ 邮箱预设为 `smtp.qq.com:587 + STARTTLS`，也可改用其他 SMTP。保存立即生效但不发送邮件，密码框永不回显；留空会保留已保存的新授权码。
- 已安全读取旧目录中的 4 个笔记本，只导入一致的 SMTP 服务器、端口、发件人和收件人。检测到的旧 `email_pass` 被明确忽略，当前仍需用户在本机页面填入轮换后的新授权码。

## 本机数据与 API

- 数据库：`data/cardcookie_monitor.db`（命中仓库现有 `*.db` 忽略规则，不进入 Git）。
- `cardcookie_snapshots`：每次成功、网络失败、解析失败和验证页结果。
- `cardcookie_target_state`：每个商家的上次有效状态、连续失败数和最近错误。
- `cardcookie_events`：首次基线、库存/价格变化、连续失败和恢复事件，以及邮件发送结果。
- 私有接口：
  - `GET /api/cardcookie-monitor/status`
  - `GET /api/cardcookie-monitor/email-settings`（仅返回可编辑的非敏感字段和 `password_set`）
  - `POST /api/cardcookie-monitor/start`
  - `POST /api/cardcookie-monitor/stop`
  - `POST /api/cardcookie-monitor/check-now`
  - `POST /api/cardcookie-monitor/email-settings`（只保存，不发送）
- 状态接口默认仅本机可读；所有 POST 继续受平台现有写权限保护。

## 邮件参数

参数由本机页面写入 gitignored 的 `D:\claude\.secrets`：

```text
CARDCOOKIE_SMTP_HOST=smtp.qq.com
CARDCOOKIE_SMTP_PORT=587
CARDCOOKIE_SMTP_USE_SSL=0
CARDCOOKIE_SMTP_STARTTLS=1
CARDCOOKIE_SMTP_USER=sender@example.com
CARDCOOKIE_SMTP_PASS=新生成的邮箱授权码或应用密码
CARDCOOKIE_SMTP_FROM=sender@example.com
CARDCOOKIE_NOTIFY_TO=recipient@example.com
```

旧版通用 `SMTP_*` 参数仍可兼容读取；一旦保存页面配置，CardCookie 会完整切换到独立参数，绝不从通用命名空间拼接密码。旧 Cardcookie 笔记本中存在过硬编码邮箱授权信息。旧文件保持原样，但在正式启用前应先到邮箱后台撤销旧授权码并生成新授权码，不能复制旧值到代码或仓库。

## 来源侦察与解析纪律

- Walmart：`https://cardcookie.com/buy-gift-cards/walmart`
- Best Buy：`https://cardcookie.com/buy-gift-cards/best-buy`

2026-08-01 的低频侦察中，两页均返回 HTTP 200 和包含 `Gift Card / Value / Discount / Price` 的表格；当时 Walmart 可识别 `$20 / 6% / $18.80` 与 `$11 / 6% / $10.34`，Best Buy 可识别 `$25 / 9% / $22.75`。这些只是页面当时状态，不作为固定种子数据写入代码。

解析器按表头识别字段、只接收目标品牌行、聚合相同卡片并保留数量。页面行顺序变化不会误报；数量变化会报告。明确的 `out of stock` 才记为缺货，没有商品表且没有缺货说明时记为解析失败。

## 验证

- 新增纯解析、状态机与邮件配置测试：有货、明确缺货、未知页、验证页、行顺序稳定、首次基线、真实变化单次邮件、手动检查不发邮件、连续失败阈值、失败不覆盖有效状态、密码不进入 payload、开启前收件人确认、数据库幂等与默认关闭；另覆盖旧笔记本安全发现、命名空间不混用、保存不发送、保留其他密钥、密码不回显及留空保留新授权码。
- 导航、首页、私有访问和路由契约测试已同步。
- 2026-08-01 邮件配置定向验证：37 个相关测试全部通过；全仓回归 398 个测试全部通过。
- 服务重启后实测：页面、私有状态接口和邮件设置接口均为 HTTP 200，设置接口为 `no-store, private`；
  运行态为 `stopped`、后台线程关闭，原有 30 条检查记录与 3 条事件完整保留。邮件接口确认
  `smtp.qq.com:587 + STARTTLS`、发件人与 1 个收件人均已迁移，`password_set=false`，响应中不存在
  `password` 字段。浏览器自动控制因当前 WSL 路径映射问题未能建立连接，因此没有把 HTTP/HTML 验证
  冒充为视觉点击验收；页面内嵌脚本和共享导航已用 Node.js 完成语法检查。

## 文件

- `services/cardcookie_monitor_service.py`
- `static/cardcookie_monitor.html`
- `tests/test_cardcookie_monitor_service.py`
- `server.py`
- `static/research-nav.js`
- `static/index.html`
- `README.md`
