# -*- coding: utf-8 -*-
"""The observatory's read model: what each layer holds, and how far it reaches.

Everything the loaders and the archive have built so far lives in two SQLite
files and has been reachable only from a command-line report. This assembles
the same figures for the page.

One rule runs through every payload here: **a count travels with its coverage
and with what it is not.** IPEDS doctoral production is not a candidate pool;
SED's realised tenure-track outcomes are not a supply; PERM history is not a
statement about any particular job; enrolled doctoral students are not
job-market candidates. Those caveats are fields in the response, not prose in
a template, so a caller cannot render the number without them.

Read-only. Nothing here migrates, writes or fetches.
"""

import json
import sqlite3
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACULTY_DB = ROOT / "data" / "faculty_jobs.db"
MARKET_DB = ROOT / "data" / "academic_market.db"


def _read_only(path):
    return sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, timeout=30)


def _scalar(conn, sql, args=(), default=0):
    try:
        row = conn.execute(sql, args).fetchone()
    except sqlite3.DatabaseError:
        return default
    return row[0] if row and row[0] is not None else default


def _rows(conn, sql, args=()):
    try:
        return [dict(row) for row in conn.execute(sql, args)]
    except sqlite3.DatabaseError:
        return []


def _observation_layer(conn):
    """Jobs, history, provenance -- the part that cannot be re-downloaded."""
    from services.faculty_jobs_market_cycle import current_cycle
    from services.faculty_jobs_scope import scope_counts
    from services.faculty_jobs_service import _job_select

    strict = scope_counts(conn, "business_school", _job_select())
    active = ("derived_quality='accepted' AND faculty_market_eligible=1 "
              "AND business_scope='business_school' "
              "AND status IN ('open','likely_open','closing_soon')")
    total = _scalar(conn, f"SELECT COUNT(*) FROM jobs WHERE {active}")

    def coverage(label, condition, note):
        filled = _scalar(conn, f"SELECT COUNT(*) FROM jobs WHERE {active} AND ({condition})")
        return {"field": label, "filled": filled, "of": total,
                "percent": round(100.0 * filled / total, 1) if total else 0.0,
                "note": note}

    return {
        "schema_version": _scalar(conn, "PRAGMA user_version"),
        "canonical_jobs": _scalar(conn, "SELECT COUNT(*) FROM jobs"),
        "source_observations": _scalar(conn, "SELECT COUNT(*) FROM source_job_records"),
        "field_provenance_rows": _scalar(conn, "SELECT COUNT(*) FROM job_field_provenance"),
        "status_history_rows": _scalar(conn, "SELECT COUNT(*) FROM job_status_history"),
        "ingestion_runs": _scalar(conn, "SELECT COUNT(*) FROM ingestion_runs"),
        "earliest_observation": _scalar(
            conn, "SELECT MIN(first_seen_at) FROM jobs", default=None),
        "current_market_cycle": current_cycle(date.today())[1],
        "strict_scope": {
            "active": strict["active_jobs"],
            "catalogue": strict["catalogue_records"],
            "inactive_by_status": strict["inactive_by_status"],
        },
        "market_cycle_known": _scalar(
            conn, "SELECT COUNT(*) FROM jobs WHERE hiring_cycle IS NOT NULL"),
        "market_cycle_breakdown": _rows(conn, """
            SELECT COALESCE(hiring_cycle,'unknown') AS cycle, COUNT(*) AS jobs
            FROM jobs GROUP BY 1 ORDER BY (cycle='unknown'), cycle DESC LIMIT 8"""),
        "field_coverage": [
            coverage("Official application URL", "official_url IS NOT NULL",
                     "The employer's own page, not the board's."),
            coverage("Deadline or rolling",
                     "deadline_date IS NOT NULL OR deadline_mode IN "
                     "('open_until_filled','rolling')",
                     "A stated closing date, or an explicit rolling statement."),
            coverage("Salary", "salary_min IS NOT NULL",
                     "A figure the posting published."),
            coverage("Track", "track_type IS NOT NULL AND track_type!='unknown'",
                     "Tenure-track, teaching, fixed-term."),
            coverage("Appointment type",
                     "appointment_type IS NOT NULL AND appointment_type!='unknown'",
                     "Continuing, visiting, adjunct, postdoc."),
            coverage("Work authorization",
                     "visa_status IS NOT NULL AND visa_status!='unknown'",
                     "What the posting said about sponsorship. Unknown is not 'no'."),
            coverage("School linked", "school_id IS NOT NULL",
                     "Resolved to a business school entity."),
            coverage("Full posting body", "LENGTH(description_excerpt)>=600",
                     "Enough text for the body-derived fields to be answerable."),
        ],
        "detail_fetches": dict(conn.execute(
            "SELECT status, COUNT(*) FROM job_detail_fetches GROUP BY 1").fetchall() or []),
        "bottleneck": (
            "Work authorization, salary, track and deadline all live in a posting's "
            "own page. Until the detail pass reads one, they stay unknown -- which "
            "is why those rows are low and why raising them is one job, not four."),
    }


