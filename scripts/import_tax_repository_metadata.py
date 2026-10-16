#!/usr/bin/env python3
"""Import a corroborated institutional bibliography record for a tracked journal."""

import argparse
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.astar_history_service import HistoryRunner, normalize_doi, utc_now, write_new_json, digest

REPOSITORY_NAMES = {
    "research.monash.edu": "Monash University",
    "researchers.westernsydney.edu.au": "Western Sydney University",
    "eprints.qut.edu.au": "Queensland University of Technology",
}
JOURNAL_TITLES = {"Australian Tax Forum", "Australian Tax Forum: a journal of taxation policy, law and reform"}


def citation_fields(soup, hostname):
    allowed = {"citation_title", "citation_author", "citation_publication_date", "citation_journal_title",
               "citation_issn", "citation_volume", "citation_issue", "citation_firstpage", "citation_lastpage", "citation_doi"}
    eprints_names = {"eprints.title": "citation_title", "eprints.creators_name": "citation_author",
                     "eprints.date": "citation_publication_date", "eprints.publication": "citation_journal_title",
                     "eprints.issn": "citation_issn", "eprints.volume": "citation_volume", "eprints.number": "citation_issue"}
    citation = {}
    for tag in soup.select("meta[name][content]"):
        name = eprints_names.get(tag["name"]) if hostname == "eprints.qut.edu.au" else tag["name"]
        if name in allowed:
            citation.setdefault(name, []).append(tag["content"])
    if hostname == "eprints.qut.edu.au":
        published = soup.select_one('meta[name="eprints.ispublished"]')
        kind = soup.select_one('meta[name="eprints.type"]')
        if published is None or published.get("content") != "pub" or kind is None or kind.get("content") != "article":
            raise ValueError("the QUT record is not a published journal article")
        pages = soup.select_one('meta[name="eprints.pagerange"]')
        if pages and "-" in pages.get("content", ""):
            first, last = pages["content"].split("-", 1)
            citation.update({"citation_firstpage": [first], "citation_lastpage": [last]})
    return citation


def parse_publication_date(reported_date):
    """Retain the precision supplied by the repository without inventing a day."""
    parts = reported_date.split("/")
    if len(parts) == 1 and len(parts[0]) == 4 and parts[0].isdigit():
        return int(parts[0]), None, None, "year"
    if len(parts) == 2:
        parsed = datetime.strptime(reported_date, "%Y/%m")
        return parsed.year, None, parsed.strftime("%Y-%m"), "month"
    parsed = datetime.strptime(reported_date, "%Y/%m/%d")
    return parsed.year, parsed.date().isoformat(), parsed.strftime("%Y-%m"), "day"


def import_record(run_dir, source_url):
    parsed_url = urlparse(source_url)
    hostname = parsed_url.hostname
    if parsed_url.scheme != "https" or hostname not in REPOSITORY_NAMES:
        raise ValueError("this collector only accepts the observed public institutional repositories")
    response = requests.get(source_url, headers={"User-Agent": "ResearchTools-HistoryAudit/1.0"}, timeout=30)
    if response.status_code != 200 or urlparse(response.url).hostname != hostname:
        raise ValueError(f"repository metadata unavailable: HTTP {response.status_code}")
    soup = BeautifulSoup(response.text, "html.parser")
    citation = citation_fields(soup, hostname)
    required = ("citation_title", "citation_author", "citation_publication_date", "citation_journal_title", "citation_issn")
    if any(key not in citation for key in required):
        raise ValueError("required repository citation fields are missing")
    if len(citation["citation_journal_title"]) != 1 or citation["citation_journal_title"][0] not in JOURNAL_TITLES or citation["citation_issn"] != ["0812-695X"]:
        raise ValueError("repository record does not corroborate the tracked journal identity")
    reported_date = citation["citation_publication_date"][0]
    year, publication_date, publication_month, precision = parse_publication_date(reported_date)
    reported_doi = normalize_doi((citation.get("citation_doi") or [None])[0])
    # The observed Western Sydney DOI is a Crossref posted-content/preprint
    # record. It must not become the journal version's canonical identifier.
    excluded_preprint_doi = reported_doi if (reported_doi or "").startswith("10.2139/ssrn.") else None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = run_dir / "repository_supplements" / stamp
    folder.mkdir(parents=True)
    with gzip.open(folder / "repository.html.gz", "wt", encoding="utf-8") as stream:
        stream.write(response.text)
    write_new_json(folder / "citation.json", {"requested_at": utc_now(), "source_url": source_url,
                                              "citation_fields": citation, "excluded_preprint_doi": excluded_preprint_doi,
                                              "reading_scope": "public HTML bibliographic metadata; paper full text not read"})
    article = {
        "doi": None if excluded_preprint_doi else reported_doi, "openalex_id": None,
        "title": citation["citation_title"][0], "authors": citation["citation_author"],
        "publication_year": year, "publication_date": publication_date,
        "publication_month": publication_month, "date_precision": precision,
        "journal_title": "Australian Tax Forum", "journal_issn": "0812-695X", "publisher": None,
        "abstract": None, "abstract_status": "missing", "concepts": [], "keywords": [],
        "url": source_url, "landing_page_url": source_url, "source_url": source_url,
        "source_name": REPOSITORY_NAMES[hostname] + " public repository metadata", "source_type": "publisher_metadata",
        "source_raw_id": source_url, "data_status": "repository_metadata", "record_type": "journal-article",
    }
    runner = HistoryRunner(run_dir)
    try:
        journal = next(j for j in runner.journals.values() if j["journal_title"] == "Australian Tax Forum")
        runner.main.execute("BEGIN IMMEDIATE")
        aid, disposition = runner.ingest_article(article, journal)
        runner.main.commit()
        result = {"created_at": utc_now(), "article_id": aid, "disposition": disposition,
                  "publication_year": year, "publication_date": publication_date,
                  "publication_month": publication_month, "date_precision": precision,
                  "excluded_preprint_doi": excluded_preprint_doi,
                  "source_url": source_url, "artifact_dir": str(folder), "script_sha256": digest(__file__)}
        write_new_json(folder / "import_result.json", result)
        runner.event("repository_metadata_supplemented", result)
        return result
    except Exception:
        runner.main.rollback()
        raise
    finally:
        runner.close()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    args = parser.parse_args()
    print(json.dumps(import_record(args.run_dir.resolve(), args.source_url), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
