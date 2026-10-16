#!/usr/bin/env python3
"""Resolve printed article start pages and stage conservative first-page metadata."""

import argparse
import hashlib
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import fitz

SPEC = importlib.util.spec_from_file_location("frontmatter_helpers", Path(__file__).with_name("verify_ejtr_frontmatter.py"))
FRONT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FRONT)


def issue_from_front(document):
    # A copied running header can retain an earlier volume. Prefer the separate
    # cover-body issue label, and record all header labels as contradictory evidence.
    cover = document[0].get_text()
    body = re.findall(r"^\s*\((20\d{2})\)\s*Volume\s+(\d+)(?:\s*\((\d+)\))?\s*$", cover, re.M | re.I)
    if body:
        year, volume, issue = body[-1]
        return int(year), int(volume), issue or None, "cover_body_issue_label", cover
    for number in range(min(2, len(document))):
        text = document[number].get_text()
        match = re.search(r"JOURNAL OF AUSTRALIAN TAXATION\s*\(?\s*(20\d{2})\)?\s*Vol\.?\s*(\d+)\s*\((\d+)\)", text, re.I)
        if match:
            return int(match[1]), int(match[2]), match[3], "cover_or_contents_journal_heading", text
    raise ValueError("No explicit cover/contents issue year")


def printed_number(page):
    regions = [fitz.Rect(0, page.rect.height - 110, page.rect.width, page.rect.height),
               fitz.Rect(0, 0, page.rect.width, 125)]
    for region in regions:
        text = page.get_text(clip=region)
        values = [int(line.strip()) for line in text.splitlines() if re.fullmatch(r"\d{1,4}", line.strip())]
        if values:
            return values[-1]
    return None


def first_page_fields(page):
    lines = FRONT.page_lines(page)
    boundary = next((row for row in lines if row["text"].strip().upper() in ("ABSTRACT", "INTRODUCTION", "1. INTRODUCTION", "I. INTRODUCTION", "I. Introduction")
                     and row["bbox"][1] > 100), None)
    upper = boundary["bbox"][1] if boundary else page.rect.height * 0.45
    region = [row for row in lines if 60 < row["bbox"][1] < upper and not re.fullmatch(r"\d+", row["text"])
              and not row["text"].upper().startswith("JOURNAL OF AUSTRALIAN")]
    if not region:
        raise ValueError("No isolated first-page title region")
    size = max(row["size"] for row in region)
    candidates = [row for row in region if row["size"] >= size - 0.25]
    selected = []
    for row in candidates:
        if selected and row["bbox"][1] - selected[-1]["bbox"][3] > max(8, size * 0.45):
            break
        selected.append(row)
    title = FRONT.clean(" ".join(row["text"] for row in selected))
    if (size < 11 or not 8 <= len(title) <= 350 or len(selected) > 8 or
            re.match(r"^(?:\d{1,2}|[IVXL]+|[A-Z])\.\s", title) or
            title.upper() in ("TABLE OF CONTENTS", "INTRODUCTION")):
        raise ValueError("Title needs visual confirmation")
    end = max(row["bbox"][3] for row in selected)
    bylines = [row["text"] for row in region if row["bbox"][1] > end and row["size"] >= 10.5]
    authors = []
    if boundary:
        for line in bylines:
            for name in re.split(r"\s*,\s*|\s+AND\s+|\s+and\s+", line):
                name = re.sub(r"^[\s\d*†‡#∗]+|[\s\d*†‡#∗]+$", "", name).strip()
                name = re.sub(r"\*[A-Z]?$", "", name).strip()
                if name:
                    authors.append(name)
    return {"title": title, "authors": authors, "observed_byline_lines": bylines,
            "abstract": None, "abstract_status": "not_extracted", "field_scope": "article_first_page_title_region"}


def prepare(locator_file, output):
    locators = json.loads(locator_file.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=False)
    records, reviews = [], []
    for locator in locators:
        path = Path(locator["pdf_path"])
        if FRONT.sha256(path) != locator["pdf_sha256"]:
            raise ValueError("An original public issue PDF changed")
        with fitz.open(path) as document:
            year, volume, issue, basis, evidence = issue_from_front(document)
            starts = locator["printed_article_start_pages"]
            offset = None
            first = min(starts)
            for number in range(min(16, len(document))):
                page = document[number]
                header = page.get_text(clip=fitz.Rect(0, 0, page.rect.width, 125))
                if "CONTENTS" in page.get_text(clip=fitz.Rect(0, 0, page.rect.width, 250)).upper():
                    continue
                if printed_number(page) == first:
                    try:
                        first_page_fields(page)
                        offset = number - first
                        break
                    except ValueError:
                        continue
            if offset is None:
                reviews.append({"pdf_path": str(path), "reason": "printed_to_physical_page_offset_unconfirmed"})
                continue
            for printed in starts:
                number = printed + offset
                try:
                    fields = None
                    if 0 <= number < len(document) and printed_number(document[number]) == printed:
                        try:
                            fields = first_page_fields(document[number])
                        except ValueError:
                            pass
                    if fields is None:
                        # Concatenated article PDFs can insert unnumbered pages.
                        # Search pagination regions, then read only a candidate
                        # first page whose actual printed number is corroborated.
                        found = None
                        for candidate in range(max(2, number - 8), min(len(document), number + 18)):
                            if printed_number(document[candidate]) != printed:
                                continue
                            try:
                                fields = first_page_fields(document[candidate])
                                found = candidate
                                break
                            except ValueError:
                                continue
                        if found is None:
                            raise ValueError("Printed start page does not match a corroborated physical page")
                        number = found
                    if fields is None:
                        raise ValueError("A candidate page has no confirmed title")
                    raw_id = "austax_issue_item:" + hashlib.sha256(json.dumps([locator["url"], year, volume, issue, printed]).encode()).hexdigest()
                    record = dict(fields, status="PENDING_FIRST_PAGE_VISUAL_SPOTCHECK", source_url=locator["url"], source_raw_id=raw_id,
                        archive_year=year, publication_year=year, volume=volume, issue=issue,
                        publication_date=None, publication_month=None, date_precision="year",
                        year_basis=basis, issue_year_evidence=evidence,
                        pdf_path=str(path), pdf_sha256=locator["pdf_sha256"], physical_pdf_page=number+1,
                        printed_start_page=printed, source_index_pages=locator["source_index_pages"],
                        reading_scope="cover_contents_pagination_regions_and_selected_article_first_pages", full_text_reviewed=False)
                    records.append(record)
                except ValueError as error:
                    reviews.append({"pdf_path": str(path), "printed_page": printed, "reason": str(error)})
    for name, data in (("records.json", records), ("reviews.json", reviews)):
        with (output / name).open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "issue_pdfs": len(locators),
              "staged_records": len(records), "reviews": len(reviews), "article_database_writes": 0,
              "full_text_reviewed": False, "script_sha256": FRONT.sha256(__file__)}
    with (output / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locator-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.locator_file.resolve(), args.output_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
