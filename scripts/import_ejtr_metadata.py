#!/usr/bin/env python3
"""Import a fully verified eJTR metadata pass with strong publisher-URL identity."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.astar_history_service import HistoryRunner, digest, utc_now, write_new_json
from services.astar_archive_year_service import ensure_tables, put_year


class PublisherRunner(HistoryRunner):
    def existing_id(self, article, journal):
        # Different publisher URLs remain distinct even for generic editorials
        # with the same title, author and year. No title/year fallback is used.
        raw_id = article["source_raw_id"]
        row = self.main.execute("SELECT article_id FROM astar_article_sources WHERE source_type='publisher_metadata' AND raw_id=? ORDER BY id LIMIT 1", (raw_id,)).fetchone()
        if row:
            return row[0]
        row = self.main.execute("SELECT id FROM astar_articles WHERE journal_title='eJournal of Tax Research' AND (url=? OR landing_page_url=?) ORDER BY is_duplicate,id LIMIT 1",
                                (article["url"], article["url"])).fetchone()
        return row[0] if row else None


def verified_records(report_path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    from collections import Counter
    if dict(Counter(row["status"] for row in report["records"])) != report["states"]:
        raise ValueError("Publisher verification counts do not reconcile")
    if set(report["states"]) - {"VERIFIED_METADATA", "OUTSIDE_VERIFIED_PRINT_YEAR_SCOPE"}:
        raise ValueError("Publisher metadata reviews remain unresolved")
    records = []
    seen = set()
    for row in report["records"]:
        if digest(row["metadata_path"]) != row["metadata_sha256"]:
            raise ValueError("A verified metadata record changed")
        metadata = json.loads(Path(row["metadata_path"]).read_text(encoding="utf-8"))
        if digest(metadata["pdf_path"]) != metadata["pdf_sha256"]:
            raise ValueError("A verified publisher PDF changed")
        if metadata["status"] != row["status"]:
            raise ValueError("A record status differs from the completed verification")
        if metadata["status"] != "VERIFIED_METADATA":
            if 2010 <= metadata["archive_year"] <= 2026:
                raise ValueError("An in-scope record was excluded")
            continue
        if not metadata.get("title") or metadata.get("publication_date") is not None:
            raise ValueError("A title is missing or an unsupported exact date was supplied")
        if metadata["source_url"] in seen or not 2010 <= metadata["archive_year"] <= 2026:
            raise ValueError("Publisher identities or year scope are invalid")
        seen.add(metadata["source_url"])
        records.append(metadata)
    for path, checksum in report["original_metadata_hashes"].items():
        if digest(path) != checksum:
            raise ValueError("An original verification record was overwritten")
    return records, report


def article_from_metadata(metadata):
    return {"title": metadata["title"], "doi": None, "openalex_id": None,
            "abstract": metadata.get("abstract"),
            "abstract_status": "available" if metadata.get("abstract") else "missing",
            "publication_year": metadata["publication_year"], "publication_date": None,
            "date_precision": "year", "publication_month": None,
            "journal_title": "eJournal of Tax Research", "journal_issn": "1448-2398",
            "publisher": "UNSW", "authors": metadata.get("authors") or [],
            "concepts": [], "keywords": metadata.get("keywords") or [],
            "url": metadata["source_url"], "landing_page_url": metadata["source_url"],
            "source_url": metadata["source_url"], "source_raw_id": metadata["source_url"],
            "source_name": "UNSW eJournal of Tax Research public front-matter metadata",
            "source_type": "publisher_metadata", "data_status": "publisher_metadata",
            "record_type": "journal-metadata-item", "open_access_status": "public_pdf_available"}


def apply_metadata(report_path, run_dir, output_dir):
    records, report = verified_records(report_path)
    output_dir.mkdir(parents=True, exist_ok=False)
    write_new_json(output_dir / "manifest.json", {"created_at": utc_now(), "repair_report": str(report_path),
        "repair_report_sha256": digest(report_path), "run_dir": str(run_dir), "record_count": len(records),
        "script_sha256": digest(__file__), "identity_policy": "verified_publisher_URL; no_title_year_merge",
        "scope": "ABDC A eJournal of Tax Research, archive 2010-2026",
        "publication_date_imputation": False, "full_text_reviewed": False})
    state = sqlite3.connect(output_dir / "checkpoint.sqlite3", timeout=30)
    state.execute("CREATE TABLE records(source_url TEXT PRIMARY KEY,article_id INTEGER,disposition TEXT,metadata_sha256 TEXT,imported_at TEXT)")
    runner = PublisherRunner(run_dir)
    journal = next((row for row in runner.journals.values() if row["journal_title"] == "eJournal of Tax Research"), None)
    if journal is None:
        runner.close()
        state.close()
        raise ValueError("The verified journal is absent from the frozen import scope")
    try:
        # Sparse derived indexes avoid rescanning the million-record corpus
        # for each DOI-less publisher item. Existing article/source rows stay fixed.
        runner.main.execute("CREATE INDEX IF NOT EXISTS idx_astar_publisher_raw_identity ON astar_article_sources(raw_id,article_id) WHERE source_type='publisher_metadata'")
        runner.main.execute("CREATE INDEX IF NOT EXISTS idx_astar_ejtr_publisher_urls ON astar_articles(url,landing_page_url,id) WHERE journal_title='eJournal of Tax Research'")
        ensure_tables(runner.main)
        runner.main.commit()
        for metadata in records:
            article = article_from_metadata(metadata)
            runner.main.execute("BEGIN IMMEDIATE")
            before = {}
            try:
                existing = runner.existing_id(article, journal)
                if existing:
                    before = {"article": dict(runner.main.execute("SELECT * FROM astar_articles WHERE id=?", (existing,)).fetchone()),
                              "classification": dict(runner.main.execute("SELECT * FROM astar_article_classifications WHERE article_id=?", (existing,)).fetchone())}
                prior_source = runner.main.execute("SELECT id FROM astar_article_sources WHERE source_type='publisher_metadata' AND raw_id=?", (article["source_raw_id"],)).fetchone()
                aid, disposition = runner.ingest_article(article, journal)
                if aid is None:
                    raise ValueError("Verified publisher metadata was excluded: " + disposition)
                basis = metadata["year_basis"]
                reference = metadata["source_url"]
                priority = 30
                if basis == "publisher_archive_issue_label_year":
                    reference = metadata["issue_year_evidence"]["source_url"]
                    priority = 15
                put_year(runner.main, aid, metadata["archive_year"], basis, article["source_name"], reference,
                         {"volume": metadata["volume"], "issue": metadata["issue"], "pdf_sha256": metadata["pdf_sha256"],
                          "year_evidence": metadata.get("issue_year_evidence"), "raw_index_evidence": metadata["index_evidence"]}, priority)
                if prior_source is None:
                    proof = {key: value for key, value in metadata.items() if key != "selected_page_text"}
                    runner.main.execute("UPDATE astar_article_sources SET raw_json=?,parser_notes=? WHERE article_id=? AND source_type='publisher_metadata' AND raw_id=? AND raw_json IS NULL",
                                        (json.dumps(proof, ensure_ascii=False), "verified public front matter; full_text_reviewed=false; source pages/hash and archive-year basis retained", aid, article["source_raw_id"]))
                runner.main.commit()
            except BaseException:
                runner.main.rollback()
                raise
            if before:
                with (output_dir / ("before_" + str(aid) + ".json")).open("x", encoding="utf-8") as stream:
                    json.dump(before, stream, ensure_ascii=False, indent=2)
            checksum = next(row["metadata_sha256"] for row in report["records"] if row["url"] == metadata["source_url"])
            state.execute("INSERT INTO records VALUES(?,?,?,?,?)", (metadata["source_url"], aid, disposition, checksum, utc_now()))
            state.commit()
        result = {"finished_at": utc_now(), "states": [list(row) for row in state.execute("SELECT disposition,COUNT(*) FROM records GROUP BY disposition")],
                  "record_count": len(records), "original_raw_files_overwritten": False,
                  "exact_days_imputed": 0, "full_text_reviewed": False, "final_baseline_audit_required": True}
        write_new_json(output_dir / "report.json", result)
        return result
    finally:
        runner.close()
        state.close()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair-report", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        if not args.output_dir:
            parser.error("--apply requires --output-dir")
        result = apply_metadata(args.repair_report.resolve(), args.run_dir.resolve(), args.output_dir.resolve())
    else:
        records, report = verified_records(args.repair_report.resolve())
        result = {"verified_in_scope": len(records), "verified_outside_scope": report["states"].get("OUTSIDE_VERIFIED_PRINT_YEAR_SCOPE", 0),
                  "abstracts_extracted": sum(bool(row.get("abstract")) for row in records), "article_database_writes": 0,
                  "exact_days_to_impute": 0, "full_text_reviewed": False}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
