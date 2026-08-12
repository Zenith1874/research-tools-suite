# 研究语音工作台：转录、说话人区分与翻译状态

核对日期：2026-07-21（America/Denver）<br>
本地项目：`/mnt/d/claude`（Windows：`D:\claude`）<br>
远端根目录：`/home/simurghnobackup/zcui/audio_transcription/`

## 1. 目标与研究边界

该模块面向访谈、会议、讲座和研究录音，目标是形成可复核的中间文本，而不是把音频直接交给不可审计的端到端服务：

1. 逐词 ASR 时间戳；
2. 匿名说话人区分；
3. 按说话人轮次组织原文；
4. 可选逐轮翻译；
5. 原文、译文和双语 TXT / JSON / SRT / VTT / ZIP；
6. 保存输入与输出 SHA-256、模型/包版本、参数、进度、运行主机和清理审计。

`SPEAKER_00` 等标签只表示当前音频内的聚类，不表示真实身份。模块不推断姓名、性别、年龄、情绪、健康状态或其他声音属性，
也不进行跨录音的声纹识别。重叠发言、背景噪声、电话压缩、串音和极短发言可能导致误分，重要研究材料必须抽查切换点。

## 2. 已复用的 nobackup 资产

只读盘点确认已有以下模型和环境，因此没有重复下载权重：

- ASR：`Systran/faster-whisper-medium`，快照
  `08e178d48790749d25932bbc082711ddcfdfbc4f`，约 1.5 GB；
- 说话人区分：`pyannote/speaker-diarization-community-1`，快照
  `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee`；配置包含 segmentation、embedding、PLDA 和 VBx 聚类资产；
- 基础环境：`/home/simurghnobackup/zcui/venvs/reddit_env`，Python 3.13.13、PyTorch 2.11.0、
  pyannote-audio 4.0.4；
- 模块隔离依赖：`audio_transcription/vendor-20260721/`，429 MB；faster-whisper 1.2.1、
  CTranslate2 4.8.1，并用 `scripts/audio_transcription_constraints.txt` 将共享依赖钉到原环境兼容版本。

部署 worker 与本地源码 SHA-256 均为：

`b1910eb6988738d886d840e2f8ac2b5fbbad06bdde7eec533aa3661882ef5cd2`

首次依赖尝试留下 `audio_transcription/vendor/`（431 MB）：该目录含被新版 transitive metadata 遮蔽的版本，保留作审计，
运行器明确不引用它；未获用户明确授权前不删除。

## 3. HF key 处理

旧 notebook 中存在明文 HF token。部署脚本没有打印、回传或写入仓库，而是在远端内存中逐个调用 Hugging Face `whoami`
验证授权，只把有效 token 原子写入：

`/home/simurghnobackup/zcui/audio_transcription/.secrets/hf_token`

实测权限为 `0600`。正式推理直接从本地快照离线加载，不把 token 放入 worker 命令或环境；该文件只供以后受控刷新 gated 模型。
历史 notebook 未修改，以免破坏研究记录，但这也意味着旧明文副本仍存在。建议后续撤销/轮换旧 token；离线推理不会因此中断，
刷新模型前再把新 token 写入同一私有文件。

## 4. 隐私与执行架构

```text
本机浏览器（loopback only）
  -> HTTPServer 分块写入 data/audio_jobs/<job_id>/source.<ext>
  -> 空闲 GPU 探测：Keller（语音专用默认主机）
  -> SSH/SCP 加密暂存到 audio_transcription/jobs/<job_id>/
  -> CPU INT8 faster-whisper medium：逐词时间戳 + VAD
  -> PyAV 解码为 16 kHz mono waveform（内存输入，不依赖 torchcodec/系统 ffmpeg）
  -> 所选 GPU 上的 Community-1 exclusive diarization
  -> 逐词重叠优先、1.5 秒内最近段回退，形成匿名轮次
  -> result.json 回传并与本机输入 SHA-256 比较
  -> 删除并确认远端精确 job 目录不存在
  -> 可选 Iverson Qwen 逐轮翻译；共用原时间轴
  -> 本机导出与 ZIP
```

Keller GPU 必须同时满足显存占用不高于 1,024 MiB、利用率不高于 10%；繁忙时默认等待
900 秒，不强行共享。ASR 使用 CPU INT8，是因为当前基础环境提供 CUDA 13，而 CTranslate2 官方 GPU 路径要求 CUDA 12 cuBLAS；
避免额外安装约 1 GB 的旧 CUDA 运行库。Community-1 继续使用所选 GPU。

远端任务在成功或失败路径都会尝试删除；成功 manifest 必须记录 `remote_cleanup_verified=true`。若清理不能确认，任务保留明确警告，
不宣称远端副本已删除。

## 5. 对齐、断点与输出

