#!/usr/bin/env python3
"""Acquire observed current-host free PDFs and retain bounded front-page evidence."""

import argparse
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import fitz
import requests


def run(candidate_file, output):
    candidates = json.loads(candidate_file.read_text(encoding="utf-8"))
    current = [row for row in candidates if urlparse(row["url"]).hostname == "journalofaustraliantax.com.au"]
    legacy = [row for row in candidates if row not in current]
    output.mkdir(parents=True, exist_ok=False)
    conn = sqlite3.connect(output / "checkpoint.sqlite3")
    conn.execute("CREATE TABLE records(url TEXT PRIMARY KEY,status TEXT,details_json TEXT)")
    conn.executemany("INSERT INTO records(url,status) VALUES(?,'PENDING')", [(row["url"],) for row in current]);conn.commit()
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump({"created_at": datetime.now(timezone.utc).isoformat(), "candidate_file": str(candidate_file),
                   "candidate_sha256": hashlib.sha256(candidate_file.read_bytes()).hexdigest(),
                   "current_host_free_pdf_count": len(current), "legacy_domain_link_count": len(legacy),
                   "maximum_front_pages": 8, "full_text_reviewed": False, "article_database_writes": 0}, stream, indent=2)
    with (output / "legacy_unavailable_links.json").open("x", encoding="utf-8") as stream:
        json.dump(legacy, stream, ensure_ascii=False, indent=2)
    try:
        for row in current:
            url = row["url"];key = hashlib.sha256(url.encode()).hexdigest()[:20]
            try:
                response = requests.get(url, headers={"User-Agent": "ResearchTools-PublicBibliographyAudit/1.0"}, timeout=(15, 45))
                if response.status_code != 200 or not response.content.startswith(b"%PDF-"):
                    raise ValueError("The observed public link did not return a PDF")
                pdf = output / (key + ".pdf")
                with pdf.open("xb") as stream:
                    stream.write(response.content)
                with fitz.open(pdf) as document:
                    texts = [document[page].get_text() for page in range(min(8, len(document)))]
                    metadata = dict(row, pdf_path=str(pdf), pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
                                    total_pages=len(document), pages_text_extracted=list(range(1, len(texts) + 1)),
                                    selected_page_text=texts, full_text_reviewed=False,
                                    all_pdf_pages_text_extracted=len(texts) == len(document), status="FRONT_PAGES_SAVED")
                path = output / (key + ".frontmatter.json")
                with path.open("x", encoding="utf-8") as stream:
                    json.dump(metadata, stream, ensure_ascii=False, indent=2)
                conn.execute("UPDATE records SET status='FRONT_PAGES_SAVED',details_json=? WHERE url=?",
                             (json.dumps({"metadata_path": str(path), "metadata_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}), url))
                print(json.dumps({"key": key, "status": "FRONT_PAGES_SAVED", "pages": len(texts)}), flush=True)
            except Exception as error:
                conn.execute("UPDATE records SET status='REVIEW_ACCESS_OR_PARSE',details_json=? WHERE url=?",
                             (json.dumps({"error_type": type(error).__name__}), url))
                print(json.dumps({"key": key, "status": "REVIEW_ACCESS_OR_PARSE", "error_type": type(error).__name__}), flush=True)
            conn.commit();time.sleep(1)
        report = {"finished_at": datetime.now(timezone.utc).isoformat(),
                  "states": [list(row) for row in conn.execute("SELECT status,COUNT(*) FROM records GROUP BY status")],
                  "legacy_link_count": len(legacy), "article_database_writes": 0,
                  "full_text_reviewed": False, "next_step": "verify_explicit_issue_year_and_contents_items"}
        with (output / "report.json").open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
        return report
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.candidates.resolve(), args.output_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
