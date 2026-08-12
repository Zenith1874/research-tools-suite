# 学术语言工作台：文档翻译模块状态

核对日期：2026-07-21<br>
本地项目：`/mnt/d/claude`（Windows 对应 `D:\claude`）<br>
远端部署根目录：`/home/simurghnobackup/zcui/paper_translation/`

## 1. 目标与边界

本模块用于中英文论文翻译，优先级依次为：

1. 原论文和译文不进入第三方云模型或公开仓库；
2. DOCX 的包结构、段落、行内样式、表格、图片、页眉页脚、脚注/尾注、字段和关系文件尽量保持；
3. 引用、DOI、URL、邮箱、数字和用户术语表经过占位保护并逐项校验；
4. 模型返回的单元数、片段数或保护标记不一致时，任务失败，不静默输出伪完成文件；
5. 每个任务保存输入/输出 SHA-256、模型、参数、分批检查点和结构审计结果。

当前正式支持带文本层的 `.pdf`、`.docx`、UTF-8 `.txt` 和 `.md`。PDF 输出是保持页尺寸和原坐标的
高保真阅读副本，不宣称字节级无损；表格内部、参考文献、页眉页脚和竖排版权文字默认保留原文。
扫描型 PDF 在本地 OCR/VLM 尚未配置时明确失败，不生成不完整译文。DOCX/PDF 最终结果仍须逐页目视检查。

## 2. 隐私架构

```text
本机浏览器
  -> 本机 Research Tools HTTPServer（上传仅允许 loopback）
  -> data/translation_jobs/<job_id>/（gitignored；原件/检查点/译文）
  -> 分段、术语与引用保护
  -> 127.0.0.1:18001 SSH 隧道
  -> iverson 127.0.0.1:8000 vLLM
  -> 仅返回结构化翻译片段
  -> 本机回填 PDF 坐标层 / DOCX OOXML + 完整性验证
```

默认情况下，即使平台其他页面可从局域网读取，翻译任务清单、文件名、译文下载和删除接口仍只允许回环地址。
只有同时显式设置 `TRANSLATION_ALLOW_REMOTE=1` 并满足平台写权限时才放开。

## 3. 主机选择与模型

2026-07-21 17:11 MDT 的只读探测结果：

| 主机 | GPU | 显存占用 | GPU 利用率 | 判定 |
|---|---|---:|---:|---|
| simurgh | 2 x NVIDIA H100 NVL 95,830 MiB | 43,790 / 44,222 MiB | 100% / 100% | 忙 |
| kaiju | NVIDIA A100 PCIe 40,960 MiB | 25,801 MiB | 97% | 忙 |
| iverson | NVIDIA RTX 4000 Ada 20,475 MiB | 13 MiB | 0% | 选用 |

只读检查脚本：`scripts/check_translation_hosts.py`。统一启停脚本：`scripts/manage_translation_vllm.py`。
`manage_translation_vllm.py start` 会检查三台主机、自动选择符合阈值且显存占用最少的 GPU；无合格 GPU 时不启动。
它把实际主机写入 gitignored 的 `data/translation_runtime.json`，隧道和 `stop` 自动读取该记录，停止成功后删除记录。
默认空闲阈值为显存占用不高于 1,024 MiB 且利用率不高于 10%。
WSL 下无参数运行时会自动发现 Windows 用户目录中的 SSH 配置、密钥和 `known_hosts`，私钥以 mode 0600
临时复制到 `/tmp` 并在退出时清理；2026-07-21 的无参数实测推荐 `iverson`。
远端启动脚本会再次执行相同护栏；GPU 忙时拒绝启动，除非管理员明确设置
`TRANSLATION_FORCE_START=1`。
需要人工指定时可用 `manage_translation_vllm.py start --host <FQDN> --gpu-index <n>`；仍须通过相同空闲护栏。

模型采用 `Qwen/Qwen3-14B-AWQ`：官方开源 AWQ 权重，本地运行，不调用 Qwen-MT 云 API。部署参数：

