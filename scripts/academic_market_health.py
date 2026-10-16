#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Academic Market Data Health: what the observatory actually holds today.

Read-only. Reports each layer of the stack separately and states its coverage
alongside its counts, because a number without its coverage is the thing this
project keeps having to correct.

    python scripts/academic_market_health.py
    python scripts/academic_market_health.py --json
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import academic_market_store as store
from services import ipeds_ingest, perm_ingest, sed_ingest
from services.faculty_jobs_market_cycle import current_cycle
from services.faculty_jobs_scope import scope_counts

FACULTY_DB = ROOT / "data" / "faculty_jobs.db"
MARKET_DB = ROOT / "data" / "academic_market.db"


def _ro(path):
    return sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, timeout=30)


def _scalar(conn, sql, args=(), default=0):
    try:
        row = conn.execute(sql, args).fetchone()
    except sqlite3.DatabaseError:
        return default
    return (row[0] if row and row[0] is not None else default)


def faculty_side(path=FACULTY_DB):
    """Jobs, history, archive and field coverage."""
    if not Path(path).exists():
        return {"available": False, "reason": f"{path} not found"}
    conn = _ro(path)
    conn.row_factory = sqlite3.Row
    try:
        from services.faculty_jobs_service import _job_select
        strict = scope_counts(conn, "business_school", _job_select())
        active_where = (
            "derived_quality='accepted' AND faculty_market_eligible=1 "
            "AND business_scope='business_school' "
            "AND status IN ('open','likely_open','closing_soon')")
        total = _scalar(conn, f"SELECT COUNT(*) FROM jobs WHERE {active_where}")

        def coverage(condition):
            if not total:
                return 0.0
            n = _scalar(conn, f"SELECT COUNT(*) FROM jobs WHERE {active_where} AND ({condition})")
            return round(100.0 * n / total, 1)

        archive_available_since = None
        try:
            row = conn.execute(
                "SELECT settings_json FROM faculty_job_policy_metadata "
                "WHERE policy_name='raw_source_archive'").fetchone()
            if row:
                archive_available_since = json.loads(row[0]).get("available_since")
        except sqlite3.DatabaseError:
            pass

        return {
            "available": True,
            "schema_user_version": _scalar(conn, "PRAGMA user_version"),
            "canonical_jobs": _scalar(conn, "SELECT COUNT(*) FROM jobs"),
            "source_observations": _scalar(conn, "SELECT COUNT(*) FROM source_job_records"),
            "field_provenance_rows": _scalar(conn, "SELECT COUNT(*) FROM job_field_provenance"),
            "status_history_rows": _scalar(conn, "SELECT COUNT(*) FROM job_status_history"),
            "ingestion_runs": _scalar(conn, "SELECT COUNT(*) FROM ingestion_runs"),
            "earliest_observation": _scalar(
                conn, "SELECT MIN(first_seen_at) FROM jobs", default=None),
            "strict_scope": {
                "catalogue": strict["catalogue_records"],
                "active": strict["active_jobs"],
                "inactive_by_status": strict["inactive_by_status"],
            },
            "current_market_cycle": current_cycle(__import__("datetime").date.today())[1],
            "market_cycle_known": _scalar(
                conn, "SELECT COUNT(*) FROM jobs WHERE hiring_cycle IS NOT NULL"),
            "field_coverage_percent": {
                "official_url": coverage("official_url IS NOT NULL"),
                "deadline": coverage(
                    "deadline_date IS NOT NULL OR deadline_mode IN "
                    "('open_until_filled','rolling')"),
                "salary": coverage("salary_min IS NOT NULL"),
                "track_type": coverage("track_type IS NOT NULL AND track_type!='unknown'"),
                "appointment_type": coverage(
                    "appointment_type IS NOT NULL AND appointment_type!='unknown'"),
                "visa_status": coverage("visa_status IS NOT NULL AND visa_status!='unknown'"),
                "school_linked": coverage("school_id IS NOT NULL"),
                "body_over_600_chars": coverage("LENGTH(description_excerpt)>=600"),
            },
            "detail_fetches": dict(conn.execute(
                "SELECT status, COUNT(*) FROM job_detail_fetches GROUP BY 1").fetchall() or []),
            "raw_archive": {
                "available_since": archive_available_since,
                "blobs": _scalar(conn, "SELECT COUNT(*) FROM raw_source_blobs"),
                "observations": _scalar(conn, "SELECT COUNT(*) FROM raw_observations"),
                "stored_bytes": _scalar(conn, "SELECT COALESCE(SUM(stored_size),0) FROM raw_source_blobs"),
                "raw_bytes": _scalar(conn, "SELECT COALESCE(SUM(byte_size),0) FROM raw_source_blobs"),
            },
            "market_snapshots": {
                "rows": _scalar(conn, "SELECT COUNT(*) FROM market_snapshots"),
                "days": _scalar(conn, "SELECT COUNT(DISTINCT snapshot_date) FROM market_snapshots"),
                "earliest": _scalar(conn, "SELECT MIN(snapshot_date) FROM market_snapshots", default=None),
                "reconstructed_days": _scalar(
                    conn, "SELECT COUNT(DISTINCT snapshot_date) FROM market_snapshots "
                          "WHERE reconstructed=1"),
            },
        }
    finally:
        conn.close()


