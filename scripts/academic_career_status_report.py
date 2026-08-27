# -*- coding: utf-8 -*-
"""Generate the Academic Career status report and audit snapshot.

Every figure is read from the live database at run time. The point is that the
report cannot drift from reality the way a hand-written status document does:
if a number here is wrong, the query is wrong, and the query is visible.

    python scripts/academic_career_status_report.py            # print
    python scripts/academic_career_status_report.py --write    # also write docs/ + outputs/
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACULTY_DB = os.path.join(ROOT, "data", "faculty_jobs.db")
ASTAR_DB = os.path.join(ROOT, "pboc_data.db")

MARKET = ("derived_quality='accepted' AND faculty_market_eligible=1 "
          "AND business_scope IN ('business_school','business_discipline')")


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


def collect(faculty_path=FACULTY_DB, astar_path=ASTAR_DB):
    conn = connect(faculty_path)
    try:
        report = {
            "generated_at": now_utc(),
            "integrity": {
                "quick_check": one(conn, "PRAGMA quick_check"),
                "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
                "schema_version": one(conn, "SELECT MAX(version) FROM faculty_job_migrations"),
            },
            "grain": {
                "jobs": one(conn, "SELECT COUNT(*) FROM jobs"),
                "source_records": one(conn, "SELECT COUNT(*) FROM source_job_records"),
                "job_source_links": one(conn, "SELECT COUNT(*) FROM job_sources"),
            },
            "scope": group(conn, "SELECT business_scope, COUNT(*) FROM jobs GROUP BY 1"),
            "market": {
                "jobs": one(conn, f"SELECT COUNT(*) FROM jobs WHERE {MARKET}"),
                "with_school_entity": one(
                    conn, f"SELECT COUNT(*) FROM jobs WHERE {MARKET} AND school_id IS NOT NULL"),
                "with_city_or_state": one(
                    conn, f"SELECT COUNT(*) FROM jobs WHERE {MARKET} AND ((city IS NOT NULL "
                          "AND city!='') OR (state_province IS NOT NULL AND state_province!=''))"),
                "with_official_url": one(
                    conn, f"SELECT COUNT(*) FROM jobs WHERE {MARKET} AND official_url IS NOT NULL "
                          "AND official_url!=''"),
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
            "school_evidence": group(
                conn, "SELECT evidence_type, COUNT(*) FROM school_evidence GROUP BY 1"),
            "duplicates": {
                "open": one(conn, "SELECT COUNT(*) FROM possible_duplicates WHERE resolved=0"),
                "resolved": one(conn, "SELECT COUNT(*) FROM possible_duplicates WHERE resolved=1"),
                "by_basis": group(
                    conn, "SELECT match_basis, COUNT(*) FROM possible_duplicates "
                          "WHERE resolved=0 GROUP BY 1"),
            },
            "aacsb_roster": {
                "active": one(conn, "SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1"),
                "inactive": one(conn, "SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=0"),
                "pending_miss_streak": one(
                    conn, "SELECT COUNT(*) FROM aacsb_directory_schools "
                          "WHERE consecutive_missing_runs>0 AND active=1"),
            },
            "invariants": {},
        }
        report["invariants"]["jobs_on_retired_school"] = one(conn, """
            SELECT COUNT(*) FROM jobs j JOIN business_schools bs ON bs.id=j.school_id
            WHERE bs.is_current=0""")
        report["invariants"]["jobs_on_retired_institution"] = one(conn, """
            SELECT COUNT(*) FROM jobs j JOIN institutions i ON i.id=j.institution_id
            WHERE i.is_current=0""")
        report["invariants"]["source_links_without_job"] = one(conn, """
            SELECT COUNT(*) FROM job_sources js
            LEFT JOIN jobs j ON j.id=js.job_id WHERE j.id IS NULL""")
    finally:
        conn.close()

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
    return report


def failures(report):
    """Invariants that must hold. A non-empty list means the report is a problem."""
    problems = []
    if report["integrity"]["quick_check"] != "ok":
        problems.append(f"quick_check returned {report['integrity']['quick_check']}")
    if report["integrity"]["foreign_key_violations"]:
        problems.append(
            f"{report['integrity']['foreign_key_violations']} foreign-key violations")
    for key, label in (("jobs_on_retired_school", "jobs pointing at a retired school"),
                       ("jobs_on_retired_institution", "jobs pointing at a retired institution"),
                       ("source_links_without_job", "source links with no job")):
        if report["invariants"].get(key):
            problems.append(f"{report['invariants'][key]} {label}")
    return problems


def render(report):
    market = report["market"]
    total = market["jobs"] or 1
    lines = [
        f"# Academic Career status — {report['generated_at'][:10]}",
        "",
        "Generated by `scripts/academic_career_status_report.py` from the live database.",
        "",
        "## Integrity",
        "",
        f"- `quick_check`: **{report['integrity']['quick_check']}**",
        f"- Foreign-key violations: **{report['integrity']['foreign_key_violations']}**",
        f"- Schema version: {report['integrity']['schema_version']}",
        f"- Jobs / source records / source links: "
        f"{report['grain']['jobs']} / {report['grain']['source_records']} / "
        f"{report['grain']['job_source_links']}",
        "",
        "Invariants (all must be zero):",
        "",
        "| Invariant | Count |",
        "|---|---:|",
    ]
    for key, value in report["invariants"].items():
        lines.append(f"| {key.replace('_', ' ')} | {value} |")
    lines += [
        "",
        "## Default business market",
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
    lines += ["", "## AACSB roster", "",
              f"- Active: {report['aacsb_roster']['active']} · inactive: "
              f"{report['aacsb_roster']['inactive']} · pending miss streak: "
              f"{report['aacsb_roster']['pending_miss_streak']}",
              "",
              "Records are retired only after three consecutive complete runs; a bounded run",
              "never reconciles.", ""]
    problems = failures(report)
    lines += ["## Verdict", ""]
    lines += ([f"- ❌ {item}" for item in problems] if problems
              else ["- ✅ Every invariant holds."])
    return "\n".join(lines) + "\n"


def main():
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
        stamp = report["generated_at"][:10]
        doc = os.path.join(ROOT, "docs", f"academic_career_STATUS_{stamp}.md")
        with open(doc, "w", encoding="utf-8") as handle:
            handle.write(markdown)
        snapshot = os.path.join(ROOT, "outputs",
                                f"academic_career_audit_{stamp.replace('-', '')}.json")
        with open(snapshot, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
        print(f"wrote {doc}\nwrote {snapshot}")

    return 1 if failures(report) else 0


if __name__ == "__main__":
    sys.exit(main())