- 权重缓存：`/home/simurghnobackup/zcui/.cache/huggingface/hub/models--Qwen--Qwen3-14B-AWQ/`，实测 9.4 GB；
- vLLM：0.25.0；PyTorch：2.11.0；Transformers：5.5.3；
- 模型服务：远端 `127.0.0.1:8000`；本地隧道：`127.0.0.1:18001`；
- 最大模型上下文：8,192 tokens；最大并发序列：4；GPU memory utilization：0.90；
- 翻译批次默认不超过 4,200 字符和 10 个单元；temperature 0.1、top_p 0.8、固定 seed 20260721；
- 输出 token 最多 5,000，保证系统提示、输入和输出不超过 8,192 token 上下文；
- Qwen3 thinking 关闭，要求严格 JSON 输出；失败最多重试 2 次。
- 模型 JSON、单元、句末或保护标记校验失败时自动二分批次；每个通过单元保存源 SHA-256，重试时只复用哈希一致的译文。

## 4. 格式实现

DOCX 使用 ZIP + OOXML 原位处理，而不是把全文抽取后重新生成一个 Word 文件：

- 扫描 `document.xml`、页眉、页脚、脚注、尾注和批注 XML；
- 相邻且样式相同的 run 合并为翻译片段，翻译结果写回原 `<w:t>` 节点；
- 字段代码及字段显示文本保持锁定；含 Office Math 的段落整段锁定；
- 默认从 References/Bibliography/参考文献标题后保留书目条目，遇到同级或更高级标题恢复翻译；
- 输出 ZIP 成员名称和顺序必须与输入一致；媒体逐文件 SHA-256 必须一致；
- 各 XML part 的段落、表格和 drawing 计数必须一致。
- manifest 明确记录因参考文献、Office Math 或字段保护而跳过的段落/片段数量。

PDF 使用 PyMuPDF 的文本坐标、redaction 和 `insert_htmlbox` 在原文件副本上回写：

- 合并出版商拆散的 justified spans，识别双栏、段落、标题和跨行连字符；
- 修复已确认的出版商字符映射（负号、η、脚注上标），并禁止输出新增乱码或控制字形；
- 使用表格检测和灰色行带合并锁定整张表，避免只翻译表格的一半；
- 默认锁定参考文献、页眉页脚、竖排版权文字及表格内部，正文/标题/图注在原矩形内写入中文；
- 中文由 PyMuPDF Story/CSS 自动使用 CJK fallback 字体，段落最低允许缩放 58%；无法完整放回时硬失败；
- 输出必须保持页数和每页尺寸、显示图片内容/位置及链接数量；记录最小缩放、跳过行和原/输出异常字形计数；
- 任务检查点记录源片段 SHA-256；抽取规则升级或失败重试时只重译哈希变化或术语审计未通过的单元。

PyMuPDF 为 AGPL / 商业双许可证，依赖和许可边界已在 `requirements.txt` 注明。当前实现不使用
`pymupdf-layout` 的非商业许可组件。

### 扫描 PDF 的本地模型评估

当前文本层论文不需要视觉模型；版面由确定性坐标管线保持，`Qwen/Qwen3-14B-AWQ` 只负责翻译。
扫描件后续优先评估 `PaddlePaddle/PaddleOCR-VL-1.5`（0.9B，页面级文本/表格/公式/图表解析），
备选 `Qwen/Qwen3-VL-4B-Instruct`（文档 OCR 与 HTML/位置解析）。二者都只能提供结构化识别，仍需本机
PDF 回写管线才能产生近似原版式文件；在部署、显存烟雾测试和版面基准完成前，扫描件继续硬失败。

## 5. 本地文件与 API

新增页面：`/paper-translation`。

新增 API（默认 loopback only）：

- `GET /api/translation/config`：模型隧道状态和限制；
- `GET /api/translation/jobs`：最近 30 个本机任务；
- `POST /api/translation/jobs`：原始文件 body + 编码选项头，创建异步任务；
- `GET /api/translation/jobs/<id>`：任务进度；
- `GET /api/translation/jobs/<id>/download`：下载完成译文；
- `POST /api/translation/jobs/<id>/retry`：重试失败或中断任务；
- `POST /api/translation/jobs/<id>/delete`：用户确认后删除该任务原件、检查点和译文。

