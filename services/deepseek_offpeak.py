# -*- coding: utf-8 -*-
"""DeepSeek 优惠时段 gating for batch LLM work.

DeepSeek meters v4 by wall clock: standard hours cost exactly twice off-peak.
Standard hours are Beijing time Mon-Fri 09:00-12:00 and 14:00-18:00, which is
UTC 01:00-04:00 and 06:00-10:00 on the same weekday -- Beijing is UTC+8, so both
windows sit inside one Beijing day and the UTC weekday matches the Beijing one.
Everything else bills at half price: 17 hours of every weekday, and both weekend
days in full.

    deepseek-v4-flash   输入(缓存未命中)   ¥1.5/M 优惠   ¥3.0/M 标准
                        输出               ¥4.5/M 优惠   ¥9.0/M 标准

The gap only matters at volume. The daily 150-article pass is ¥0.23 either way.
Draining the 23,621-article uncertain backlog is ¥36 off-peak against ¥73 in
standard hours, and at the measured 1.8s per article it runs 11.8 hours -- long
enough to start off-peak and finish inside a standard window. So the check
belongs in the batch loop, once per item, rather than around a single HTTP call:
a long run has to notice the rate changing under it, not just at the start.

Interactive callers must not wait. A button press that silently sleeps four
hours is worse than paying double, so waiting is opt-in and off by default.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

LOG = logging.getLogger(__name__)

# UTC hour ranges, Monday-Friday, billed at the standard (double) rate.
STANDARD_WINDOWS_UTC = ((1, 4), (6, 10))

# What a caller may ask for before each billable call.
MODES = ('wait', 'stop', 'off')

# A wait logs this often, so a paused batch stays visible in the log.
WAIT_LOG_INTERVAL = 600.0

# DeepSeek documents the standard hours as "北京时间周一至周五 9:00 - 12:00、
# 14:00 - 18:00（其余为空闲时段）" and says nothing about whether the endpoints
# are inclusive -- whether 12:00:00 Beijing sharp still bills at the standard
# rate is simply not stated.  The predicates below read the ranges as
# left-closed, right-open, which is the natural reading of a 12:00-14:00 lunch
# gap, but a wait that resumes on the exact second gambles on that reading.
# Starting a moment later does not: 60 seconds costs at most 33 articles' worth
# of delay and removes the question.
SAFETY_MARGIN = 60.0


def _utc(now=None):
    """Naive datetimes are read as UTC; the windows are only defined there."""
    if now is None:
        return datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _hour_of_day(now):
    return now.hour + now.minute / 60.0 + now.second / 3600.0


def normalize_mode(value):
    """Validate an off-peak policy name. None and '' mean no gating.

    A typo must not silently degrade into paying the standard rate, which is the
    failure this module exists to prevent, so an unknown mode raises instead of
    falling through to 'off'.
    """
    mode = (value or 'off').strip().lower()
    if mode not in MODES:
        raise ValueError(f"未知的 offpeak 模式 {value!r}，可选：{', '.join(MODES)}")
    return mode


def is_offpeak(now=None):
    """True when DeepSeek bills the 优惠时段 (half) rate."""
    now = _utc(now)
    if now.weekday() >= 5:            # Saturday and Sunday are off-peak in full
        return True
    hour = _hour_of_day(now)
    return not any(lo <= hour < hi for lo, hi in STANDARD_WINDOWS_UTC)


def seconds_until_offpeak(now=None):
    """Seconds until the standard window covering ``now`` ends; 0 if off-peak."""
    now = _utc(now)
    if is_offpeak(now):
        return 0.0
    hour = _hour_of_day(now)
    for lo, hi in STANDARD_WINDOWS_UTC:
        if lo <= hour < hi:
            return (hi - hour) * 3600.0
    return 0.0


def next_standard_start(now=None):
    """When the next standard-rate window opens (UTC), or None within a week."""
    now = _utc(now)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for day in range(9):
        date = midnight + timedelta(days=day)
        if date.weekday() >= 5:
            continue
        for lo, _ in STANDARD_WINDOWS_UTC:
            opens = date + timedelta(hours=lo)
            if opens > now:
                return opens
    return None


def offpeak_seconds_left(now=None):
    """Uninterrupted off-peak seconds from ``now``; 0 during standard hours.

    This is what tells a long batch whether it fits without the rate changing
    halfway: the Friday 10:00 UTC to Monday 01:00 UTC block is 63 hours, room
    for the 11.8-hour backlog drain several times over.
    """
    now = _utc(now)
    if not is_offpeak(now):
        return 0.0
    opens = next_standard_start(now)
    return (opens - now).total_seconds() if opens else float('inf')


def wait_for_offpeak(sleeper=time.sleep, clock=None, margin=None):
    """Block until the off-peak rate applies. Returns the seconds waited.

    Waits past the boundary by ``SAFETY_MARGIN`` (see above): resuming on the
    exact second bets on an endpoint convention DeepSeek never published.
    Already being off-peak returns immediately -- the margin guards the
    crossing, and there is nothing to guard once we are inside.

    Sleeps in ``WAIT_LOG_INTERVAL`` chunks so a batch paused for up to four
    hours says so in the log rather than looking hung.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    margin = SAFETY_MARGIN if margin is None else margin
    now = clock()
    if is_offpeak(now):
        return 0.0
    # 目标时刻一次算定：中途机器休眠或时钟跳变时，绝对时刻仍然正确。
    target = now + timedelta(seconds=seconds_until_offpeak(now) + margin)
    LOG.info('DeepSeek 标准时段（2 倍价），暂停到 %s（含 %.0f 秒安全边际）',
             target.strftime('%m-%d %H:%M:%S UTC'), margin)
    waited = 0.0
    while True:
        remaining = (target - clock()).total_seconds()
        if remaining <= 0:
            return waited
        chunk = min(remaining, WAIT_LOG_INTERVAL)
        LOG.info('仍在等优惠时段，还有 %.1f 分钟', remaining / 60.0)
        sleeper(chunk)
        waited += chunk


def describe(now=None):
    """One line for logs and API replies: which rate applies and for how long."""
    now = _utc(now)
    if is_offpeak(now):
        left = offpeak_seconds_left(now)
        return f'优惠时段（半价），还剩 {left / 3600.0:.1f} 小时'
    return f'标准时段（2 倍价），还有 {seconds_until_offpeak(now) / 3600.0:.1f} 小时转入优惠时段'
