#!/usr/bin/env python3
"""Verify public UNSW journal PDF front matter without writing article data.

Original PDFs are retained privately. Reading is bounded to cover/contents pages
and the first page containing the article's bibliographic header. Abstracts are
extracted only where their boundary is explicit; no full-text review is claimed.
"""

import argparse
import difflib
import hashlib
import importlib.metadata
import json
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import fitz
import requests

CITATION = re.compile(r"eJournal\s+of\s+Tax\s+Research\s*\(\s*(\d{4})\s*\)\s*vol\.?\s*(\d+)\s*,?\s*(?:no\.?|number)\s*(\d+)", re.I)
ISSUE_HEADER = re.compile(r"eJournal\s+of\s+Tax\s+Research\s*(?:\(\s*(\d{4})\s*\))?\s*vol\.?\s*(\d+)\s*,?\s*(?:no\.?|number)\s*(\d+)", re.I)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    with Path(path).open("rb") as stream:
        result = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
        return result.hexdigest()


def clean(text):
    return " ".join(text.split())


def comparable(text):
    return "".join(character for character in unicodedata.normalize("NFKD", text).casefold()
                   if character.isalnum())


def page_lines(page):
    result = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            text = clean("".join(span["text"] for span in spans))
            if text:
                result.append({"text": text, "bbox": line["bbox"],
                               "size": max(span["size"] for span in spans)})
    return sorted(result, key=lambda row: (round(row["bbox"][1], 1), row["bbox"][0]))


def extract(pdf_path, candidate_title, max_front_pages=8, issue_year_evidence=None):
    with fitz.open(pdf_path) as doc:
        selected_text, matched_page = [], None
        match = None
        for page_number in range(min(max_front_pages, len(doc))):
            text = doc[page_number].get_text()
            selected_text.append(text)
            match = ISSUE_HEADER.search(text)
            if match:
                matched_page = page_number
                break
        result = {"pdf_page_count": len(doc), "pages_text_extracted": list(range(1, len(selected_text) + 1)),
                  "all_pdf_pages_text_extracted": len(selected_text) == len(doc),
                  "full_text_reviewed": False, "reading_scope": "bounded_pdf_front_pages_text_extraction",
                  "selected_page_text": selected_text}
        if matched_page is None:
            return dict(result, status="REVIEW_BIBLIOGRAPHIC_HEADER_NOT_FOUND")
        volume, issue = int(match.group(2)), int(match.group(3))
        result.update(volume=volume, issue=issue, article_first_page=matched_page + 1)
        if match.group(1):
            year = int(match.group(1))
            result.update(print_year=year, archive_year=year, publication_year=year,
                          year_basis="article_bibliographic_header_year")
        elif (issue_year_evidence and issue_year_evidence.get("volume") == volume and
              issue_year_evidence.get("issue") == issue and
              isinstance(issue_year_evidence.get("year"), int) and
              issue_year_evidence.get("basis") in ("publisher_issue_cover_year", "publisher_archive_issue_label_year")):
            year = issue_year_evidence["year"]
            result.update(archive_year=year, publication_year=year,
                          print_year=year if issue_year_evidence["basis"] == "publisher_issue_cover_year" else None,
                          year_basis=issue_year_evidence["basis"], issue_year_evidence=issue_year_evidence)
        else:
            return dict(result, status="REVIEW_ISSUE_YEAR_NOT_REPORTED")
        lines = page_lines(doc[matched_page])
        header = next((row for row in lines if ISSUE_HEADER.search(row["text"])), None)
        if header is None:
            return dict(result, status="REVIEW_HEADER_LAYOUT")
        abstract_heading = next((row for row in lines if row["text"].casefold() == "abstract"), None)
        upper = abstract_heading["bbox"][1] if abstract_heading else doc[matched_page].rect.height * 0.45
        region = [row for row in lines if header["bbox"][3] < row["bbox"][1] < upper]
        if not region:
            return dict(result, status="REVIEW_TITLE_LAYOUT")
        largest = max(row["size"] for row in region)
        large_lines = [row for row in region if row["size"] >= largest - 0.2]
        title_lines = []
        for row in large_lines:
            if title_lines and row["bbox"][1] - title_lines[-1]["bbox"][3] > max(8, largest * 0.45):
                break
            title_lines.append(row)
        title = clean(" ".join(row["text"] for row in title_lines))
        similarity = difflib.SequenceMatcher(None, comparable(title), comparable(candidate_title)).ratio()
        result.update(title=title, title_match_similarity=similarity, index_title=candidate_title)
        prefix_alias = bool(comparable(candidate_title) and comparable(title).startswith(comparable(candidate_title)))
        result["index_title_is_prefix_alias"] = prefix_alias
        if (similarity < 0.80 and not prefix_alias) or largest < 12:
            return dict(result, status="REVIEW_TITLE_MISMATCH")
        authors, author_lines = [], []
        if abstract_heading:
            title_end = max(row["bbox"][3] for row in title_lines)
            author_lines = [row["text"] for row in region if row["bbox"][1] > title_end]
            for line in author_lines:
                normalized = "".join(character for character in line if unicodedata.category(character) != "Co")
                normalized = re.sub(r"[\d*#†‡]+$", "", normalized).strip()
                for name in re.split(r"\s*,\s*|\s+and\s+", normalized):
                    name = re.sub(r"[\d*#†‡]+$", "", clean(name)).strip()
                    if name and name not in authors:
                        authors.append(name)
        abstract, keywords = None, []
        keyword_heading = next((row for row in lines if re.match(r"key\s*words\s*:", row["text"], re.I)), None)
        boundary = None
        if abstract_heading:
            boundary = next((row for row in lines if row["bbox"][1] > abstract_heading["bbox"][3] and
                             (re.match(r"(?:key\s*words|JEL\s*classification|PsycINFO\s*classification)\s*:", row["text"], re.I) or
                              re.match(r"^(?:\d+\.?\s+)?INTRODUCTION\b", row["text"], re.I) or
                              (re.match(r"^\d+\.\s+[A-Z]", row["text"]) and row["text"].isupper()))), None)
        if abstract_heading and boundary:
            abstract = clean(" ".join(row["text"] for row in lines
                                      if abstract_heading["bbox"][3] < row["bbox"][1] < boundary["bbox"][1]))
        if keyword_heading:
            keywords = [clean(value) for value in keyword_heading["text"].split(":", 1)[1].split(",") if clean(value)]
        result.update(authors=authors, observed_author_lines=author_lines, abstract=abstract or None,
                      abstract_scope="article_first_page_with_explicit_boundary" if abstract else "not_extracted",
                      keywords=keywords, publication_date=None, date_precision="year", status="VERIFIED_METADATA")
        return result


