#!/usr/bin/env python3
"""Prepare source-backed NZULR issue metadata without inferring exact days."""

import argparse
import copy
import gzip
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

MONTHS = {name: number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}
ISSUE = re.compile(r"Vol\.?\s*(\d+)\s*,?\s*No\.?\s*(\d+[A-Za-z]?)\s+(\w+)\s+(\d{4})", re.I)


def paragraph_items(node, section):
    """Split legacy paragraphs that place several works around standalone authors."""
    def nonempty_sibling(tag, direction):
        sibling = getattr(tag, direction)
        while sibling is not None:
            text = sibling.get_text(' ', strip=True) if hasattr(sibling, 'get_text') else str(sibling).strip()
            if getattr(sibling, 'name', None) == 'br' or text:
                return sibling
            sibling = getattr(sibling, direction)
        return None

    standalone = []
    for tag in node.find_all('em', recursive=False):
        previous = nonempty_sibling(tag, 'previous_sibling')
        following = nonempty_sibling(tag, 'next_sibling')
        if (tag.get_text(' ', strip=True) and
                (previous is None or getattr(previous, 'name', None) == 'br') and
                (following is None or getattr(following, 'name', None) == 'br')):
            standalone.append(tag)
    # Ordinary one-work paragraphs retain their existing composite identities.
    if len(standalone) < 2:
        return [(node, section)]
    chunks, pending, current_section, book_breaks = [], [], section, 0

    def fragment(values):
        return BeautifulSoup('<p>' + ''.join(str(value) for value in values) + '</p>', 'lxml').p

    for child in node.children:
        text = child.get_text(' ', strip=True) if hasattr(child, 'get_text') else str(child).strip()
        if text.upper() in ('BOOK REVIEW', 'BOOK REVIEWS', 'ARTICLES', 'NOTES', 'CASE NOTE', 'CASE NOTES'):
            if fragment(pending).get_text(' ', strip=True):
                chunks.append((fragment(pending), current_section))
            pending = []
            current_section = text.lower()
            continue
        is_standalone = any(child is tag for tag in standalone)
        if 'book' in current_section:
            pending.append(child)
            if getattr(child, 'name', None) == 'br':
                book_breaks += 1
                if book_breaks >= 2 and fragment(pending).get_text(' ', strip=True):
                    chunks.append((fragment(pending), current_section))
                    pending = []
            elif text:
                book_breaks = 0
        elif (is_standalone and re.match(r'^and\b', text, flags=re.I) and chunks
              and chunks[-1][0].find('em') and not fragment(pending).get_text(' ', strip=True)):
            # A wrapped author block can end with a separate italic "and Name".
            previous_author = chunks[-1][0].find_all('em')[-1]
            previous_author.string = previous_author.get_text(' ', strip=True) + ' ' + text
            pending = []
        elif is_standalone and fragment(pending).get_text(' ', strip=True):
            chunks.append((fragment(pending + [child]), current_section))
            pending = []
        else:
            pending.append(child)
    if fragment(pending).get_text(' ', strip=True):
        chunks.append((fragment(pending), current_section))
    return chunks


def parse_issue(html, source_url, source_path, sha256):
    # Browser-like repair closes malformed nested paragraphs in legacy pages.
    if isinstance(html, bytes):
        try:
            html = html.decode("utf-8")
        except UnicodeDecodeError:
            html = html.decode("cp1252")
    soup = BeautifulSoup(html, "lxml")
    headings = [node for node in soup.select("h3") if ISSUE.search(node.get_text(" ", strip=True))]
    if not headings:
        raise ValueError("An issue year/month/number is not explicitly reported")
    records, summaries = [], []
    for heading in headings:
        extracted, summary = parse_one_issue(heading, source_url, source_path, sha256)
        records += extracted
        summaries.append(summary)
    return records, summaries


