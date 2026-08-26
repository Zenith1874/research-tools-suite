# -*- coding: utf-8 -*-
"""OpenAlex meters by daily budget, and two different refusals share status 429.

A burst limit is worth waiting out. An exhausted daily budget is not: the wait is
until midnight UTC, so the only correct response is to stop asking. These tests
pin that distinction and the run-level state that keeps a loop from rediscovering
exhaustion once per iteration.
"""

from types import SimpleNamespace
import unittest

from services.openalex_budget import (
    BudgetState,
    RateLimited,
    raise_for_rate_limit,
)


def response(status=200, headers=None, payload=None):
    return SimpleNamespace(status_code=status, headers=headers or {},
                           json=lambda: payload or {})


BUDGET_HEADERS = {'Retry-After': '60561', 'x-ratelimit-limit': '1000',
                  'x-ratelimit-remaining': '0'}
BUDGET_BODY = {'error': 'Rate limit exceeded',
               'message': 'Insufficient budget. Resets at midnight UTC'}


class RateLimitClassificationTests(unittest.TestCase):
    def test_non_429_passes_through(self):
        self.assertIsNone(raise_for_rate_limit(response(200)))
        self.assertIsNone(raise_for_rate_limit(response(503)))

    def test_429_becomes_typed_error_carrying_the_headers(self):
        with self.assertRaises(RateLimited) as caught:
            raise_for_rate_limit(response(429, BUDGET_HEADERS, BUDGET_BODY))
        exc = caught.exception
        self.assertEqual('60561', exc.retry_after)
        self.assertEqual('1000', exc.limit)
        self.assertEqual('0', exc.remaining)
        self.assertIn('Insufficient budget', exc.message)

    def test_long_retry_after_is_budget_exhaustion(self):
        with self.assertRaises(RateLimited) as caught:
            raise_for_rate_limit(response(429, BUDGET_HEADERS, BUDGET_BODY))
        self.assertTrue(caught.exception.budget_exhausted)
        self.assertIn('daily budget exhausted', caught.exception.describe())

    def test_short_retry_after_is_a_burst_limit(self):
        with self.assertRaises(RateLimited) as caught:
            raise_for_rate_limit(response(429, {'Retry-After': '2'}))
        self.assertFalse(caught.exception.budget_exhausted)
        self.assertIn('rate limited', caught.exception.describe())

    def test_missing_retry_after_is_not_assumed_to_be_budget(self):
        with self.assertRaises(RateLimited) as caught:
            raise_for_rate_limit(response(429, {}))
        self.assertFalse(caught.exception.budget_exhausted)

    def test_unparseable_retry_after_is_not_assumed_to_be_budget(self):
        with self.assertRaises(RateLimited) as caught:
            raise_for_rate_limit(response(429, {'Retry-After': 'Wed, 26 Aug 2026 07:00:00 GMT'}))
        self.assertFalse(caught.exception.budget_exhausted)

    def test_a_broken_json_body_does_not_mask_the_rate_limit(self):
        broken = SimpleNamespace(status_code=429, headers={'Retry-After': '5'},
                                 json=lambda: (_ for _ in ()).throw(ValueError('no json')))
        with self.assertRaises(RateLimited) as caught:
            raise_for_rate_limit(broken)
        self.assertIsNone(caught.exception.message)


class WaitSecondsTests(unittest.TestCase):
    def test_server_stated_interval_wins_over_our_exponential_guess(self):
        exc = RateLimited(retry_after='7')
        self.assertEqual(7.0, exc.wait_seconds(attempt=3, base_delay=1.0))

    def test_explicit_zero_is_honoured_rather_than_rounded_up(self):
        self.assertEqual(0.0, RateLimited(retry_after='0').wait_seconds(attempt=4))

    def test_exponential_backoff_only_when_the_server_says_nothing(self):
        exc = RateLimited(retry_after=None)
        self.assertEqual(1.0, exc.wait_seconds(attempt=0, base_delay=1.0))
        self.assertEqual(4.0, exc.wait_seconds(attempt=2, base_delay=1.0))

    def test_a_wait_is_capped_so_one_request_cannot_stall_a_run(self):
        self.assertEqual(300.0, RateLimited(retry_after='99999').wait_seconds())


class BudgetStateTests(unittest.TestCase):
    def test_a_fresh_run_attempts_openalex(self):
        state = BudgetState()
        self.assertFalse(state.should_skip())
        self.assertFalse(state.exhausted)

    def test_burst_limits_do_not_close_the_run(self):
        state = BudgetState()
        self.assertFalse(state.note(RateLimited(retry_after='3')))
        self.assertFalse(state.should_skip())

    def test_unrelated_errors_do_not_close_the_run(self):
        state = BudgetState()
        self.assertFalse(state.note(RuntimeError('connection reset')))
        self.assertFalse(state.should_skip())

    def test_budget_exhaustion_closes_the_run_and_counts_what_it_saved(self):
        state = BudgetState()
        self.assertTrue(state.note(RateLimited(retry_after='60561', limit='1000', remaining='0')))
        self.assertTrue(state.exhausted)
        for _ in range(218):
            self.assertTrue(state.should_skip())
        summary = state.as_dict()
        self.assertTrue(summary['openalex_budget_exhausted'])
        self.assertEqual(218, summary['openalex_calls_skipped'],
                         "one refusal must cover every remaining journal in the run")
        self.assertIn('resets in 60561s', summary['openalex_budget_detail'])


if __name__ == '__main__':
    unittest.main()
