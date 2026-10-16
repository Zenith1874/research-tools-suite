#!/usr/bin/env python3
"""Verify Stanford archive records against public title/citation detail HTML."""

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


def parse_detail(html, candidate):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("main h1")
    if not title or title.get_text(" ", strip=True) != candidate["title"]:
        raise ValueError("The public detail title differs from the archive record")
    citation = soup.select_one(".publication-citation") or soup.select_one('[itemprop="citation"]')
    if not citation:
        raise ValueError("The publisher citation is unavailable")
    text = citation.get_text(" ", strip=True)
    match = re.search(r"(?:Stan\.\s+J\.L\.\s+Bus\.\s*&\s*Fin\.|Stanford Journal of Law,\s*Business\s+(?:&|and)\s+Finance)\s+(?:\d+\s*)?\((\d{4})\)", text)
    if not match:
        raise ValueError("The citation does not establish this journal's issue year")
    year = int(match.group(1))
    content = soup.select_one('[itemprop="articleBody"]') or soup.select_one(".publication-content")
    abstract = content.get_text(" ", strip=True) if content else None
    return dict(candidate, title=title.get_text(" ", strip=True), publisher_citation=text,
                publication_year=year, archive_year=year, publication_date=None,
                publication_month=None, date_precision="year", year_basis="publisher_citation_issue_year",
                abstract=abstract, abstract_status="available" if abstract else "not_extracted",
                status="VERIFIED_PUBLISHER_HTML_METADATA" if 2010 <= year <= 2026 else "OUTSIDE_YEAR_SCOPE",
                source_raw_id=candidate["publisher_article_url"], source_url=candidate["publisher_article_url"],
                full_text_reviewed=False, reading_scope="publisher_bibliographic_detail_HTML")


def run(candidate_file, output):
    candidates = json.loads(candidate_file.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=False)
    state = sqlite3.connect(output / "checkpoint.sqlite3")
    state.execute("CREATE TABLE records(url TEXT PRIMARY KEY,status TEXT,metadata_path TEXT,error TEXT,updated_at TEXT)")
    state.executemany("INSERT INTO records(url,status) VALUES(?,'PENDING')", [(row["publisher_article_url"],) for row in candidates]);state.commit()
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump({"created_at": datetime.now(timezone.utc).isoformat(), "candidate_file": str(candidate_file),
                   "candidate_sha256": hashlib.sha256(candidate_file.read_bytes()).hexdigest(), "candidate_count": len(candidates),
                   "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   "article_database_writes": 0, "full_text_reviewed": False}, stream, indent=2)
    try:
        for candidate in candidates:
            url = candidate["publisher_article_url"]
            key = hashlib.sha256(url.encode()).hexdigest()[:20]
            raw = output / (key + ".html.gz")
            metadata = output / (key + ".metadata.json")
            try:
                response = requests.get(url, headers={"User-Agent": "ResearchTools-PublicBibliographyAudit/1.0"}, timeout=(15, 45))
                if response.status_code != 200:
                    raise RuntimeError(f"Publisher detail HTTP {response.status_code}; no bypass")
                with raw.open("xb") as handle:
                    with gzip.GzipFile(fileobj=handle, mode="wb") as stream:
                        stream.write(response.content)
                result = parse_detail(response.content, candidate)
                result.update(source_html_path=str(raw), source_html_sha256=hashlib.sha256(raw.read_bytes()).hexdigest())
                with metadata.open("x", encoding="utf-8") as stream:
                    json.dump(result, stream, ensure_ascii=False, indent=2)
                state.execute("UPDATE records SET status=?,metadata_path=?,updated_at=? WHERE url=?",
                              (result["status"], str(metadata), datetime.now(timezone.utc).isoformat(), url))
                print(json.dumps({"key": key, "status": result["status"], "year": result["archive_year"]}), flush=True)
            except Exception as error:
                state.execute("UPDATE records SET status='REVIEW_REQUIRED',error=?,updated_at=? WHERE url=?",
                              (f"{type(error).__name__}: {str(error)[:220]}", datetime.now(timezone.utc).isoformat(), url))
                print(json.dumps({"key": key, "status": "REVIEW_REQUIRED", "error_type": type(error).__name__}), flush=True)
            state.commit();time.sleep(0.75)
        report = {"finished_at": datetime.now(timezone.utc).isoformat(), "candidate_count": len(candidates),
                  "states": [list(row) for row in state.execute("SELECT status,COUNT(*) FROM records GROUP BY status")],
                  "article_database_writes": 0, "full_text_reviewed": False}
        with (output / "report.json").open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
        return report
    finally:
        state.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.candidates.resolve(), args.output_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
