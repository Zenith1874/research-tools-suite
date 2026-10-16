# -*- coding: utf-8 -*-
"""Daily market snapshots, and the source panel that makes them comparable.

A snapshot is a materialisation, not a source of truth. Everything here can be
recomputed from ``jobs``, ``job_status_history`` and ``ingestion_runs``; the
table exists so a chart does not re-derive four years of history on every page
load. If a snapshot ever disagrees with those tables, the tables are right.

The trap this module exists to avoid: **adding a source is not the market
growing.** If a Workday adapter lands in 2027 and observed jobs go 400 -> 650,
the naive series shows 62% growth in a market that did not move. So every
snapshot records which sources were actually contributing that day, and the
comparable series is computed over the sources present in *both* periods --
the stable panel. The raw observed count is kept too, clearly named, because
hiding it would be its own distortion.

Scope comes from ``faculty_jobs_scope`` rather than being redefined here. The
project has already had the failure where the list, the summary and the
analytics each carried their own predicate and reported three different totals
for one question.
"""

import json
from datetime import date, datetime, timedelta, timezone

from services.faculty_jobs_market_cycle import UNKNOWN, current_cycle
from services.faculty_jobs_scope import SCOPES, active_sql, catalogue_sql

# Statuses that mean a posting is still live. Imported meaning, not a second
# definition: active_sql() owns the predicate; this is only for the change
# counts, which work off history rows rather than the current row.
LIVE_STATUSES = ("open", "likely_open", "closing_soon")


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_tables(conn):
    """Snapshot tables. Idempotent."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date     TEXT NOT NULL,
            scope             TEXT NOT NULL,
            market_cycle      TEXT NOT NULL,
            dimension         TEXT NOT NULL,
            dimension_value   TEXT NOT NULL,
            active_jobs       INTEGER NOT NULL DEFAULT 0,
            catalogue_records INTEGER NOT NULL DEFAULT 0,
            new_jobs          INTEGER NOT NULL DEFAULT 0,
            closed_jobs       INTEGER NOT NULL DEFAULT 0,
            reopened_jobs     INTEGER NOT NULL DEFAULT 0,
            deadline_changed  INTEGER NOT NULL DEFAULT 0,
            salary_changed    INTEGER NOT NULL DEFAULT 0,
            title_changed     INTEGER NOT NULL DEFAULT 0,
            source_count      INTEGER NOT NULL DEFAULT 0,
            complete_source_count INTEGER NOT NULL DEFAULT 0,
            source_panel      TEXT,
            reconstructed     INTEGER NOT NULL DEFAULT 0,
            created_at        TEXT NOT NULL,
            UNIQUE (snapshot_date, scope, dimension, dimension_value)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_date "
                 "ON market_snapshots(snapshot_date, scope)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_dim "
                 "ON market_snapshots(dimension, dimension_value, snapshot_date)")
    # The window functions above partition by job and order by time. Without
    # this index every backfilled day sorts 48,000 history rows from scratch.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status_history_job_time "
                 "ON job_status_history(job_id, observed_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status_history_day "
                 "ON job_status_history(substr(observed_at,1,10))")
    # Which sources were working on a given day. Without this a gap in a
    # series cannot be told apart from a market that shrank.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_daily_health (
            snapshot_date   TEXT NOT NULL,
            source_id       INTEGER NOT NULL,
            source_name     TEXT NOT NULL,
            runs            INTEGER NOT NULL DEFAULT 0,
            successful_runs INTEGER NOT NULL DEFAULT 0,
            items_seen      INTEGER NOT NULL DEFAULT 0,
            coverage_complete INTEGER,
            reported_total  INTEGER,
            active_jobs     INTEGER NOT NULL DEFAULT 0,
            reconstructed   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (snapshot_date, source_id)
        )
    """)


def _scalar(conn, sql, args=()):
    row = conn.execute(sql, args).fetchone()
    return (row[0] if row else 0) or 0


