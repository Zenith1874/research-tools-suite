# -*- coding: utf-8 -*-
"""Source × field coverage: which board is carrying which part of the market.

The question this answers is not "how many did we scrape" but "what are we
missing, and where". Those are different, and the second one is the only one
that tells you whether a field-level count can be trusted.

Three things it reports that a plain count cannot:

**Unique contribution.** A source carrying 148 postings that four other boards
also carry is worth much less than one carrying 40 nobody else has. Losing the
first costs almost nothing; losing the second puts a hole in a discipline.

**Field-level quality, not just volume.** A board can supply 2,824 rows and a
deadline for none of them. Volume and usefulness are separate columns here.

**What is absent rather than zero.** A discipline with no postings from a
source may mean the board does not cover it, or that the board was blocked, or
that our classifier never assigned the discipline. Only the first is a fact
about the market, so a zero is reported next to the source's run health rather
than alone.

Read-only.
"""

import sqlite3

from services.faculty_jobs_scope import active_sql, catalogue_sql

# The disciplines the matrix reports as columns. Ordered by how much of the
# market they carry, so the important gaps are visible without scrolling.
DISCIPLINE_ORDER = (
    "Management",
    "Information Systems / MIS",
    "Accounting",
    "Finance",
    "Marketing",
    "Operations / Supply Chain",
    "Business Analytics / AI",
    "Entrepreneurship",
    "Organizational Behavior / HR",
    "Strategy",
    "International Business",
    "Other",
)

# Fields whose presence decides whether a posting is actually usable. Volume
# without these is a row count, not coverage.
QUALITY_FIELDS = (
    ("official_url", "j.official_url IS NOT NULL"),
    ("deadline", "j.deadline_date IS NOT NULL OR j.deadline_mode IN "
                 "('open_until_filled','rolling')"),
    ("salary", "j.salary_min IS NOT NULL"),
    ("track_type", "j.track_type IS NOT NULL AND j.track_type != 'unknown'"),
    ("department", "j.department IS NOT NULL AND j.department != ''"),
    ("start_term", "j.start_year IS NOT NULL"),
    ("visa_language", "j.visa_status IS NOT NULL AND j.visa_status != 'unknown'"),
    ("body_600_chars", "LENGTH(j.description_excerpt) >= 600"),
)


def _source_health(conn):
    """Run outcome per source, so a zero can be read correctly."""
    rows = conn.execute("""
        SELECT s.id, s.name, s.enabled, s.support_status,
               (SELECT MAX(started_at) FROM ingestion_runs r
                WHERE r.source_id = s.id AND r.status = 'success') AS last_success,
               (SELECT coverage_complete FROM ingestion_runs r
                WHERE r.source_id = s.id AND r.status = 'success'
                ORDER BY r.id DESC LIMIT 1) AS coverage_complete,
               (SELECT reported_total FROM ingestion_runs r
                WHERE r.source_id = s.id AND r.status = 'success'
                ORDER BY r.id DESC LIMIT 1) AS reported_total,
               (SELECT items_seen FROM ingestion_runs r
                WHERE r.source_id = s.id AND r.status = 'success'
                ORDER BY r.id DESC LIMIT 1) AS items_seen
        FROM sources s
    """).fetchall()
    return {row["id"]: dict(row) for row in rows}


def _completeness_state(health):
    """The same vocabulary the source-health panel uses.

    `partial` is a measurement -- we know the shortfall. `unverifiable` is the
    absence of one. Collapsing them once made a board measured at 47% of its
    own advertised total look unmeasurable.
    """
    if health.get("coverage_complete") == 1:
        return "complete"
    if health.get("coverage_complete") == 0:
        return "partial"
    if not health.get("last_success"):
        return "not_read"
    return "unverifiable"