def official_side(path=MARKET_DB):
    """IPEDS, SED and PERM, each with what it can and cannot answer."""
    if not Path(path).exists():
        return {"available": False, "reason": f"{path} not found; run the loaders"}
    conn = _ro(path)
    conn.row_factory = sqlite3.Row
    try:
        releases = [dict(row) for row in conn.execute(
            "SELECT dataset, release_key, data_year, byte_size, substr(sha256,1,12) AS sha, "
            "downloaded_at, status FROM source_releases ORDER BY dataset, data_year")]
        failed = [dict(row) for row in conn.execute(
            "SELECT dataset, release_key, status, error FROM ingest_events "
            "WHERE status NOT IN ('ok','running') ORDER BY id DESC LIMIT 10")]
        ipeds_years = [row[0] for row in conn.execute(
            "SELECT DISTINCT data_year FROM ipeds_completions ORDER BY data_year")]
        sed_years = [row[0] for row in conn.execute(
            "SELECT DISTINCT data_year FROM sed_observations ORDER BY data_year")]
        perm_years = [row[0] for row in conn.execute(
            "SELECT DISTINCT fiscal_year FROM perm_faculty_cases ORDER BY fiscal_year")]

        result = {
            "available": True,
            "releases": releases,
            "failed_events": failed,
            "ipeds": {
                "years": ipeds_years,
                "completion_rows": _scalar(conn, "SELECT COUNT(*) FROM ipeds_completions"),
                "institution_rows": _scalar(conn, "SELECT COUNT(*) FROM ipeds_institutions"),
                "crosswalk_rows": _scalar(conn, "SELECT COUNT(*) FROM business_cip_crosswalk"),
            },
            "sed": {
                "years": sed_years,
                "observations": _scalar(conn, "SELECT COUNT(*) FROM sed_observations"),
            },
            "perm": {
                "fiscal_years": perm_years,
                "faculty_cases": _scalar(conn, "SELECT COUNT(*) FROM perm_faculty_cases"),
                "by_evidence": dict(conn.execute(
                    "SELECT faculty_evidence, COUNT(*) FROM perm_faculty_cases "
                    "GROUP BY 1").fetchall() or []),
                "with_phd_origin": _scalar(
                    conn, "SELECT COUNT(*) FROM perm_faculty_cases "
                          "WHERE phd_institution IS NOT NULL AND phd_institution!=''"),
                "matched_institutions": _scalar(
                    conn, "SELECT COUNT(*) FROM perm_faculty_cases "
                          "WHERE institution_id IS NOT NULL"),
            },
            "institution_matching": {
                "matched_names": _scalar(conn, "SELECT COUNT(*) FROM institution_matches"),
                "by_method": dict(conn.execute(
                    "SELECT method, COUNT(*) FROM institution_matches "
                    "GROUP BY 1").fetchall() or []),
                "queued_for_review": _scalar(
                    conn, "SELECT COUNT(*) FROM institution_match_queue"),
                "queue_top": [dict(row) for row in conn.execute(
                    "SELECT external_name, occurrences FROM institution_match_queue "
                    "ORDER BY occurrences DESC LIMIT 5")],
            },
        }
        if ipeds_years:
            latest = max(ipeds_years)
            broad = ipeds_ingest.doctoral_production(conn, latest)
            proxy = ipeds_ingest.doctoral_production(
                conn, latest, carnegie=(ipeds_ingest.CARNEGIE_R1,))
            result["ipeds"]["broad_doctoral_production"] = {
                "year": latest, "total": broad["total_doctorates"]}
            result["ipeds"]["research_academic_proxy_r1"] = {
                "year": latest, "total": proxy["total_doctorates"]}
        if sed_years:
            result["sed"]["benchmark"] = sed_ingest.business_benchmark(conn, max(sed_years))
        return result
    finally:
        conn.close()


