# -*- coding: utf-8 -*-
"""Association for Information Systems Academic Careers adapter."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import AdapterResponse, SourceAdapter, SourceJob, dedupe_source_jobs, detail_excerpt, now_utc, visible_text


_RESULT_COUNT_RE = re.compile(r"\b\d[\d,]*\s*-\s*\d[\d,]*\s+results?\s+of\s+(\d[\d,]*)", re.I)


def _reported_total(soup):
    """The result count the board prints: "1 - 25 Results of 53" -> 53."""
    match = _RESULT_COUNT_RE.search(soup.get_text(" ", strip=True))
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


class AISAdapter(SourceAdapter):
    name = "ais"
    adapter_name = "ais"
    region = "United States"
    base_url = "https://academiccareers.aisnet.org/jobs/"
    priority = 10
    # Verified 2026-08-27: ?page= returns page one again and the real
    # paging endpoint answers this fetcher with HTTP 403.
    paginates = False
    max_items = 40

    def fetch(self):
        jobs = []
        pages = 0
        reported_total = None
        notes = []
        for page in range(self.max_pages):
            url = self.base_url if page == 0 else self.base_url + f"?page={page + 1}"
            response = self.request(url)
            pages += 1
            soup = BeautifulSoup(response.text, "html.parser")
            if reported_total is None:
                reported_total = _reported_total(soup)
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
            # This board's "next page" control is not a link. Verified
            # 2026-08-27:
            #   * /jobs/?page=1|2|3 all return the same 25 ids, so the plain
            #     query parameter does not paginate;
            #   * /jobseeker/search/results/?page=N behaves the same way;
            #   * the control calls searchJobs(n) -> a GET to
            #     /c/@search_results/controller/includes/search_jobs.cfm, and
            #     that path answers this fetcher with HTTP 403.
            # A browser session is accepted there; ours is refused. Working
            # around a 403 would be the anti-bot bypass this project does not
            # do, so stop after the first page and report the shortfall.
            break
        unique = dedupe_source_jobs(jobs)
        complete = None
        if reported_total is not None:
            complete = len(unique) >= reported_total
            if not complete:
                notes.append(
                    f"Observed {len(unique)} of {reported_total} results the board reports. "
                    "The ?page= parameter does not paginate this board, and its real paging "
                    "endpoint answers this fetcher with HTTP 403, so only the first page is "
                    "reachable without bypassing that refusal."
                )
        return AdapterResponse(unique, pages_fetched=pages, notes=notes,
                               reported_total=reported_total, coverage_complete=complete)


def parse_fixture(html, base_url="https://academiccareers.aisnet.org/jobs/"):
    """Small deterministic parser hook used by unit tests."""
    from unittest.mock import patch
    adapter = AISAdapter(max_pages=1, max_items=100)
    with patch.object(adapter, "request") as request:
        request.return_value.text = html
        return adapter.fetch().jobs
