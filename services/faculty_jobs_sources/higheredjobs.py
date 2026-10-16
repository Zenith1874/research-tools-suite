# -*- coding: utf-8 -*-
"""Opt-in HigherEdJobs Business faculty listing adapter.

HigherEdJobs is an unstable-but-sometimes-public source. Its robots.txt allows
the faculty search path, and on 2026-08-28 the exact Business category returned
server-rendered listing HTML with a reported 2,824 records. The same edge can
later return an Imperva ``Pardon Our Interruption`` page for an otherwise valid
numbered page. This adapter therefore has an all-or-nothing contract:

* it uses only ordinary public GET requests and normal HTTP session cookies;
* it never executes a challenge, solves a CAPTCHA, or replays a challenge token;
* it requires enough page budget for the board's reported total;
* it raises before ingestion when any page is challenged or cannot be parsed;
* it returns ``coverage_complete=True`` only when distinct listing cards equal
  the source-reported total.

Only listing-card metadata is collected. Opening every detail page would add
roughly one request per posting and is deliberately outside this bounded source
operation; the source detail URL remains available for manual verification.
"""

from math import ceil
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from .base import (
    AdapterError, AdapterResponse, NonRetryableAdapterError, SourceAdapter,
    SourceJob, dedupe_source_jobs, now_utc, visible_text,
)


_RESULT_RANGE = re.compile(
    r"\bResults\s+(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)\s+of\s+(\d[\d,]*)\b",
    re.I,
)
_POSTED = re.compile(
    r"\bPosted\s+(?:today|yesterday|\d+\s+(?:hours?|days?|weeks?|months?)\s+ago|"
    r"[A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})\b",
    re.I,
)


