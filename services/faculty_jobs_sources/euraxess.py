# -*- coding: utf-8 -*-
"""EURAXESS public jobs search adapter.

The first page is intentionally broad.  It is a Europe research-career source,
not a business-only catalogue; downstream taxonomy keeps unrelated disciplines
visible as Other rather than pretending the source is business-complete.
"""

import re
from dataclasses import replace
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from services.faculty_jobs_normalizer import country_code_for

from .base import AdapterResponse, SourceAdapter, SourceJob, dedupe_source_jobs, detail_excerpt, now_utc, visible_text


class EuraxessAdapter(SourceAdapter):
    name = "euraxess"
    adapter_name = "euraxess"
    region = "Europe"
    base_url = "https://euraxess.ec.europa.eu/jobs/search"
    priority = 16
    max_items = 30
    support_reason = "Broad European research source; business coverage is not complete."

    @staticmethod
    def _work_location(value):
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        text = re.sub(r"^work\s+locations?\s*:\s*", "", text, flags=re.I)
        text = re.sub(r"^number\s+of\s+offers?\s*:\s*\d+\s*,?\s*", "", text, flags=re.I)
        parts = [item.strip() for item in text.split(",") if item.strip()]
        country_index = next((index for index, item in enumerate(parts) if country_code_for(item)), None)
        if country_index is None:
            return text, None
        country = parts[country_index]
        before = parts[:country_index]
        rest = parts[country_index + 1:]
        host = None
        city = before[-1] if before else None
        if len(rest) >= 2:
            host, city = rest[0], rest[-1]
        elif len(rest) == 1:
            if re.search(r"university|universite|college|institute|school|centre|center", rest[0], re.I):
                host = rest[0]
            else:
                city = rest[0]
        # EURAXESS sometimes exposes a street address rather than a city. Do
        # not surface ``Mekelweg 5``/``Princetonlaan 8a`` as a city.
        if city and re.search(r"\d", city) and re.search(r"(?:\b(?:street|road|avenue|allee|boulevard)\b|\b\w*(?:laan|weg|straat)\b)", city, re.I):
            city = None
        location = ", ".join(item for item in (city, country) if item)
        return location or country, host

    def fetch(self):
        response = self.request(self.base_url)
        soup = BeautifulSoup(response.text, "html.parser")
        jobs = []
        for card in soup.select("article.ecl-content-item"):
            anchor = next((a for a in card.find_all("a", href=True)
                           if re.search(r"/jobs/\d+/?$", a.get("href", ""))), None)
            if not anchor:
                continue
            match = re.search(r"/jobs/(\d+)/?$", anchor.get("href", ""))
            title = visible_text(anchor)
            if not match or not title:
                continue
            location_text = visible_text(card.select_one(".id-Work-Locations"))
            location, host_institution = self._work_location(location_text)
            research = visible_text(card.select_one(".id-Research-Field"))
            deadline = visible_text(card.select_one(".id-Application-Deadline"))
            meta = card.select(".ecl-content-block__primary-meta-item")
            job = SourceJob(
                source=self.name,
                source_job_id=match.group(1),
                source_url=urljoin(self.base_url, anchor["href"]),
                title_raw=title,
                institution_raw=host_institution or (visible_text(meta[0]) if meta else "Unknown institution"),
                location_raw=location,
                department_raw=research,
                description_excerpt=detail_excerpt(card),
                deadline_raw=deadline,
                posted_date_raw=visible_text(meta[1]) if len(meta) > 1 else None,
                captured_at=now_utc(),
            )
            try:
                detail = self.request(job.source_url)
                detail_soup = BeautifulSoup(detail.text, "html.parser")
                official = None
                for apply_link in detail_soup.find_all("a", href=True):
                    label = visible_text(apply_link).casefold()
                    candidate = urljoin(job.source_url, apply_link["href"])
                    if "apply" in label and candidate.startswith(("http://", "https://")) and "euraxess.ec.europa.eu" not in candidate:
                        official = candidate
                        break
                if official:
                    job = replace(job, official_url=official)
            except Exception:
                # Detail enrichment is optional; listing ingestion remains live
                # if an individual record cannot be opened.
                pass
            jobs.append(job)
            if len(jobs) >= self.max_items:
                break
        return AdapterResponse(dedupe_source_jobs(jobs), pages_fetched=1,
                                notes=["EURAXESS search is a broad European research source; business coverage is not complete."])


def parse_fixture(html):
    adapter = EuraxessAdapter(max_pages=1)
    from unittest.mock import patch
    with patch.object(adapter, "request") as request:
        request.return_value.text = html
        return adapter.fetch().jobs
