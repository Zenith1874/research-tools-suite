# -*- coding: utf-8 -*-
"""One place that knows how to talk to DeepSeek, because the invariants keep
getting lost.

Four call sites grew their own request bodies -- article classification, AIM
extraction, the classification audit, and visa reading -- and two of them
shipped without ``thinking: disabled``.

That omission is expensive and silent. ``deepseek-v4-flash`` reasons by
default; the reasoning tokens spend the whole ``max_tokens`` budget before any
answer is written, so ``content`` comes back empty. The request is billed in
full. The caller sees only "no JSON object in the reply" and counts a parse
failure, which looks like a model quirk rather than a configuration bug. It
survived in two places until 2026-09-05, and was found only because a visa run
returned 3 empty replies out of 20.

The other invariant worth centralising is ``response_format``: every caller
here wants JSON, and asking for it is what keeps the reply parseable.

Anything about *how* to reach DeepSeek lives here. What to ask, and what to do
with the answer, stays with the caller -- this module never parses, validates,
or interprets a reply.
"""

import logging
import os
import time

import requests

LOG = logging.getLogger(__name__)

URL = 'https://api.deepseek.com/chat/completions'
BALANCE_URL = 'https://api.deepseek.com/user/balance'

# 旧名 deepseek-chat 于 2026-07-24 退役；别在别处再写一份字面量。
MODEL_DEFAULT = 'deepseek-v4-flash'


def available():
    return bool(os.environ.get('DEEPSEEK_API_KEY'))


def _headers():
    return {'Authorization': 'Bearer %s' % os.environ['DEEPSEEK_API_KEY'],
            'Content-Type': 'application/json'}


def build_body(system, user, model=None, max_tokens=700, temperature=0.0,
               json_object=True):
    """The request body, with the two invariants applied.

    Exposed separately so a test can assert on what would be sent without
    reaching the network.
    """
    body = {
        'model': model or MODEL_DEFAULT,
        'max_tokens': max_tokens,
        'temperature': temperature,
        # 不是可选项：开着思考模式，推理 token 会吃光 max_tokens，content 返回空，
        # 而请求照常计费。见模块开头。
        'thinking': {'type': 'disabled'},
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': user}],
    }
    if json_object:
        body['response_format'] = {'type': 'json_object'}
    return body


def chat(system, user, model=None, max_tokens=700, temperature=0.0,
         timeout=60, retries=0, json_object=True):
    """Send one prompt, return the reply text. Raises the last error if all
    attempts fail.

    ``retries`` retries the whole call on any exception, backing off 1.5s per
    attempt -- the shape aim_extract already used.
    """
    body = build_body(system, user, model, max_tokens, temperature, json_object)
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(URL, headers=_headers(), json=body, timeout=timeout)
            r.raise_for_status()
            return r.json()['choices'][0]['message']['content']
        except Exception as exc:
            last = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last


def balance_cny():
    """账户人民币余额；查询本身不计费。取不到返回 None，不猜。"""
    if not available():
        return None
    try:
        r = requests.get(BALANCE_URL, headers={'Authorization': _headers()['Authorization']},
                         timeout=20)
        r.raise_for_status()
        for info in r.json().get('balance_infos', []):
            if info.get('currency') == 'CNY':
                return float(info['total_balance'])
    except Exception as exc:
        LOG.warning('余额查询失败(不影响调用): %s', exc)
    return None
