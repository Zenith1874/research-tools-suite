# -*- coding: utf-8 -*-
"""Which hiring cycle a posting belongs to, derived from when the job starts.

A faculty market runs on the academic year, not the calendar. A post that
begins in Fall 2029 is advertised from roughly summer 2028 and filled by spring
2029: it belongs to the 2028-29 cycle, whatever month we first saw it. Grouping
by calendar year splits one cycle across two buckets and makes every
year-over-year comparison compare halves of different markets.

This replaces a derivation that combined two unrelated facts. The previous
``hiring_cycle`` was ``f"{year we first saw it}-{last two digits of start
year}"``, which produced labels such as ``2026-24`` for a job first seen in
2026 with a 2024 start -- not a cycle, and not sortable as one. Those values
are recomputed by the migration that ships with this module.

The convention, fixed here so the snapshot, the analytics and the UI cannot
drift apart:

    expected_start_year      2029        the job starts then
    market_cycle_start_year  2028        recruiting opened in that academic year
    market_cycle_label       "2028-29"   how it is displayed and sorted

One rule covers every term. Fall 2029 is recruited during AY 2028-29; so is
Spring 2029, which is advertised in the autumn of 2028. Both map to the cycle
beginning 2028.

Absence stays absence. A posting with no stated start is ``unknown`` -- never
placed in the current cycle because that is the likeliest guess.
"""

import re

UNKNOWN = "unknown"

# Terms we recognise in a start field, and whether they belong to the academic
# year that opens in the same calendar year (Fall) or closes in it.
_TERMS = ("fall", "autumn", "spring", "winter", "summer", "january", "august",
          "september")

# A term immediately followed by its year: "Fall 2029", "August 2029",
# "Fall of 2029". The year has to belong to the term -- searching a whole
# excerpt for a term and separately for any four-digit number pairs "Fall
# semester" with a job ID and reports a start in 2000.
_TERM_YEAR_RE = re.compile(
    r"\b(fall|autumn|spring|winter|summer|january|august|september)\b"
    r"[\s,]*(?:of\s+)?(20\d{2})\b",
    re.I,
)
# An explicit start cue followed closely by a year, for postings that give a
# date without naming a term: "The appointment begins in 2029."
_START_CUE_RE = re.compile(
    r"\b(?:start(?:s|ing)?(?:\s+date)?|begin(?:s|ning)?|commenc(?:e|es|ing)|"
    r"effective|appointment\s+(?:date|begins)|available)\b[^.]{0,40}?\b(20\d{2})\b",
    re.I,
)
# "2029-30", "AY 2029-2030" -- an academic year written as a range. The first
# year is the one the range opens in.
_ACADEMIC_RANGE_RE = re.compile(r"\b(20\d{2})\s*[-/–—]\s*(?:20)?(\d{2})\b")
# The commonest sentence in an academic advertisement -- and it is about the
# committee's calendar, not the job's. Reading its date as a start would misfile
# a large share of the market into whatever year review happens to open.
_REVIEW_CUE_RE = re.compile(
    r"\b(?:review|consideration|screening|evaluation)\s+of\s+"
    r"(?:applications?|candidates?|materials?)\b|"
    r"\bapplications?\s+(?:will\s+be\s+)?(?:reviewed|accepted|considered)\b|"
    r"\bdeadline\b|\bclos(?:es|ing)\b",
    re.I,
)
# A range is only an academic year when something says so. "2024-2025" in a
# grant history is not a start date.
_ACADEMIC_CUE_RE = re.compile(
    r"\b(?:academic\s+year|ay|school\s+year|start(?:ing|s)?|begin(?:s|ning)?|"
    r"appointment|effective|for\s+the)\b",
    re.I,
)
# How far a start can plausibly sit from when we saw the posting. A job
# advertised now does not begin four years ago, and rarely more than three
# years ahead.
_MAX_YEARS_AHEAD = 4
# Three, not one. A posting still up in 2026 that says "Starting Date:
# 2024-2025" is stale, and its staleness is a fact about the posting worth
# recording. The misreads this bound exists to stop were off by 10 and 27 years,
# not by two.
_MAX_YEARS_BEHIND = 3


def cycle_label(start_year):
    """``2028`` -> ``"2028-29"``. The label is the cycle's own name."""
    if start_year is None:
        return UNKNOWN
    start = int(start_year)
    return f"{start}-{(start + 1) % 100:02d}"