class HigherEdJobsAdapter(SourceAdapter):
    name = "higheredjobs"
    adapter_name = "higheredjobs"
    region = "United States"
    base_url = (
        "https://www.higheredjobs.com/faculty/search.cfm?"
        "JobCat=232&CatName=Business"
    )
    priority = 25
    paginates = True
    max_items = 5000
    page_delay = 2.0

    # A complete run currently needs roughly 113 listing requests. Keep it
    # outside the three-page daily refresh and require an explicit source name.
    enabled = False
    support_status = "opt_in"
    support_reason = (
        "The public Business faculty category is robots-allowed and can return "
        "server-rendered listings, but the edge intermittently substitutes an "
        "Imperva challenge. Run explicitly with a complete page budget or import a "
        "fully validated ordinary visible-browser pagination snapshot; challenged or "
        "partial runs fail without writing a partial source snapshot. No challenge "
        "execution, CAPTCHA solving, or cookie-token bypass is used."
    )

    @classmethod
    def _page_url(cls, page):
        return cls.base_url if int(page) <= 1 else f"{cls.base_url}&Page={int(page)}"

    @staticmethod
    def _challenge_reason(html):
        text = str(html or "")
        lower = text.casefold()
        signals = (
            "pardon our interruption" in lower,
            "reeseskipexpirationcheck" in lower,
            "initializeprotection" in lower,
            "_incapsula_resource" in lower,
        )
        if any(signals) and "row record" not in lower:
            return "Imperva/Incapsula challenge substituted for the public listing"
        return None

    @staticmethod
    def _result_range(soup):
        match = _RESULT_RANGE.search(soup.get_text(" ", strip=True))
        if not match:
            return None
        return tuple(int(value.replace(",", "")) for value in match.groups())

    @staticmethod
    def _card_job(card, page_url):
        anchor = card.select_one('a[href*="details.cfm?JobCode="]')
        title = visible_text(anchor)
        if not anchor or not title:
            return None
        detail_url = urljoin(page_url, anchor.get("href", ""))
        source_ids = parse_qs(urlsplit(detail_url).query).get("JobCode") or []
        source_job_id = str(source_ids[0]).strip() if source_ids else ""
        if not source_job_id:
            return None

        left = card.select_one(".col-sm-7")
        salary = visible_text(left.select_one(".job-salary")) if left else ""
        values = []
        if left:
            for value in left.stripped_strings:
                cleaned = re.sub(r"\s+", " ", str(value)).strip()
                if cleaned and cleaned not in values:
                    values.append(cleaned)
        remaining = [
            value for value in values
            if value.casefold() != title.casefold()
            and (not salary or value.casefold() != salary.casefold())
            and value.casefold() != "save job"
        ]
        institution = remaining[0] if remaining else "Unknown institution"
        # HigherEdJobs may insert a department/campus line between the employer
        # and location. The final non-salary line is the location; treating the
        # second line as location produced cities such as "College of Business".
        location = remaining[-1] if len(remaining) > 1 else None
        middle_lines = remaining[1:-1] if len(remaining) > 2 else []

        right = card.select_one(".col-sm-5")
        category = visible_text(right.select_one(".text-nowrap")) if right else ""
        right_text = visible_text(right)
        posted_match = _POSTED.search(right_text)
        posted = posted_match.group(0) if posted_match else None
        card_text = visible_text(card)
        excerpt = " ".join(filter(None, (
            f"HigherEdJobs category: {category}." if category else None,
            card_text,
        )))[:2000]
        priority = bool(card.select_one(".addon-marker"))
        return SourceJob(
            source=HigherEdJobsAdapter.name,
            source_job_id=source_job_id,
            source_url=detail_url,
            title_raw=title,
            institution_raw=institution,
            location_raw=location,
            description_excerpt=excerpt or None,
            posted_date_raw=posted,
            salary_raw=salary or None,
            captured_at=now_utc(),
            extra={
                "source_category": category or None,
                "source_priority_listing": priority,
                "source_middle_lines": middle_lines,
            },
        )

    def fetch(self):
        jobs = []
        pages_fetched = 0
        reported_total = None
        required_pages = None
        listing_page_size = None

        for page in range(1, self.max_pages + 1):
            page_url = self._page_url(page)
            response = self.request(page_url)
            pages_fetched += 1
            challenge = self._challenge_reason(response.text)
            if challenge:
                raise NonRetryableAdapterError(
                    f"HigherEdJobs page {page}: {challenge}; no partial snapshot returned"
                )

            soup = BeautifulSoup(response.text, "html.parser")
            result_range = self._result_range(soup)
            cards = soup.select("div.row.record")
            if not result_range or not cards:
                raise AdapterError(
                    f"HigherEdJobs page {page} did not expose a result range and parseable cards"
                )
            start, end, observed_total = result_range
            observed_page_size = max(1, end - start + 1)
            if listing_page_size is None:
                listing_page_size = observed_page_size
            if reported_total is None:
                reported_total = observed_total
            else:
                # New postings can arrive during a long crawl. Use the largest
                # reported total so a moving board cannot make a partial result
                # look complete merely because its first page was smaller.
                reported_total = max(reported_total, observed_total)
            required_pages = ceil(reported_total / listing_page_size)
            if reported_total > self.max_items:
                raise AdapterError(
                    f"HigherEdJobs reports {reported_total} records, above the adapter "
                    f"max_items={self.max_items}; no partial snapshot returned"
                )
            if required_pages > self.max_pages:
                raise AdapterError(
                    f"HigherEdJobs reports {reported_total} records and requires at least "
                    f"{required_pages} pages at {listing_page_size} per page; rerun with "
                    f"--max-pages {required_pages} or higher. No partial snapshot returned"
                )

            for card_node in cards:
                job = self._card_job(card_node, page_url)
                if job:
                    jobs.append(job)
            if page >= required_pages:
                break
            if self.page_delay:
                time.sleep(max(0.0, float(self.page_delay)))

        unique_jobs = dedupe_source_jobs(jobs)
        if reported_total is None or required_pages is None:
            raise AdapterError("HigherEdJobs did not report a source total")
        if pages_fetched < required_pages or len(unique_jobs) != reported_total:
            raise AdapterError(
                f"HigherEdJobs reported {reported_total} records but {len(unique_jobs)} "
                f"distinct listing cards were parsed across {pages_fetched}/{required_pages} "
                "pages; no partial snapshot returned"
            )
        return AdapterResponse(
            unique_jobs,
            pages_fetched=pages_fetched,
            listing_pages=pages_fetched,
            reported_total=reported_total,
            coverage_complete=True,
            notes=[
                "Complete HigherEdJobs Business listing-card snapshot; detail pages were not "
                "fetched and source category membership is not treated as proof of default-market scope."
            ],
        )


