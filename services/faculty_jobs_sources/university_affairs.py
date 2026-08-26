# -*- coding: utf-8 -*-
"""University Affairs Canada public job board adapter."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import AdapterResponse, SourceAdapter, SourceJob, dedupe_source_jobs, detail_excerpt, now_utc, visible_text


class UniversityAffairsAdapter(SourceAdapter):
    name = "university_affairs"
    adapter_name = "university_affairs"
    region = "Canada"
    base_url = "https://universityaffairs.ca/search-job/"
    priority = 12
    max_items = 60

    @staticmethod
    def _date_fields(value):
        text = visible_text(value)
        if re.search(r"\b(?:posting\s+date|date\s+placed|posted(?:\s+on)?)\b", text, re.I):
            posted = text
        else:
            posted = None
        if re.search(r"\b(?:deadline|closing(?:\s+date)?|closes|apply\s+by|expires?)\b", text, re.I):
            deadline = text
        else:
            deadline = None
        return posted, deadline

    def fetch(self):
        response = self.request(self.base_url)
        soup = BeautifulSoup(response.text, "html.parser")
        jobs = []
        for card in soup.select(".job__block"):
            anchor = card.select_one('a[href*="search-jobs/?job_id="]')
            if not anchor:
                continue
            match = re.search(r"job_id=(\d+)", anchor.get("href", ""))
            title = visible_text(card.select_one(".job__title")) or visible_text(anchor)
            if not match or not title:
                continue
            posted_raw, deadline_raw = self._date_fields(card.select_one(".job__block-date"))
            jobs.append(SourceJob(
                source=self.name,
                source_job_id=match.group(1),
                source_url=urljoin(self.base_url, anchor["href"]),
                title_raw=title,
                institution_raw=visible_text(card.select_one(".job__block-institution")) or "Unknown institution",
                location_raw=visible_text(card.select_one(".job__block-location")),
                description_excerpt=detail_excerpt(card),
                posted_date_raw=posted_raw,
                deadline_raw=deadline_raw,
                captured_at=now_utc(),
            ))
            if len(jobs) >= self.max_items:
                break
        return AdapterResponse(dedupe_source_jobs(jobs), pages_fetched=1)


def parse_fixture(html):
    adapter = UniversityAffairsAdapter(max_pages=1)
    from unittest.mock import patch
    with patch.object(adapter, "request") as request:
        request.return_value.text = html
        return adapter.fetch().jobs
