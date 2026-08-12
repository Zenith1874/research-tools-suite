# 文章原文问答实现状态（2026-07-24）

## 目标与边界

在现有“学术语言工作台”内，为已完成的 PDF、DOCX、TXT 和 Markdown 任务增加多轮文章问答。
问答以原文件为唯一证据来源，不把模型生成的译文或总结当作事实依据，也不拆出新的独立模块。

## 实现

- 已完成任务显示“问这篇文章”，同一任务卡内查看历史并继续追问。
- PDF 证据保留页码和最近章节标题；DOCX、TXT、Markdown 保留章节或正文段落位置。
- 原文按有限字符块提取并在本机缓存；参考文献列表不作为正文主张证据。
- 中文问题检索英文论文时，仅扩展样本、访谈、方法、测量、因果、结果、理论等受控学术概念。
- 模型只接收本轮检索出的有限原文块和最近四轮对话；历史回答仅提供对话上下文，不是证据。
- 模型必须返回已知证据编号；未知、重复或未在回答正文中标注的编号会硬失败。
- 原文件 SHA-256 改变后停止问答，避免旧证据缓存与新文件混用。
- 每轮保存问题、回答、证据位置与摘录、模型、提示版本、置信度和输入哈希到任务目录
  `questions.jsonl`；全文证据缓存和问答记录均保持本机、默认仅回环地址可访问。

## API

- `GET /api/translation/jobs/<job_id>/questions`：读取本机问答历史。
- `POST /api/translation/jobs/<job_id>/questions`：提交 `{"question":"..."}` 并返回带原文引用的回答。

两个接口均复用翻译模块的本机访问限制，并返回 `Cache-Control: no-store, private`。

## 验证

```powershell
python.exe -m py_compile services/paper_summary_service.py services/paper_translation_service.py server.py
python.exe -m unittest tests.test_paper_summary tests.test_paper_translation tests.test_server_access_security -v
python.exe -m unittest discover -s tests -v
```

聚焦回归覆盖：Markdown 章节定位、PDF 页码、参考文献排除、中英跨语言检索、未知证据拒绝、
证据不足、多轮本机保存和原文件哈希保护。

实际验证结果：

- Python 编译通过；页面内联 JavaScript 由 Node.js 语法解析通过。
- 聚焦回归 74 项通过；全项目回归 264 项通过，0 failure、0 error。
- 服务经既有看门狗安全重启；页面、健康接口、问答历史接口均返回 HTTP 200。
- 使用临时合成 Markdown 完成真实本地 Qwen 端到端：问题“这个研究的样本是多少？”返回
  Methods 证据 `The sample contains 84 longitudinal interviews.`、证据编号 `E0001` 和 high 置信度；
  临时任务由 `TemporaryDirectory` 自动清理，未写入正式任务目录。
- 浏览器自动截图验收受当前 Codex/WSL 浏览器连接的工作区 URI 错误阻塞；页面 HTML、API、
  交互脚本语法和真实模型链路已验证，但本次不声称完成浏览器视觉验收。

## 已知限制

- 当前检索是本机确定性词项与受控中英概念扩展，不是全库向量检索；隐含语义较强的问题可能需要换一种问法。
- 回答引用的是抽取到的文本区域。表格线内文字、扫描型 PDF、公式和抽取器明确排除的区域仍不进入问答证据。
- “置信度”描述的是当前检索证据对回答的支持程度，不代表论文结论本身正确，也不替代回查原文。

## 2026-07-25 真实论文追问修复

- 修复带编号的参考文献标题（如 `7. References`）未被识别的问题；提示版本升级后，旧证据缓存会按原文自动重建，历史问答不删除。
- “方法”类中文问题增加对 model、simulation、ABM、reinforcement learning 等方法描述词的受控检索扩展，支持方法内容未置于 `Methods` 标题下的论文。
- 当前问题与最近两轮上下文分开计分：当前问题优先，上下文仅以较低权重辅助理解省略式追问，避免旧问题固定后续证据。
- 问答提示明确要求重新核对型追问必须重评证据，不得仅复述历史回答。
- 新增编号参考文献排除、非标准方法章节命中、跨主题追问切换三项回归测试。
- 修复 Windows `pythonw` 的精简 PATH 下找不到系统 `ssh.exe` 和 `powershell.exe` 的问题；看门狗会从 Windows 系统目录安全回退，保证模型隧道和服务重启可恢复。
- 验证：问答相关 60 项和全项目 266 项测试通过。真实问题 PDF 重建后得到 58 个正文证据块、0 个参考文献块；“方法都写了什么”将第 4 页 `Figure 1. ABM model` 与模型行为段落排在前两位。
- 真实 Qwen 端到端复测在保留原有重复对话上下文的情况下，改为说明任务类型、三种策略、反馈和强化学习更新流程，并引用 `E0028`、`E0027`，未再复述“方法没有详细描述”。该复测直接调用模型且未写入用户问答历史。