def _archive_layer(conn):
    since = None
    try:
        row = conn.execute(
            "SELECT settings_json FROM faculty_job_policy_metadata "
            "WHERE policy_name='raw_source_archive'").fetchone()
        if row:
            since = json.loads(row[0]).get("available_since")
    except (sqlite3.DatabaseError, ValueError, TypeError):
        pass
    raw_bytes = _scalar(conn, "SELECT COALESCE(SUM(byte_size),0) FROM raw_source_blobs")
    stored = _scalar(conn, "SELECT COALESCE(SUM(stored_size),0) FROM raw_source_blobs")
    return {
        "available_since": since,
        "blobs": _scalar(conn, "SELECT COUNT(*) FROM raw_source_blobs"),
        "observations": _scalar(conn, "SELECT COUNT(*) FROM raw_observations"),
        "observations_without_body": _scalar(
            conn, "SELECT COUNT(*) FROM raw_observations WHERE content_hash IS NULL"),
        "raw_bytes": raw_bytes,
        "stored_bytes": stored,
        "compression": round(raw_bytes / stored, 1) if stored else None,
        "by_kind": dict(conn.execute(
            "SELECT kind, COUNT(*) FROM raw_observations GROUP BY 1").fetchall() or []),
        "why": (
            "The only asset here with a deadline. IPEDS, SED and PERM can be "
            "downloaded again in 2029; a job posting's page cannot, because the "
            "next posting replaces it. Anything observed before the date above "
            "rests on text nobody kept."),
    }


def _snapshot_layer(conn):
    from services.faculty_jobs_snapshots import stable_panel_series
    series = stable_panel_series(conn)
    daily = _rows(conn, """
        SELECT snapshot_date, active_jobs, new_jobs, closed_jobs, deadline_changed,
               source_count, reconstructed
        FROM market_snapshots
        WHERE scope='business_school' AND dimension='total'
        ORDER BY snapshot_date""")
    return {
        "days": _scalar(conn, "SELECT COUNT(DISTINCT snapshot_date) FROM market_snapshots"),
        "rows": _scalar(conn, "SELECT COUNT(*) FROM market_snapshots"),
        "earliest": _scalar(conn, "SELECT MIN(snapshot_date) FROM market_snapshots",
                            default=None),
        "reconstructed_days": _scalar(
            conn, "SELECT COUNT(DISTINCT snapshot_date) FROM market_snapshots "
                  "WHERE reconstructed=1"),
        "daily": daily,
        "stable_panel": series.get("panel", []),
        "stable_panel_size": series.get("panel_size", 0),
        "reconstruction_note": (
            "Change counts and the source panel come from history rows written on "
            "the day and are genuine. Active counts on reconstructed days are "
            "computed from today's rows -- no daily state was recorded at the time, "
            "which is why they do not move."),
        "panel_note": (
            "Compare periods over the stable panel, never over the observed count. "
            "A source added between two dates raises the count without the market "
            "moving."),
    }


