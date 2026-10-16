# -*- coding: utf-8 -*-
"""Shared predicates for the Academic Career read models.

The default market is deliberately narrower than the preserved posting
catalogue.  Keeping its definition in one small dependency prevents the API,
School Explorer and generated status report from silently drifting apart.
"""

from services.faculty_jobs_lifecycle import effective_status, effective_status_sql

DEFAULT_MARKET_STATUSES = ("open", "likely_open", "closing_soon")
DEFAULT_MARKET_SCOPES = ("business_school", "business_discipline")
DEFAULT_MARKET_FILTER_DEFINITION = {
    # A posting folded into another as the same vacancy on a second board is
    # not a second opening. See migration 85 and services/cross_source_merge.
    "merged_into_job_id": None,
    "derived_quality": "accepted",
    "faculty_market_eligible": 1,
    "business_scope": list(DEFAULT_MARKET_SCOPES),
    "status": list(DEFAULT_MARKET_STATUSES),
}


def default_market_where(alias=None):
    """Return the exact SQL predicate for the default business market.

    ``alias`` may be ``None``, ``"j"`` or ``"j."``.  The return value is SQL
    only; callers must not append private scope overrides to this predicate
    when they are reporting the default market.
    """
    prefix = ""
    if alias:
        prefix = str(alias)
        if not prefix.endswith("."):
            prefix += "."
    return (
        f"{prefix}merged_into_job_id IS NULL AND "
        f"{prefix}derived_quality='accepted' AND "
        f"{prefix}faculty_market_eligible=1 AND "
        f"{prefix}business_scope IN ('business_school','business_discipline') AND "
        f"{effective_status_sql(alias)} IN ('open','likely_open','closing_soon')"
    )


def is_default_market_row(row):
    """Evaluate the shared predicate for a mapping/SQLite row in Python."""
    def value(key, default=None):
        if hasattr(row, "get"):
            return row.get(key, default)
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return default

    return (
        value("merged_into_job_id") is None
        and str(value("derived_quality") or "") == "accepted"
        and int(value("faculty_market_eligible") or 0) == 1
        and str(value("business_scope") or "") in DEFAULT_MARKET_SCOPES
        and effective_status(row) in DEFAULT_MARKET_STATUSES
    )


__all__ = [
    "DEFAULT_MARKET_FILTER_DEFINITION", "DEFAULT_MARKET_SCOPES",
    "DEFAULT_MARKET_STATUSES",
    "default_market_where", "is_default_market_row",
]
