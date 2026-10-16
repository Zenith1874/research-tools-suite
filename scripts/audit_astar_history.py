#!/usr/bin/env python3
"""Independently verify a historical article run against its baseline and live DB.

All input connections are read-only. Output files are new, timestamped artifacts
in the private run directory. The checkpoint is snapshotted before the live DB
read so all audited source records have already committed to the production DB.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.astar_history_service import connect, digest, utc_now, write_new_json


def csv_new(path, rows, fields=None):
    with Path(path).open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def audit_run(run_dir, verify_hashes=False):
    run_dir = Path(run_dir).resolve()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    journals = json.loads((run_dir / "journals.json").read_text(encoding="utf-8"))
    journal_map = {journal["history_key"]: journal for journal in journals}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = run_dir / "audits" / stamp
    folder.mkdir(parents=True)
    with (folder / "audit_script.py").open("xb") as stream:
        stream.write(Path(__file__).read_bytes())
    checkpoint_path = folder / "checkpoint.at_audit.sqlite3"
    state_live = connect(run_dir / "checkpoint.sqlite3", readonly=True)
    state_copy = sqlite3.connect(checkpoint_path)
    try:
        state_live.backup(state_copy)
    finally:
        state_live.close()
        state_copy.close()
    publisher_checkpoint = run_dir / "publisher_tax_forum" / "checkpoint.sqlite3"
    publisher_snapshot = None
    if publisher_checkpoint.exists():
        publisher_snapshot = folder / "publisher.at_audit.sqlite3"
        publisher_live = connect(publisher_checkpoint, readonly=True)
        publisher_copy = sqlite3.connect(publisher_snapshot)
        try:
            publisher_live.backup(publisher_copy)
        finally:
            publisher_live.close()
            publisher_copy.close()
    conn = connect(manifest["db_path"], readonly=True)
    try:
        conn.execute("ATTACH DATABASE ? AS original", (Path(manifest["snapshot_path"]).as_uri() + "?mode=ro",))
        conn.execute("ATTACH DATABASE ? AS history", (checkpoint_path.as_uri() + "?mode=ro",))
        if publisher_snapshot:
            conn.execute("ATTACH DATABASE ? AS publisher", (publisher_snapshot.as_uri() + "?mode=ro",))
        conn.execute("BEGIN")
        baseline_rows = conn.execute("SELECT COUNT(*) FROM original.astar_articles").fetchone()[0]
        missing_old = conn.execute("SELECT COUNT(*) FROM original.astar_articles b LEFT JOIN main.astar_articles a ON a.id=b.id WHERE a.id IS NULL").fetchone()[0]
        columns = [row["name"] for row in conn.execute("PRAGMA original.table_info(astar_articles)")]
        # Blank-field enrichment may change updated_at and the availability
        # label for an originally absent abstract. Existing content stays fixed.
        protected = [column for column in columns if column not in ("updated_at", "abstract_status")]
        # Check all protected fields in one joined pass over the large baseline.
        expressions = [f"SUM(CASE WHEN b.{column} IS NOT NULL AND b.{column}!='' AND a.{column} IS NOT b.{column} THEN 1 ELSE 0 END) AS {column}" for column in protected]
        differences = conn.execute("SELECT " + ",".join(expressions) + " FROM original.astar_articles b JOIN main.astar_articles a ON a.id=b.id").fetchone()
        protected_counts = {column: differences[column] or 0 for column in protected}
        protected_counts["abstract_status_when_abstract_present"] = conn.execute(
            "SELECT COUNT(*) FROM original.astar_articles b JOIN main.astar_articles a ON a.id=b.id WHERE b.abstract IS NOT NULL AND b.abstract!='' AND a.abstract_status IS NOT b.abstract_status").fetchone()[0]
        cls_columns = [row["name"] for row in conn.execute("PRAGMA original.table_info(astar_article_classifications)")]
        cls_difference = " OR ".join(f"a.{column} IS NOT b.{column}" for column in cls_columns)
        changed_classifications = conn.execute(
            f"SELECT COUNT(*) FROM original.astar_article_classifications b LEFT JOIN main.astar_article_classifications a ON a.id=b.id WHERE a.id IS NULL OR {cls_difference}").fetchone()[0]
        missing_original_sources = conn.execute(
            "SELECT COUNT(*) FROM original.astar_article_sources b LEFT JOIN main.astar_article_sources a ON a.id=b.id WHERE a.id IS NULL").fetchone()[0]
        missing_imported_ids = conn.execute(
            "SELECT COUNT(DISTINCT r.article_id) FROM history.records r LEFT JOIN main.astar_articles a ON a.id=r.article_id WHERE r.article_id IS NOT NULL AND a.id IS NULL").fetchone()[0]
        missing_classifications = conn.execute(
            "SELECT COUNT(DISTINCT r.article_id) FROM history.records r LEFT JOIN main.astar_article_classifications c ON c.article_id=r.article_id WHERE r.article_id IS NOT NULL AND c.article_id IS NULL").fetchone()[0]
        missing_provenance = conn.execute(
            "SELECT COUNT(DISTINCT r.article_id) FROM history.records r WHERE r.article_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM main.astar_article_sources s WHERE s.article_id=r.article_id)").fetchone()[0]
        max_before = conn.execute("SELECT MAX(id) FROM original.astar_articles").fetchone()[0] or 0
        from services.astar_archive_year_service import year_expression
        archive_year_sql = year_expression(conn)
        all_new_checks = {
            "new_ids_without_classification": conn.execute("SELECT COUNT(*) FROM main.astar_articles a WHERE a.id>? AND NOT EXISTS (SELECT 1 FROM main.astar_article_classifications c WHERE c.article_id=a.id)", (max_before,)).fetchone()[0],
            "new_ids_without_provenance": conn.execute("SELECT COUNT(*) FROM main.astar_articles a WHERE a.id>? AND NOT EXISTS (SELECT 1 FROM main.astar_article_sources s WHERE s.article_id=a.id)", (max_before,)).fetchone()[0],
            "new_ids_outside_authorized_years": conn.execute("SELECT COUNT(*) FROM main.astar_articles a WHERE a.id>? AND (" + archive_year_sql + " IS NULL OR " + archive_year_sql + "<? OR " + archive_year_sql + ">?)", (max_before, int(manifest['from_date'][:4]), int(manifest['to_date'][:4]))).fetchone()[0],
        }
        years = [dict(row) for row in conn.execute(
            "SELECT a.publication_year AS year,COUNT(*) AS total_records,SUM(CASE WHEN a.id>? THEN 1 ELSE 0 END) AS records_added_after_baseline FROM main.astar_articles a WHERE a.is_duplicate=0 GROUP BY a.publication_year ORDER BY a.publication_year", (max_before,))]
        archive_years = [dict(row) for row in conn.execute(
            "SELECT " + archive_year_sql + " AS year,COUNT(*) AS total_records FROM main.astar_articles a WHERE a.is_duplicate=0 GROUP BY " + archive_year_sql + " ORDER BY " + archive_year_sql)]
        units = [dict(row) for row in conn.execute("SELECT * FROM history.units ORDER BY provider,journal_key")]
        source_counts = {row["unit_key"]: row["n"] for row in conn.execute("SELECT unit_key,COUNT(*) AS n FROM history.records GROUP BY unit_key")}
        for unit in units:
            unit["journal_title"] = journal_map[unit["journal_key"]]["journal_title"]
            unit["unique_raw_records"] = source_counts.get(unit["unit_key"], 0)
            unit["count_reconciled"] = unit["status"] == "COMPLETE" and unit["expected_count"] == unit["unique_raw_records"]
            unit["publication_coverage_label"] = (
                "ZERO_SOURCE_RESULTS_REQUIRES_ARCHIVE_CHECK" if unit["count_reconciled"] and unit["expected_count"] == 0
                else "SOURCE_QUERY_EXHAUSTED" if unit["count_reconciled"] else "INCOMPLETE_OR_UNVERIFIED")
        source_years = [dict(row) for row in conn.execute(
            "SELECT unit_key,publication_year,COUNT(*) AS source_records,SUM(CASE WHEN article_id IS NOT NULL THEN 1 ELSE 0 END) AS linked_records FROM history.records GROUP BY unit_key,publication_year")]
        year_map = {(row["unit_key"], row["publication_year"]): row for row in source_years}
        source_year_output = []
        for unit in units:
            for year in range(int(manifest["from_date"][:4]), int(manifest["to_date"][:4]) + 1):
                row = year_map.get((unit["unit_key"], year), {})
                source_year_output.append({
                    "journal_title": unit["journal_title"], "provider": unit["provider"],
                    "year": year, "unit_status": unit["status"],
                    "observed_source_records": row.get("source_records", 0),
                    "linked_database_records": row.get("linked_records", 0),
                    "empty_year_label": "UNVERIFIED_PUBLICATION_COVERAGE" if not row else "HAS_SOURCE_RECORDS",
                })
        exclusions = [dict(row) for row in conn.execute(
            "SELECT u.provider,u.journal_key,r.source_id,r.disposition,r.publication_year,r.record_type FROM history.records r JOIN history.units u ON u.unit_key=r.unit_key WHERE r.article_id IS NULL ORDER BY u.provider,u.journal_key,r.publication_year")]
        for row in exclusions:
            row["journal_title"] = journal_map[row["journal_key"]]["journal_title"]
        record_types = [dict(row) for row in conn.execute(
            "SELECT u.provider,r.record_type,COUNT(*) AS source_records,COUNT(DISTINCT r.article_id) AS linked_article_ids FROM history.records r JOIN history.units u ON u.unit_key=r.unit_key GROUP BY u.provider,r.record_type")]
        pages = [dict(row) for row in conn.execute("SELECT * FROM history.pages ORDER BY unit_key,page")]
        checks = {
            "baseline_article_rows": baseline_rows,
            "missing_baseline_articles": missing_old,
            "changed_nonempty_baseline_fields": {column: n for column, n in protected_counts.items() if n},
            "changed_or_missing_baseline_classifications": changed_classifications,
            "missing_baseline_source_rows": missing_original_sources,
            "missing_imported_article_ids": missing_imported_ids,
            "imported_ids_without_classification": missing_classifications,
            "imported_ids_without_any_provenance": missing_provenance,
            "completed_units_with_count_mismatch": sum(unit["status"] == "COMPLETE" and not unit["count_reconciled"] for unit in units),
            "source_units": len(units), "frozen_journals": len(journals),
            "committed_pages": len(pages),
            "historical_2010_records_present": any(row["year"] == 2010 and row["total_records"] > 0 for row in years),
            **all_new_checks,
        }
        publisher_checks = {}
        publisher_pages = []
        if publisher_snapshot:
            publisher_checks = {
                "target_records": conn.execute("SELECT COUNT(*) FROM publisher.articles").fetchone()[0],
                "imported_records": conn.execute("SELECT COUNT(*) FROM publisher.articles WHERE status='IMPORTED'").fetchone()[0],
                "unverified_records": conn.execute("SELECT COUNT(*) FROM publisher.articles WHERE status!='IMPORTED'").fetchone()[0],
                "missing_imported_ids": conn.execute("SELECT COUNT(*) FROM publisher.articles p LEFT JOIN main.astar_articles a ON a.id=p.article_id WHERE p.status='IMPORTED' AND a.id IS NULL").fetchone()[0],
                "publication_date_mismatches": conn.execute("SELECT COUNT(*) FROM publisher.articles p JOIN main.astar_articles a ON a.id=p.article_id WHERE p.status='IMPORTED' AND a.publication_date IS NOT json_extract(p.verified_json,'$.publication_date')").fetchone()[0],
                "missing_publisher_provenance": conn.execute("SELECT COUNT(*) FROM publisher.articles p WHERE p.status='IMPORTED' AND NOT EXISTS (SELECT 1 FROM main.astar_article_sources s WHERE s.article_id=p.article_id AND s.source_type='publisher_metadata' AND s.raw_id=p.path)").fetchone()[0],
                "missing_classifications": conn.execute("SELECT COUNT(*) FROM publisher.articles p WHERE p.status='IMPORTED' AND NOT EXISTS (SELECT 1 FROM main.astar_article_classifications c WHERE c.article_id=p.article_id)").fetchone()[0],
            }
            publisher_pages = [dict(row) for row in conn.execute("SELECT html_path,html_sha256 FROM publisher.articles WHERE html_path IS NOT NULL")]
        conn.rollback()
    finally:
        conn.close()
    hash_errors = []
    if verify_hashes:
        if digest(manifest["snapshot_path"]) != manifest["snapshot_sha256"]:
            hash_errors.append("baseline snapshot hash differs from manifest")
        for page in pages:
            path = (run_dir / page["path"]).resolve()
            if not path.is_relative_to(run_dir) or not path.is_file() or digest(path) != page["sha256"]:
                hash_errors.append(f"page hash failure: {page['unit_key']} page {page['page']}")
        for page in publisher_pages:
            path = (run_dir / "publisher_tax_forum" / page["html_path"]).resolve()
            if not path.is_relative_to(run_dir) or not path.is_file() or digest(path) != page["html_sha256"]:
                hash_errors.append(f"publisher page hash failure: {page['html_path']}")
    checks["hash_verification_requested"] = verify_hashes
    checks["hash_errors"] = hash_errors
    preservation_ok = (not missing_old and not any(protected_counts.values()) and
                       not changed_classifications and not missing_original_sources)
    integrity_ok = (not missing_imported_ids and not missing_classifications and not missing_provenance and
                    not checks["completed_units_with_count_mismatch"] and not hash_errors and
                    not any(all_new_checks.values()))
    if publisher_checks:
        integrity_ok = integrity_ok and not any(publisher_checks[key] for key in (
            "missing_imported_ids", "publication_date_mismatches", "missing_publisher_provenance", "missing_classifications"))
    zero_journals = defaultdict(list)
    for unit in units:
        if unit["count_reconciled"] and unit["expected_count"] == 0:
            zero_journals[unit["journal_title"]].append(unit["provider"])
    both_zero = {title: providers for title, providers in zero_journals.items() if len(providers) == 2}
    summary = {
        "created_at": utc_now(), "audit_directory": str(folder), "checks": checks,
        "baseline_content_preserved": preservation_ok, "import_integrity_checks_passed": integrity_ok,
        "unit_states": dict(Counter(unit["status"] for unit in units)),
        "by_provider": {provider: dict(Counter(unit["status"] for unit in units if unit["provider"] == provider)) for provider in ("crossref", "openalex")},
        "database_years": years, "database_total": sum(row["total_records"] for row in years),
        "archive_years": archive_years,
        "year_scope_basis": "human-confirmed journal issue year; original publication years/dates are retained separately",
        "publisher_supplement": publisher_checks,
        "new_records_after_baseline": sum(row["records_added_after_baseline"] for row in years),
        "journals_with_zero_results_in_both_sources": both_zero,
        "all_source_queries_reconciled": all(unit["count_reconciled"] for unit in units),
        "full_publication_coverage_verified": False,
        "completion_note": "Source pagination/count checks do not verify every publisher issue archive. Remaining incomplete units and empty-source journals need review.",
    }
    csv_new(folder / "database_years.csv", years)
    csv_new(folder / "archive_years.csv", archive_years)
    csv_new(folder / "source_coverage.csv", units)
    csv_new(folder / "journal_year_source_coverage.csv", source_year_output)
    csv_new(folder / "excluded_source_records.csv", exclusions,
            ("provider", "journal_key", "source_id", "disposition", "publication_year", "record_type", "journal_title"))
    csv_new(folder / "source_record_types.csv", record_types)
    write_new_json(folder / "verification.json", summary)
    return summary


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--verify-page-hashes", action="store_true")
    args = parser.parse_args()
    print(json.dumps(audit_run(args.run_dir, args.verify_page_hashes), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