def parse_one_issue(heading, source_url, source_path, sha256):
    match = ISSUE.search(heading.get_text(" ", strip=True))
    volume, issue, month, year = int(match.group(1)), match.group(2).upper(), match.group(3).title(), int(match.group(4))
    if month not in MONTHS:
        raise ValueError("Unrecognized explicitly printed issue month")
    if not 2010 <= year <= 2026:
        return [], {"source_url": source_url, "status": "OUTSIDE_YEAR_SCOPE", "year": year}
    container = heading.parent
    section = "articles"
    records = []
    for node in heading.next_siblings:
        if getattr(node, "name", None) == "h3" and ISSUE.search(node.get_text(" ", strip=True)):
            break
        if getattr(node, "name", None) == "h4":
            section = node.get_text(" ", strip=True).lower()
            continue
        if getattr(node, "name", None) != "p":
            continue
        text = node.get_text(" ", strip=True)
        if text.upper() in ("ARTICLES", "BOOK REVIEW", "BOOK REVIEWS", "NOTES", "CASE NOTE", "CASE NOTES"):
            section = text.lower()
            continue
        if node.find("a") or not text:
            continue
        for item_node, item_section in paragraph_items(node, section):
            section = item_section
            emphasis = item_node.find_all("em")
            valid_emphasis = [(index, tag) for index, tag in enumerate(emphasis) if tag.get_text(" ", strip=True)]
            book_review = "book" in item_section
            author_text, authors = None, []
            title_node = copy.copy(item_node)
            if valid_emphasis and (not book_review or len(valid_emphasis) > 1):
                index, author_node = valid_emphasis[-1]
                author_text = author_node.get_text(" ", strip=True)
                title_node.find_all("em")[index].decompose()
                authors = [" ".join(name.split()) for name in re.split(r"\s*,\s*|\s+and\s+", author_text) if name.strip()]
            title = " ".join(title_node.get_text(" ", strip=True).split())
            title = re.sub(r"^NOTE\s+", "", title)
            if not title or title.lower().startswith(("see the", "to purchase", "to subscribe")):
                continue
            key_data = [source_url, volume, issue, year, title, author_text]
            raw_id = "nzulr_issue_item:" + hashlib.sha256(json.dumps(key_data, ensure_ascii=False).encode()).hexdigest()
            records.append({"journal_title": "New Zealand Universities Law Review", "source_url": source_url,
            "source_raw_id": raw_id, "title": title, "authors": authors, "observed_author_text": author_text,
            "volume": volume, "issue": issue, "archive_year": year, "publication_year": year,
            "publication_month": f"{year:04d}-{MONTHS[month]:02d}", "publication_date": None,
            "date_precision": "month", "year_basis": "publisher_issue_heading_year",
            "record_type": "book-review" if book_review else "journal-metadata-item", "section_label": item_section,
            "status": "VERIFIED_ISSUE_HTML_METADATA", "abstract": None, "abstract_status": "not_yet_extracted",
            "source_html_path": str(source_path), "source_html_sha256": sha256,
            "source_issue_heading": heading.get_text(" ", strip=True), "full_text_reviewed": False})
    abstract_links = [urljoin(source_url, node["href"]) for node in container.select("a[href]") if "abstract" in node["href"].lower() and ".pdf" in node["href"].lower()]
    return records, {"source_url": source_url, "year": year, "volume": volume, "issue": issue,
                     "status": "PARSED", "record_count": len(records), "public_abstract_pdf_urls": sorted(set(abstract_links))}


def prepare(issue_dir, current_receipt, output_dir):
    inputs = []
    conn = sqlite3.connect((issue_dir / "checkpoint.sqlite3").as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute("SELECT * FROM records WHERE status='SAVED' AND url LIKE '%nzulr.com%'"):
            value = json.loads(row["details_json"])
            inputs.append({"url": row["url"], "raw_path": value["path"], "sha256": value["sha256"]})
    finally:
        conn.close()
    current = json.loads(current_receipt.read_text(encoding="utf-8"))
    inputs.append(current)
    records, issues = [], []
    for source in inputs:
        path = Path(source["raw_path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("An original issue HTML changed")
        with gzip.open(path, "rb") as stream:
            extracted, summary = parse_issue(stream.read(), source["url"], path, source["sha256"])
        records += extracted
        issues += summary
    if len({row["source_raw_id"] for row in records}) != len(records):
        raise ValueError("Duplicate issue/item identities must be reviewed")
    output_dir.mkdir(parents=True, exist_ok=False)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "journal_title": "New Zealand Universities Law Review",
              "issue_pages_read": len(inputs), "in_scope_issues": sum(row["status"] == "PARSED" for row in issues),
              "records": len(records), "explicit_exact_days": 0, "article_database_writes": 0,
              "reading_scope": "publisher_issue_HTML_metadata_only", "full_text_reviewed": False,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for name, data in (("records.json", records), ("issues.json", issues), ("report.json", report)):
        with (output_dir / name).open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-dir", type=Path, required=True)
    parser.add_argument("--current-receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.issue_dir.resolve(), args.current_receipt.resolve(), args.output_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