def _pipeline_layer(conn):
    return {
        "programs_registered": _scalar(conn, "SELECT COUNT(*) FROM phd_program_sources"),
        "by_carnegie": _rows(conn, """
            SELECT COALESCE(carnegie_basic,0) AS carnegie, COUNT(*) AS programs
            FROM phd_program_sources GROUP BY 1 ORDER BY 1"""),
        "confirmed_urls": {
            "roster": _scalar(conn, "SELECT COUNT(*) FROM phd_program_sources "
                                    "WHERE roster_url IS NOT NULL"),
            "job_market": _scalar(conn, "SELECT COUNT(*) FROM phd_program_sources "
                                        "WHERE jmc_url IS NOT NULL"),
            "placement": _scalar(conn, "SELECT COUNT(*) FROM phd_program_sources "
                                       "WHERE placement_url IS NOT NULL"),
        },
        "snapshots": _scalar(conn, "SELECT COUNT(*) FROM phd_page_snapshots"),
        # What happened when each programme page was read. The four outcomes are
        # kept apart because only one of them is evidence: `not_found` describes
        # a website, while `blocked` and `unreachable` mean we do not know what
        # the page says.
        "discovery": _rows(conn, """
            SELECT COALESCE(status,'unchecked') AS status, COUNT(*) AS programs
            FROM phd_program_sources GROUP BY 1 ORDER BY programs DESC"""),
        "last_checked": _scalar(
            conn, "SELECT MAX(last_checked) FROM phd_program_sources", default=None),
        "layers": _rows(conn, """
            SELECT layer, COUNT(DISTINCT person_key) AS people
            FROM phd_person_observations GROUP BY 1"""),
        "why_most_urls_are_still_missing": (
            "Each programme page was read and the outcome recorded. Most seeded "
            "addresses no longer resolve -- schools reorganise their sites and "
            "there is no URL convention to fall back on -- and several origins "
            "refuse an automated reader outright. A programme with no job-market "
            "URL has a website we could not read or one that does not publish "
            "such a page; neither says anything about how many of its students "
            "are on the market."),
        "not_a_supply": (
            "Layers are reported separately and must never be summed. Enrolment is "
            "not market participation, and an explicit job-market-candidate count "
            "covers only programmes that publish one."),
    }