def initialize(directory, candidate_file, probe_report=None):
    directory = Path(directory).resolve()
    candidate_file = Path(candidate_file).resolve()
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["candidate_sha256"] != sha256(candidate_file):
            raise ValueError("Candidate list changed; do not overwrite an existing verification run")
        return manifest
    directory.mkdir(parents=True, exist_ok=False)
    candidates = json.loads(candidate_file.read_text(encoding="utf-8"))
    urls = [row["publisher_pdf_url"] for row in candidates]
    if len(set(urls)) != len(urls):
        raise ValueError("Candidate URLs are not unique")
    cache = {}
    if probe_report:
        for row in json.loads(Path(probe_report).read_text(encoding="utf-8"))["results"]:
            if row.get("pdf_path") and row.get("status_code") == 200:
                if sha256(row["pdf_path"]) != row["pdf_sha256"]:
                    raise ValueError("A cached sample PDF changed")
                cache[row["url"]] = {"path": row["pdf_path"], "sha256": row["pdf_sha256"]}
    conn = sqlite3.connect(directory / "checkpoint.sqlite3")
    conn.execute("CREATE TABLE records(url TEXT PRIMARY KEY,status TEXT,metadata_path TEXT,pdf_path TEXT,pdf_sha256 TEXT,error TEXT,updated_at TEXT)")
    conn.executemany("INSERT INTO records(url,status,updated_at) VALUES(?,'PENDING',?)", [(url, now()) for url in urls])
    conn.commit()
    conn.close()
    manifest = {"created_at": now(), "candidate_file": str(candidate_file), "candidate_sha256": sha256(candidate_file),
                "candidate_count": len(candidates), "cached_pdf_sources": cache,
                "from_year": 2010, "to_year": 2026, "max_front_pages": 8,
                "max_download_bytes": 30 * 1024 * 1024, "request_delay_seconds": 1,
                "pdf_downloads_are_public_complete_files": True, "full_text_reviewed": False,
                "article_database_writes": 0, "script_sha256": sha256(__file__),
                "packages": {name: importlib.metadata.version(name) for name in ("PyMuPDF", "requests")}}
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
    return manifest


