# 翻译 SSH 隧道安全修复状态

核对日期：2026-08-12 MDT  
项目目录：`/mnt/d/claude`

## 发现

邮件报告 `iverson.cs.nmsu.edu` 上每分钟出现新的 SSH 登录。只读检查本机日志后，
`logs/watchdog.log` 从 12:58 到 14:56 持续记录：

```text
翻译隧道不通 → 重建 ssh -L 18001→iverson.cs.nmsu.edu:8000
```

Windows 进程命令行进一步确认旧 watchdog 以以下参数运行：

```text
pythonw.exe D:\claude\scripts\watchdog.py --start-if-down --interval 20 --fails 2
```

根因是 watchdog 把 gitignored 的 `data/translation_runtime.json` 当成远端模型仍在线的
充分证据；隧道失败后每 60 秒重新启动 SSH。登录启动项
`ClaudeServerWatchdog.vbs` 会在用户登录时拉起该 watchdog。

## 已修改

- `scripts/watchdog.py` 默认只探测本机 `127.0.0.1:5001`，不再自动创建 SSH 隧道。
- 只有显式传入 `--auto-tunnel` 才启用自动隧道恢复；失败后采用 60 秒起步、最长 1 小时的指数退避。
- 保留 `scripts/start_translation_tunnel.sh` 作为需要翻译时的显式、前台隧道入口。
- `README.md` 改为说明默认不远端连接，并警告不要把 `--auto-tunnel` 放入登录启动项或计划任务。
- 新增 `tests/test_watchdog.py`，锁定“默认不调用隧道恢复、显式开关才调用”的边界。
- `server.py` 增加两个默认关闭的模块开关；关闭时不实例化任务管理器，相关页面、静态文件和 API 均返回 404。
- 首页和共享导航移除了两个工具链接，并明确显示“GPU 工具已关闭”。
- 登录启动文件夹中的 `ClaudeServerWatchdog.vbs` 恢复本地平台自启，但强制关闭两个 GPU 模块，且不使用 `--auto-tunnel`。

已停止当时匹配 `D:\claude\scripts\watchdog.py` 的 Windows watchdog 进程；没有停止
`server.py`、删除数据或向远端发送新的命令。

## 本次验证

- `python.exe -m unittest tests.test_watchdog -v`：2 项通过。
- `python.exe -m unittest tests.test_paper_translation tests.test_server_access_security tests.test_research_navigation -q`：65 项通过。
- `python3 -m py_compile scripts/watchdog.py tests/test_watchdog.py`：通过。
- `git diff --check`：通过。
- Windows 进程复查：没有匹配 `watchdog.py` 或 `iverson.cs.nmsu.edu` 的残留进程。
- 日志复查：最后一条自动重连记录为 14:56:30，此后未新增。
- 启动项边界：只恢复本地平台；启动环境固定 `PAPER_TRANSLATION_ENABLED=0` 和 `AUDIO_TRANSCRIPTION_ENABLED=0`。

## 使用方式

需要翻译时，先手动启动远端模型，再在一个保持打开的终端运行：

```bash
scripts/start_translation_tunnel.sh
```

完成后按现有流程停止隧道并运行：

```bash
python scripts/manage_translation_vllm.py stop
```

## 尚需观察

修改后应确认 `logs/watchdog.log` 不再出现新的“重建 ssh”记录，并在 Windows 任务管理器中
确认没有旧版 watchdog 或 Iverson SSH 子进程残留。其他研究工具的 SSH/SCP 任务仍只应在
用户显式启动对应任务时运行；本次未停止与 Iverson 无关的其他 SSH 进程。

## 平台恢复与模块级关闭验收（2026-08-12 15:45 MDT）

用户仍需使用 `http://127.0.0.1:5001/` 的其他研究模块，因此恢复本地 `server.py`，但不恢复
论文翻译和语音转写：

- Windows 本机实际请求：`/` 与 `/api/health` 返回 HTTP 200。
- `/paper-translation`、`/audio-transcription`、对应直接 HTML 路径和两个配置 API 返回 HTTP 404。
- 两个任务创建 POST API 返回 HTTP 404，不能写入任务或启动后台线程。
- `/api/health` 明确返回两个模块 `enabled: false`。
- 首页不再含两个模块链接，显示“0 个可用工具 / GPU 工具已关闭”。
- Windows 进程复查无 SSH、SCP、vLLM 或远端音频 worker；5001 仅由本地 `server.py` 监听。
- watchdog 命令行只有 `--start-if-down`，没有 `--auto-tunnel`。
- 34 项访问/导航/watchdog 测试与 48 项翻译/转写服务测试通过；`py_compile` 和
  `git diff --check` 通过。
