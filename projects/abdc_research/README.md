# ABDC 商科研究

项目 ID：abdc_research

该域拥有 /abdc 和 /abdc-astar-research，包括期刊列表、文章增量、来源健康检查、研究兴趣分类、语义检索和调试审计。

公开 Git 可包含代码、测试、期刊元数据快照、分类 schema 和不含受限正文的状态说明。以下材料只进入私有快照：

- 原始 ABDC xlsx；
- 文章数据库与嵌入；
- 出版社摘要正文 override；
- 授权 API 探测、逐条 publisher 报告和全量扫描结果。

摘要状态必须区分元数据可访问、公开摘要可访问、授权受限和实际已补录，不通过验证码、登录或权限限制。

最低验证：

    python.exe -m unittest discover -s tests -p "test_astar*.py" -q
    python.exe -m unittest discover -s tests -p "test_aim*.py" -q
