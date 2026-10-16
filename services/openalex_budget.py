# -*- coding: utf-8 -*-
"""Shared OpenAlex rate-limit and daily-budget handling.

OpenAlex meters by daily credits; account authentication raises the anonymous
allowance. The response headers report the actual budget, reset at midnight UTC,
after which requests return 429 with a
``Retry-After`` pointing at the reset:

    x-ratelimit-limit: 1000
    x-ratelimit-remaining: 0
    Retry-After: 60561
    {"error":"Rate limit exceeded","message":"Insufficient budget. This request
     costs $0.0001 but you only have $0 remaining. Resets at midnight UTC."}

Two refusals wear the same 429 status and must be handled differently:

* a **burst limit** carries a short ``Retry-After``; wait the interval the server
  states and retry.
* an **exhausted daily budget** carries a ``Retry-After`` of hours. Waiting is
  not backoff, it is sleeping until tomorrow. The caller has to stop asking.

Both the A* radar and the affiliation backfill share this budget, so once one
caller sees exhaustion every other OpenAlex call in the same run is doomed.
``BudgetState`` carries that fact across a run so a loop over 219 journals does
not spend 219 more requests discovering it one journal at a time.
"""

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

LOG = logging.getLogger(__name__)

_SOURCE_SETTINGS_PATH = Path(__file__).resolve().parents[1] / '.secrets'


def openalex_headers(url, headers=None):
    """Attach the local key only to HTTPS requests to the OpenAlex API.

    CLI updates and an already-running service can read the same local setting.
    Only this setting is consumed; other local credentials are never loaded.
    Authentication stays in the header rather than URLs or saved parameters.
    """
    result = dict(headers or {})
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'api.openalex.org':
        return result
    if any(name.lower() == 'authorization' for name in result):
        return result
    key = os.environ.get('OPENALEX_API_KEY', '').strip()
    if not key:
        try:
            for line in _SOURCE_SETTINGS_PATH.read_text(encoding='utf-8-sig').splitlines():
                if '=' not in line or line.lstrip().startswith('#'):
                    continue
                name, value = line.split('=', 1)
                if name.strip() == 'OPENALEX_API_KEY':
                    key = value.strip().strip('\"\'')
                    break
        except OSError:
            pass
    if key:
        result['Authorization'] = 'Bearer ' + key
    return result

# A Retry-After longer than this means the daily budget is gone rather than a
# burst limit needing to be ridden out.
BUDGET_RESET_THRESHOLD = 900.0
# How many times one request waits out a burst limit before giving up.
MAX_RATE_LIMIT_RETRIES = 5


class RateLimited(RuntimeError):
    """OpenAlex refused a request for rate or budget reasons."""

    def __init__(self, retry_after=None, remaining=None, limit=None, message=None):
        super().__init__(f"429 Too Many Requests (Retry-After={retry_after})")
        self.retry_after = retry_after
        self.remaining = remaining
        self.limit = limit
        self.message = message

    @property
    def budget_exhausted(self):
        """True when waiting would mean sleeping until the daily reset."""
        try:
            return float(self.retry_after) > BUDGET_RESET_THRESHOLD
        except (TypeError, ValueError):
            return False

    def wait_seconds(self, attempt=0, base_delay=1.0):
        """How long to wait before retrying a burst limit.

        An explicit ``Retry-After`` is the server stating what it wants, so it
        wins over our own exponential guess.
        """
        if self.retry_after is not None:
            try:
                return min(300.0, max(0.0, float(self.retry_after)))
            except (TypeError, ValueError):
                pass
        return base_delay * (2 ** attempt)

    def describe(self):
        return (f"OpenAlex daily budget exhausted (limit={self.limit}, "
                f"remaining={self.remaining}, resets in {self.retry_after}s)"
                if self.budget_exhausted else
                f"OpenAlex rate limited (Retry-After={self.retry_after}s)")


def raise_for_rate_limit(response):
    """Turn a 429 response into a typed RateLimited. Other statuses pass through."""
    if getattr(response, 'status_code', 200) != 429:
        return
    headers = getattr(response, 'headers', {}) or {}
    try:
        message = (response.json() or {}).get('message')
    except Exception:
        message = None
    raise RateLimited(headers.get('Retry-After'),
                      remaining=headers.get('x-ratelimit-remaining'),
                      limit=headers.get('x-ratelimit-limit'),
                      message=message)


class BudgetState:
    """Remembers, for one run, that the OpenAlex daily budget is spent.

    Without this a caller rediscovers exhaustion on every iteration and pays a
    request each time. With it the first refusal is the last request.
    """

    def __init__(self):
        self.exhausted = False
        self.detail = None
        self.skipped_calls = 0

    def note(self, exc):
        """Record a RateLimited. Returns True when the budget is gone."""
        if isinstance(exc, RateLimited) and exc.budget_exhausted:
            if not self.exhausted:
                LOG.warning("%s; skipping further OpenAlex calls this run", exc.describe())
            self.exhausted = True
            self.detail = exc.describe()
            return True
        return False

    def should_skip(self):
        """True when an OpenAlex call would certainly be refused."""
        if self.exhausted:
            self.skipped_calls += 1
            return True
        return False

    def as_dict(self):
        return {'openalex_budget_exhausted': self.exhausted,
                'openalex_budget_detail': self.detail,
                'openalex_calls_skipped': self.skipped_calls}


__all__ = ['BudgetState', 'RateLimited', 'raise_for_rate_limit',
           'BUDGET_RESET_THRESHOLD', 'MAX_RATE_LIMIT_RETRIES', 'openalex_headers']
