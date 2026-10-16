# -*- coding: utf-8 -*-
"""Generate the Academic Career status report and audit snapshot.

Every figure is read from the live database at run time. The point is that the
report cannot drift from reality the way a hand-written status document does:
if a number here is wrong, the query is wrong, and the query is visible.

    python scripts/academic_career_status_report.py            # print
    python scripts/academic_career_status_report.py --write    # also write docs/ + outputs/
"""

import argparse
import csv
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACULTY_DB = os.path.join(ROOT, "data", "faculty_jobs.db")
ASTAR_DB = os.path.join(ROOT, "pboc_data.db")

from services.faculty_jobs_scope import (  # noqa: E402
    active_filter_definition, active_sql, catalogue_sql,
)
from services.faculty_jobs_query import (  # noqa: E402
    DEFAULT_MARKET_SCOPES, DEFAULT_MARKET_STATUSES,
)
from services.faculty_jobs_normalizer import COUNTRY_ALIASES  # noqa: E402
from services.faculty_jobs_sources.aacsb import AACSB_SCAN_RULE_VERSION  # noqa: E402

REPORT_VERSION = "academic_career_status_v8_20260922"
# Invariants that must be zero for the report to pass. Anything not listed here
# is a review signal: it is still printed, still counted, and still shown in the
# verdict, but it does not claim the dataset is broken. The distinction exists
# because some same-name institution pairs are genuinely separate campuses
# (CUHK Shenzhen vs Hong Kong, ESCP London vs Turin) and must not be merged.
_BLOCKING_INVARIANTS = (
    "jobs_on_retired_school", "jobs_on_retired_institution",
    "current_schools_on_retired_institution",
    "source_links_without_job", "graduate_assistant_active",
    "duplicate_current_institutions", "duplicate_current_institution_country_keys",
    "duplicate_current_schools", "source_identity_duplicates",
    "entity_redirect_cycles", "contaminated_current_institutions",
    "aacsb_false_positive_active_default", "aacsb_active_without_current_evidence",
    "active_aacsb_false_positive_links", "active_aacsb_source_without_partition",
    "country_prefixed_slash_city", "board_default_region_leak",
    "schema_version_mismatch",
)
REPORT_SCOPE = "business_school"
MARKET = active_sql(REPORT_SCOPE, "")
HISTORICAL_ELIGIBLE = catalogue_sql(REPORT_SCOPE, "")


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def one(conn, sql, args=()):
    row = conn.execute(sql, args).fetchone()
    return row[0] if row else 0


def group(conn, sql, args=()):
    return {str(row[0]): row[1] for row in conn.execute(sql, args).fetchall()}


