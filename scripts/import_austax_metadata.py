#!/usr/bin/env python3
"""Import corroborated Australian Taxation issue/paper metadata with source IDs."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from import_nzulr_metadata import IssueItemRunner
from services.astar_history_service import digest, utc_now, write_new_json
from services.astar_archive_year_service import ensure_tables, put_year

TITLE = "Journal of Australian Taxation"


def run(record_file, run_dir, output):
    records = json.loads(record_file.read_text(encoding="utf-8"))
    if len(records) != len({row["source_raw_id"] for row in records}):
        raise ValueError("Repeated source item identities")
    for row in records:
        if row["status"] != "VERIFIED_PUBLISHER_METADATA" or row["journal_title"] != TITLE:
            raise ValueError("Unverified/out-of-journal record")
        if not row["title"] or not 2010 <= row["archive_year"] <= 2026 or row["publication_date"] is not None:
            raise ValueError("Title/year/date scope needs review")
        if digest(row["pdf_path"]) != row["pdf_sha256"]:
            raise ValueError("An original publisher PDF changed")
    output.mkdir(parents=True, exist_ok=False)
    write_new_json(output / "manifest.json", {"created_at": utc_now(), "record_file": str(record_file),
        "record_sha256": digest(record_file), "script_sha256": digest(__file__), "record_count": len(records),
        "journal_title": TITLE, "full_text_reviewed": False, "date_imputation": False})
    state = sqlite3.connect(output / "checkpoint.sqlite3")
    state.execute("CREATE TABLE records(source_id TEXT PRIMARY KEY,article_id INTEGER,disposition TEXT)")
    runner = IssueItemRunner(run_dir)
    journal = next((row for row in runner.journals.values() if row["journal_title"] == TITLE), None)
    if journal is None:
        runner.close();state.close();raise ValueError("Journal absent from frozen scope")
    try:
        ensure_tables(runner.main);runner.main.commit()
        for row in records:
            article = {"title": row["title"], "doi": None, "openalex_id": None, "abstract": row.get("abstract"),
                "abstract_status": "available" if row.get("abstract") else "missing", "publication_year": row["publication_year"],
                "publication_date": None, "publication_month": None, "date_precision": "year", "journal_title": TITLE,
                "journal_issn": journal["issn_print"], "publisher": journal.get("publisher"), "authors": row["authors"],
                "concepts": [], "keywords": [], "url": row["source_url"], "landing_page_url": row["source_url"],
                "source_url": row["source_url"], "source_raw_id": row["source_raw_id"], "source_name": "Journal of Australian Taxation public issue metadata",
                "source_type": "publisher_metadata", "data_status": "publisher_metadata", "record_type": "journal-metadata-item"}
            runner.main.execute("BEGIN IMMEDIATE")
            try:
                prior = runner.main.execute("SELECT id FROM astar_article_sources WHERE source_type='publisher_metadata' AND raw_id=?", (article["source_raw_id"],)).fetchone()
                aid, disposition = runner.ingest_article(article, journal)
                if aid is None:
                    raise ValueError("Verified publisher record excluded: " + disposition)
                put_year(runner.main, aid, row["archive_year"], "publisher_printed_issue_year", article["source_name"], row["source_url"],
                    {"volume": row["volume"], "issue": row["issue"], "pdf_sha256": row["pdf_sha256"],
                     "year_basis": row["year_basis"], "physical_page": row.get("physical_pdf_page"),
                     "printed_start_page": row["printed_start_page"], "field_scope": row.get("field_scope")}, 30)
                if prior is None:
                    runner.main.execute("UPDATE astar_article_sources SET raw_json=?,parser_notes=? WHERE article_id=? AND source_type='publisher_metadata' AND raw_id=? AND raw_json IS NULL",
                        (json.dumps(row, ensure_ascii=False), "publisher printed issue/front-page metadata; exact day unknown; full_text_reviewed=false; limited TOC-only item explicitly marked", aid, article["source_raw_id"]))
                runner.main.commit()
            except BaseException:
                runner.main.rollback();raise
            state.execute("INSERT INTO records VALUES(?,?,?)", (article["source_raw_id"], aid, disposition));state.commit()
        result = {"finished_at": utc_now(), "record_count": len(records), "dispositions": [list(row) for row in state.execute("SELECT disposition,COUNT(*) FROM records GROUP BY disposition")],
                  "exact_days_imputed": 0, "full_text_reviewed": False, "final_baseline_audit_required": True}
        write_new_json(output / "report.json", result)
        return result
    finally:
        runner.close();state.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-file", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.record_file.resolve(), args.run_dir.resolve(), args.output_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
