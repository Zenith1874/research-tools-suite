# -*- coding: utf-8 -*-
"""jobs.ac.uk public HTML adapter, restricted to academic-looking roles."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import AdapterResponse, SourceAdapter, SourceJob, dedupe_source_jobs, detail_excerpt, now_utc, visible_text


ACADEMIC_TERMS = re.compile(
    r"professor|lecturer|reader|academic|research fellow|postdoc|teaching fellow|"
    r"professorship|faculty|business school|research associate",
    re.I,
)


def _label_value(text, label, stop_labels=()):
    pattern = rf"(?:{label})\s*:?\s*(.*?)(?=\s+(?:{'|'.join(stop_labels)})\s*:|$)"
    match = re.search(pattern, text, re.I)
    return match.group(1).strip(" -|") if match else None


def _posted_raw(text):
    return _label_value(text, r"Date\s+Placed|Posted", ("Closes", "Closing", "Salary", "Location"))


def _deadline_raw(text):
    match = re.search(r"\b(?:Closes|Closing(?:\s+date)?|Apply\s+by|Expires?)\s*:?[\s-]*(.+?)(?=\s+(?:Save|Salary|Date\s+Placed|Location)\b|$)", text, re.I)
    return match.group(0).strip() if match else None


def _salary_raw(text):
    return _label_value(text, r"Salary", (r"Date\s+Placed", "Closes", "Location", "Save"))


class JobsAcUkAdapter(SourceAdapter):
    name = "jobs_ac_uk"
    adapter_name = "jobs_ac_uk"
    region = "Europe"
    base_url = "https://www.jobs.ac.uk/search/?keywords=lecturer%20business"
    priority = 14
    # This board exposes a working page parameter, so a second page is
    # genuinely reachable.
    paginates = True
    max_items = 40

    def fetch(self):
        jobs = []
        pages = 0
        for page in range(self.max_pages):
            url = self.base_url if page == 0 else self.base_url + f"&startIndex={page * 25 + 1}"
            response = self.request(url)
            pages += 1
            soup = BeautifulSoup(response.text, "html.parser")
            for card in soup.select(".j-search-result__result"):
                anchor = card.select_one('a[href*="/job/"]')
                if not anchor:
                    continue
                title = visible_text(anchor)
                if not title or not ACADEMIC_TERMS.search(title):
                    continue
                href = urljoin(url, anchor.get("href", ""))
                source_id = card.get("data-advert-id") or href.rstrip("/").split("/")[-1]
                school_raw = "UCD Business" if re.search(r"\bUCD Business\b", title, re.I) else None
                card_text = visible_text(card)
                location = visible_text(card.select_one(".j-search-result__location"))
                if not location:
                    location = _label_value(card_text, r"Location", ("Salary", r"Date\s+Placed", "Closes", "Save"))
                deadline_raw = _deadline_raw(card_text) or visible_text(card.select_one(".j-search-result__date"))
                posted_raw = _posted_raw(card_text)
                salary_raw = _salary_raw(card_text) or visible_text(card.select_one(".j-search-result__info"))
                # jobs.ac.uk is a global board.  Do not turn an unqualified
                # London/Leeds/etc. card into GB merely because the board is
                # UK-based; explicit country text is handled by the normalizer.
                jobs.append(SourceJob(
                    source=self.name,
                    source_job_id=str(source_id),
                    source_url=href,
                    title_raw=title,
                    institution_raw=visible_text(card.select_one(".j-search-result__employer")) or "Unknown institution",
                    school_raw=school_raw,
                    location_raw=location,
                    description_excerpt=detail_excerpt(card),
                    deadline_raw=deadline_raw,
                    salary_raw=salary_raw,
                    posted_date_raw=posted_raw,
                    captured_at=now_utc(),
                ))
                if len(jobs) >= self.max_items:
                    break
            if len(jobs) >= self.max_items:
                break
        return AdapterResponse(dedupe_source_jobs(jobs), pages_fetched=pages)


def parse_fixture(html):
    adapter = JobsAcUkAdapter(max_pages=1)
    from unittest.mock import patch
    with patch.object(adapter, "request") as request:
        request.return_value.text = html
        return adapter.fetch().jobs