def run(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    candidates = {row["publisher_pdf_url"]: row for row in
                  json.loads(Path(manifest["candidate_file"]).read_text(encoding="utf-8"))}
    if sha256(manifest["candidate_file"]) != manifest["candidate_sha256"]:
        raise ValueError("Candidate list changed")
    conn = sqlite3.connect(directory / "checkpoint.sqlite3", timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        for original in conn.execute("SELECT * FROM records WHERE status='PENDING' ORDER BY url").fetchall():
            url = original["url"]
            key = hashlib.sha256(url.encode()).hexdigest()[:20]
            pdf = directory / "raw" / (key + ".pdf")
            output = directory / "metadata" / (key + ".json")
            try:
                if urlparse(url).hostname != "www.unsw.edu.au" or not url.startswith("https://"):
                    raise ValueError("Candidate is not an observed HTTPS UNSW publisher URL")
                pdf.parent.mkdir(exist_ok=True)
                if not pdf.exists():
                    cache = manifest["cached_pdf_sources"].get(url)
                    if cache:
                        if sha256(cache["path"]) != cache["sha256"]:
                            raise ValueError("A cached public PDF changed")
                        with Path(cache["path"]).open("rb") as source, pdf.open("xb") as target:
                            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                target.write(chunk)
                    else:
                        response = requests.get(url, headers={"User-Agent": "ResearchTools-PublicBibliographyAudit/1.0"}, timeout=(15, 45))
                        if response.status_code != 200:
                            raise RuntimeError(f"Public publisher PDF HTTP {response.status_code}")
                        if not response.content.startswith(b"%PDF-") or len(response.content) > manifest["max_download_bytes"]:
                            raise ValueError("Unexpected PDF format or size; retain candidate for review")
                        with pdf.open("xb") as target:
                            target.write(response.content)
                        time.sleep(manifest["request_delay_seconds"])
                if output.exists():
                    result = json.loads(output.read_text(encoding="utf-8"))
                    if result["pdf_sha256"] != sha256(pdf):
                        raise ValueError("A previously verified original PDF changed")
                else:
                    result = extract(pdf, candidates[url]["candidate_title"], manifest["max_front_pages"])
                    if (result["status"] == "VERIFIED_METADATA" and result.get("archive_year") and
                            not manifest["from_year"] <= result["archive_year"] <= manifest["to_year"]):
                        result["status"] = "OUTSIDE_VERIFIED_PRINT_YEAR_SCOPE"
                    result.update(source_url=url, source_name="UNSW eJournal of Tax Research public PDF front matter",
                                  pdf_path=str(pdf), pdf_sha256=sha256(pdf), pdf_bytes=pdf.stat().st_size,
                                  verified_at=now(), index_evidence=candidates[url]["index_evidence"],
                                  pdf_downloaded=True, source_type="publisher_metadata")
                    output.parent.mkdir(exist_ok=True)
                    with output.open("x", encoding="utf-8") as stream:
                        json.dump(result, stream, ensure_ascii=False, indent=2)
                conn.execute("UPDATE records SET status=?,metadata_path=?,pdf_path=?,pdf_sha256=?,error=NULL,updated_at=? WHERE url=?",
                             (result["status"], str(output), str(pdf), result["pdf_sha256"], now(), url))
                conn.commit()
                print(json.dumps({"url_key": key, "status": result["status"], "print_year": result.get("print_year"),
                                  "pages_text_extracted": result["pages_text_extracted"]}), flush=True)
            except Exception as exc:
                conn.execute("UPDATE records SET status='REVIEW_FETCH_OR_PARSE_ERROR',error=?,updated_at=? WHERE url=?",
                             (f"{type(exc).__name__}: {str(exc)[:250]}", now(), url))
                conn.commit()
                print(json.dumps({"url_key": key, "status": "REVIEW_FETCH_OR_PARSE_ERROR", "error_type": type(exc).__name__}), flush=True)
        report = {"finished_at": now(), "states": [list(row) for row in conn.execute("SELECT status,COUNT(*) FROM records GROUP BY status")],
                  "article_database_writes": 0, "full_text_reviewed": False}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        with (directory / ("report_" + stamp + ".json")).open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
        return report
    finally:
        conn.close()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cached-probe-report", type=Path)
    args = parser.parse_args()
    initialize(args.output_dir, args.candidates, args.cached_probe_report)
    # Reuse the existing OS-lock helper; the file is not evidence of process liveness.
    from supplement_astar_openalex_scope import exclusive_runner
    with exclusive_runner(args.output_dir):
        print(json.dumps(run(args.output_dir), indent=2))


if __name__ == "__main__":
    main()