def pipeline_side(path=FACULTY_DB):
    """The PhD panel, if its tables exist yet."""
    if not Path(path).exists():
        return {"available": False}
    conn = _ro(path)
    conn.row_factory = sqlite3.Row
    try:
        registered = _scalar(conn, "SELECT COUNT(*) FROM phd_program_sources", default=None)
        if registered is None:
            return {"available": False, "reason": "panel tables not created yet"}
        return {
            "available": True,
            "programs_registered": registered,
            "snapshots": _scalar(conn, "SELECT COUNT(*) FROM phd_page_snapshots"),
            "cycles": [row[0] for row in conn.execute(
                "SELECT DISTINCT market_cycle FROM phd_page_snapshots")],
            "note": "Systematic JMC tracking begins 2026-27; earlier cycles cannot "
                    "be reconstructed because schools replace these pages each year.",
        }
    finally:
        conn.close()


def render(report):
    out = []
    add = out.append
    add("=" * 78)
    add("ACADEMIC MARKET DATA HEALTH")
    add("=" * 78)

    jobs = report["faculty"]
    if not jobs.get("available"):
        add(f"\nFaculty jobs: UNAVAILABLE ({jobs.get('reason')})")
    else:
        archive = jobs["raw_archive"]
        snapshots = jobs["market_snapshots"]
        add(f"\nFaculty jobs                schema v{jobs['schema_user_version']}")
        add(f"  canonical jobs            {jobs['canonical_jobs']:,}")
        add(f"  source observations       {jobs['source_observations']:,}")
        add(f"  field provenance rows     {jobs['field_provenance_rows']:,}")
        add(f"  status history rows       {jobs['status_history_rows']:,}")
        add(f"  earliest observation      {jobs['earliest_observation']}")
        add(f"  current market cycle      {jobs['current_market_cycle']}")
        add(f"  jobs with a known cycle   {jobs['market_cycle_known']:,}")
        strict = jobs["strict_scope"]
        add(f"  strict scope              {strict['active']:,} active of "
            f"{strict['catalogue']:,} catalogue")
        add(f"    not active              {strict['inactive_by_status'] or 'none'}")
        add("")
        add("  Raw source archive")
        add(f"    available since         {archive['available_since'] or 'NOT ENABLED'}")
        add(f"    blobs / observations    {archive['blobs']:,} / {archive['observations']:,}")
        if archive["stored_bytes"]:
            add(f"    stored / raw            {archive['stored_bytes']/1048576:.1f} MB / "
                f"{archive['raw_bytes']/1048576:.1f} MB "
                f"({archive['raw_bytes']/archive['stored_bytes']:.1f}x)")
        add("")
        add("  Market snapshots")
        add(f"    days / rows             {snapshots['days']:,} / {snapshots['rows']:,}")
        add(f"    earliest                {snapshots['earliest'] or 'none written'}")
        add(f"    reconstructed days      {snapshots['reconstructed_days']:,}"
            "   (computed from history, not observed on the day)")
        add("")
        add("  Field coverage, strict active scope")
        for field, percent in jobs["field_coverage_percent"].items():
            bar = "#" * int(round(percent / 4))
            add(f"    {field:<22} {percent:5.1f}%  {bar}")
        add(f"  detail fetch attempts     {jobs['detail_fetches'] or 'none yet'}")

    official = report["official"]
    add("")
    if not official.get("available"):
        add(f"Official reference data: UNAVAILABLE ({official.get('reason')})")
    else:
        ipeds = official["ipeds"]
        add("Official reference data")
        add(f"  IPEDS years               {ipeds['years'] or 'none'}")
        add(f"    completion rows         {ipeds['completion_rows']:,}")
        add(f"    institutions            {ipeds['institution_rows']:,}")
        add(f"    CIP crosswalk           {ipeds['crosswalk_rows']} codes")
        if "broad_doctoral_production" in ipeds:
            broad = ipeds["broad_doctoral_production"]
            proxy = ipeds["research_academic_proxy_r1"]
            add(f"    broad doctoral production ({broad['year']})  {broad['total']:,}")
            add(f"    research academic proxy, R1 only   {proxy['total']:,}")
        sed = official["sed"]
        add(f"  SED years                 {sed['years'] or 'none'}")
        add(f"    observations            {sed['observations']:,}")
        if "benchmark" in sed:
            b = sed["benchmark"]
            add(f"    business doctorates     {b['business_research_doctorates']}")
            add(f"    temporary visa share    {b['temporary_visa_share']}%")
            add(f"    realized TT outcomes    {b['realized_tt_outcomes_est']}"
                "   (an outcome, NOT candidate supply)")
        perm = official["perm"]
        add(f"  PERM fiscal years         {perm['fiscal_years'] or 'none'}")
        add(f"    faculty cases           {perm['faculty_cases']:,}")
        add(f"    by evidence             {perm['by_evidence'] or 'none'}")
        add(f"    with PhD origin         {perm['with_phd_origin']:,}")
        cases = perm["faculty_cases"] or 0
        rate = (100.0 * perm["matched_institutions"] / cases) if cases else 0.0
        add(f"    matched to institutions {perm['matched_institutions']:,}  ({rate:.1f}%)")
        matching = official.get("institution_matching") or {}
        if matching:
            add(f"    match methods           {matching['by_method'] or 'none'}")
            add(f"    queued for review       {matching['queued_for_review']:,}"
                "   (unmatched names are queued, never dropped)")
            for row in matching["queue_top"][:3]:
                add(f"      {row['external_name'][:52]:<52} {row['occurrences']}")
        add("")
        add("  Releases loaded")
        for release in official["releases"]:
            add(f"    {release['dataset']:<20} {release['release_key']:<22} "
                f"{release['data_year']}  {(release['byte_size'] or 0)/1048576:6.1f} MB  "
                f"sha={release['sha']}")
        if official["failed_events"]:
            add("")
            add("  FAILED LOADS (recorded, not silently zero)")
            for event in official["failed_events"]:
                add(f"    {event['dataset']:<20} {event['status']:<8} {(event['error'] or '')[:60]}")

    pipeline = report["pipeline"]
    add("")
    if pipeline.get("available"):
        add("PhD pipeline panel")
        add(f"  programmes registered     {pipeline['programs_registered']}")
        add(f"  page snapshots            {pipeline['snapshots']}")
        add(f"  cycles captured           {pipeline['cycles'] or 'none'}")
    else:
        add(f"PhD pipeline panel: not started ({pipeline.get('reason', 'no tables')})")

    add("")
    add("-" * 78)
    add("What these numbers are not")
    add("  IPEDS doctoral production is not a candidate pool. AWLEVEL 17 is the")
    add("  institution's own report and includes practitioner and online doctorates.")
    add("  SED realized TT outcomes count people who landed a post, not people who")
    add("  competed: everyone still seeking, every postdoc, every foreign-trained")
    add("  candidate and every lateral move is missing.")
    add("  PERM covers labour certifications only; EB-1B needs none, so these are")
    add("  floors on sponsorship activity and say nothing about a specific job.")
    add("  Enrolled doctoral students are not job-market candidates.")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the raw report")
    parser.add_argument("--faculty-db", default=str(FACULTY_DB))
    parser.add_argument("--market-db", default=str(MARKET_DB))
    args = parser.parse_args(argv)

    report = {
        "faculty": faculty_side(args.faculty_db),
        "official": official_side(args.market_db),
        "pipeline": pipeline_side(args.faculty_db),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
