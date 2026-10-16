#!/usr/bin/env python3
"""Prepare bibliographic candidates from saved public UNSW issue indexes.

This performs no network requests or article-database writes. Publisher labels
and URL year hints are preserved separately; they are not verified print years.
The next step is to verify public PDF front matter for titles, authors and years.
"""

import argparse
import gzip
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

ORIGIN = "https://www.unsw.edu.au"
YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def normalize_text(text):
    return " ".join(text.split())


def groups(soup):
    for node in soup.select("li.accordion-list-item"):
        heading = node.select_one(".accordion-item-heading")
        if heading is not None:
            yield normalize_text(heading.get_text(" ", strip=True)), node
    for heading in soup.select(".cmp-text h5"):
        label = normalize_text(heading.get_text(" ", strip=True))
        if "Volume" in label and YEAR.search(label):
            yield label, heading.parent


def prepare(probe_report, output_dir):
    report = json.loads(probe_report.read_text(encoding="utf-8"))
    records, excluded, sources = {}, [], []
    for source in report:
        if source["name"] not in ("ejtr_past", "ejtr_current") or source.get("status_code") != 200:
            continue
        raw = Path(source["raw_path"])
        if hashlib.sha256(raw.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("An original publisher index hash changed")
        with gzip.open(raw, "rt", encoding="utf-8") as stream:
            soup = BeautifulSoup(stream.read(), "html.parser")
        sources.append({key: source[key] for key in ("name", "url", "raw_path", "sha256", "requested_at")})
        for heading, group in groups(soup):
            full_issue_label = None
            for anchor in group.select("a[href]"):
                href = anchor["href"]
                if ".pdf" not in href.lower():
                    continue
                label = normalize_text(anchor.get_text(" ", strip=True))
                url = urljoin(ORIGIN, href)
                if re.match(r"full\s+edition", label, re.IGNORECASE):
                    full_issue_label = label
                    excluded.append({"url": url, "label": label, "reason": "full_issue_pdf_not_an_individual_article"})
                    continue
                observed_labels = {"group_heading": heading, "full_issue_label": full_issue_label,
                                   "article_link_label": label, "publisher_url_path": unquote(href)}
                year_hints = {key: sorted(set(int(year) for year in YEAR.findall(text or "")))
                              for key, text in observed_labels.items()}
                year_set = set(value for years in year_hints.values() for value in years)
                if not any(2010 <= value <= 2026 for value in year_set):
                    excluded.append({"url": url, "label": label, "reason": "no_explicit_in_scope_year_hint"})
                    continue
                clean_title = re.sub(r"\s*\(?[Pp]\s*\d+(?:\s*[-–]\s*\d+)?\)?\s*$", "", label).strip()
                parent_text = normalize_text(anchor.parent.get_text(" ", strip=True))
                evidence = {"source_index_url": source["url"], "source_index_sha256": source["sha256"],
                            "labels": observed_labels, "year_hints": year_hints, "parent_text": parent_text}
                record = records.setdefault(url, {"journal_title": "eJournal of Tax Research",
                    "publisher_pdf_url": url, "candidate_title": clean_title, "index_evidence": [],
                    "status": "PENDING_FRONT_MATTER_VERIFICATION", "publication_year": None,
                    "publication_date": None, "authors": [], "abstract": None,
                    "title_encoding_requires_review": "\ufffd" in label,
                    "pdf_downloaded": False, "full_text_read": False})
                if evidence not in record["index_evidence"]:
                    record["index_evidence"].append(evidence)
    output_dir.mkdir(parents=True, exist_ok=False)
    summary = {"created_at": datetime.now(timezone.utc).isoformat(), "journal_title": "eJournal of Tax Research",
               "candidate_count": len(records), "excluded_link_count": len(excluded),
               "titles_with_encoding_damage": sum(row["title_encoding_requires_review"] for row in records.values()),
               "sources": sources, "network_requests": 0, "article_database_writes": 0,
               "pdf_downloads": 0, "reading_scope": "two_publisher_issue_index_HTML_pages",
               "verified_print_years": 0, "next_step": "public_PDF_front_matter_verification",
               "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for name, value in (("candidates.json", list(records.values())), ("excluded_links.json", excluded), ("report.json", summary)):
        with (output_dir / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.probe_report.resolve(), args.output_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
