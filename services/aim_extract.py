# -*- coding: utf-8 -*-
"""兴趣匹配的 DeepSeek 结构化抽取：一次调用同时产出
(a) 与画像无关的论文基础标签，(b) 对每个启用画像的多维分。

数据纪律：temperature=0 可复现；证据必须引摘要原文片段；信息不足置 uncertainty。
"""
import hashlib
import json
import os
import re
import time

import requests

DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'
PROMPT_VERSION = 'aim-v1'

BASE_LABEL_INSTR = (
    "你是资深管理学/组织行为文献分析员。只依据给出的期刊名、标题、摘要判断，"
    "不得臆测；信息不足时相应字段留空并把 uncertainty 设为 true。"
    "所有标签用简短英文短语。evidence_spans 必须是摘要里的原文片段(逐字)，"
    "作为你判断的依据；没有摘要时 evidence_spans 为空且 uncertainty=true。"
)

LABEL_FIELDS = (
    "research_topics(研究主题, 如 remote work / algorithmic management), "
    "constructs(核心构念, 如 autonomy/burnout/turnover/trust), "
    "theories(理论, 如 JD-R/TAM/institutional theory), "
    "methods(方法, 如 experiment/survey/panel/DiD/event study/text analysis/machine learning/SEM/qualitative), "
    "data_sources(数据来源, 如 survey/interview/Glassdoor/Reddit/social media/job postings/archival), "
    "settings(研究场景, 如 remote work/platform labor/healthcare/hospitality/manufacturing/knowledge work), "
    "analysis_levels(分析层级: individual/team/organization/industry/platform), "
    "country(国家/地区, 无则空), time_range(时间范围, 无则空), "
    "research_question(一句英文), key_findings(一句英文), "
    "evidence_spans(摘要原文片段数组), uncertainty(布尔)"
)


def _dims_desc(profile):
    a = profile.get('aspects', {})
    parts = []
    for d in ('topic', 'theory', 'method', 'data', 'setting'):
        vals = a.get(d) or []
        if vals:
            parts.append(f"{d}: " + " | ".join(vals))
    return "\n".join(parts)


def build_messages(article, profiles):
    prof_blocks = []
    for p in profiles:
        prof_blocks.append(
            f"[{p['profile_id']}] {p.get('name','')}: {p.get('description','')}\n"
            f"该画像各维关注点:\n{_dims_desc(p)}")
    profiles_text = "\n\n".join(prof_blocks)
    ids = ", ".join(p['profile_id'] for p in profiles)
    sys = (
        f"{BASE_LABEL_INSTR}\n\n"
        f"第一部分：抽取论文基础标签，字段为 labels 对象，含：{LABEL_FIELDS}。\n\n"
        f"第二部分：针对下列每个研究画像，给 0-100 的六维匹配分并说明。画像:\n{profiles_text}\n\n"
        "六维含义：topic(主题贴合)、theory(理论可用/贴合)、method(方法贴合或可借鉴)、"
        "data(数据来源贴合)、setting(研究场景贴合)、opportunity(对该画像的研究机会/理论迁移/方法借鉴潜力，"
        "即使主题不同但能给该项目启发则高)。rationale 用一句中文点出关键证据。\n\n"
        "严格只输出一个 JSON 对象："
        '{"labels": {...上述字段...}, '
        f'"profiles": {{ "<profile_id>": {{"topic":int,"theory":int,"method":int,"data":int,'
        '"setting":int,"opportunity":int,"rationale":"一句中文"}}, ... }} }}。'
        f"profiles 的键必须是且仅是: {ids}。不要输出 JSON 以外任何内容。"
    )
    abstract = article.get('abstract') or ''
    user = (f"期刊: {article.get('journal_title','')}\n"
            f"标题: {article.get('title','')}\n"
            f"发表: {article.get('publication_date','')}\n"
            f"摘要: {abstract[:2500] if abstract else '(无摘要，仅凭标题与期刊保守判断，uncertainty=true)'}")
    return sys, user


def prompt_hash(profiles):
    ids = ",".join(sorted(p['profile_id'] for p in profiles))
    return hashlib.sha256((PROMPT_VERSION + '|' + ids + '|' + BASE_LABEL_INSTR).encode()).hexdigest()[:16]


def extract_one(article, profiles, model='deepseek-chat', timeout=90, retries=2):
    sys, user = build_messages(article, profiles)
    body = {'model': model, 'max_tokens': 1400, 'temperature': 0.0,
            'response_format': {'type': 'json_object'},
            'messages': [{'role': 'system', 'content': sys},
                         {'role': 'user', 'content': user}]}
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(DEEPSEEK_URL, headers={
                'Authorization': f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                'Content-Type': 'application/json'}, json=body, timeout=timeout)
            r.raise_for_status()
            text = r.json()['choices'][0]['message']['content']
            m = re.search(r'\{.*\}', text, re.DOTALL)
            return json.loads(m.group(0)) if m else None
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last