def source_health_for(conn, day):
    """Which sources ran on ``day`` and how they did, from ingestion_runs."""
    rows = conn.execute("""
        SELECT s.id AS source_id, s.name AS source_name,
               COUNT(r.id) AS runs,
               SUM(CASE WHEN r.status='success' THEN 1 ELSE 0 END) AS successful_runs,
               COALESCE(SUM(r.items_seen),0) AS items_seen,
               MAX(r.coverage_complete) AS coverage_complete,
               MAX(r.reported_total) AS reported_total
        FROM sources s
        JOIN ingestion_runs r ON r.source_id = s.id
        WHERE substr(r.started_at,1,10) = ?
        GROUP BY s.id, s.name
    """, (day,)).fetchall()
    return [dict(row) for row in rows]


def _panel_signature(health):
    """The set of sources that actually delivered, as a stable string.

    Only sources with a successful run count. A source that errored all day
    contributed nothing and including it would make a broken day look like a
    comparable one.
    """
    names = sorted(h["source_name"] for h in health if (h.get("successful_runs") or 0) > 0)
    return json.dumps(names, ensure_ascii=False)


def _dimension_counts(conn, day, scope, dimension, column):
    """Active and catalogue counts for one dimension on one day.

    Counted from the current ``jobs`` rows, so this is only truthful for
    today. Reconstructed history uses ``_reconstructed_counts`` instead and
    marks itself as such.
    """
    catalogue = catalogue_sql(scope)
    active = active_sql(scope)
    rows = conn.execute(f"""
        SELECT COALESCE(NULLIF(TRIM({column}),''),'unknown') AS value,
               SUM(CASE WHEN {active} THEN 1 ELSE 0 END) AS active_jobs,
               COUNT(*) AS catalogue_records
        FROM jobs j
        WHERE {catalogue}
        GROUP BY 1
    """).fetchall()
    return [dict(row) for row in rows]


def _change_counts(conn, day, scope):
    """New, closed and reopened on a day, from the status history.

    History rows are the evidence: the current ``jobs`` row only knows where a
    posting ended up, not when it moved.
    """
    catalogue = catalogue_sql(scope)
    live = ",".join(f"'{status}'" for status in LIVE_STATUSES)
    new_jobs = _scalar(conn, f"""
        SELECT COUNT(*) FROM jobs j
        WHERE {catalogue} AND substr(j.first_seen_at,1,10) = ?
    """, (day,))
    # A close is a transition, not a status: a job already closed yesterday and
    # observed again today has not closed today. LAG gives the previous status
    # in one pass, where the EXISTS form re-scanned the history per row.
    transitions = conn.execute(f"""
        WITH ordered AS (
            SELECT h.job_id, h.observed_at, h.status,
                   LAG(h.status) OVER (PARTITION BY h.job_id ORDER BY h.observed_at)
                     AS prev_status
            FROM job_status_history h
            JOIN jobs j ON j.id = h.job_id
            WHERE {catalogue}
        )
        SELECT
          COUNT(DISTINCT CASE WHEN status='closed' AND prev_status IN ({live})
                              THEN job_id END) AS closed_jobs,
          COUNT(DISTINCT CASE WHEN status IN ({live}) AND prev_status='closed'
                              THEN job_id END) AS reopened_jobs
        FROM ordered WHERE substr(observed_at,1,10) = ?
    """, (day,)).fetchone()
    closed = transitions["closed_jobs"] or 0
    reopened = transitions["reopened_jobs"] or 0
    # Field movement, comparing each history row with the one before it for the
    # same job. LAG does this in one pass; the correlated-subquery form -- an
    # EXISTS containing a MAX() over the same table -- was quadratic and did not
    # finish a single day against 48,000 history rows.
    changes = conn.execute(f"""
        WITH ordered AS (
            SELECT h.job_id, h.observed_at, h.deadline, h.salary_raw, h.title_raw,
                   LAG(h.deadline)   OVER w AS prev_deadline,
                   LAG(h.salary_raw) OVER w AS prev_salary,
                   LAG(h.title_raw)  OVER w AS prev_title
            FROM job_status_history h
            JOIN jobs j ON j.id = h.job_id
            WHERE {catalogue}
            WINDOW w AS (PARTITION BY h.job_id ORDER BY h.observed_at)
        )
        SELECT
          COUNT(DISTINCT CASE WHEN prev_deadline IS NOT NULL
                               AND COALESCE(prev_deadline,'') <> COALESCE(deadline,'')
                              THEN job_id END) AS deadline_changed,
          COUNT(DISTINCT CASE WHEN prev_salary IS NOT NULL
                               AND COALESCE(prev_salary,'') <> COALESCE(salary_raw,'')
                              THEN job_id END) AS salary_changed,
          COUNT(DISTINCT CASE WHEN prev_title IS NOT NULL
                               AND COALESCE(prev_title,'') <> COALESCE(title_raw,'')
                              THEN job_id END) AS title_changed
        FROM ordered WHERE substr(observed_at,1,10) = ?
    """, (day,)).fetchone()
    return {
        "new_jobs": new_jobs,
        "closed_jobs": closed,
        "reopened_jobs": reopened,
        "deadline_changed": changes["deadline_changed"] or 0,
        "salary_changed": changes["salary_changed"] or 0,
        "title_changed": changes["title_changed"] or 0,
    }