def build_matrix(conn, scope="business"):
    """Source × discipline counts, with per-source field quality.

    ``scope`` uses the shared contract rather than a predicate written here:
    the project has already had the failure where three surfaces each carried
    their own definition and reported three totals for one question.
    """
    catalogue = catalogue_sql(scope)
    still_open = active_sql(scope)
    health = _source_health(conn)

    # The catalogue is every posting ever observed in this scope, closed ones
    # included, so these columns are cumulative reach rather than the market as
    # it stands today. Both are worth having and they are not interchangeable:
    # a board that carried a discipline for two years and has posted nothing
    # since looks identical to an active one in the cumulative column alone.
    active_by_source = {row["source_id"]: row["jobs"] for row in conn.execute(f"""
        SELECT js.source_id, COUNT(DISTINCT j.id) AS jobs
        FROM jobs j
        JOIN job_sources js ON js.job_id = j.id AND js.active = 1
        WHERE {still_open}
        GROUP BY js.source_id
    """)}
    active_by_discipline = {row["discipline"]: row["jobs"] for row in conn.execute(f"""
        SELECT COALESCE(NULLIF(TRIM(j.discipline_primary),''),'Unclassified') AS discipline,
               COUNT(DISTINCT j.id) AS jobs
        FROM jobs j
        JOIN job_sources js ON js.job_id = j.id AND js.active = 1
        WHERE {still_open}
        GROUP BY discipline
    """)}

    # Per source, per discipline. Counting distinct jobs because a job carried
    # by one source on two links must not count twice.
    counts = conn.execute(f"""
        SELECT s.id AS source_id, s.name AS source_name,
               COALESCE(NULLIF(TRIM(j.discipline_primary),''),'Unclassified') AS discipline,
               COUNT(DISTINCT j.id) AS jobs
        FROM jobs j
        JOIN job_sources js ON js.job_id = j.id AND js.active = 1
        JOIN sources s ON s.id = js.source_id
        WHERE {catalogue}
        GROUP BY s.id, s.name, discipline
    """).fetchall()

    # A job only this source carries. This is what would actually be lost.
    unique = {row["source_id"]: row["unique_jobs"] for row in conn.execute(f"""
        SELECT js.source_id, COUNT(DISTINCT j.id) AS unique_jobs
        FROM jobs j
        JOIN job_sources js ON js.job_id = j.id AND js.active = 1
        WHERE {catalogue}
          AND (SELECT COUNT(DISTINCT k.source_id) FROM job_sources k
               WHERE k.job_id = j.id AND k.active = 1) = 1
        GROUP BY js.source_id
    """)}

    # Distinct postings per discipline. Deliberately not the sum of the source
    # columns: a posting carried by three boards is one posting, and adding the
    # columns up reports a discipline at three times its real size -- which then
    # makes every share computed against it wrong.
    discipline_totals = {row["discipline"]: row["jobs"] for row in conn.execute(f"""
        SELECT COALESCE(NULLIF(TRIM(j.discipline_primary),''),'Unclassified') AS discipline,
               COUNT(DISTINCT j.id) AS jobs
        FROM jobs j
        JOIN job_sources js ON js.job_id = j.id AND js.active = 1
        WHERE {catalogue}
        GROUP BY discipline
    """)}

    # Per source, per discipline, the postings nobody else carries -- what would
    # actually go missing from that discipline if the board stopped.
    sole = {}
    for row in conn.execute(f"""
        SELECT js.source_id,
               COALESCE(NULLIF(TRIM(j.discipline_primary),''),'Unclassified') AS discipline,
               COUNT(DISTINCT j.id) AS jobs
        FROM jobs j
        JOIN job_sources js ON js.job_id = j.id AND js.active = 1
        WHERE {catalogue}
          AND (SELECT COUNT(DISTINCT k.source_id) FROM job_sources k
               WHERE k.job_id = j.id AND k.active = 1) = 1
        GROUP BY js.source_id, discipline
    """):
        sole.setdefault(row["source_id"], {})[row["discipline"]] = row["jobs"]

    totals = {}
    grid = {}
    for row in counts:
        grid.setdefault(row["source_id"], {})[row["discipline"]] = row["jobs"]
        totals[row["source_id"]] = totals.get(row["source_id"], 0) + row["jobs"]

    # Field quality per source, over that source's own postings.
    quality = {}
    for source_id in grid:
        source_quality = {}
        held = conn.execute(f"""
            SELECT COUNT(DISTINCT j.id) FROM jobs j
            JOIN job_sources js ON js.job_id = j.id AND js.active = 1
            WHERE {catalogue} AND js.source_id = ?
        """, (source_id,)).fetchone()[0]
        for field, condition in QUALITY_FIELDS:
            filled = conn.execute(f"""
                SELECT COUNT(DISTINCT j.id) FROM jobs j
                JOIN job_sources js ON js.job_id = j.id AND js.active = 1
                WHERE {catalogue} AND js.source_id = ? AND ({condition})
            """, (source_id,)).fetchone()[0]
            source_quality[field] = {
                "filled": filled, "of": held,
                "percent": round(100.0 * filled / held, 1) if held else 0.0,
            }
        quality[source_id] = source_quality

    disciplines = [d for d in DISCIPLINE_ORDER
                   if any(d in row for row in grid.values())]
    extra = sorted({d for row in grid.values() for d in row} - set(disciplines))
    disciplines += extra

    sources = []
    for source_id, by_discipline in grid.items():
        info = health.get(source_id, {})
        sources.append({
            "source_id": source_id,
            "source": info.get("name", str(source_id)),
            "enabled": bool(info.get("enabled")),
            "support_status": info.get("support_status"),
            "last_success": info.get("last_success"),
            "completeness_state": _completeness_state(info),
            "reported_total": info.get("reported_total"),
            "items_seen": info.get("items_seen"),
            "total_jobs": totals.get(source_id, 0),
            "active_jobs": active_by_source.get(source_id, 0),
            "unique_jobs": unique.get(source_id, 0),
            "unique_share": (round(100.0 * unique.get(source_id, 0) / totals[source_id], 1)
                             if totals.get(source_id) else 0.0),
            "by_discipline": {d: by_discipline.get(d, 0) for d in disciplines},
            "sole_by_discipline": {d: sole.get(source_id, {}).get(d, 0)
                                   for d in disciplines},
            "field_quality": quality.get(source_id, {}),
        })
    sources.sort(key=lambda row: -row["total_jobs"])

    # A source that is configured but contributed nothing. Reported, because a
    # missing row and a zero row mean different things.
    silent = [
        {"source": info["name"], "enabled": bool(info["enabled"]),
         "support_status": info["support_status"],
         "last_success": info["last_success"],
         "completeness_state": _completeness_state(info)}
        for source_id, info in health.items() if source_id not in grid
    ]

    # How much of each discipline rests on one board, in the two senses that
    # differ: how much the biggest board *carries*, and how much would actually
    # be *lost* if it went dark. A discipline can be 100% carried by one board
    # and lose nothing when it stops, because every posting is cross-listed.
    by_discipline = {}
    for discipline in disciplines:
        contributions = sorted(
            ((row["source"],
              row["by_discipline"].get(discipline, 0),
              row["sole_by_discipline"].get(discipline, 0)) for row in sources),
            key=lambda triple: -triple[1])
        total = discipline_totals.get(discipline, 0)
        top_name, top_n, top_sole = contributions[0] if contributions else (None, 0, 0)
        single_sourced = sum(sole_n for _name, _n, sole_n in contributions)
        by_discipline[discipline] = {
            "jobs": total,
            "active_jobs": active_by_discipline.get(discipline, 0),
            "sources_contributing": sum(1 for _name, n, _sole in contributions if n),
            "largest_source": top_name,
            "largest_share": round(100.0 * top_n / total, 1) if total else 0.0,
            "largest_source_only_share": (round(100.0 * top_sole / total, 1)
                                          if total else 0.0),
            "single_sourced_share": (round(100.0 * single_sourced / total, 1)
                                     if total else 0.0),
        }

    # How much of the cross-listing this scope shows was recovered rather than
    # observed directly. Without it single_sourced_share reads as a finding
    # about boards, when part of it is a finding about our own keying.
    folded = conn.execute(f"""
        SELECT COUNT(*) FROM jobs d
        JOIN jobs j ON j.id = d.merged_into_job_id
        WHERE d.merged_into_job_id IS NOT NULL AND {catalogue}
    """).fetchone()[0]

    return {
        "scope": scope,
        "basis": "catalogue",
        "folded_duplicates": int(folded),
        "basis_note": (
            "Counts are the catalogue -- every posting observed in this scope, "
            "closed ones included -- so they measure cumulative reach, not the "
            "market as it stands today. `active_jobs` beside each row is the "
            "still-open subset; a board with reach and no active postings has "
            "stopped, which the cumulative column alone cannot show."),
        "catalogue_filter_sql": catalogue,
        "active_filter_sql": still_open,
        "disciplines": disciplines,
        "sources": sources,
        "silent_sources": silent,
        "by_discipline": by_discipline,
        "quality_fields": [name for name, _ in QUALITY_FIELDS],
        "reading_note": (
            "A zero is not evidence a board does not cover a discipline. Read it "
            "beside that source's completeness state: `not_read` and `unverifiable` "
            "mean we cannot tell, `partial` means we measured a shortfall, and only "
            "`complete` makes a zero a statement about the board."),
        "concentration_note": (
            "largest_share is how much of a discipline the biggest board carries; "
            "shares across boards sum to more than 100% wherever postings are "
            "cross-listed. largest_source_only_share is the part that would actually "
            "disappear if that board went dark, and single_sourced_share is the part "
            "of the discipline resting on exactly one board. A high value in either "
            "of the latter two means that discipline's counts move when one source "
            "has a bad day, and a comparison across periods should use the stable "
            "panel."),
        "single_sourced_note": (
            f"{folded} postings in this scope were the same vacancy carried by two "
            "boards under two rows, and are now counted once with both boards "
            "attached. What single_sourced_share still measures after that is "
            "mostly how deeply we crawl: a board can only be shown as a second "
            "carrier for an institution we read on both boards. It is a floor on "
            "cross-listing, not a measurement of it."),
    }


def field_gaps(conn, scope="business", threshold=25.0, matrix=None):
    """Where a field is thin, ranked by how many postings that costs.

    The point is triage: 8% deadline coverage on 2,824 postings is a bigger
    problem than 0% on 5.

    ``matrix`` lets a caller that already built one pass it in; the observatory
    endpoint needs both and would otherwise run the whole scan twice.
    """
    matrix = matrix if matrix is not None else build_matrix(conn, scope)
    gaps = []
    for source in matrix["sources"]:
        for field, stats in source["field_quality"].items():
            if stats["of"] and stats["percent"] < threshold:
                gaps.append({
                    "source": source["source"],
                    "field": field,
                    "percent": stats["percent"],
                    "missing": stats["of"] - stats["filled"],
                    "completeness_state": source["completeness_state"],
                })
    gaps.sort(key=lambda row: -row["missing"])
    return {"threshold": threshold, "gaps": gaps[:40],
            "note": ("Ranked by postings affected, not by percentage: a low share "
                     "on a large board costs more than a zero on a small one.")}


__all__ = ["DISCIPLINE_ORDER", "QUALITY_FIELDS", "build_matrix", "field_gaps"]