def database_fingerprint(path):
    """Hash the database plus any live SQLite sidecars visible to the reader."""
    path = str(path)
    digest = hashlib.sha256()
    observed = []
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if not os.path.exists(candidate):
            continue
        stat = os.stat(candidate)
        observed.append({"path": suffix or "main", "bytes": stat.st_size,
                         "mtime_ns": stat.st_mtime_ns})
        digest.update((suffix or "main").encode("utf-8"))
        with open(candidate, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return {"sha256": digest.hexdigest(), "files": observed}


def git_snapshot():
    try:
        commit = subprocess.check_output(
            ["git", "-C", ROOT, "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    return commit


def git_worktree_state():
    """Expose whether the reported code is ahead of the recorded HEAD."""
    try:
        status = subprocess.check_output(
            ["git", "-C", ROOT, "status", "--short", "--untracked-files=all"],
            text=True, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return {"dirty": None, "changed_paths": None}
    return {
        "dirty": bool(status.strip()),
        "changed_paths": len([line for line in status.splitlines() if line.strip()]),
    }


def _duplicate_current_count(conn, table, country=False):
    if table == "institutions":
        key = "normalized_name,country_code" if country else "normalized_name"
        return one(conn, f"""
            SELECT COALESCE(SUM(n-1),0) FROM (
              SELECT COUNT(*) AS n FROM institutions
              WHERE is_current=1 AND normalized_name IS NOT NULL AND normalized_name!=''
              GROUP BY {key} HAVING COUNT(*)>1
            )
        """)
    return one(conn, """
        SELECT COALESCE(SUM(n-1),0) FROM (
          SELECT COUNT(*) AS n FROM business_schools
          WHERE is_current=1 AND institution_id IS NOT NULL
          GROUP BY institution_id,normalized_name HAVING COUNT(*)>1
        )
    """)


def _cycle_count(conn, table):
    rows = conn.execute(f"SELECT id FROM {table} WHERE merged_into_id IS NOT NULL").fetchall()
    cycles = 0
    for row in rows:
        seen = set()
        current = int(row["id"])
        while current:
            if current in seen:
                # Only a repeated redirect node is a cycle. Reaching a current
                # survivor is the normal, valid terminal state.
                cycles += 1
                break
            seen.add(current)
            target = conn.execute(
                f"SELECT merged_into_id,is_current FROM {table} WHERE id=?", (current,)
            ).fetchone()
            if not target:
                break
            if int(target["is_current"] or 0) == 1:
                break
            current = int(target["merged_into_id"] or 0)
    return cycles


def collect(faculty_path=FACULTY_DB, astar_path=ASTAR_DB):
    faculty_path = str(faculty_path)
    astar_path = str(astar_path)
    generated_at = now_utc()
    run_id = str(uuid.uuid4())
    conn = connect(faculty_path)
    try:
        # One read transaction gives every report section one coherent SQLite
        # snapshot. The JSON and Markdown writers both consume this same
        # in-memory object later; neither writer re-queries the database.
        conn.execute("BEGIN")
        fingerprint = database_fingerprint(faculty_path)
        schema_version = one(conn, "SELECT MAX(version) FROM faculty_job_migrations")
        sqlite_user_version = one(conn, "PRAGMA user_version")
        snapshot_id = hashlib.sha256(
            f"{fingerprint['sha256']}|{schema_version}".encode("utf-8")
        ).hexdigest()
        country_prefixes = sorted({
            str(alias).casefold()
            for code, aliases in COUNTRY_ALIASES.items()
            for alias in (code, *aliases)
        })
        country_prefix_placeholders = ",".join("?" for _ in country_prefixes)
        report = {
            "run_id": run_id,
            "generated_at": generated_at,
            "git_commit": git_snapshot(),
            "git_worktree": git_worktree_state(),
            "report_version": REPORT_VERSION,
            "active_filter": {
                **active_filter_definition(REPORT_SCOPE),
                "sql": MARKET,
                "version": "faculty_market_v3_20260827",
            },
            "db_snapshot": {
                "snapshot_id": snapshot_id,
                "sha256": fingerprint["sha256"],
                "files": fingerprint["files"],
                "path": faculty_path,
            },
            "integrity": {
                "quick_check": one(conn, "PRAGMA quick_check"),
                "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
                "schema_version": schema_version,
                "sqlite_user_version": sqlite_user_version,
            },
            "grain": {
                "jobs": one(conn, "SELECT COUNT(*) FROM jobs"),
                "source_records": one(conn, "SELECT COUNT(*) FROM source_job_records"),
                "job_source_links": one(conn, "SELECT COUNT(*) FROM job_sources"),
                "school_evidence": one(conn, "SELECT COUNT(*) FROM school_evidence"),
                "repair_audit_rows": one(conn, "SELECT COUNT(*) FROM faculty_job_repair_audit"),
            },
            "scope": group(conn, "SELECT COALESCE(business_scope,'unknown'), COUNT(*) FROM jobs GROUP BY 1"),
            "market": {
                "jobs": one(conn, f"SELECT COUNT(*) FROM jobs WHERE {MARKET}"),
                "historical_eligible_jobs": one(conn, f"SELECT COUNT(*) FROM jobs WHERE {HISTORICAL_ELIGIBLE}"),
                "status_breakdown": group(
                    conn, f"SELECT COALESCE(status,'unknown'), COUNT(*) FROM jobs WHERE {HISTORICAL_ELIGIBLE} GROUP BY 1"),
                "active_status_breakdown": group(
                    conn, f"SELECT COALESCE(status,'unknown'), COUNT(*) FROM jobs WHERE {MARKET} GROUP BY 1"),
                "with_school_entity": one(
                    conn, f"SELECT COUNT(*) FROM jobs WHERE {MARKET} AND school_id IS NOT NULL"),
                "with_city_or_state": one(
                    conn, f"SELECT COUNT(*) FROM jobs WHERE {MARKET} AND ((city IS NOT NULL "
                          "AND city!='') OR (state_province IS NOT NULL AND state_province!=''))"),
                "with_official_url": one(
                    conn, f"SELECT COUNT(*) FROM jobs WHERE {MARKET} AND official_url IS NOT NULL "
                          "AND official_url!=''"),
                "with_enabled_source": one(conn, f"""
                    SELECT COUNT(*) FROM jobs j WHERE {MARKET}
                      AND EXISTS (SELECT 1 FROM job_sources js JOIN sources s ON s.id=js.source_id
                                  WHERE js.job_id=j.id AND js.active=1 AND s.enabled=1)"""),
                "with_disabled_or_opt_in_source_only": one(conn, f"""
                    SELECT COUNT(*) FROM jobs j WHERE {MARKET}
                      AND EXISTS (SELECT 1 FROM job_sources js
                                  WHERE js.job_id=j.id AND js.active=1)
                      AND NOT EXISTS (SELECT 1 FROM job_sources js JOIN sources s ON s.id=js.source_id
                                      WHERE js.job_id=j.id AND js.active=1 AND s.enabled=1)"""),
                "with_no_active_source": one(conn, f"""
                    SELECT COUNT(*) FROM jobs j WHERE {MARKET}
                      AND NOT EXISTS (SELECT 1 FROM job_sources js
                                      WHERE js.job_id=j.id AND js.active=1)"""),
                "source_snapshot_policy": (
                    "Active job links include enabled-source observations and preserved "
                    "disabled/opt-in/manual snapshots; source metadata is not a row filter."
                ),
            },
            "location_evidence": group(
                conn, "SELECT COALESCE(location_evidence,'none'), COUNT(*) FROM jobs "
                      f"WHERE {MARKET} GROUP BY 1"),
            "visa_status": group(
                conn, "SELECT COALESCE(visa_status,'unknown'), COUNT(*) FROM jobs GROUP BY 1"),
            "entities": {
                "institutions_current": one(
                    conn, "SELECT COUNT(*) FROM institutions WHERE is_current=1"),
                "institutions_retired": one(
                    conn, "SELECT COUNT(*) FROM institutions WHERE is_current=0"),
                "schools_current": one(
                    conn, "SELECT COUNT(*) FROM business_schools WHERE is_current=1"),
                "schools_retired": one(
                    conn, "SELECT COUNT(*) FROM business_schools WHERE is_current=0"),
                "institutions_with_ror": one(
                    conn, "SELECT COUNT(*) FROM institutions WHERE is_current=1 AND ror IS NOT NULL"),
            },
            "tiers": group(
                conn, "SELECT COALESCE(business_research_tier,'NULL'), COUNT(*) "
                      "FROM business_schools WHERE is_current=1 GROUP BY 1"),
            "school_evidence": {
                "all": group(conn, "SELECT evidence_type, COUNT(*) FROM school_evidence GROUP BY 1"),
                "current": group(conn, "SELECT evidence_type, COUNT(*) FROM school_evidence WHERE is_current=1 GROUP BY 1"),
                "historical": group(conn, "SELECT evidence_type, COUNT(*) FROM school_evidence WHERE is_current=0 GROUP BY 1"),
            },
            "duplicates": {
                "open": one(conn, "SELECT COUNT(*) FROM possible_duplicates WHERE resolved=0"),
                "resolved": one(conn, "SELECT COUNT(*) FROM possible_duplicates WHERE resolved=1"),
                "by_basis": group(
                    conn, "SELECT match_basis, COUNT(*) FROM possible_duplicates "
                          "WHERE resolved=0 GROUP BY 1"),
            },
            "entity_resolution": {
                "pending": one(conn, "SELECT COUNT(*) FROM entity_resolution_queue WHERE status='pending'"),
                "with_conflicting_identity": one(
                    conn, "SELECT COUNT(*) FROM entity_resolution_queue "
                          "WHERE status='pending' AND conflicting_identity_json!='{}'"),
                "impacted_jobs": one(
                    conn, "SELECT COALESCE(SUM(impacted_jobs),0) FROM entity_resolution_queue WHERE status='pending'"),
                "impacted_schools": one(
                    conn, "SELECT COALESCE(SUM(impacted_schools),0) FROM entity_resolution_queue WHERE status='pending'"),
                "impacted_evidence": one(
                    conn, "SELECT COALESCE(SUM(impacted_evidence),0) FROM entity_resolution_queue WHERE status='pending'"),
            },
            "aacsb_roster": {
                "active": one(conn, "SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1"),
                "active_with_website": one(
                    conn, "SELECT COUNT(*) FROM aacsb_directory_schools "
                         "WHERE active=1 AND official_website IS NOT NULL AND official_website!=''"),
                "inactive": one(conn, "SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=0"),
                "pending_miss_streak": one(
                    conn, "SELECT COUNT(*) FROM aacsb_directory_schools "
                          "WHERE consecutive_missing_runs>0 AND active=1"),
                "active_current_evidence": one(conn, """
                    SELECT COUNT(*) FROM aacsb_directory_schools d
                    JOIN business_schools bs ON bs.id=d.linked_business_school_id
                    WHERE d.active=1 AND bs.is_current=1
                      AND EXISTS (SELECT 1 FROM school_evidence se
                                  WHERE se.school_id=bs.id AND se.evidence_type='AACSB' AND se.is_current=1)"""),
                "job_partitions_active": one(conn, "SELECT COUNT(*) FROM aacsb_job_source_partitions WHERE active=1"),
                "job_partitions_inactive": one(conn, "SELECT COUNT(*) FROM aacsb_job_source_partitions WHERE active=0"),
                "complete_history_rows": one(conn, "SELECT COUNT(*) FROM aacsb_scan_history WHERE reconciliation_complete=1"),
                "complete_current_rule_history_rows": one(
                    conn, "SELECT COUNT(DISTINCT directory_school_id) FROM aacsb_scan_history "
                          "WHERE reconciliation_complete=1 AND scan_rule_version=?",
                    (AACSB_SCAN_RULE_VERSION,)),
                "stale_or_unchecked_websites": one(
                    conn, "SELECT COUNT(*) FROM aacsb_directory_schools "
                          "WHERE active=1 AND official_website IS NOT NULL AND official_website!='' "
                          "AND (website_checked_at IS NULL OR COALESCE(scan_rule_version,'')!=?)",
                    (AACSB_SCAN_RULE_VERSION,)),
                "scan_rule_version": AACSB_SCAN_RULE_VERSION,
            },
            "invariants": {},
        }
        report["aacsb_roster"]["incomplete_current_rule_schools"] = max(
            0,
            report["aacsb_roster"]["active_with_website"]
            - report["aacsb_roster"]["complete_current_rule_history_rows"],
        )
        report["aacsb_roster"]["complete_current_rule_schools"] = report[
            "aacsb_roster"]["complete_current_rule_history_rows"]
        report["invariants"]["jobs_on_retired_school"] = one(conn, """
            SELECT COUNT(*) FROM jobs j JOIN business_schools bs ON bs.id=j.school_id
            WHERE bs.is_current=0""")
        report["invariants"]["jobs_on_retired_institution"] = one(conn, """
            SELECT COUNT(*) FROM jobs j JOIN institutions i ON i.id=j.institution_id
            WHERE i.is_current=0""")
        report["invariants"]["current_schools_on_retired_institution"] = one(conn, """
            SELECT COUNT(*) FROM business_schools bs
            JOIN institutions i ON i.id=bs.institution_id
            WHERE bs.is_current=1 AND i.is_current=0""")
        report["invariants"]["source_links_without_job"] = one(conn, """
            SELECT COUNT(*) FROM job_sources js
            LEFT JOIN jobs j ON j.id=js.job_id WHERE j.id IS NULL""")
        report["invariants"]["graduate_assistant_active"] = one(
            conn, f"SELECT COUNT(*) FROM jobs WHERE {MARKET} AND lower(title_raw) LIKE '%graduate assistant%'"
        )
        # Country is part of the available institution identity. Same-name
        # rows in different countries are retained as a reviewable conflict,
        # never silently merged; duplicate current identity *keys* must still
        # be zero.
        report["invariants"]["duplicate_current_institutions"] = _duplicate_current_count(
            conn, "institutions", country=True)
        report["invariants"]["current_institution_name_country_conflicts"] = one(conn, """
            SELECT COALESCE(SUM(n-1),0) FROM (
              SELECT normalized_name,COUNT(*) AS n
              FROM institutions
              WHERE is_current=1 AND normalized_name IS NOT NULL AND normalized_name!=''
              GROUP BY normalized_name HAVING COUNT(DISTINCT COALESCE(country_code,''))>1
            )
        """)
        report["invariants"]["duplicate_current_institution_country_keys"] = _duplicate_current_count(
            conn, "institutions", country=True)
        report["invariants"]["duplicate_current_schools"] = _duplicate_current_count(conn, "business_schools")
        report["invariants"]["source_identity_duplicates"] = one(conn, """
            SELECT COALESCE(SUM(n-1),0) FROM (
              SELECT COUNT(*) AS n FROM job_sources GROUP BY source_id,source_job_id HAVING COUNT(*)>1
            )""")
        report["invariants"]["entity_redirect_cycles"] = (
            _cycle_count(conn, "institutions") + _cycle_count(conn, "business_schools")
        )
        report["invariants"]["contaminated_current_institutions"] = one(conn, """
            SELECT COUNT(*) FROM institutions
            WHERE is_current=1 AND (
              official_name IN ('College of Busines','Miami University Police',
                                'Ohio Not Specified Miami University','Management. University',
                                'Technology Management. University','Business Analytics. University')
              OR (length(official_name)>180 AND lower(official_name) LIKE '%akadeus%')
              OR lower(official_name) LIKE '%personal data protection policy%'
              OR lower(official_name) LIKE '%previously viewed%'
            )""")
        report["invariants"]["aacsb_false_positive_active_default"] = one(
            conn,
            f"""SELECT COUNT(DISTINCT j.id) FROM jobs j
                JOIN job_sources js ON js.job_id=j.id AND js.active=1
                JOIN sources s ON s.id=js.source_id AND s.name='aacsb_official'
                JOIN source_record_decisions d
                  ON d.source_id=js.source_id AND d.source_job_id=js.source_job_id
                WHERE d.decision='false_positive' AND d.is_current=1 AND {MARKET}""",
        )
        report["invariants"]["aacsb_active_without_current_evidence"] = one(conn, """
            SELECT COUNT(*) FROM aacsb_directory_schools d
            JOIN business_schools bs ON bs.id=d.linked_business_school_id
            WHERE d.active=1 AND bs.is_current=1
              AND NOT EXISTS (SELECT 1 FROM school_evidence se
                              WHERE se.school_id=bs.id AND se.evidence_type='AACSB' AND se.is_current=1)""")
        report["invariants"]["active_aacsb_false_positive_links"] = one(
            conn,
            """SELECT COUNT(*) FROM job_sources js
                JOIN sources s ON s.id=js.source_id AND s.name='aacsb_official'
                JOIN source_record_decisions d
                  ON d.source_id=js.source_id AND d.source_job_id=js.source_job_id
                WHERE js.active=1 AND d.decision='false_positive' AND d.is_current=1""",
        )
        report["invariants"]["active_aacsb_source_without_partition"] = one(conn, """
            SELECT COUNT(*) FROM job_sources js
            JOIN sources s ON s.id=js.source_id AND s.name='aacsb_official'
            LEFT JOIN aacsb_job_source_partitions p
              ON p.source_id=js.source_id AND p.source_job_id=js.source_job_id
            WHERE js.active=1 AND p.id IS NULL""")
        report["invariants"]["country_prefixed_slash_city"] = one(
            conn,
            f"""SELECT COUNT(*) FROM jobs
                 WHERE instr(COALESCE(city,''),'/')>0
                   AND lower(trim(substr(city,1,instr(city,'/')-1)))
                       IN ({country_prefix_placeholders})""",
            country_prefixes,
        )
        report["invariants"]["board_default_region_leak"] = one(conn, """
            SELECT COUNT(*) FROM jobs
            WHERE location_evidence='source_region_only_unknown_country'
              AND (
                COALESCE(country_code,'')!='' OR COALESCE(country,'')!=''
                OR COALESCE(region_group,'Other')!='Other'
              )""")
        report["invariants"]["schema_version_mismatch"] = int(
            int(schema_version or 0) != int(sqlite_user_version or 0))
        schema_current = not report["invariants"]["schema_version_mismatch"]
        conn.commit()
    finally:
        conn.close()

    # Every scope, as the product actually serves it, plus the parity that the
    # surfaces were failing: list, summary, CSV and analytics answering one
    # query with four numbers.
    from services.faculty_jobs_scope import scope_counts as _scope_counts
    from services.faculty_jobs_service import (
        _job_select as _select, build_faculty_job_summary as _summary,
        build_faculty_jobs_payload as _payload, build_job_market_analytics as _analytics,
        export_faculty_jobs_csv as _csv,
    )
    if schema_current:
        scope_report = {}
        parity_report = {}
        scope_conn = connect(faculty_path)
        try:
            for scope_name in ("business_school", "business", "all"):
                scope_report[scope_name] = _scope_counts(scope_conn, scope_name, _select())
        finally:
            scope_conn.close()
        for scope_name in ("business_school", "business", "all"):
            query = {"scope": scope_name}
            listed = _payload(faculty_path, query)["pagination"]["total"]
            summary = _summary(faculty_path, query)["summary"]
            analytics = _analytics(faculty_path, query)["analytics"]
            # Quoted evidence and application materials can span physical lines.
            # Count CSV records, never newline-delimited pieces of one posting.
            csv_rows = sum(1 for _ in csv.DictReader(
                io.StringIO(_csv(faculty_path, query).lstrip('\ufeff'))))
            parity_report[scope_name] = {
                "list_total": listed,
                "summary_matching_records": summary.get("matching_records"),
                "summary_active_jobs": summary.get("active_jobs"),
                "csv_rows": csv_rows,
                "analytics_active_jobs": analytics.get("active_jobs"),
                "analytics_by_region_sum": sum(i["count"] for i in analytics.get("by_region", [])),
                "analytics_by_discipline_sum": sum(
                    i["count"] for i in analytics.get("by_discipline", [])),
                "active_filter_sql": analytics.get("active_filter_sql"),
                "catalogue_parity": listed == summary.get("matching_records") == csv_rows,
                "analytics_parity": (
                    analytics.get("active_jobs")
                    == sum(i["count"] for i in analytics.get("by_region", []))
                    == sum(i["count"] for i in analytics.get("by_discipline", []))),
            }
        report["scopes"] = scope_report
        report["surface_parity"] = parity_report
        report["surface_parity_status"] = {"status": "verified"}
    else:
        report["scopes"] = {}
        report["surface_parity"] = {}
        report["surface_parity_status"] = {
            "status": "unavailable",
            "reason": "schema user_version does not match the migration ledger; API parity was not executed",
        }

    detail_conn = connect(faculty_path)
    try:
        report["detail_enrichment"] = {
            row["status"]: int(row["n"]) for row in detail_conn.execute(
                "SELECT status, COUNT(*) AS n FROM job_detail_fetches GROUP BY 1")
        }
        from services.faculty_jobs_write_guard import discover_private_tables, table_counts
        private = discover_private_tables(detail_conn)
        report["private_state"] = table_counts(detail_conn, private)
    finally:
        detail_conn.close()

    report["astar"] = {"available": os.path.exists(astar_path)}
    if report["astar"]["available"]:
        astar = connect(astar_path)
        try:
            total = one(astar, "SELECT COUNT(*) FROM astar_articles")
            checked = one(astar, "SELECT COUNT(*) FROM astar_articles "
                                 "WHERE affiliation_status IS NOT NULL")
            report["astar"].update({
                "articles": total,
                "affiliation_checked": checked,
                "affiliation_coverage_pct": round(100.0 * checked / total, 2) if total else 0.0,
                "distinct_institutions": one(
                    astar, "SELECT COUNT(DISTINCT institution_openalex_id) "
                           "FROM astar_article_affiliations WHERE institution_openalex_id!=''"),
                "coverage_by_year": {
                    str(row[0]): round(100.0 * row[1] / row[2], 1) if row[2] else 0.0
                    for row in astar.execute("""
                        SELECT publication_year,
                               SUM(CASE WHEN affiliation_status IS NOT NULL THEN 1 ELSE 0 END),
                               COUNT(*)
                        FROM astar_articles WHERE publication_year IS NOT NULL
                        GROUP BY publication_year ORDER BY publication_year""")},
            })
        finally:
            astar.close()
    error_keys = _BLOCKING_INVARIANTS
    warnings = []
    if not report["astar"]["available"]:
        warnings.append("A* corpus is unavailable in this runtime; no new footprint coverage can be verified.")
    elif report["astar"].get("affiliation_coverage_pct", 0) < 100:
        warnings.append(
            f"A* affiliation coverage is {report['astar'].get('affiliation_coverage_pct', 0)}%; "
            "school counts remain institution-level floors."
        )
    if report["aacsb_roster"]["pending_miss_streak"]:
        warnings.append(
            f"{report['aacsb_roster']['pending_miss_streak']} AACSB roster rows have a pending "
            "missing streak and remain active until three complete runs."
        )
    aacsb_website_total = report["aacsb_roster"].get("active_with_website", 0)
    aacsb_complete = report["aacsb_roster"].get("complete_current_rule_history_rows", 0)
    if aacsb_website_total and aacsb_complete < aacsb_website_total:
        warnings.append(
            f"AACSB official-site reconciliation is partial: {aacsb_complete}/"
            f"{aacsb_website_total} active roster schools with websites have complete "
            f"observations under scan rule {report['aacsb_roster'].get('scan_rule_version')}; "
            f"{report['aacsb_roster'].get('incomplete_current_rule_schools', 0)} remain "
            "incomplete and are not evidence of no vacancies."
        )
    if report["aacsb_roster"].get("stale_or_unchecked_websites"):
        warnings.append(
            f"{report['aacsb_roster']['stale_or_unchecked_websites']} active AACSB official "
            "websites are unchecked or stale under the current scan rule; this is a rescan "
            "backlog, not evidence that those schools have no vacancies."
        )
    if report["invariants"].get("current_institution_name_country_conflicts"):
        warnings.append(
            f"{report['invariants']['current_institution_name_country_conflicts']} same-name institution "
            "rows have conflicting country identities; they remain separate and require review rather than automatic merging."
        )
    errors = [key for key in error_keys if report["invariants"].get(key, 0)]
    report["quality"] = {
        "verdict": "fail" if errors else ("pass_with_warnings" if warnings else "pass"),
        "error_invariants": errors,
        "blocking_invariants": list(_BLOCKING_INVARIANTS),
        "warnings": warnings,
        "checks": [
            {"name": key, "count": report["invariants"].get(key, 0),
             "status": "fail" if report["invariants"].get(key, 0) else "pass"}
            for key in error_keys
        ],
    }
    structural_ok = report["integrity"]["quick_check"] == "ok" and not report["integrity"]["foreign_key_violations"] and not any(
        report["invariants"].get(key, 0) for key in (
            "source_links_without_job", "source_identity_duplicates", "schema_version_mismatch")
    )
    entity_ok = not any(report["invariants"].get(key, 0) for key in (
        "jobs_on_retired_school", "jobs_on_retired_institution",
        "current_schools_on_retired_institution",
        "duplicate_current_institutions", "duplicate_current_schools",
        "entity_redirect_cycles", "contaminated_current_institutions"))
    source_ok = not any(report["invariants"].get(key, 0) for key in (
        "graduate_assistant_active", "aacsb_false_positive_active_default",
        "active_aacsb_false_positive_links", "active_aacsb_source_without_partition",
        "country_prefixed_slash_city", "board_default_region_leak"))
    lifecycle_ok = (
        not report["aacsb_roster"].get("pending_miss_streak")
        and not report["aacsb_roster"].get("stale_or_unchecked_websites")
        and (
            not aacsb_website_total
            or aacsb_complete >= aacsb_website_total
        )
    )
    evidence_limited = bool(report["quality"]["warnings"])
    source_precision_limited = bool(
        aacsb_website_total
        and (
            report["aacsb_roster"].get("stale_or_unchecked_websites")
            or aacsb_complete < aacsb_website_total
        )
    )
    report["quality_verdicts"] = {
        "structural_integrity": "pass" if structural_ok else "fail",
        "entity_quality": "pass_with_review" if entity_ok and report["invariants"].get("current_institution_name_country_conflicts") else ("pass" if entity_ok else "fail"),
        "source_precision": "fail" if not source_ok else ("conditional" if source_precision_limited else "pass"),
        "lifecycle_freshness": "pass_with_warnings" if lifecycle_ok and report["quality"]["warnings"] else ("pass" if lifecycle_ok else "conditional"),
        "evidence_limitations": "conditional" if evidence_limited else "pass",
        # Backwards-compatible aliases for existing consumers.
        "database_integrity": "pass" if structural_ok else "fail",
        "market_boundary": "pass" if source_ok else "fail",
        "entity_resolution": "pass" if entity_ok else "fail",
        "aacsb_lifecycle": "pass" if lifecycle_ok else "conditional",
        "astar_evidence": "conditional" if evidence_limited else "pass",
    }
    return report


def failures(report):
    """Invariants that must hold. A non-empty list means the report is a problem."""
    problems = []
    if report["integrity"]["quick_check"] != "ok":
        problems.append(f"quick_check returned {report['integrity']['quick_check']}")
    if report["integrity"]["foreign_key_violations"]:
        problems.append(
            f"{report['integrity']['foreign_key_violations']} foreign-key violations")
    labels = {
        "jobs_on_retired_school": "jobs pointing at a retired school",
        "jobs_on_retired_institution": "jobs pointing at a retired institution",
        "current_schools_on_retired_institution": "current schools attached to a retired institution",
        "source_links_without_job": "source links with no job",
        "graduate_assistant_active": "graduate-assistant jobs in the default market",
        "duplicate_current_institutions": "duplicate current institution entities",
        "duplicate_current_institution_country_keys": "duplicate current institution country keys",
        "duplicate_current_schools": "duplicate current school entities",
        "source_identity_duplicates": "duplicate source identities",
        "entity_redirect_cycles": "entity redirect cycles",
        "contaminated_current_institutions": "contaminated current institutions",
        "aacsb_false_positive_active_default": "known AACSB false positives in the default market",
        "aacsb_active_without_current_evidence": "active AACSB rows without current evidence",
        "active_aacsb_false_positive_links": "active AACSB false-positive links",
        "active_aacsb_source_without_partition": "active AACSB source links without a school partition",
        "country_prefixed_slash_city": "city values that still repeat a country prefix",
        "board_default_region_leak": "jobs placed in a region using only the source board's registered location",
        "schema_version_mismatch": "SQLite user_version values that differ from the migration ledger",
    }
    keys = report.get("quality", {}).get("error_invariants") or labels.keys()
    for key in keys:
        if report["invariants"].get(key):
            problems.append(f"{report['invariants'][key]} {labels.get(key, key)}")
    return problems


def render(report):
    market = report["market"]
    total = market["jobs"] or 1
    worktree = report.get("git_worktree") or {}
    if worktree.get("dirty") is True:
        worktree_note = f"dirty ({worktree.get('changed_paths', '?')} changed paths; commit is HEAD)"
    elif worktree.get("dirty") is False:
        worktree_note = "clean"
    else:
        worktree_note = "unknown"
    lines = [
        f"# Academic Career status — {report['generated_at'][:10]}",
        "",
        "Generated by `scripts/academic_career_status_report.py` from the live database.",
        f"Run ID: `{report.get('run_id', 'unknown')}` · git commit: `{report.get('git_commit', 'unknown')}` · worktree: {worktree_note}",
        f"Snapshot ID: `{report.get('db_snapshot', {}).get('snapshot_id', 'unknown')}` · report version: `{report.get('report_version', REPORT_VERSION)}`",
        "",
        "## Integrity",
        "",
        f"- `quick_check`: **{report['integrity']['quick_check']}**",
        f"- Foreign-key violations: **{report['integrity']['foreign_key_violations']}**",
        f"- Schema version: {report['integrity']['schema_version']}",
        f"- SQLite user version: {report['integrity'].get('sqlite_user_version', 'unknown')}",
        f"- Jobs / source records / source links: "
        f"{report['grain']['jobs']} / {report['grain']['source_records']} / "
        f"{report['grain']['job_source_links']}",
        "",
        "Invariants. A **blocking** row must be zero; a **review** row is a known",
        "ambiguity that is surfaced rather than silently resolved.",
        "",
        "| Invariant | Count | Severity |",
        "|---|---:|---|",
    ]
    blocking = set(report.get("quality", {}).get("blocking_invariants")
                   or _BLOCKING_INVARIANTS)
    parity = report.get("surface_parity") or {}
    parity_status = report.get("surface_parity_status") or {}
    if parity_status.get("status") == "unavailable":
        parity_section = [
            "Surface parity: **unavailable** — the schema/user-version mismatch "
            "prevented calling the read APIs against this snapshot.",
            f"Reason: {parity_status.get('reason', 'unknown')}.",
            "",
        ]
    else:
        parity_section = [
            "| Scope | list | summary matching | CSV | analytics active | by_region | by_discipline | parity |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ] + [
            f"| `{name}` | {p['list_total']} | {p['summary_matching_records']} | {p['csv_rows']} | "
            f"{p['analytics_active_jobs']} | {p['analytics_by_region_sum']} | "
            f"{p['analytics_by_discipline_sum']} | "
            f"{'ok' if p['catalogue_parity'] and p['analytics_parity'] else 'MISMATCH'} |"
            for name, p in parity.items()
        ] + [""]
    for key, value in report["invariants"].items():
        severity = "blocking" if key in blocking else "review"
        flag = "" if not value else (" ❌" if severity == "blocking" else " ⚠️")
        lines.append(f"| {key.replace('_', ' ')} | {value}{flag} | {severity} |")
    lines += [
        "",
        "## Scopes as the product serves them",
        "",
        "The page defaults to `business_school`. `business` adds discipline roles whose",
        "school is unverified; `all` is the audit catalogue.",
        "",
        "`catalogue_records` counts every record in a scope and `active_jobs` only",
        "those still open. For the audit scope the difference is retained closed *and*",
        "status-unknown records -- different things, listed separately below.",
        "",
        "The summary reports a third number, `matching_records`: what the current query",
        "returned. For the default active view it should match the list and CSV result",
        "count. `catalogue_records` remains a separate denominator because closed and",
        "status-unknown records are retained for audit and lifecycle analysis.",
        "",
        "| Scope | Catalogue | Active | Inactive by status |",
        "|---|---:|---:|---|",
    ] + [
        f"| `{name}` | {counts['catalogue_records']} | {counts['active_jobs']} | "
        f"{counts['inactive_by_status'] or '—'} |"
        for name, counts in (report.get("scopes") or {}).items()
    ] + [
        "",
        "### Surface parity",
        "",
        "List, summary, CSV and analytics are checked against the same scope contract.",
        "The active result can be smaller than the catalogue because the catalogue",
        "retains closed and status-unknown records; grouping sums must still match",
        "the active result for the requested scope.",
        "",
    ] + parity_section + [
        "",
        "### Detail enrichment",
        "",
        f"Attempt records by outcome: {report.get('detail_enrichment') or 'none recorded'}.",
        "A listing-card snapshot being complete says nothing about detail pages;",
        "detail outcomes and unread records are reported separately.",
        "",
        "### Private state",
        "",
        f"Rows that a repair must never reduce: {report.get('private_state') or 'none'}.",
        "These tables are discovered from the schema, not from a hand-written list --",
        "`user_job_state` went unreported for several runs because it was simply absent",
        "from one.",
        "",
        "## Default business market",
        "",
        f"Exact active predicate: `{report.get('active_filter', {}).get('sql', MARKET)}`",
        f"Source inclusion policy: {market.get('source_snapshot_policy', 'unknown')}",
        "",
        "| Field | Covered | Share |",
        "|---|---:|---:|",
        f"| jobs | {market['jobs']} | — |",
        f"| linked school entity | {market['with_school_entity']} | "
        f"{100.0 * market['with_school_entity'] / total:.1f}% |",
        f"| city or state | {market['with_city_or_state']} | "
        f"{100.0 * market['with_city_or_state'] / total:.1f}% |",
        f"| official application URL | {market['with_official_url']} | "
        f"{100.0 * market['with_official_url'] / total:.1f}% |",
        f"| active link from enabled source | {market.get('with_enabled_source', 0)} | "
        f"{100.0 * market.get('with_enabled_source', 0) / total:.1f}% |",
        f"| active link only from disabled/opt-in snapshot | {market.get('with_disabled_or_opt_in_source_only', 0)} | "
        f"{100.0 * market.get('with_disabled_or_opt_in_source_only', 0) / total:.1f}% |",
        f"| no active source link | {market.get('with_no_active_source', 0)} | "
        f"{100.0 * market.get('with_no_active_source', 0) / total:.1f}% |",
        f"| historical eligible jobs (all statuses) | {market.get('historical_eligible_jobs', 0)} | — |",
        "",
        "| Historical eligible status | Jobs |",
        "|---|---:|",
    ]
    for key, value in sorted(market.get("status_breakdown", {}).items(), key=lambda item: -item[1]):
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "## Scope boundary",
        "",
        "| Scope | Jobs |",
        "|---|---:|",
    ]
    for key, value in sorted(report["scope"].items(), key=lambda item: -item[1]):
        lines.append(f"| {key} | {value} |")
    lines += ["", "## Entities", "", "| Metric | Value |", "|---|---:|"]
    for key, value in report["entities"].items():
        lines.append(f"| {key.replace('_', ' ')} | {value} |")
    lines += ["", "## School tiers", "",
              "Tiers reflect the evidence ladder only. The A* publication footprint is shown",
              "separately on each school and does not move a tier unless",
              "`FACULTY_ASTAR_TIER_SIGNAL=1` is set.", "",
              "| Tier | Schools |", "|---|---:|"]
    for key, value in sorted(report["tiers"].items(), key=lambda item: -item[1]):
        lines.append(f"| {key} | {value} |")
    if report["astar"].get("available"):
        astar = report["astar"]
        lines += [
            "",
            "## Observed A* publication footprint",
            "",
            f"- Corpus: {astar['articles']} A* articles, "
            f"**{astar['affiliation_coverage_pct']}%** affiliation-checked",
            f"- Distinct institutions observed: {astar['distinct_institutions']}",
            f"- Institutions linked with a ROR id: {report['entities']['institutions_with_ror']}",
            "",
            "Coverage is uneven across years, so a school's count is a floor, not a",
            "publication record:",
            "",
            "| Year | Checked |", "|---|---:|",
        ]
        for year, pct in astar.get("coverage_by_year", {}).items():
            lines.append(f"| {year} | {pct}% |")
    lines += ["", "## Duplicate review queue", "",
              f"- Open: **{report['duplicates']['open']}** · resolved: "
              f"{report['duplicates']['resolved']}", "",
              "| Basis | Open |", "|---|---:|"]
    for key, value in sorted(report["duplicates"]["by_basis"].items(), key=lambda i: -i[1]):
        lines.append(f"| {key} | {value} |")
    resolution = report.get("entity_resolution", {})
    lines += ["", "## Entity-resolution review queue", "",
              f"- Pending: **{resolution.get('pending', 0)}** · conflicting identities: "
              f"**{resolution.get('with_conflicting_identity', 0)}**",
              f"- Impacted jobs / schools / evidence: **{resolution.get('impacted_jobs', 0)}** / "
              f"**{resolution.get('impacted_schools', 0)}** / **{resolution.get('impacted_evidence', 0)}**",
              "Rows remain review-only until an explicit reversible decision; cross-country identities are not auto-merged."]
    lines += ["", "## AACSB lifecycle", "",
              f"- Active/inactive roster rows: {report['aacsb_roster']['active']} / {report['aacsb_roster']['inactive']}",
              f"- Active/inactive job partitions: {report['aacsb_roster'].get('job_partitions_active', 0)} / {report['aacsb_roster'].get('job_partitions_inactive', 0)}",
              f"- Active roster rows with current AACSB evidence: {report['aacsb_roster'].get('active_current_evidence', 0)}",
              f"- Current scan rule: `{report['aacsb_roster'].get('scan_rule_version', 'unknown')}`",
              f"- Active roster rows with websites: {report['aacsb_roster'].get('active_with_website', 0)}",
              f"- Complete current-rule schools: {report['aacsb_roster'].get('complete_current_rule_schools', 0)} / "
              f"{report['aacsb_roster'].get('active_with_website', 0)}",
              f"- Incomplete current-rule schools: {report['aacsb_roster'].get('incomplete_current_rule_schools', 0)}",
              f"- Stale or unchecked official websites: {report['aacsb_roster'].get('stale_or_unchecked_websites', 0)}",
              f"- Pending roster missing streak: {report['aacsb_roster']['pending_miss_streak']}",
              "",
              "Only complete roster metadata and complete official-site statuses advance missing streaks; raw source records are retained.",
              ""]
    lines += ["## Data quality verdict", "",
              f"Overall: **{report.get('quality', {}).get('verdict', 'unknown')}**", "",
              "| Check | Status | Count |", "|---|---|---:|"]
    for check in report.get("quality", {}).get("checks", []):
        lines.append(f"| {check['name']} | {check['status']} | {check['count']} |")
    if report.get("quality", {}).get("warnings"):
        lines += ["", "Warnings:"]
        lines.extend(f"- {warning}" for warning in report["quality"]["warnings"])
    lines.append("")
    problems = failures(report)
    # A single green line hid the fact that a non-zero review invariant was
    # printed two sections earlier. The verdict is reported per dimension, and
    # every warning is shown, so "structurally sound" can never read as
    # "the whole dataset is trustworthy".
    verdicts = report.get("quality_verdicts", {}) or {}
    warnings = report.get("quality", {}).get("warnings") or []
    symbols = {"pass": "✅", "pass_with_review": "⚠️", "pass_with_warnings": "⚠️",
               "conditional": "⚠️", "fail": "❌"}
    lines += ["## Verdict", "",
              "| Dimension | Status |", "|---|---|"]
    for dimension in ("structural_integrity", "entity_quality", "source_precision",
                      "lifecycle_freshness", "evidence_limitations"):
        status = verdicts.get(dimension, "unknown")
        lines.append(f"| {dimension.replace('_', ' ')} | "
                     f"{symbols.get(status, '•')} {status.replace('_', ' ')} |")
    lines += ["", f"Overall: **{report.get('quality', {}).get('verdict', 'unknown')}**", ""]
    if problems:
        lines += ["Blocking:", ""] + [f"- ❌ {item}" for item in problems] + [""]
    else:
        lines += ["- ✅ No blocking invariant is violated.", ""]
    if warnings:
        lines += ["Review / limitations:", ""] + [f"- ⚠️ {item}" for item in warnings] + [""]
    return "\n".join(lines) + "\n"


def main():
    # Windows may expose a legacy GBK console even though the report intentionally
    # contains Unicode status symbols.  Configure the stream before the first
    # print so a successful audit cannot fail before its artifacts are written.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--faculty-db", default=FACULTY_DB)
    parser.add_argument("--astar-db", default=ASTAR_DB)
    parser.add_argument("--write", action="store_true",
                        help="write docs/academic_career_STATUS_<date>.md and an outputs/ snapshot")
    args = parser.parse_args()

    report = collect(args.faculty_db, args.astar_db)
    markdown = render(report)
    print(markdown)

    if args.write:
        stamp = report["generated_at"].replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
        run_suffix = report["run_id"].replace("-", "")[:12]
        os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
        os.makedirs(os.path.join(ROOT, "outputs"), exist_ok=True)
        doc = os.path.join(ROOT, "docs", f"academic_career_STATUS_{stamp}_{run_suffix}.md")
        with open(doc, "x", encoding="utf-8") as handle:
            handle.write(markdown)
        snapshot = os.path.join(ROOT, "outputs",
                                f"academic_career_audit_{stamp}_{run_suffix}.json")
        with open(snapshot, "x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
        print(f"wrote {doc}\nwrote {snapshot}")

    return 1 if failures(report) else 0


if __name__ == "__main__":
    sys.exit(main())