DIMENSIONS = (
    ("total", "'all'"),
    ("discipline", "j.discipline_primary"),
    ("region", "j.region_group"),
    ("rank", "j.rank_normalized"),
    ("track", "j.track_type"),
    ("market_cycle", "j.hiring_cycle"),
)


def write_snapshot(conn, day=None, scopes=SCOPES, reconstructed=False):
    """Materialise one day, for every scope and dimension.

    ``reconstructed`` marks a row computed after the fact from history rather
    than observed on the day. Both are useful; conflating them would let a
    back-fill masquerade as a contemporaneous reading.
    """
    day = day or date.today().isoformat()
    ensure_tables(conn)
    health = source_health_for(conn, day)
    panel = _panel_signature(health)
    source_count = sum(1 for h in health if (h.get("successful_runs") or 0) > 0)
    complete_count = sum(1 for h in health if h.get("coverage_complete") == 1)
    cycle_start, cycle = current_cycle(date.fromisoformat(day))
    stamp = now_utc()
    written = 0

    for source in health:
        conn.execute("""
            INSERT INTO source_daily_health
              (snapshot_date, source_id, source_name, runs, successful_runs,
               items_seen, coverage_complete, reported_total, active_jobs, reconstructed)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(snapshot_date, source_id) DO UPDATE SET
              runs=excluded.runs, successful_runs=excluded.successful_runs,
              items_seen=excluded.items_seen, coverage_complete=excluded.coverage_complete,
              reported_total=excluded.reported_total
        """, (day, source["source_id"], source["source_name"], source["runs"],
              source["successful_runs"], source["items_seen"],
              source["coverage_complete"], source["reported_total"], 0,
              1 if reconstructed else 0))

    for scope in scopes:
        changes = _change_counts(conn, day, scope)
        for dimension, column in DIMENSIONS:
            for row in _dimension_counts(conn, day, scope, dimension, column):
                # Change counts belong to the day, not to each dimension value;
                # attaching them only to the total row keeps them from being
                # summed several times over.
                extra = changes if dimension == "total" else {
                    k: 0 for k in changes}
                conn.execute("""
                    INSERT INTO market_snapshots
                      (snapshot_date, scope, market_cycle, dimension, dimension_value,
                       active_jobs, catalogue_records, new_jobs, closed_jobs,
                       reopened_jobs, deadline_changed, salary_changed, title_changed,
                       source_count, complete_source_count, source_panel,
                       reconstructed, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(snapshot_date, scope, dimension, dimension_value)
                    DO UPDATE SET
                      active_jobs=excluded.active_jobs,
                      catalogue_records=excluded.catalogue_records,
                      new_jobs=excluded.new_jobs, closed_jobs=excluded.closed_jobs,
                      reopened_jobs=excluded.reopened_jobs,
                      deadline_changed=excluded.deadline_changed,
                      salary_changed=excluded.salary_changed,
                      title_changed=excluded.title_changed,
                      source_count=excluded.source_count,
                      complete_source_count=excluded.complete_source_count,
                      source_panel=excluded.source_panel
                """, (day, scope, cycle, dimension, str(row["value"]),
                      row["active_jobs"], row["catalogue_records"],
                      extra["new_jobs"], extra["closed_jobs"], extra["reopened_jobs"],
                      extra["deadline_changed"], extra["salary_changed"],
                      extra["title_changed"], source_count, complete_count, panel,
                      1 if reconstructed else 0, stamp))
                written += 1
    return {"snapshot_date": day, "rows": written, "market_cycle": cycle,
            "sources_contributing": source_count, "reconstructed": reconstructed}


