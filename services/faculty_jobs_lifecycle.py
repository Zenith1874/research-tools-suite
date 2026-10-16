"""Read-time deadline status, without rewriting historical observations.

Only an explicit fixed deadline can expire a previously active posting.
Review dates and open-until-filled language are not closing dates. The local
calendar date is used consistently by the SQLite and Python read models.
"""

from datetime import date, datetime, timedelta

ACTIVE_STATUSES = ("open", "likely_open", "closing_soon")


def _value(row, key, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def effective_status(row, today=None):
    today = today or date.today()
    observed = _value(row, "status") or "unknown"
    if observed == "closing_soon" and _value(row, "deadline_mode") in {"open_until_filled", "rolling"}:
        return "likely_open"
    if observed not in ACTIVE_STATUSES or _value(row, "deadline_mode") != "fixed":
        return observed
    text = str(_value(row, "deadline_date") or "")
    try:
        deadline = date.fromisoformat(text)
    except ValueError:
        return observed
    if deadline.isoformat() != text:
        return observed
    if deadline < today:
        return "closed"
    return "closing_soon" if deadline <= today + timedelta(days=14) else "open"


def effective_status_sql(alias="j", today=None):
    """A SQL expression usable in WHERE, SELECT, grouping, and count queries."""
    prefix = (str(alias).rstrip(".") + ".") if alias else ""
    current = f"'{today.isoformat()}'" if today else "date('now','localtime')"
    status, mode, deadline = (prefix + name for name in ("status", "deadline_mode", "deadline_date"))
    return (
        f"(CASE WHEN {status} IN ('open','likely_open','closing_soon') "
        f"AND {mode}='fixed' AND length({deadline})=10 "
        f"AND date({deadline},'+0 days')={deadline} THEN "
        f"CASE WHEN {deadline} < {current} THEN 'closed' "
        f"WHEN {deadline} <= date({current},'+14 days') THEN 'closing_soon' "
        f"ELSE 'open' END ELSE CASE WHEN {status}='closing_soon' "
        f"AND {mode} IN ('open_until_filled','rolling') THEN 'likely_open' "
        f"ELSE COALESCE({status},'unknown') END END)"
    )


def lifecycle_fields(row, today=None):
    today = today or date.today()
    observed = _value(row, "status") or "unknown"
    status = effective_status(row, today)
    age = None
    try:
        checked = datetime.fromisoformat(str(_value(row, "last_seen_at") or "").replace("Z", "+00:00"))
        checked_date = checked.astimezone().date() if checked.tzinfo else checked.date()
        age = max(0, (today - checked_date).days)
    except ValueError:
        pass
    return {
        "observed_status": observed,
        "status": status,
        "status_as_of": today.isoformat(),
        "status_basis": "open_ended_is_not_hard_close" if observed == "closing_soon" and _value(row, "deadline_mode") in {"open_until_filled", "rolling"}
                        else "fixed_deadline_elapsed" if status == "closed" and observed in ACTIVE_STATUSES
                        else "fixed_deadline_calendar" if _value(row, "deadline_mode") == "fixed" and status in ACTIVE_STATUSES
                        else "last_source_observation",
        "last_seen_age_days": age,
        "freshness": "unknown" if age is None else "stale" if age > 14 else "recent",
        "freshness_window_days": 14,
    }
