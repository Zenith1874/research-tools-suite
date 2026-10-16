# -*- coding: utf-8 -*-
"""共用的 DeepSeek 请求构造。

这些断言存在的理由很具体：thinking 没关掉时 v4-flash 会用推理 token 吃光
max_tokens，content 返回空，请求照常计费，而调用端只看到"回复里没有 JSON"。
每一层都不报错，所以它在两个调用点里活到了 2026-09-05。测试要盯的就是这个。
"""

import unittest
from unittest.mock import MagicMock, patch

from services import deepseek_client as dc


class BodyTests(unittest.TestCase):
    def test_thinking_is_always_disabled(self):
        body = dc.build_body('sys', 'user')
        self.assertEqual({'type': 'disabled'}, body.get('thinking'),
                         '开着思考模式会烧完 max_tokens 并返回空 content，且照常计费')

    def test_json_object_is_requested_by_default(self):
        self.assertEqual({'type': 'json_object'}, dc.build_body('s', 'u')['response_format'])

    def test_json_object_can_be_turned_off(self):
        self.assertNotIn('response_format', dc.build_body('s', 'u', json_object=False))

    def test_model_defaults_to_the_live_one(self):
        # deepseek-chat 于 2026-07-24 退役；默认值只该有这一处。
        self.assertEqual('deepseek-v4-flash', dc.build_body('s', 'u')['model'])
        self.assertEqual('deepseek-v4-pro', dc.build_body('s', 'u', model='deepseek-v4-pro')['model'])

    def test_caller_controls_budget_and_temperature(self):
        body = dc.build_body('s', 'u', max_tokens=200, temperature=0.7)
        self.assertEqual(200, body['max_tokens'])
        self.assertEqual(0.7, body['temperature'])

    def test_messages_carry_system_then_user(self):
        body = dc.build_body('SYS', 'USR')
        self.assertEqual([{'role': 'system', 'content': 'SYS'},
                          {'role': 'user', 'content': 'USR'}], body['messages'])


def ok(content='{"a": 1}'):
    r = MagicMock()
    r.json.return_value = {'choices': [{'message': {'content': content}}]}
    r.raise_for_status.return_value = None
    return r


class ChatTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'k'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_reply_text_and_sends_the_invariants(self):
        with patch.object(dc.requests, 'post', return_value=ok()) as post:
            self.assertEqual('{"a": 1}', dc.chat('s', 'u'))
        sent = post.call_args.kwargs['json']
        self.assertEqual({'type': 'disabled'}, sent['thinking'])
        self.assertEqual('Bearer k', post.call_args.kwargs['headers']['Authorization'])

    def test_retries_then_succeeds(self):
        with patch.object(dc.requests, 'post',
                          side_effect=[RuntimeError('boom'), ok('{}')]) as post, \
             patch.object(dc.time, 'sleep'):
            self.assertEqual('{}', dc.chat('s', 'u', retries=1))
        self.assertEqual(2, post.call_count)

    def test_raises_the_last_error_when_retries_run_out(self):
        with patch.object(dc.requests, 'post', side_effect=RuntimeError('boom')), \
             patch.object(dc.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                dc.chat('s', 'u', retries=2)

    def test_no_retry_by_default(self):
        with patch.object(dc.requests, 'post', side_effect=RuntimeError('boom')) as post:
            with self.assertRaises(RuntimeError):
                dc.chat('s', 'u')
        self.assertEqual(1, post.call_count)


class BalanceTests(unittest.TestCase):
    def test_returns_none_without_a_key_rather_than_guessing(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertIsNone(dc.balance_cny())

    def test_reads_the_cny_row(self):
        r = MagicMock()
        r.json.return_value = {'balance_infos': [{'currency': 'USD', 'total_balance': '0.00'},
                                                 {'currency': 'CNY', 'total_balance': '84.86'}]}
        r.raise_for_status.return_value = None
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'k'}), \
             patch.object(dc.requests, 'get', return_value=r):
            self.assertEqual(84.86, dc.balance_cny())

    def test_a_failed_lookup_is_none_not_an_exception(self):
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'k'}), \
             patch.object(dc.requests, 'get', side_effect=RuntimeError('down')):
            self.assertIsNone(dc.balance_cny())


if __name__ == '__main__':
    unittest.main()
