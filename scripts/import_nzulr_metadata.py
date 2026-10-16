#!/usr/bin/env python3
"""Import verified publisher issue items with composite source identities."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.astar_history_service import HistoryRunner, digest, utc_now, write_new_json
from services.astar_archive_year_service import ensure_tables, put_year


class IssueItemRunner(HistoryRunner):
    def refresh_indexes(self):
        # Composite publisher IDs use the persistent source lookup index. Avoid
        # building a million-row Python identity cache for a small issue import.
        self.doi_index, self.oa_index, self.title_index = {}, {}, {}
        self.publisher_source_index = {}

    def existing_id(self, article, journal):
        # One issue URL contains multiple works. Match the recorded composite
        # publisher item ID; a shared URL/title/year cannot merge the items.
        row = self.main.execute("SELECT article_id FROM astar_article_sources WHERE source_type='publisher_metadata' AND raw_id=? ORDER BY id LIMIT 1", (article["source_raw_id"],)).fetchone()
        return row[0] if row else None


def load_verified(record_file):
    records = json.loads(record_file.read_text(encoding="utf-8"))
    if not records or len({row["source_raw_id"] for row in records}) != len(records):
        raise ValueError("Missing or repeated publisher item identities")
    checked = set()
    for row in records:
        if row["status"] != "VERIFIED_ISSUE_HTML_METADATA" or row["journal_title"] != "New Zealand Universities Law Review":
            raise ValueError("Unverified or out-of-journal metadata")
        if not row["title"] or "\ufffd" in row["title"] or row["publication_date"] is not None:
            raise ValueError("Missing/corrupt title or unsupported exact date")
        if not 2010 <= row["archive_year"] <= 2026 or row["date_precision"] != "month":
            raise ValueError("Issue year or observed precision is invalid")
        source = row["source_html_path"]
        if source not in checked:
            if digest(source) != row["source_html_sha256"]:
                raise ValueError("An original publisher issue page changed")
            checked.add(source)
    return records


def apply_records(record_file, run_dir, output):
    records = load_verified(record_file)
    output.mkdir(parents=True, exist_ok=False)
    write_new_json(output / "manifest.json", {"created_at": utc_now(), "record_file": str(record_file),
        "record_file_sha256": digest(record_file), "record_count": len(records), "run_dir": str(run_dir),
        "script_sha256": digest(__file__), "source_identity": "issue_URL_volume_issue_title_observed_author_composite",
        "exact_days_imputed": 0, "full_text_reviewed": False})
    state = sqlite3.connect(output / "checkpoint.sqlite3")
    state.execute("CREATE TABLE records(source_id TEXT PRIMARY KEY,article_id INTEGER,disposition TEXT,imported_at TEXT)")
    runner = IssueItemRunner(run_dir)
    journal = next((row for row in runner.journals.values() if row["journal_title"] == "New Zealand Universities Law Review"), None)
    if journal is None:
        runner.close(); state.close()
        raise ValueError("The journal is absent from the frozen scope")
    try:
        ensure_tables(runner.main); runner.main.commit()
        for metadata in records:
            article = {"title": metadata["title"], "doi": None, "openalex_id": None,
                "abstract": metadata.get("abstract"), "abstract_status": "available" if metadata.get("abstract") else "missing",
                "publication_year": metadata["publication_year"], "publication_month": metadata["publication_month"],
                "publication_date": None, "date_precision": "month", "journal_title": journal["journal_title"],
                "journal_issn": journal["issn_print"] or journal["issn_online"], "publisher": journal.get("publisher"),
                "authors": metadata["authors"], "concepts": [], "keywords": [], "url": metadata["source_url"],
                "landing_page_url": metadata["source_url"], "source_url": metadata["source_url"],
                "source_name": "NZULR public publisher issue metadata", "source_type": "publisher_metadata",
                "source_raw_id": metadata["source_raw_id"], "data_status": "publisher_metadata",
                "record_type": metadata["record_type"], "open_access_status": "public_metadata"}
            runner.main.execute("BEGIN IMMEDIATE")
            try:
                prior = runner.main.execute("SELECT id FROM astar_article_sources WHERE source_type='publisher_metadata' AND raw_id=?", (article["source_raw_id"],)).fetchone()
                aid, disposition = runner.ingest_article(article, journal)
                if aid is None:
                    raise ValueError("Verified issue item excluded: " + disposition)
                put_year(runner.main, aid, metadata["archive_year"], metadata["year_basis"], article["source_name"], metadata["source_url"],
                         {"source_html_sha256": metadata["source_html_sha256"], "source_issue_heading": metadata["source_issue_heading"],
                          "volume": metadata["volume"], "issue": metadata["issue"], "observed_month": metadata["publication_month"]}, 30)
                if prior is None:
                    runner.main.execute("UPDATE astar_article_sources SET raw_json=?,parser_notes=? WHERE article_id=? AND source_type='publisher_metadata' AND raw_id=? AND raw_json IS NULL",
                                        (json.dumps(metadata, ensure_ascii=False), "public issue metadata; exact day unknown; full_text_reviewed=false; composite item identity retained", aid, article["source_raw_id"]))
                runner.main.commit()
            except BaseException:
                runner.main.rollback(); raise
            state.execute("INSERT INTO records VALUES(?,?,?,?)", (article["source_raw_id"], aid, disposition, utc_now())); state.commit()
        result = {"finished_at": utc_now(), "record_count": len(records),
                  "dispositions": [list(row) for row in state.execute("SELECT disposition,COUNT(*) FROM records GROUP BY disposition")],
                  "original_raw_files_overwritten": False, "exact_days_imputed": 0, "abstracts_imported": sum(bool(row.get("abstract")) for row in records),
                  "full_text_reviewed": False, "final_baseline_audit_required": True}
        write_new_json(output / "report.json", result)
        return result
    finally:
        runner.close(); state.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-file", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        if args.output_dir is None:
            parser.error("--apply requires --output-dir")
        result = apply_records(args.record_file.resolve(), args.run_dir.resolve(), args.output_dir.resolve())
    else:
        records = load_verified(args.record_file.resolve())
        result = {"verified_records": len(records), "missing_author_fields": sum(not row["authors"] for row in records),
                  "exact_days_to_impute": 0, "article_database_writes": 0}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
