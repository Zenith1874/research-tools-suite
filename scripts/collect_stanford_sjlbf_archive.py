#!/usr/bin/env python3
"""Collect the public Stanford SJLBF archive through its observed pager API."""

import argparse
import gzip
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def config_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    config = http = None
    for script in soup.select("script"):
        for variable in ("FWP_JSON", "FWP_HTTP"):
            match = re.search(r"window\." + variable + r"\s*=\s*(\{.*\});", script.get_text(), re.S)
            if match:
                if variable == "FWP_JSON":
                    config = json.loads(match.group(1))
                else:
                    http = json.loads(match.group(1))
    template = soup.select_one(".facetwp-template").get("data-name")
    if not config or not http or template != "sjlbf_archive":
        raise ValueError("The public archive configuration changed")
    return soup, config, http, template


def parse_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    result = []
    for card in soup.select("article.pt-publication"):
        heading = card.select_one("h2.li-title a")
        journal = card.select_one(".ptp-publisher [itemprop=name]")
        if not heading or not journal or journal.get_text(" ", strip=True) != "Stanford Journal of Law, Business & Finance":
            raise ValueError("A card is missing identity or belongs to another journal")
        date = card.select_one("time[datetime]")
        volume = card.select_one("[itemprop=volumeNumber]")
        issue = card.select_one("[itemprop=issueNumber]")
        pages = card.select_one("[itemprop=pagination]")
        result.append({"title": heading.get_text(" ", strip=True), "publisher_article_url": heading["href"],
            "authors": [node.get_text(" ", strip=True) for node in card.select("[itemprop=author] [itemprop=name]")],
            "reported_web_datetime": date["datetime"] if date else None,
            "reported_web_date_attributes": date.get("itemprop") if date else None,
            "volume_label": volume.get_text(" ", strip=True) if volume else None,
            "issue_label": issue.get_text(" ", strip=True) if issue else None,
            "pages": pages.get_text(" ", strip=True) if pages else None,
            "publisher_pdf_urls": [node["href"] for node in card.select(".ptp-attachments a[href]")],
            "publication_year": None, "archive_year": None, "status": "PENDING_ISSUE_YEAR_VERIFICATION",
            "full_text_reviewed": False})
    return result


def collect(source_html, page2_probe, output_dir):
    with gzip.open(source_html, "rt", encoding="utf-8") as stream:
        html = stream.read()
    soup, config, http, template = config_from_html(html)
    pager = config["preload_data"]["settings"]["pager"]
    expected, pages = int(pager["total_rows"]), int(pager["total_pages"])
    output_dir.mkdir(parents=True, exist_ok=False)
    records, hashes = {}, []
    for page in range(1, pages + 1):
        if page == 1:
            envelope = {"provider": "Stanford public archive", "page": 1,
                        "source_html_sha256": checksum(source_html), "template": html,
                        "pager": pager, "source_url": "https://law.stanford.edu/stanford-journal-of-law-business-finance-sjlbf/sjlbf-archive/"}
        elif page == 2:
            with gzip.open(page2_probe, "rt", encoding="utf-8") as stream:
                saved = json.load(stream)
            envelope = dict(saved, provider="Stanford public archive", page=2,
                            template=saved["data"]["template"], pager=saved["data"]["settings"]["pager"])
        else:
            request = {"action": "facetwp_refresh", "data": {"facets": {"sjlbf_search": "", "sjlbf_volume": []},
                "frozen_facets": {}, "http_params": http, "template": template, "extras": {},
                "soft_refresh": 0, "is_bfcache": 0, "first_load": 0, "paged": page}}
            response = requests.post(config["ajaxurl"], json=request,
                headers={"X-WP-Nonce": config["nonce"], "User-Agent": "ResearchTools-PublicBibliographyAudit/1.0"}, timeout=30)
            if response.status_code != 200:
                raise RuntimeError(f"Public pagination HTTP {response.status_code}; do not bypass")
            data = response.json()
            envelope = {"provider": "Stanford public archive", "page": page,
                "url": config["ajaxurl"], "request": request, "data": data,
                "template": data["template"], "pager": data["settings"]["pager"]}
            time.sleep(1)
        if int(envelope["pager"]["total_rows"]) != expected or int(envelope["pager"]["page"]) != page:
            raise ValueError("Public archive count/page changed during pagination")
        raw = output_dir / ("page_%02d.json.gz" % page)
        with raw.open("xb") as target:
            with gzip.GzipFile(fileobj=target, mode="wb") as stream:
                stream.write(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
        found = parse_cards(envelope["template"])
        for record in found:
            if record["publisher_article_url"] in records:
                raise ValueError("An archive record repeated across pages")
            record.update(source_page=page, source_page_sha256=checksum(raw))
            records[record["publisher_article_url"]] = record
        hashes.append({"page": page, "path": str(raw), "sha256": checksum(raw), "row_count": len(found)})
    if len(records) != expected:
        raise ValueError("Observed archive records do not reconcile to its advertised total")
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "expected": expected, "observed": len(records),
              "page_count": pages, "raw_pages": hashes, "source_html_sha256": checksum(source_html),
              "page2_probe_sha256": checksum(page2_probe), "script_sha256": checksum(__file__),
              "reading_scope": "public_archive_metadata_HTML_only", "full_text_reviewed": False,
              "article_database_writes": 0, "issue_years_verified": 0}
    for name, data in (("candidates.json", list(records.values())), ("report.json", report)):
        with (output_dir / name).open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
    return {key: report[key] for key in ("expected", "observed", "page_count", "article_database_writes", "issue_years_verified")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-html", type=Path, required=True)
    parser.add_argument("--page2-probe", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.source_html.resolve(), args.page2_probe.resolve(), args.output_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