每个任务使用独立 UUID 目录，manifest 采用临时文件 + `os.replace` 原子更新。模型调用日志和服务异常不记录论文正文。

## 6. 验证记录

已完成的聚焦测试命令：

```bash
python.exe -m unittest \
  tests.test_paper_translation \
  tests.test_server_access_security \
  tests.test_research_navigation -v
```

2026-07-21 最新运行：`python.exe -m unittest discover -s tests -v` 全仓库 166 项通过；
`paper_translation.html` 的 2 个内联脚本均通过 Node 语法检查。覆盖：

- 术语、引用、DOI、URL 与数字保护/恢复；保护标记缺失时硬失败；
- DOCX ZIP 成员、媒体字节、粗粒度 OOXML 结构、表格和粗体 run 保持；
- 参考文献条目和含公式段落不被翻译；
- TXT CRLF/LF 与空行保持；
- 文本层 PDF 的页尺寸、图片内容/位置、链接、表格锁定、参考文献和扫描件硬失败路径；
- 翻译上传使用独立 50 MB 上限；普通 API 的 1 MB 上限不变；
- 翻译任务默认仅回环地址可访问；共享导航和页面接入。
- 空闲 GPU 推荐会选择合格机器中显存占用最低者；单台 SSH 探测超时不会中断其余主机检查。

WSL `python3` 的新增模块测试通过，但导入整个 `server.py` 时本环境缺少既有依赖 `beautifulsoup4`；这不是测试断言失败。
使用项目实际 Windows Python 环境复跑后全部通过。

真实模型烟雾测试（合成文本，不含用户论文数据）：

- `/v1/models` 健康检查 11 ms；
- 两片段结构化翻译 2.26 秒，术语表强制得到“算法管理 / 自主性”，`(Smith, 2024)` 原样保留；
- 第一份 DOCX 共 9 个可译单元，8 秒内完成；ZIP 成员、媒体、OOXML 粗结构、粗体、斜体和表格均通过；
- 第二份 DOCX 修正并验证中文 run 边界空格，审计正确报告 1 张表格，参考文献条目保持英文；
- 使用本机 Microsoft Word 导出 PDF，并在 100% 页面视图检查：一页文档无乱码、重叠或截断，标题、表格、页眉页脚和参考文献清晰。
- 统一管理脚本真实自动选中 `iverson`，成功启动 PID 245964，再按本地记录停止；最终恢复 13 MiB / 0%。

真实 PDF 端到端验收（Brosi & Gerpott, *Journal of Organizational Behavior*，18 页双栏论文）：

- 输入 18 页，抽取后 214 个翻译单元；表格 140 行、参考文献 89 个区域、页眉 36 行和竖排 17 行锁定；
- 输出仍为 18 页，页面尺寸、显示图片内容与坐标不变，274 个链接全部保留；
- 输入未映射控制字形 15 个，输出降至 3 个（仅原字体表格负号）；无 Unicode replacement character；
- 最小文字缩放 85.6%，低缩放区域 0；封面、正文、跨双栏表格、第 9 页脚注/COVID-19 和末页逐页渲染检查通过；
- 最终任务 `9cb8b5fbd0b748c881c010e8d6172eb4`，输出 SHA-256
  `7a3bc82fbf1d2ab420c7ff35a747f9e0cb6127a2583d0e741ba02d3a5c016d53`。

首次远端启动从 17:28:22 到 17:34:20 MDT 约 6 分钟，其中下载权重 131.6 秒；模型权重 9.44 GiB，
可用 KV cache 6.61 GiB，运行时 `nvidia-smi` 总占用约 16.8 GiB。验证结束后已停止 vLLM 和 SSH 隧道，
iverson 恢复到 13 MiB / 0%；权重与脚本保留，供需要时按空闲主机检查结果启动。

## 7. 尚需人工验收

