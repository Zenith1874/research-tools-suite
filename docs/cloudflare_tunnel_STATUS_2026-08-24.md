# Cloudflare Tunnel 状态（2026-08-24）

## 当前状态

- Cloudflare 域名 `zhengresearch.com` 已购买并出现在当前账号的域名区域；发票截图显示本次金额为 `$10.46`。
- Cloudflare Tunnel `research-pc` 已创建，截图显示连接器状态为 `Healthy`；公开主机名 `research.zhengresearch.com` 已映射到 `http://127.0.0.1:5001`，Access 应用仍待创建。
- 现有研究平台仍运行在 Windows `0.0.0.0:5001`，默认远程只读。
- Windows `C:\Cloudflared\bin\cloudflared.exe` 已准备好并验证为 `2026.8.2`；尚未安装 Tunnel 服务，因为还没有从 Cloudflare 控制台取得 Tunnel token。

## 已完成的安全修复

- `server.py` 新增 `TRUST_CLOUDFLARE_HEADERS`（默认关闭）。启用后，Cloudflare Tunnel 发到 loopback 的 `CF-Connecting-IP` 会参与远程/本机权限判断。
- 这样经 `cloudflared` 转发的公网请求不会因为 origin socket 是 `127.0.0.1` 而获得本机写权限。
- Windows 登录启动脚本已预置 `TRUST_CLOUDFLARE_HEADERS=1`；`ALLOW_REMOTE_WRITES` 仍保持关闭。
- 为避免看门狗由其他启动入口或重启路径拉起时丢失该环境变量，已将 `TRUST_CLOUDFLARE_HEADERS=1` 固化到 gitignored 的 Windows 本机 `.secrets`；不进入 Git。
- `.secrets.example` 已记录该配置及启用条件。

## 验证

- `python3 -m unittest discover -s tests -p 'test_server_access_security.py' -v`
- 25 个访问安全测试通过，包括 Cloudflare loopback 转发、非法代理头、LAN 只读、远程令牌精确匹配和敏感模块本机隔离。
- Windows 服务已由看门狗恢复；`http://127.0.0.1:5001/api/health` 返回 200。
- 带有效 `CF-Connecting-IP` 的 loopback health 返回 `access_mode=read_only`，对应 POST 返回 403；无该头的本机请求仍保留管理权限。
- Cloudflare 控制台已显示 Published application route：`research.zhengresearch.com` → `HTTP http://127.0.0.1:5001`；在 Access 保护完成前，不应把该地址当作安全入口分享。
- 外部 IPv4 实测：`https://research.zhengresearch.com/api/health` 返回 200、`access_mode=read_only`、`client_can_write=false`；外部 POST 实测返回 403。说明公网 Tunnel 和远程只读边界均已生效，但尚未证明 Access 登录保护已启用。
- 修复前曾出现公网 `/api/health` 被误判为 `access_mode=manage`；重启加载本机 `.secrets` 后复测：`127.0.0.1` 无代理头为 `manage`，带有效 `CF-Connecting-IP` 的 loopback 为 `read_only`，公网域名为 `read_only`，公网 POST 为 403。

## 下一步

1. 在 Cloudflare Zero Trust → Networks → Tunnels 创建 `cloudflared` Tunnel。
2. 将公开主机名映射到 `http://127.0.0.1:5001`。
3. 用 Cloudflare Access 只允许指定邮箱登录。
4. 安装并持久化运行 `cloudflared`，然后从外部 5G/学校网络验证登录、GET 200 和 POST 403。