def cycle_for_start_year(expected_start_year):
    """The cycle a job starting in ``expected_start_year`` was recruited in.

    Returns ``(cycle_start_year, label)``. Recruiting for a start in year Y
    happens during the academic year that opens in Y-1, for every term.
    """
    if expected_start_year is None:
        return None, UNKNOWN
    start = int(expected_start_year) - 1
    return start, cycle_label(start)


def _plausible(year, reference_year):
    """Is this year a possible start for a posting seen in ``reference_year``?"""
    if reference_year is None:
        return True
    return (reference_year - _MAX_YEARS_BEHIND) <= year <= (reference_year + _MAX_YEARS_AHEAD)


def parse_expected_start(text, start_year=None, start_term=None, reference_year=None):
    """Read an expected start year out of whatever the posting stated.

    Only explicit statements count, and the year has to belong to the statement
    that names it. "Review of applications begins November 1" gives a date and
    says nothing about when the job starts; "Statement of purpose (250-300
    words)" in a posting that mentions Fall somewhere else is not a Fall 2000
    start.
    """
    if start_year:
        return int(start_year), "explicit start_year field"

    haystack = " ".join(str(part) for part in (start_term, text) if part).strip()
    if not haystack:
        return None, "no start information captured"

    # A term with its own year is the strongest signal and the most common.
    for match in _TERM_YEAR_RE.finditer(haystack):
        year = int(match.group(2))
        if _plausible(year, reference_year):
            return year, f"term and year together in {match.group(0).strip()!r}"

    # An academic-year range, but only where something marks it as one.
    for match in _ACADEMIC_RANGE_RE.finditer(haystack):
        window = haystack[max(0, match.start() - 44):match.start()]
        if not _ACADEMIC_CUE_RE.search(window):
            continue
        year = int(match.group(1))
        if _plausible(year, reference_year):
            return year, f"academic-year range {match.group(0).strip()!r}"

    # An explicit start cue with a year close behind it, unless the sentence is
    # about reviewing applications rather than starting the job.
    for match in _START_CUE_RE.finditer(haystack):
        window = haystack[max(0, match.start() - 40):match.end()]
        if _REVIEW_CUE_RE.search(window):
            continue
        year = int(match.group(1))
        if _plausible(year, reference_year):
            return year, f"start cue {match.group(0).strip()[:48]!r}"

    if any(term in haystack.casefold() for term in _TERMS):
        return None, "a term was named without a year beside it"
    return None, "no term or academic year stated; a bare date is not a start"


def derive(expected_start_year=None, start_term=None, text=None, start_year=None,
           reference_year=None):
    """Everything the columns need, from what the posting actually said.

    ``reference_year`` is the year the posting was first observed. Supplying it
    rejects readings that cannot be about this posting -- a 2026 advertisement
    does not begin in 2000.
    """
    year = expected_start_year
    reason = "expected start supplied directly"
    if year is None:
        year, reason = parse_expected_start(text, start_year=start_year,
                                            start_term=start_term,
                                            reference_year=reference_year)
    cycle_start, label = cycle_for_start_year(year)
    if year is None:
        return {
            "expected_start_year": None,
            "market_cycle_start_year": None,
            "market_cycle_label": UNKNOWN,
            "market_cycle_reason": (
                f"Cycle unknown: {reason}. Not placed in the current cycle -- "
                "an unstated start is not evidence of a start this year."),
        }
    return {
        "expected_start_year": int(year),
        "market_cycle_start_year": cycle_start,
        "market_cycle_label": label,
        "market_cycle_reason": (
            f"Starts {year} ({reason}); recruiting for a {year} start runs in "
            f"the academic year opening {cycle_start}, so cycle {label}."),
    }


def current_cycle(today):
    """The cycle a market is in on a given date.

    The academic hiring year turns over in the summer: a posting appearing in
    August 2026 is competing in the 2026-27 cycle, one appearing in March 2026
    is still in 2025-26. July is the boundary -- late enough that the previous
    cycle's searches have closed.
    """
    start = today.year if today.month >= 7 else today.year - 1
    return start, cycle_label(start)


__all__ = ["UNKNOWN", "current_cycle", "cycle_for_start_year", "cycle_label",
           "derive", "parse_expected_start"]