- 用一篇包含两栏、复杂表格、Zotero/EndNote 字段、脚注和公式的真实 DOCX 做小规模翻译；
- 在装有 Word 或 LibreOffice 的环境逐页渲染输入/输出，核对分页、表格宽度、脚注位置和字体替换；
- 固定一份 IS/Management 术语表，并由人工抽查若干段落的意义、语气、因果强度和构念区分；
- 固定更多出版商（Elsevier、Springer、SAGE、APA）各 1–2 篇双栏/单栏 PDF 回归样本；
- 如要支持扫描件，先在空闲 GPU 上对 PaddleOCR-VL-1.5 0.9B 做页级显存、OCR、表格和公式基准，再决定是否接入；
- 译文是本地模型生成的阅读副本，仍需研究者抽查术语、构念、语气和统计叙述，不应直接作为正式出版译稿。

## 8. 页面可用性修复（2026-07-21 19:41 MDT）

- 根因：按需释放 vLLM 和 SSH 隧道后，页面会安全地禁用“开始隐私翻译”，但旧界面没有在文件选择区说明禁用原因，容易误判为上传失败。
- 修复：文件仍可先选择；选择后明确显示文件已选中及模型连接状态，并新增“重新检查模型”按钮。页面仍每 15 秒自动轮询，模型健康检查通过后自动解锁开始按钮。
- 现场恢复：重新只读检查三台主机，simurgh 与 kaiju 不满足空闲阈值，自动选择 iverson GPU 0；启动 vLLM PID 252137 并重建本机 18001 SSH 隧道。
- 验证结果：1 个内联脚本通过 Node 语法检查，28 项翻译/访问控制/导航聚焦测试全部通过；Playwright 真实浏览器完成“刷新页面 → 选择本机 PDF → 开始按钮解锁 → 手动重新检查模型后仍保持可用”，未提交新任务。截图保存于 `output/playwright/paper-translation-fixed.png`。

## 9. 独立科研工具入口与语音扩展路线（2026-07-21）

- 信息架构：翻译不再归入“ABDC 商科研究”，而是独立放入一级“科研工具”；页面显示名改为“学术语言工作台”。既有 `/paper-translation` 路由、API、任务目录和检查点全部保持，避免破坏书签与正在运行的任务。
- 当时边界（已由下一节取代）：只启用“文档翻译”，不显示不可用的语音按钮，也不下载或部署新的语音模型。
- 第一阶段建议做“音频转写”：本地解码音频，保存带时间戳的原文转写、语言检测、模型版本、输入哈希和分段检查点。
- 第二阶段复用现有文本翻译护栏：按时间段翻译转写文本，保护数字、术语和专名，并输出原文/译文对齐的 TXT、JSON、SRT 与 VTT。
- 第三阶段再评估语音输出：默认生成普通合成语音，不默认启用声音克隆；原音频、转写、译文和合成结果分目录保存，并明确记录用户是否允许音频通过 SSH 发送到校内 GPU。
- 技术路线优先采用“ASR → 可审阅文本 → 翻译 → 可选 TTS”的可审计流水线；端到端语音到语音模型只作为后续对照实验，不替代可检查的中间文本。
- 现场验证：共享导航脚本与主页/工作台内联脚本均通过 Node 语法检查，翻译、访问控制与导航共 29 项聚焦测试通过；Playwright 验证了主页独立“科研工具”区域、顶部第四入口、工作台高亮、站内搜索归类和响应式版面。调整期间任务 `ebcbb19901fe4bd9bf0ace1b0f4a2092` 从 17/292 继续推进到 44/292，无报错、无服务重启。

## 10. 语音路线已落地（2026-07-21）

语音能力现以独立 `/audio-transcription` 页面交付，不改变文档翻译路由、任务目录或输出。已复用 nobackup 中的
faster-whisper-medium 和 pyannote Community-1，形成“逐词 ASR → 匿名说话人对齐 → 可选逐轮 Qwen 翻译 →
原文/译文/双语字幕”的可审计流水线；真实双合成说话人端到端 smoke、追加翻译、远端清理、时间轴一致性和浏览器交互均已通过。
完整版本、隐私边界、命令、API 与验证证据见
[audio_transcription_STATUS_2026-07-21.md](audio_transcription_STATUS_2026-07-21.md)。