def _official_layer():
    if not MARKET_DB.exists():
        return {"available": False,
                "reason": "academic_market.db not found; the loaders have not run"}
    from services import ipeds_ingest, lca_ingest, sed_ingest
    conn = _read_only(MARKET_DB)
    conn.row_factory = sqlite3.Row
    try:
        ipeds_years = [r[0] for r in conn.execute(
            "SELECT DISTINCT data_year FROM ipeds_completions ORDER BY data_year")]
        sed_years = [r[0] for r in conn.execute(
            "SELECT DISTINCT data_year FROM sed_observations ORDER BY data_year")]
        perm_years = [r[0] for r in conn.execute(
            "SELECT DISTINCT fiscal_year FROM perm_faculty_cases ORDER BY fiscal_year")]
        try:
            lca_years = [r[0] for r in conn.execute(
                "SELECT DISTINCT fiscal_year FROM lca_faculty_cases ORDER BY fiscal_year")]
        except sqlite3.OperationalError:
            lca_years = []  # store predates the LCA migration

        ipeds = {"years": ipeds_years,
                 "completion_rows": _scalar(conn, "SELECT COUNT(*) FROM ipeds_completions"),
                 "institutions": _scalar(conn, "SELECT COUNT(*) FROM ipeds_institutions"),
                 "crosswalk_codes": _scalar(conn, "SELECT COUNT(*) FROM business_cip_crosswalk")}
        if ipeds_years:
            latest = max(ipeds_years)
            broad = ipeds_ingest.doctoral_production(conn, latest)
            proxy = ipeds_ingest.doctoral_production(
                conn, latest, carnegie=(ipeds_ingest.CARNEGIE_R1,))
            ipeds.update({
                "latest_year": latest,
                "broad_doctoral_production": broad["total_doctorates"],
                "research_academic_proxy_r1": proxy["total_doctorates"],
                "by_broad_field": broad["by_broad_field"],
                "caveat": broad["caveat"],
            })

        sed = {"years": sed_years,
               "observations": _scalar(conn, "SELECT COUNT(*) FROM sed_observations")}
        if sed_years:
            sed["benchmark"] = sed_ingest.business_benchmark(conn, max(sed_years))
            # Every loaded cycle, not only the newest. A single year cannot show
            # that the share of business doctorates still seeking employment at
            # graduation went from 11.8% to 18.2% while output fell 10% -- and
            # that movement is the whole reason to hold more than one year.
            sed["series"] = [sed_ingest.business_benchmark(conn, year)
                             for year in sed_years]
            sed["series_note"] = (
                "Each row is one SED cycle as published. These are national "
                "figures for business research doctorates, not a candidate pool "
                "and not institution-level; two cycles is a comparison, not a "
                "trend.")

        # Whether the years can be compared at all. DOL withdrew the college
        # and university teacher checkbox from the FY2025 public file, so that
        # year is classified by occupation code instead -- a broader net, which
        # roughly doubles the case count for reasons that have nothing to do
        # with sponsorship activity. Plotting these years on one axis would
        # show a jump that is entirely an artefact of the form changing.
        evidence_by_year = {}
        for row in conn.execute("""
                SELECT fiscal_year, faculty_evidence, COUNT(*) AS n
                FROM perm_faculty_cases GROUP BY 1, 2"""):
            evidence_by_year.setdefault(row["fiscal_year"], {})[
                row["faculty_evidence"]] = row["n"]
        flag_years = sorted(y for y, kinds in evidence_by_year.items()
                            if kinds.get("college_u_teacher_flag"))
        inferred_years = sorted(set(evidence_by_year) - set(flag_years))

        perm = {
            "fiscal_years": perm_years,
            "evidence_by_year": evidence_by_year,
            "comparable_years": flag_years,
            "inferred_years": inferred_years,
            "comparability": (
                "Not a single series. "
                + (f"FY{', FY'.join(str(y) for y in flag_years)} identify faculty by the "
                   "form's own college-and-university-teacher checkbox. " if flag_years else "")
                + (f"FY{', FY'.join(str(y) for y in inferred_years)} cannot: DOL withdrew "
                   "that field from the public file, so those years fall back to the "
                   "occupation code, which is a wider net and yields roughly twice the "
                   "cases. The difference between the years is the form changing, not "
                   "sponsorship changing." if inferred_years else "")),
            "withdrawn_fields_note": (
                "The FY2025 release also dropped country of citizenship, class of "
                "admission, and the foreign worker's institution and major -- so "
                "PhD-origin analysis stops at FY2024 rather than showing zero."),
            "faculty_cases": _scalar(conn, "SELECT COUNT(*) FROM perm_faculty_cases"),
            "by_evidence": dict(conn.execute(
                "SELECT faculty_evidence, COUNT(*) FROM perm_faculty_cases "
                "GROUP BY 1").fetchall() or []),
            "with_phd_origin": _scalar(
                conn, "SELECT COUNT(*) FROM perm_faculty_cases "
                      "WHERE phd_institution IS NOT NULL AND phd_institution!=''"),
            "matched_cases": _scalar(
                conn, "SELECT COUNT(*) FROM perm_faculty_cases "
                      "WHERE institution_id IS NOT NULL"),
            "top_fields": _rows(conn, """
                SELECT business_field AS field, COUNT(*) AS cases
                FROM perm_faculty_cases WHERE business_field IS NOT NULL
                GROUP BY 1 ORDER BY cases DESC LIMIT 8"""),
            "matching": {
                "by_method": dict(conn.execute(
                    "SELECT method, COUNT(*) FROM institution_matches "
                    "GROUP BY 1").fetchall() or []),
                "queued": _scalar(conn, "SELECT COUNT(*) FROM institution_match_queue"),
                "queue_top": _rows(conn, """
                    SELECT external_name AS name, occurrences FROM institution_match_queue
                    ORDER BY occurrences DESC LIMIT 6"""),
            },
            "caveat": (
                "PERM covers labour certifications only. EB-1B outstanding-professor "
                "petitions require none and never appear here, so these are floors on "
                "sponsorship activity. An institution's history says nothing about "
                "whether a particular job sponsors."),
        }
        # H-1B filings. Deliberately a separate block from PERM rather than a
        # combined "sponsorship" number: PERM is the permanent-residency step
        # and an LCA is the pre-petition attestation before a temporary work
        # visa. An institution can file dozens of the second and none of the
        # first, and adding them would answer neither question.
        lca = {"fiscal_years": lca_years,
               "faculty_cases": (_scalar(conn, "SELECT COUNT(*) FROM lca_faculty_cases")
                                 if lca_years else 0)}
        if lca_years:
            summary = lca_ingest.business_faculty_summary(conn)
            lca.update({
                "by_evidence": dict(conn.execute(
                    "SELECT faculty_evidence, COUNT(*) FROM lca_faculty_cases "
                    "GROUP BY 1").fetchall() or []),
                "business_soc": summary["soc_code"],
                "business_soc_title": summary["soc_title"],
                "business_totals": summary["totals"],
                "business_wages": summary["wages"],
                "top_employers": summary["top_employers"][:10],
                "by_year": _rows(conn, """
                    SELECT fiscal_year,
                           COUNT(*) AS cases,
                           SUM(CASE WHEN case_status='Certified' THEN 1 ELSE 0 END) AS certified,
                           SUM(COALESCE(new_employment,0)) AS new_employment,
                           COUNT(DISTINCT employer_name) AS employers
                    FROM lca_faculty_cases WHERE soc_code LIKE '25-1011%'
                    GROUP BY fiscal_year ORDER BY fiscal_year"""),
                "caveat": summary["caveat"],
                "versus_perm": (
                    "PERM and LCA are different steps and are not added together. "
                    "PERM is an employer sponsoring someone for permanent residency; "
                    "an LCA is the wage attestation filed before an H-1B petition. "
                    "An institution with many LCAs and no PERM cases hires "
                    "internationally on temporary status without having sponsored "
                    "anyone for a green card -- which is a real and common pattern, "
                    "not a gap in the data."),
            })

        return {
            "available": True,
            "ipeds": ipeds, "sed": sed, "perm": perm, "lca": lca,
            "releases": _rows(conn, """
                SELECT dataset, release_key, data_year, byte_size,
                       substr(sha256,1,12) AS sha, downloaded_at
                FROM source_releases WHERE status='downloaded'
                ORDER BY dataset, data_year"""),
            "failed_loads": _rows(conn, """
                SELECT dataset, release_key, status, error FROM ingest_events
                WHERE status NOT IN ('ok','running') ORDER BY id DESC LIMIT 8"""),
        }
    finally:
        conn.close()