- faster-whisper 使用 beam size 5、Silero VAD、500 ms silence threshold、word timestamps；
- Community-1 优先使用 `exclusive_speaker_diarization`，便于与非精确 ASR 时间对齐；
- 已知人数用 `num_speakers`；否则支持 `min_speakers` / `max_speakers`，范围 1–20；
- 每个词先按时间重叠分配；无重叠时只允许 1.5 秒内最近说话人回退，否则标为 `UNKNOWN`；
- 轮次在说话人变化、间隔超过 1.5 秒、时长超过 15 秒或 240 字符时拆分，适配字幕阅读；
- 翻译沿用 Qwen 严格 JSON、保护片段和分批检查点；翻译失败不丢失已完成转录；
- “追加翻译”会校验已有 `transcript.json` 与输入 SHA-256，只运行翻译和重新导出；
- 原文、译文和双语字幕使用完全相同的起止时间行。

本机 manifest 与输出均用临时文件 + `os.replace` 原子更新。服务重启时，遗留 `running` 任务标记为 `interrupted`，允许重试。
本地异常详细栈和远端 worker 诊断只保存在私有 job 目录，不进入 API 或下载包。

## 6. 页面与 API

新增独立页面 `/audio-transcription`，位于一级“科研工具”，不归入 ABDC 商科期刊。上传按钮必须同时满足：

- 已选择支持的音频/视频；
- 用户勾选“经 SSH 暂存并回传后删除”的隐私确认。

新增 loopback-only API：

- `GET /api/audio/config`
- `GET /api/audio/jobs`
- `POST /api/audio/jobs`
- `GET /api/audio/jobs/<id>`
- `GET /api/audio/jobs/<id>/result`
- `GET /api/audio/jobs/<id>/download?format=<kind>`
- `POST /api/audio/jobs/<id>/retry`
- `POST /api/audio/jobs/<id>/translate`
- `POST /api/audio/jobs/<id>/delete`

支持 WAV、MP3、M4A、FLAC、AAC、OGG、OPUS、MP4、MOV、MKV 和 WEBM，默认最大 1 GiB。浏览器请求体在服务端分块落盘，
不是整文件读入内存。文件名、任务清单、原录音、转录和下载默认只允许 loopback；远程放开必须显式设置
`AUDIO_TRANSCRIPTION_ALLOW_REMOTE=1` 并满足平台写权限。

任务创建后优先在新标签打开 `/audio-transcription/results/<id>`。该页面在排队/运行阶段轮询私有结果 API，完成后直接呈现
原文、译文或双语轮次，支持说话人筛选、全文搜索、复制与打印；ZIP、TXT、SRT、VTT 和审计 JSON 下载继续保留。
结果 API 使用 `Cache-Control: no-store, private`，只返回轮次级文本和时间，不返回逐词概率、原始 diarization 片段、
本机文件路径或私有诊断日志。首页“科研工具”现明确列出文档与语音两个可用工具。

## 7. 真实端到端验证

为避免使用私人会议录音，测试夹具由 Windows SAPI 的 Microsoft David / Zira 两种合成声音交替生成：24.009 秒、
22,050 Hz、mono、约 1.0 MB。成功任务：`d7a9c698b622471cba029beb426fdca5`。

结果：

- 自动选择 iverson GPU 0（开始前 13 / 20,475 MiB，0%）；
- 47 个词、4 个轮次、2 位匿名说话人；四段按 `00 -> 01 -> 00 -> 01` 正确交替；
- ASR 四句与合成输入语义一致；
- 输入 SHA-256 由远端 worker 与本机双重验证；
- 远端 job 目录删除确认通过；
- 原文 JSON/TXT/SRT/VTT/ZIP 完整，ZIP `testzip()` 返回 `None`；
- 启动 Qwen 后对同一完成任务执行“追加翻译”，`resumed_transcript=true`，没有重跑音频模型；
- 生成译文和双语 TXT/SRT/VTT，ZIP 共 10 个成员；
- 原文、译文和双语 SRT 的四条时间行逐字节一致；
- 双语输出示例保持匿名说话人与时间：
  `SPEAKER_01: Thank you...` / `谢谢。我将讨论远程工作如何改变沟通和员工福祉。`

第一次真实 smoke `cc0fa50657764549b275dc6c2295c71a` 在 Windows subprocess 默认编码读取 UTF-8 中文进度时失败；
远端目录已确认删除，本机失败任务保留。修复为 SSH 子进程显式 `encoding='utf-8', errors='replace'` 后，同一夹具通过。

浏览器验证：Playwright 完成首页语音入口、工作台三台运行器状态、完成任务“打开查看结果”、新标签结果页、双语轮次、
原文/译文/双语切换及保留下载入口检查；控制台 0 error / 0 warning。结果页截图保存在 gitignored 的
`.playwright-cli/page-2026-07-22T03-12-39-121Z.png`。结果 API 与下载响应均含 `Cache-Control: no-store, private`。

