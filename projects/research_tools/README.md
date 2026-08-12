# 科研语言与语音工具

项目 ID：research_tools

该域拥有 /paper-translation 和 /audio-transcription。源码、格式校验、匿名说话人规则、检查点 schema 与合成测试夹具可进入 Git；论文原件、访谈录音、译文、转录、远端暂存状态和本机任务清单必须留在私有层。

远端模型只接收完成本机预处理后的必要文本或临时音频任务；SSH 密钥、HF token、API key 和邮件密码不得写入代码、日志、API 或 Git。

最低验证：

    python.exe -m unittest discover -s tests -p "test_paper*.py" -q
    python.exe -m unittest discover -s tests -p "test_audio*.py" -q