def _coverage_layer(conn):
    """Which board carries which discipline, and what each board leaves empty.

    Kept to the top rows on purpose. The full matrix is 20 sources x 12
    disciplines x 8 fields, which is a report to read at a terminal, not a card
    to scan on a page; what belongs here is the shape -- where the market rests
    on one board, and which gaps cost the most postings.
    """
    from services.faculty_jobs_coverage_matrix import build_matrix, field_gaps

    matrix = build_matrix(conn, "business")
    gaps = field_gaps(conn, "business", matrix=matrix)
    disciplines = sorted(
        ({"discipline": name, **stats} for name, stats in matrix["by_discipline"].items()),
        key=lambda row: -row["jobs"])
    return {
        "scope": matrix["scope"],
        "basis": matrix["basis"],
        "basis_note": matrix["basis_note"],
        "sources": [
            {key: row[key] for key in
             ("source", "total_jobs", "active_jobs", "unique_jobs", "unique_share",
              "completeness_state", "last_success")}
            for row in matrix["sources"][:10]],
        "source_count": len(matrix["sources"]),
        "silent_sources": matrix["silent_sources"],
        "disciplines": disciplines,
        "gaps": gaps["gaps"][:10],
        "gap_note": gaps["note"],
        "reading_note": matrix["reading_note"],
        "concentration_note": matrix["concentration_note"],
        "folded_duplicates": matrix["folded_duplicates"],
        "single_sourced_note": matrix["single_sourced_note"],
    }


def _link_layer(conn):
    """Whether the addresses this site hands out still open.

    Reported separately from coverage because it answers a different question:
    coverage is what we know about a posting, this is whether a reader can
    reach it. And it carries the host roll-up, because the case that prompted
    it -- poms.org returning 502 on all 113 of its links at once -- is one fact
    about a publisher, not 113 postings being withdrawn.
    """
    from services import link_health

    try:
        summary = link_health.health_summary(conn)
    except sqlite3.OperationalError:
        return {"available": False,
                "reason": "link_checks table not present; the schema predates it"}
    total_links = _scalar(conn, """
        SELECT COUNT(DISTINCT source_url) FROM job_sources
        WHERE active = 1 AND source_url IS NOT NULL AND source_url != ''""")
    summary.update({
        "available": True,
        "links_total": total_links,
        "links_unchecked": max(0, total_links - summary["checked_links"]),
        "hosts_down_note": (
            "A host whose links all fail the same way is reported once, as a fact "
            "about that host. poms.org answered 502 on its root, its listing page "
            "and every one of our stored links on the same afternoon; the postings "
            "were intact when it came back."),
    })
    return summary