def parse_fixture(html):
    """Parse a one-page complete fixture without any network request."""
    adapter = HigherEdJobsAdapter(max_pages=1)
    adapter.page_delay = 0
    from unittest.mock import patch
    with patch.object(adapter, "request") as request:
        request.return_value.text = html
        return adapter.fetch().jobs


def browser_snapshot_response(payload):
    """Validate one complete visible-browser snapshot and return source jobs.

    The browser collector exists because an ordinary requests client can receive
    an intermittent Imperva interstitial while a normal visible browser receives
    the public listing.  Import remains all-or-nothing: page ranges, card counts,
    total cardinality, unique stable JobCodes, and official source URLs must all
    agree before a ``SourceJob`` is constructed.
    """
    if not isinstance(payload, dict):
        raise AdapterError("HigherEdJobs browser snapshot must be a JSON object")
    if payload.get("source") != HigherEdJobsAdapter.name:
        raise AdapterError("HigherEdJobs browser snapshot has the wrong source identity")
    if payload.get("source_url") != HigherEdJobsAdapter.base_url:
        raise AdapterError("HigherEdJobs browser snapshot has the wrong category URL")
    if payload.get("capture_method") != "ordinary_visible_browser_pagination":
        raise AdapterError("HigherEdJobs browser snapshot has an unsupported capture method")
    if payload.get("coverage_complete") is not True:
        raise AdapterError("HigherEdJobs browser snapshot is not marked coverage-complete")

    try:
        reported_total = int(payload.get("reported_total"))
        page_size = int(payload.get("page_size"))
        pages_fetched = int(payload.get("pages_fetched"))
    except (TypeError, ValueError) as exc:
        raise AdapterError("HigherEdJobs browser snapshot has invalid count metadata") from exc
    if reported_total < 1 or reported_total > HigherEdJobsAdapter.max_items:
        raise AdapterError(
            f"HigherEdJobs browser snapshot total {reported_total} is outside 1-"
            f"{HigherEdJobsAdapter.max_items}"
        )
    if page_size < 1 or page_size > 100:
        raise AdapterError("HigherEdJobs browser snapshot page_size must be between 1 and 100")
    required_pages = ceil(reported_total / page_size)
    pages = payload.get("pages")
    jobs = payload.get("jobs")
    if not isinstance(pages, list) or len(pages) != required_pages or pages_fetched != required_pages:
        raise AdapterError(
            f"HigherEdJobs browser snapshot requires {required_pages} consecutive pages; "
            f"metadata recorded {pages_fetched}"
        )
    if not isinstance(jobs, list) or len(jobs) != reported_total:
        raise AdapterError(
            f"HigherEdJobs browser snapshot reported {reported_total} but contains "
            f"{len(jobs) if isinstance(jobs, list) else 0} cards"
        )

    for index, page in enumerate(pages, 1):
        if not isinstance(page, dict):
            raise AdapterError(f"HigherEdJobs browser snapshot page {index} is invalid")
        expected_start = ((index - 1) * page_size) + 1
        expected_end = min(index * page_size, reported_total)
        expected_cards = expected_end - expected_start + 1
        try:
            observed = (
                int(page.get("page")), int(page.get("start")), int(page.get("end")),
                int(page.get("cards")),
            )
        except (TypeError, ValueError) as exc:
            raise AdapterError(
                f"HigherEdJobs browser snapshot page {index} has invalid range metadata"
            ) from exc
        if observed != (index, expected_start, expected_end, expected_cards):
            raise AdapterError(
                f"HigherEdJobs browser snapshot page {index} range/card metadata is not consecutive"
            )

    source_jobs = []
    source_ids = set()
    snapshot_captured_at = str(payload.get("captured_at") or "").strip() or None
    for index, item in enumerate(jobs, 1):
        if not isinstance(item, dict):
            raise AdapterError(f"HigherEdJobs browser snapshot card {index} is invalid")
        source_job_id = str(item.get("source_job_id") or "").strip()
        source_url = str(item.get("source_url") or "").strip()
        title = str(item.get("title_raw") or "").strip()
        institution = str(item.get("institution_raw") or "").strip()
        parts = urlsplit(source_url)
        url_job_ids = parse_qs(parts.query).get("JobCode") or []
        if (not source_job_id or source_job_id in source_ids or not title or not institution
                or parts.scheme != "https" or parts.hostname != "www.higheredjobs.com"
                or parts.path.casefold() != "/faculty/details.cfm"
                or not url_job_ids or str(url_job_ids[0]).strip() != source_job_id):
            raise AdapterError(
                f"HigherEdJobs browser snapshot card {index} has invalid identity or required fields"
            )
        source_ids.add(source_job_id)
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        middle_lines = extra.get("source_middle_lines")
        if not isinstance(middle_lines, list):
            middle_lines = []
        source_jobs.append(SourceJob(
            source=HigherEdJobsAdapter.name,
            source_job_id=source_job_id,
            source_url=source_url,
            official_url=None,
            title_raw=title,
            institution_raw=institution,
            location_raw=str(item.get("location_raw") or "").strip() or None,
            description_excerpt=str(item.get("description_excerpt") or "").strip()[:2000] or None,
            posted_date_raw=str(item.get("posted_date_raw") or "").strip() or None,
            salary_raw=str(item.get("salary_raw") or "").strip() or None,
            captured_at=str(item.get("captured_at") or "").strip() or snapshot_captured_at,
            extra={
                "source_category": extra.get("source_category"),
                "source_priority_listing": bool(extra.get("source_priority_listing")),
                "source_middle_lines": [str(value).strip() for value in middle_lines if str(value).strip()][:10],
                "capture_method": "ordinary_visible_browser_pagination",
            },
        ))
    if len(source_ids) != reported_total:
        raise AdapterError(
            f"HigherEdJobs browser snapshot has {len(source_ids)} unique JobCodes; "
            f"expected {reported_total}"
        )
    return AdapterResponse(
        source_jobs,
        pages_fetched=pages_fetched,
        listing_pages=pages_fetched,
        reported_total=reported_total,
        coverage_complete=True,
        notes=[
            "Complete HigherEdJobs Business listing-card snapshot captured through ordinary "
            "visible-browser pagination; detail pages were not fetched and category membership "
            "is not treated as proof of default-market scope."
        ],
    )


class HigherEdJobsBrowserSnapshotAdapter(HigherEdJobsAdapter):
    """Offline adapter for a previously validated complete browser snapshot."""

    def __init__(self, payload):
        super().__init__(max_pages=max(1, int(payload.get("pages_fetched") or 1)))
        self._response = browser_snapshot_response(payload)

    def fetch(self):
        return self._response


def load_browser_snapshot(path):
    """Read and validate a complete HigherEdJobs browser snapshot from disk."""
    snapshot_path = Path(path)
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"Could not read HigherEdJobs browser snapshot: {exc}") from exc
    # Validate before returning so callers cannot accidentally treat a partial
    # file as a ready-to-import capture.
    browser_snapshot_response(payload)
    return payload