def backfill(conn, since=None, until=None, scopes=SCOPES, echo=None):
    """Reconstruct daily rows from the history already held.

    The database has status history back to 2026-08-23 and ingestion runs to
    match, so the change counts and the source panel are genuine for those
    days. The *active* counts are not: they are computed from today's rows,
    because no daily state was recorded at the time. Every reconstructed row
    says so, and a reader comparing a reconstructed active count with a
    contemporaneous one is told which is which.
    """
    ensure_tables(conn)
    first = since or conn.execute(
        "SELECT MIN(substr(observed_at,1,10)) FROM job_status_history").fetchone()[0]
    last = until or date.today().isoformat()
    if not first:
        return {"days": 0, "rows": 0, "reason": "no history to reconstruct from"}
    day = date.fromisoformat(first)
    end = date.fromisoformat(last)
    days = rows = 0
    while day <= end:
        result = write_snapshot(conn, day.isoformat(), scopes, reconstructed=True)
        rows += result["rows"]
        days += 1
        if echo:
            echo(f"  {day.isoformat()} rows={result['rows']} "
                 f"sources={result['sources_contributing']}")
        day += timedelta(days=1)
    return {"days": days, "rows": rows, "from": first, "to": last,
            "reconstructed": True}


def stable_panel_series(conn, scope="business_school", dimension="total",
                        dimension_value="all"):
    """A series over sources present on every day of it.

    This is the number to compare across periods. ``active_jobs`` in the raw
    snapshot answers "what did we observe"; this answers "what changed in the
    market", which is a different question whenever the source set moved.
    """
    rows = conn.execute("""
        SELECT snapshot_date, active_jobs, source_panel, reconstructed
        FROM market_snapshots
        WHERE scope=? AND dimension=? AND dimension_value=?
        ORDER BY snapshot_date
    """, (scope, dimension, dimension_value)).fetchall()
    if not rows:
        return {"series": [], "panel": [], "note": "no snapshots recorded"}
    panels = [set(json.loads(row["source_panel"] or "[]")) for row in rows]
    stable = set.intersection(*panels) if panels else set()
    return {
        "series": [{"date": row["snapshot_date"], "observed_active": row["active_jobs"],
                    "reconstructed": bool(row["reconstructed"])} for row in rows],
        "panel": sorted(stable),
        "panel_size": len(stable),
        "note": (
            "observed_active counts every source working that day. Compare "
            "periods only over the stable panel above -- a source added between "
            "two dates raises the observed count without the market moving."),
    }


__all__ = ["DIMENSIONS", "LIVE_STATUSES", "backfill", "ensure_tables",
           "source_health_for", "stable_panel_series", "write_snapshot"]
