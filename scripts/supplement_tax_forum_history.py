#!/usr/bin/env python3
"""Verify and ingest publicly listed Australian Tax Forum article metadata.

The input is the preserved, journal-filtered publisher search response. Every
eligible source URL must expose its matching article heading and publication
date before ingestion. Subscriber text, PDFs, and login endpoints are not fetched.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.astar_history_service import (
    HistoryRunner, digest, utc_now, write_new_json,
)
from services.abdc_astar_research_service import normalize_title

LOG = logging.getLogger(__name__)
PUBLISHER_BASE = "https://www.taxinstitute.com.au"
PATH_RULE = re.compile(r"^/resources/journals/australian-tax-forum/((?:19|20)\d{2})/.+$")


def parse_public_metadata(html, target):
    """A publisher heading and date must corroborate the search-index item."""
    soup = BeautifulSoup(html, "html.parser")
    headings = [tag for tag in soup.select("h1")
                if normalize_title(tag.get_text(" ", strip=True)) == normalize_title(target["title"])]
    if not headings:
        raise ValueError("article heading does not corroborate the indexed title")
    publication_date = None
    for heading in headings:
        text = heading.parent.get_text(" ", strip=True)
        match = re.search(r"Published Date:\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text)
        if match:
            for pattern in ("%d %b %Y", "%d %B %Y"):
                try:
                    publication_date = datetime.strptime(match.group(1), pattern).date()
                    break
                except ValueError:
                    pass
        if publication_date:
            break
    if not publication_date:
        raise ValueError("public article publication date is unavailable")
    match = PATH_RULE.match(target["path"])
    if not match or int(match.group(1)) != publication_date.year:
        raise ValueError("publisher page date differs from the official archive year")
    authors = target.get("contentAuthors") or []
    if not isinstance(authors, list):
        raise ValueError("publisher author metadata has an unexpected shape")
    source_url = PUBLISHER_BASE + target["path"]
    return {
        "doi": None, "openalex_id": None, "title": target["title"],
        "abstract": None, "abstract_status": "missing",
        "publication_date": publication_date.isoformat(), "publication_year": publication_date.year,
        "journal_title": "Australian Tax Forum", "journal_issn": "0812-695X",
        "publisher": "The Tax Institute", "authors": authors,
        "concepts": [], "keywords": [], "url": source_url, "landing_page_url": source_url,
        "cited_by_count": None, "open_access_status": None,
        "source_name": "The Tax Institute public article metadata",
        "source_type": "publisher_metadata", "source_url": source_url,
        "source_raw_id": target["path"], "data_status": "publisher_metadata",
        "record_type": "journal-article", "date_precision": "day",
    }


def prepare_stage(run_dir):
    folder = run_dir / "publisher_tax_forum"
    input_path = run_dir / "publisher_probes" / "taxforum_journal_metadata.json"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    data = json.loads(input_path.read_text(encoding="utf-8"))
    payload = data["data"]
    if data["status"] != 200 or len(payload["hits"]) != payload["nbHits"] or payload["nbPages"] != 1:
        raise ValueError("publisher metadata response is not completely paginated")
    targets = {}
    excluded = []
    for item in payload["hits"]:
        path = item.get("path") or ""
        match = PATH_RULE.match(path)
        if item.get("journalType") != "Australian Tax Forum" or not match:
            excluded.append({"path": path, "reason": "journal membership unverified"})
            continue
        year = int(match.group(1))
        if not int(manifest["from_date"][:4]) <= year <= int(manifest["to_date"][:4]):
            excluded.append({"path": path, "reason": "outside authorized archive years"})
            continue
        if path in targets and targets[path]["title"] != item["title"]:
            raise ValueError("conflicting titles for one canonical publisher path")
        targets[path] = item
    if not folder.exists():
        folder.mkdir()
        write_new_json(folder / "targets.json", list(targets.values()))
        write_new_json(folder / "manifest.json", {
            "created_at": utc_now(), "input_path": str(input_path),
            "input_sha256": digest(input_path), "publisher_index_records": payload["nbHits"],
            "target_records": len(targets), "date_range": [manifest["from_date"], manifest["to_date"]],
            "excluded_index_items": excluded,
            "scope": "public titles/authors plus public article heading and publication date",
            "python_version": sys.version, "requests_version": requests.__version__,
            "script_sha256": digest(__file__),
        })
        conn = sqlite3.connect(folder / "checkpoint.sqlite3")
        conn.execute("""CREATE TABLE articles (
            path TEXT PRIMARY KEY,metadata_json TEXT,status TEXT DEFAULT 'PENDING',
            html_path TEXT,html_sha256 TEXT,verified_json TEXT,error TEXT,
            article_id INTEGER,disposition TEXT,updated_at TEXT
        )""")
        for path, item in targets.items():
            conn.execute("INSERT INTO articles(path,metadata_json,updated_at) VALUES (?,?,?)",
                         (path, json.dumps(item, ensure_ascii=False), utc_now()))
        conn.commit()
        conn.close()
    else:
        saved = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if saved["input_sha256"] != digest(input_path):
            raise ValueError("publisher input changed; preserve the existing stage and use a new stage")
    return folder


def fetch_verify(folder, target):
    import hashlib
    token = hashlib.sha256(target["path"].encode()).hexdigest()[:24]
    path = folder / "pages" / f"{token}.html.gz"
    try:
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                text = stream.read()
        else:
            url = PUBLISHER_BASE + target["path"]
            response = requests.get(url, headers={"User-Agent": "ResearchTools-HistoryAudit/1.0"}, timeout=(15, 45))
            if response.status_code != 200:
                raise RuntimeError(f"public article page HTTP {response.status_code}")
            if not response.url.startswith(PUBLISHER_BASE + "/resources/journals/australian-tax-forum/"):
                raise ValueError("public article request redirected outside the approved journal path")
            text = response.text
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_name(path.name + ".partial")
            with partial.open("xb") as binary:
                with gzip.GzipFile(fileobj=binary, mode="wb") as compressed:
                    compressed.write(text.encode("utf-8"))
            partial.rename(path)
            time.sleep(0.35)
        article = parse_public_metadata(text, target)
        return target["path"], "VERIFIED", str(path.relative_to(folder)), digest(path), article, None
    except Exception as exc:
        return target["path"], "UNVERIFIED", str(path.relative_to(folder)) if path.exists() else None, digest(path) if path.exists() else None, None, f"{type(exc).__name__}: {str(exc)[:300]}"


def run_stage(run_dir, workers=2):
    folder = prepare_stage(run_dir)
    conn = sqlite3.connect(folder / "checkpoint.sqlite3", timeout=60)
    conn.row_factory = sqlite3.Row
    targets = [json.loads(row["metadata_json"]) for row in conn.execute("SELECT metadata_json FROM articles WHERE status IN ('PENDING','UNVERIFIED') ORDER BY path")]
    runner = None
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fetch_verify, folder, target) for target in targets]
            for future in as_completed(futures):
                path, status, html_path, html_sha, article, error = future.result()
                conn.execute("UPDATE articles SET status=?,html_path=?,html_sha256=?,verified_json=?,error=?,updated_at=? WHERE path=?",
                             (status, html_path, html_sha, json.dumps(article, ensure_ascii=False) if article else None, error, utc_now(), path))
                conn.commit()
                LOG.info("%s | %s | %s", status, path, error or "public heading/date match")
        runner = HistoryRunner(run_dir)
        journal = next(journal for journal in runner.journals.values() if journal["journal_title"] == "Australian Tax Forum")
        for row in conn.execute("SELECT * FROM articles WHERE status='VERIFIED' ORDER BY path").fetchall():
            article = json.loads(row["verified_json"])
            if not runner.manifest["from_date"] <= article["publication_date"] <= runner.manifest["to_date"]:
                conn.execute("UPDATE articles SET status='EXCLUDED_AFTER_DATE_VERIFICATION',updated_at=? WHERE path=?", (utc_now(), row["path"]))
                conn.commit()
                continue
            try:
                runner.main.execute("BEGIN IMMEDIATE")
                aid, disposition = runner.ingest_article(article, journal)
                runner.main.commit()
            except Exception:
                runner.main.rollback()
                runner.refresh_indexes()
                raise
            conn.execute("UPDATE articles SET status='IMPORTED',article_id=?,disposition=?,updated_at=? WHERE path=?",
                         (aid, disposition, utc_now(), row["path"]))
            conn.commit()
        records = [dict(row) for row in conn.execute("SELECT path,status,error,article_id,disposition,html_path,html_sha256 FROM articles ORDER BY path")]
        summary = {"created_at": utc_now(), "publisher_stage": str(folder), "target_count": len(records),
                   "states": {row["status"]: row["n"] for row in conn.execute("SELECT status,COUNT(*) AS n FROM articles GROUP BY status")},
                   "verified_page_date_count": conn.execute("SELECT COUNT(*) FROM articles WHERE status='IMPORTED'").fetchone()[0],
                   "source_index_is_complete_for_all_published_issues": False,
                   "coverage_note": "The preserved publisher index has 2010–2025 targets but does not establish 2026 issue completeness."}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        out = folder / "reports" / stamp
        out.mkdir(parents=True)
        with (out / "records.csv").open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
        write_new_json(out / "summary.json", summary)
        runner.event("publisher_tax_forum_supplemented", summary)
        return summary
    finally:
        conn.close()
        if runner:
            runner.close()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.workers <= 3:
        parser.error("workers must be 1–3")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run_stage(args.run_dir.resolve(), args.workers), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
