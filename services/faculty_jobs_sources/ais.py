# -*- coding: utf-8 -*-
"""Association for Information Systems Academic Careers adapter."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import AdapterResponse, SourceAdapter, SourceJob, dedupe_source_jobs, detail_excerpt, now_utc, visible_text


class AISAdapter(SourceAdapter):
    name = "ais"
    adapter_name = "ais"
    region = "United States"
    base_url = "https://academiccareers.aisnet.org/jobs/"
    priority = 10
    max_items = 40

    def fetch(self):
        jobs = []
        pages = 0
        for page in range(self.max_pages):
            url = self.base_url if page == 0 else self.base_url + f"?page={page + 1}"
            response = self.request(url)
            pages += 1
            soup = BeautifulSoup(response.text, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = urljoin(url, anchor.get("href", ""))
                match = re.search(r"/job/[^/]+/(\d+)/?$", href)
                title = visible_text(anchor)
                if not match or len(title) < 4 or title.casefold() in {"view details", "save"}:
                    continue
                tile = anchor.find_parent(class_=re.compile(r"\bjob-tile\b")) or anchor.parent
                jobs.append(SourceJob(
                    source=self.name,
                    source_job_id=match.group(1),
                    source_url=href,
                    title_raw=title,
                    institution_raw=visible_text(tile.select_one(".job-company-row")) or "Unknown institution",
                    location_raw=visible_text(tile.select_one(".job-location")),
                    description_excerpt=detail_excerpt(tile),
                    posted_date_raw=visible_text(tile.select_one(".job-posted-date")),
                    captured_at=now_utc(),
                ))
                if len(jobs) >= self.max_items:
                    break
            if len(jobs) >= self.max_items:
                break
        return AdapterResponse(dedupe_source_jobs(jobs), pages_fetched=pages)


def parse_fixture(html, base_url="https://academiccareers.aisnet.org/jobs/"):
    """Small deterministic parser hook used by unit tests."""
    from unittest.mock import patch
    adapter = AISAdapter(max_pages=1, max_items=100)
    with patch.object(adapter, "request") as request:
        request.return_value.text = html
        return adapter.fetch().jobs
