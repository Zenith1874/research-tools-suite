# 个人归档与按需监控

项目 ID：personal_tools

该域拥有 /yuedu-fm 和 /cardcookie-monitor。Git 保存播放器、同步器、监控器、测试和来源/权利说明；音频、封面、节目文字快照、监控数据库与邮件密码留在私有层。

悦读FM 归档仅供个人本地使用，不重新发布音频、图片或全文。CardCookie 默认关闭，首次检查只建基线；验证页、403 或 429 必须退避，不绕过访问限制。

最低验证：

    python.exe -m unittest discover -s tests -p "test_yuedu*.py" -q
    python.exe -m unittest discover -s tests -p "test_cardcookie*.py" -q
