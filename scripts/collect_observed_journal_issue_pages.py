#!/usr/bin/env python3
"""Collect only publisher issue URLs observed in preserved public index pages."""

import argparse
import gzip
import hashlib
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests


def now():
    return datetime.now(timezone.utc).isoformat()


def fetch(url, output):
    key = hashlib.sha256(url.encode()).hexdigest()[:20]
    path = output / "raw" / (key + ".html.gz")
    try:
        if path.exists():
            return {"url": url, "status": "SAVED", "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "resumed": True}
        if urlparse(url).hostname not in ("journalofaustraliantax.com.au", "nzulr.com"):
            raise ValueError("Unobserved publisher domain")
        response = requests.get(url, headers={"User-Agent": "ResearchTools-PublicBibliographyAudit/1.0"}, timeout=(15, 45))
        if response.status_code != 200:
            return {"url": url, "status": "ACCESS_STATUS", "http_status": response.status_code}
        if "html" not in response.headers.get("Content-Type", "").lower():
            return {"url": url, "status": "REVIEW_NON_HTML", "content_type": response.headers.get("Content-Type")}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            with gzip.GzipFile(fileobj=handle, mode="wb") as stream:
                stream.write(response.content)
        time.sleep(1)
        return {"url": url, "final_url": response.url, "status": "SAVED", "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": len(response.content),
                "requested_at": now(), "reading_scope": "publisher_issue_metadata_HTML_only"}
    except Exception as error:
        return {"url": url, "status": "ERROR", "error_type": type(error).__name__}


def collect(index_dir, output):
    inputs = []
    urls = set()
    for name in ("australian_taxation_observed_issue_links.json", "nzulr_observed_issue_links.json"):
        path = index_dir / name
        data = json.loads(path.read_text(encoding="utf-8"))
        inputs.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        urls.update(row["url"] if isinstance(row, dict) else row for row in data["links"])
    output.mkdir(parents=True, exist_ok=False)
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump({"created_at": now(), "urls": sorted(urls), "inputs": inputs,
                   "url_count": len(urls), "workers": 2, "request_delay_seconds": 1,
                   "article_database_writes": 0, "full_text_reviewed": False,
                   "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, stream, indent=2)
    state = sqlite3.connect(output / "checkpoint.sqlite3")
    state.execute("CREATE TABLE records(url TEXT PRIMARY KEY,status TEXT,details_json TEXT,updated_at TEXT)")
    state.executemany("INSERT INTO records(url,status) VALUES(?,'PENDING')", [(url,) for url in sorted(urls)])
    state.commit()
    # Each worker handles a different publisher, avoiding same-origin bursts.
    groups = [[url for url in sorted(urls) if urlparse(url).hostname == host]
              for host in ("journalofaustraliantax.com.au", "nzulr.com")]
    def run_group(group):
        for url in group:
            yield fetch(url, output)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(lambda group: list(run_group(group)), group) for group in groups]
            for future in futures:
                for row in future.result():
                    state.execute("UPDATE records SET status=?,details_json=?,updated_at=? WHERE url=?",
                                  (row["status"], json.dumps(row, ensure_ascii=False), now(), row["url"]))
                    state.commit()
                    print(json.dumps({"url_key": hashlib.sha256(row["url"].encode()).hexdigest()[:20], "status": row["status"]}), flush=True)
        result = {"finished_at": now(), "states": [list(row) for row in state.execute("SELECT status,COUNT(*) FROM records GROUP BY status")],
                  "url_count": len(urls), "article_database_writes": 0, "full_text_reviewed": False}
        with (output / "report.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
        return result
    finally:
        state.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.index_dir.resolve(), args.output_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
