"""
顶刊清单：FT50（Financial Times，2026 版）与 UTD24（UT Dallas）。

只存期刊标题；ISSN 在运行时通过匹配 ABDC 主表（data/abdc_data.json，含全部 2651 刊的 ISSN）
解析得到，避免硬编码 ISSN 出错。匹配用宽松归一化（&→and、去前导 the、去标点）。

FT50 2026 更新：移除 Human Relations / Journal of Business Ethics / Organization Studies；
新增 Academy of Management Annals / American Sociological Review / Psychological Science。
"""
import re

# ── FT50（Financial Times Research Rank，2026 版，50 种）────────────────────
FT50 = [
    "Academy of Management Annals",
    "Academy of Management Journal",
    "Academy of Management Review",
    "Accounting, Organizations and Society",
    "The Accounting Review",
    "Administrative Science Quarterly",
    "American Economic Review",
    "American Sociological Review",
    "Contemporary Accounting Research",
    "Econometrica",
    "Entrepreneurship Theory and Practice",
    "Harvard Business Review",
    "Human Resource Management",
    "Information Systems Research",
    "Journal of Accounting and Economics",
    "Journal of Accounting Research",
    "Journal of Applied Psychology",
    "Journal of Business Venturing",
    "Journal of Consumer Psychology",
    "Journal of Consumer Research",
    "Journal of Finance",
    "Journal of Financial and Quantitative Analysis",
    "Journal of Financial Economics",
    "Journal of International Business Studies",
    "Journal of Management",
    "Journal of Management Information Systems",
    "Journal of Management Studies",
    "Journal of Marketing",
    "Journal of Marketing Research",
    "Journal of Operations Management",
    "Journal of the Academy of Marketing Science",
    "Management Science",
    "Manufacturing and Service Operations Management",
    "Marketing Science",
    "MIS Quarterly",
    "MIT Sloan Management Review",
    "Operations Research",
    "Organization Science",
    "Organizational Behavior and Human Decision Processes",
    "Production and Operations Management",
    "Psychological Science",
    "Quarterly Journal of Economics",
    "Research Policy",
    "Review of Accounting Studies",
    "Review of Economic Studies",
    "Review of Finance",
    "Review of Financial Studies",
    "Strategic Entrepreneurship Journal",
    "Strategic Management Journal",
    "Journal of Political Economy",
]

# ── UTD24（UT Dallas Top 100 Business School Research Rankings，24 种）───────
UTD24 = [
    "The Accounting Review",
    "Journal of Accounting and Economics",
    "Journal of Accounting Research",
    "Journal of Finance",
    "Journal of Financial Economics",
    "Review of Financial Studies",
    "Academy of Management Journal",
    "Academy of Management Review",
    "Administrative Science Quarterly",
    "Organization Science",
    "Journal of International Business Studies",
    "Strategic Management Journal",
    "Journal of Consumer Research",
    "Journal of Marketing",
    "Journal of Marketing Research",
    "Marketing Science",
    "Information Systems Research",
    "MIS Quarterly",
    "Journal of Operations Management",
    "Management Science",
    "Manufacturing and Service Operations Management",
    "Operations Research",
    "Production and Operations Management",
    "INFORMS Journal on Computing",
]


def match_norm(s):
    """用于清单↔ABDC 标题匹配的宽松归一化。"""
    if not s:
        return ''
    s = s.lower().strip()
    s = s.replace('&', ' and ')
    s = re.sub(r'^the\s+', '', s)        # 去前导 the
    s = re.sub(r'[^a-z0-9]', ' ', s)     # 标点→空格
    s = re.sub(r'\s+', ' ', s).strip()
    return s