三台候选主机均通过 SSH、worker、两个离线模型快照与 Python 依赖只读检查：simurgh、kaiju、iverson 均可导入
`faster-whisper 1.2.1` 与 `pyannote-audio 4.0.4`。本次检查时 simurgh 两张 H100、kaiju A100 均在执行其他任务，
iverson RTX 4000 由 Qwen 占用，因此当时没有强行启动三份 GPU smoke；随后按下述 Keller 专机方案完成切分。

### Keller 语音专机切分

后续复核确认 `keller.cs.nmsu.edu` 可通过既有 SSH 配置访问，RTX 4000 Ada 20,475 MiB 在检查时为
13 MiB / 0%，并能读取共享 worker、ASR/diarization 模型快照；远端环境可导入 `faster-whisper 1.2.1`、
`pyannote-audio 4.0.4` 与 `torch 2.11.0`。因此默认语音候选主机改为仅 Keller，Iverson 不再参与语音 GPU 调度，
继续专门承载 `Qwen/Qwen3-14B-AWQ` 翻译。

第一次 Keller 尝试使用 WSL 临时环境变量启动 Windows Python，变量未跨环境传入，任务
`c7ca0e175fe447c08aa4aff24fccd4ac` 实际仍在等待旧候选主机；该进程在上传远端音频前停止并标记为 interrupted。
随后把 Keller 写成代码默认值，并给 smoke 脚本增加显式 `--host`，不再依赖跨 shell 环境变量。

成功分工任务 `a826eda0e3d54183992fa30c94b3648a` 使用同一 24 秒合成夹具：Keller 完成 47 个词、4 个轮次、
2 位匿名说话人的转录与区分，Iverson Qwen 完成 4 个轮次翻译；`input_sha256_verified_by_worker=true`、
`remote_cleanup_verified=true`，原文/译文/双语导出全部生成。重启本机服务后 `/api/audio/config` 只返回 Keller，
`data/translation_runtime.json` 与实际 `127.0.0.1:18001 -> iverson.cs.nmsu.edu:8000` SSH 隧道仍指向 Iverson。

### 主机白名单与打开页面时连接检查

通用只读主机列表更新为 `iverson / keller / lovelace / newton / riemann`，simurgh 与 kaiju 从默认列表移除。
普通路径仍严格分工：Keller 是唯一默认语音主机，Iverson 是 Qwen 默认主机；Lovelace、Newton、Riemann 仅供显式检查或
人工 `--host auto`，不会因打开语音页面自动占用。

五台 SSH、GPU、共享目录、worker、模型快照和依赖检查全部通过，均能导入 `faster-whisper 1.2.1`、
`pyannote-audio 4.0.4` 和 `torch 2.11.0`。现场状态：Iverson 18,107 / 20,475 MiB（Qwen）、Keller 13 MiB / 0%、
Lovelace 13 MiB / 0%、Newton 16 MiB / 0%、Riemann 486 MiB / 99%。`/proc/uptime` 显示五台已连续运行约
89–105 小时，因此现场证据不支持“每天重启”；但任何实际重启都会终止该机进程。

语音页面加载和手动“重新检查服务”现在会建立一次 Keller 只读 SSH 探测，并显示空闲、繁忙或无法连接；取消了页面每
30 秒重复 SSH 探测。正式任务仍为每任务独立 SSH/SCP 会话。Iverson 重启后需要重新启动 vLLM 和本机隧道，页面只做健康
检查并明确显示未连接，不自动占用其他 GPU。

聚焦测试命令：

```bash
python.exe -m unittest \
  tests.test_audio_transcription \
  tests.test_server_access_security \
  tests.test_research_navigation -v
```

结果查看、主机白名单与连接检查的相关测试均通过。仓库完整回归命令
`python.exe -m unittest discover -s tests -v` 最终通过：共 188 项测试，0 failure、0 error。

## 8. 已知限制与后续路线

- 当前是文件任务，不是实时麦克风流；超长录音仍会在远端解码为 16 kHz waveform，约 230 MB RAM / 小时；
- 1 GiB 是上传大小上限，不等同于无限时长；超长材料建议先按访谈场次切分；
- Community-1 是说话人区分，不是身份识别；匿名标签不能跨文件直接比较；
- Keller 专门承担语音模型，Iverson 继续承担 Qwen；Keller 繁忙时语音任务等待或超时，不会抢占 Iverson 翻译 GPU；
- 当前未实现 TTS 或声音克隆。若后续增加语音输出，默认只评估普通合成语音；声音克隆须单独的同意、数据保存和伦理边界；
- 模型结果用于研究整理和检索时仍需人工抽查，不应把自动转录或匿名标签直接当作无误的正式编码。