def _layer_holdings(faculty_conn):
    """How many rows each layer actually holds.

    Added because the layer strip said what each layer *means* and nothing
    about whether it had any data, so a layer holding 11,763 filings and one
    holding nothing looked identical -- and the red "not ..." caveat under each
    one read like a status saying "not done".
    """
    def market(sql, default=0):
        if not MARKET_DB.exists():
            return None
        conn = _read_only(MARKET_DB)
        try:
            return conn.execute(sql).fetchone()[0]
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()

    def people(layer):
        return _scalar(faculty_conn,
                       "SELECT COUNT(DISTINCT person_key) FROM phd_person_observations "
                       f"WHERE layer = '{layer}'")

    return {
        "IPEDS": {"rows": market("SELECT COUNT(*) FROM ipeds_completions"),
                  "unit": "completion rows"},
        "SED": {"rows": market("SELECT COUNT(*) FROM sed_observations"),
                "unit": "observations"},
        "Job market candidates": {"rows": people("explicit_jmc"), "unit": "people"},
        "Placements": {"rows": people("placement_observed"), "unit": "people"},
        "H-1B LCA": {"rows": market("SELECT COUNT(*) FROM lca_faculty_cases"),
                     "unit": "filings"},
        "PERM": {"rows": market("SELECT COUNT(*) FROM perm_faculty_cases"),
                 "unit": "cases"},
    }


def _layer_order(faculty_conn):
    """The supply chain, left to right, each with what it answers, what it is
    not, and how much it currently holds."""
    holdings = _layer_holdings(faculty_conn)
    layers = [
        {"layer": "IPEDS", "answers": "how many doctorates each institution awarded",
         "not": "a candidate pool"},
        {"layer": "SED", "answers": "national research-doctorate output and outcomes",
         "not": "institution-level, and not a supply"},
        {"layer": "Job market candidates",
         "answers": "who a school said was on the market",
         "not": "everyone competing"},
        {"layer": "Placements", "answers": "where someone actually went",
         "not": "complete"},
        {"layer": "H-1B LCA",
         "answers": "which employers file H-1B paperwork for faculty roles, "
                    "and at what wage",
         "not": "an approved visa, and not a hire"},
        {"layer": "PERM", "answers": "which employers have sponsored before",
         "not": "whether this job will"},
    ]
    # Why a layer is empty is a different fact from how much it holds, so the
    # two are separate fields rather than one string.
    empty_reason = {
        "Job market candidates": (
            "one programme's page is machine readable; the rest are a "
            "JavaScript shell, a landing page, or a dead address"),
        "Placements": (
            "no confirmed placement page carries per-person records yet"),
    }
    for entry in layers:
        held = holdings.get(entry["layer"], {})
        entry["rows"] = held.get("rows")
        entry["unit"] = held.get("unit")
        if not held.get("rows"):
            entry["empty_because"] = empty_reason.get(
                entry["layer"], "the loader for this layer has not run")
    return layers


def build_observatory(faculty_db=None, market_db=None):
    """The whole read model, layer by layer."""
    global MARKET_DB
    if market_db:
        MARKET_DB = Path(market_db)
    path = Path(faculty_db or FACULTY_DB)
    if not path.exists():
        return {"ok": False, "error": f"{path} not found"}
    conn = _read_only(path)
    conn.row_factory = sqlite3.Row
    try:
        return {
            "ok": True,
            "observations": _observation_layer(conn),
            "archive": _archive_layer(conn),
            "snapshots": _snapshot_layer(conn),
            "coverage": _coverage_layer(conn),
            "links": _link_layer(conn),
            "pipeline": _pipeline_layer(conn),
            "official": _official_layer(),
            "layer_order": _layer_order(conn),
        }
    finally:
        conn.close()


__all__ = ["build_observatory"]
