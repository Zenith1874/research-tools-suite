#!/usr/bin/env python3
"""Derive repaired front-matter metadata, preserving the first verification pass."""

import argparse
import gzip
import importlib.util
import json
import re
import sqlite3
from pathlib import Path

import fitz

SPEC = importlib.util.spec_from_file_location("ejtr_frontmatter", Path(__file__).with_name("verify_ejtr_frontmatter.py"))
FRONT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FRONT)


def verify_evidence(evidence):
    for field in ("pdf_path", "html_path"):
        if evidence.get(field):
            if FRONT.sha256(evidence[field]) != evidence[field.replace("_path", "_sha256")]:
                raise ValueError("An issue-year source changed")
    with fitz.open(evidence["pdf_path"]) as document:
        cover = document[0].get_text()
    pattern = rf"Volume\s+{evidence['volume']},\s*Number\s+{evidence['issue']}\b"
    if not re.search(pattern, cover):
        raise ValueError("The source cover belongs to a different issue")
    if evidence["basis"] == "publisher_issue_cover_year":
        if not re.search(rf"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+{evidence['year']}\b", cover):
            raise ValueError("The year is not present in the issue cover date")
    elif evidence["basis"] == "publisher_archive_issue_label_year":
        from bs4 import BeautifulSoup
        with gzip.open(evidence["html_path"], "rt", encoding="utf-8") as stream:
            soup = BeautifulSoup(stream.read(), "html.parser")
        label = f"{evidence['year']} Volume {evidence['volume']}, Number {evidence['issue']}"
        if label not in [node.get_text(" ", strip=True) for node in soup.select(".accordion-item-heading")]:
            raise ValueError("The recorded year is not in the publisher's matching issue label")
    else:
        raise ValueError("Unsupported issue-year evidence")


def repair(directory, output, authority_file, manual_file):
    authority = json.loads(authority_file.read_text(encoding="utf-8"))
    manual = json.loads(manual_file.read_text(encoding="utf-8"))
    evidence_by_issue = {(row["volume"], row["issue"]): row for row in authority["issue_year_evidence"]}
    for evidence in evidence_by_issue.values():
        verify_evidence(evidence)
    source_manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    candidates = {row["publisher_pdf_url"]: row for row in
                  json.loads(Path(source_manifest["candidate_file"]).read_text(encoding="utf-8"))}
    output.mkdir(parents=True, exist_ok=False)
    conn = sqlite3.connect((directory / "checkpoint.sqlite3").as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    results, source_hashes = [], {}
    try:
        for row in conn.execute("SELECT * FROM records ORDER BY url"):
            old_path = Path(row["metadata_path"])
            old = json.loads(old_path.read_text(encoding="utf-8"))
            source_hashes[str(old_path)] = FRONT.sha256(old_path)
            if FRONT.sha256(old["pdf_path"]) != old["pdf_sha256"]:
                raise ValueError("An immutable article PDF changed")
            key = old_path.stem
            observed = manual["records"].get(key)
            with fitz.open(old["pdf_path"]) as document:
                first_text = document[0].get_text()
                issue_match = FRONT.ISSUE_HEADER.search(first_text)
                issue_pair = ((int(issue_match.group(2)), int(issue_match.group(3)))
                              if issue_match else (old.get("volume"), old.get("issue")))
                evidence = evidence_by_issue.get(issue_pair)
                if observed and observed.get("article_first_page") == 2 and not issue_match and observed.get("volume") == 10:
                    cover = re.search(r"Volume\s+10,\s*Number\s+1.*?February\s+2012", first_text, re.S)
                    if not cover:
                        raise ValueError("The observed 2012 cover no longer matches the source")
                    result = {"status": "VERIFIED_METADATA", "archive_year": 2012, "print_year": 2012,
                              "publication_year": 2012, "volume": 10, "issue": 1,
                              "article_first_page": 2, "pages_text_extracted": [1, 2],
                              "selected_page_text": [first_text, document[1].get_text()],
                              "year_basis": "same_pdf_issue_cover_year", "date_precision": "year",
                              "publication_date": None, "abstract": None, "authors": [], "keywords": []}
                else:
                    result = FRONT.extract(old["pdf_path"], candidates[row["url"]]["candidate_title"],
                                           issue_year_evidence=evidence)
                if observed:
                    image = Path(observed["rendered_page"])
                    if FRONT.sha256(image) != observed["rendered_page_sha256"]:
                        raise ValueError("A visually checked source page changed")
                    if observed["pdf_sha256"] != old["pdf_sha256"]:
                        raise ValueError("A manual observation refers to a different PDF")
                    result.update(title=observed["title"], authors=observed["authors"],
                                  visually_checked_fields=["title", "authors"],
                                  visual_evidence=observed, status="VERIFIED_METADATA")
                    if not result.get("archive_year"):
                        raise ValueError("A visual title correction cannot supply an unobserved year")
                result.update(pdf_page_count=len(document), full_text_reviewed=False,
                              all_pdf_pages_text_extracted=len(result["pages_text_extracted"]) == len(document),
                              reading_scope="bounded_front_pages_and_recorded_visual_metadata_check")
            if result["status"] == "VERIFIED_METADATA" and not 2010 <= result["archive_year"] <= 2026:
                result["status"] = "OUTSIDE_VERIFIED_PRINT_YEAR_SCOPE"
            result.update(source_url=row["url"], pdf_path=old["pdf_path"], pdf_sha256=old["pdf_sha256"],
                          index_evidence=old["index_evidence"], supersedes_metadata_path=str(old_path),
                          supersedes_metadata_sha256=source_hashes[str(old_path)],
                          verified_at=FRONT.now(), publication_date=None, source_type="publisher_metadata")
            path = output / (key + ".json")
            with path.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
            results.append({"url": row["url"], "status": result["status"], "metadata_path": str(path),
                            "metadata_sha256": FRONT.sha256(path), "archive_year": result.get("archive_year")})
    finally:
        conn.close()
    from collections import Counter
    report = {"created_at": FRONT.now(), "records": results, "states": dict(Counter(row["status"] for row in results)),
              "original_metadata_hashes": source_hashes, "source_manifest_sha256": FRONT.sha256(directory / "manifest.json"),
              "authority_file": str(authority_file), "authority_sha256": FRONT.sha256(authority_file),
              "manual_file": str(manual_file), "manual_sha256": FRONT.sha256(manual_file),
              "script_sha256": FRONT.sha256(__file__), "extractor_sha256": FRONT.sha256(FRONT.__file__),
              "network_requests": 0, "article_database_writes": 0, "original_records_overwritten": False}
    with (output / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return {key: report[key] for key in ("created_at", "states", "network_requests", "article_database_writes", "original_records_overwritten")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--authority-file", type=Path, required=True)
    parser.add_argument("--manual-file", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(repair(args.source_dir.resolve(), args.output_dir.resolve(),
                            args.authority_file.resolve(), args.manual_file.resolve()), indent=2))


if __name__ == "__main__":
    main()
