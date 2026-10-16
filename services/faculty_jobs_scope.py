# -*- coding: utf-8 -*-
"""One scope contract, shared by every consumer that reports a count.

A scope answers two different questions and they were being conflated:

* **catalogue** -- every observed record in this scope, whatever its status.
* **active** -- the subset still open, likely open, or closing soon.

The list endpoint returned the catalogue, the summary returned active, and the
analytics groupings applied the *broad business* predicate no matter which
scope was asked for. That produced three incompatible answers to the same
user question, on one page.

The rules themselves are simple and belong in one place:

* ``business_school`` -- ``business_scope='business_school'``
* ``business``        -- ``business_scope IN ('business_school','business_discipline')``
* ``all``             -- no business-scope restriction at all

The two market scopes additionally require an accepted derivation and a
role-eligible record; the audit scope deliberately requires neither, because
its purpose is to show what the market views exclude.

Every consumer also reports the SQL it actually used. Metadata that names a
predicate the query did not run is worse than no metadata: it was telling
readers that the strict view included ``business_discipline`` and that the
audit view was limited to business scopes, and neither was true.
"""

from services.faculty_jobs_query import DEFAULT_MARKET_STATUSES
from services.faculty_jobs_lifecycle import effective_status_sql

SCOPES = ("business_school", "business", "all")

# Statuses that mean a posting is still worth applying to. Everything else is
# retained and reported separately -- "not active" is not one status.
ACTIVE_STATUSES = DEFAULT_MARKET_STATUSES
INACTIVE_REPORTED_STATUSES = ("closed", "unknown")


def active_filter_definition(scope):
    """Describe the active predicate exposed by a public scope.

    Keep this alongside the SQL contract so list, summary, analytics, and
    reports cannot quietly advertise the old broad-business predicate for a
    stricter or audit scope.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown faculty-job scope: {scope}")
    definition = {
        "scope": scope,
        "statuses": list(ACTIVE_STATUSES),
    }
    if scope in {"business_school", "business"}:
        definition.update({
            "derived_quality": "accepted",
            "faculty_market_eligible": True,
        })
    if scope == "business_school":
        definition["business_scope"] = ["business_school"]
    elif scope == "business":
        definition["business_scope"] = ["business_school", "business_discipline"]
    return definition


def _prefix(alias):
    if not alias:
        return ""
    text = str(alias)
    return text if text.endswith(".") else text + "."


def catalogue_sql(scope, alias="j"):
    """Every observed record in this scope, regardless of status.

    A row folded into another by ``cross_source_merge`` is excluded from every
    scope including the audit one. The audit scope exists to show what the
    market views leave out by *derivation*; a duplicate is not a second record
    in any view, so counting it there would only reintroduce the double count
    the merge removed. The row itself is retained -- see migration 85.
    """
    p = _prefix(alias)
    unmerged = f"{p}merged_into_job_id IS NULL"
    if scope == "all":
        return unmerged
    accepted = (f"{p}derived_quality='accepted' AND {p}faculty_market_eligible=1")
    if scope == "business_school":
        return f"{unmerged} AND {accepted} AND {p}business_scope='business_school'"
    return (f"{unmerged} AND {accepted} AND "
            f"{p}business_scope IN ('business_school','business_discipline')")


def active_sql(scope, alias="j"):
    """The still-open subset of this scope's catalogue."""
    p = _prefix(alias)
    statuses = ",".join(f"'{status}'" for status in ACTIVE_STATUSES)
    return f"{catalogue_sql(scope, alias)} AND {effective_status_sql(alias)} IN ({statuses})"


def inactive_status_sql(scope, alias="j"):
    """Records this scope retains that are not active."""
    p = _prefix(alias)
    statuses = ",".join(f"'{status}'" for status in ACTIVE_STATUSES)
    return f"{catalogue_sql(scope, alias)} AND {effective_status_sql(alias)} NOT IN ({statuses})"


def scope_counts(conn, scope, select_sql, extra_where="1=1", extra_args=()):
    """Catalogue, active, and the status breakdown of what is not active.

    ``select_sql`` is the caller's row source so filters already applied stay
    applied; the scope predicates are added on top.
    """
    def count(predicate):
        where = " AND ".join(part for part in (extra_where, predicate) if part and part != "1=1")
        return conn.execute(
            f"SELECT COUNT(*) FROM ({select_sql} WHERE {where or '1=1'})", tuple(extra_args)
        ).fetchone()[0]

    catalogue = catalogue_sql(scope, "j")
    active = active_sql(scope, "j")
    breakdown = {}
    statuses = ",".join(f"'{status}'" for status in ACTIVE_STATUSES)
    where = " AND ".join(part for part in (extra_where, catalogue) if part and part != "1=1")
    rows = conn.execute(
        f"SELECT {effective_status_sql('j')} AS status, COUNT(*) AS n "
        f"FROM ({select_sql} WHERE {where or '1=1'}) j "
        f"WHERE {effective_status_sql('j')} NOT IN ({statuses}) "
        "GROUP BY 1 ORDER BY n DESC",
        tuple(extra_args),
    ).fetchall()
    for row in rows:
        breakdown[row["status"]] = int(row["n"])
    return {
        "scope": scope,
        "catalogue_records": int(count(catalogue)),
        "active_jobs": int(count(active)),
        "inactive_by_status": breakdown,
        "catalogue_filter_sql": catalogue,
        "active_filter_sql": active,
    }


__all__ = ["ACTIVE_STATUSES", "INACTIVE_REPORTED_STATUSES", "SCOPES",
           "active_filter_definition", "active_sql", "catalogue_sql",
           "inactive_status_sql", "scope_counts"]
