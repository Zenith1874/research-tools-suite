# -*- coding: utf-8 -*-
"""Discipline-association and academic-portal job boards.

These boards are small next to an aggregator -- three to fifty postings each --
but they carry a different population: association members advertise
tenure-track and research appointments, where a general aggregator's volume is
mostly contingent teaching work. Coverage here is about the composition of the
market view, not its size.

Every board below was verified against the live site on 2026-08-29: robots.txt
permits the listing path, the page is served to this fetcher without a
challenge, and individual postings are extractable from the returned HTML.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import (AdapterResponse, SourceAdapter, SourceJob, dedupe_source_jobs,
                   now_utc, reported_result_total, visible_text)
from .source_jobboards import _PagedBoardAdapter, parse_madgex_listing


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


class TimesHigherEducationUnijobsAdapter(_PagedBoardAdapter):
    """Times Higher Education Unijobs.

    Another Madgex tenant, so the shared listing parser reads it; the only
    difference is that its postings live under ``/unijobs/listing/`` rather
    than ``/job/``. The board is all-discipline, so the downstream business
    scope gate does the narrowing rather than the adapter.
    """

    name = "the_unijobs"
    adapter_name = "the_unijobs"
    region = "Global"
    # The board publishes its own Business and Economics category, so the
    # source is narrowed at the source rather than by reading the
    # all-discipline front page and calling its first pages business coverage.
    # Verified 2026-08-29: the category page returned 21 cards, all business
    # postings, against a front page whose 20 cards produced none.
    base_url = "https://www.timeshighereducation.com/unijobs/listings/business-and-economics/"
    priority = 22
    max_items = 100
    support_reason = ("Read from the board's own Business and Economics category. That "
                      "classification is the board's, not ours, and the downstream scope gate "
                      "still decides what enters the market.")

    @staticmethod
    def parse_html(html, page_url=None, max_items=100):
        return parse_madgex_listing(
            html, TimesHigherEducationUnijobsAdapter.name,
            TimesHigherEducationUnijobsAdapter.base_url, page_url, max_items,
            job_path=r"/unijobs/listing/",
        )

    def fetch(self):
        response = self._fetch_pages(
            lambda soup, url: self.parse_html(soup.decode(), url, self.max_items))
        notes = list(response.notes or [])
        notes.append(self.support_reason)
        return AdapterResponse(response.jobs, pages_fetched=response.pages_fetched,
                               listing_pages=response.listing_pages, notes=notes,
                               reported_total=response.reported_total,
                               coverage_complete=response.coverage_complete)


class EAAAccountingAdapter(SourceAdapter):
    """European Accounting Association / Accounting Researchers Community."""

    name = "eaa_accounting"
    adapter_name = "eaa_accounting"
    region = "Europe"
    base_url = "https://eaa-online.org/arc/jobs/"
    priority = 19
    max_items = 100
    paginates = False

    @staticmethod
    def parse_html(html, page_url=None, max_items=100):
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()
        for link in soup.find_all("a", href=True):
            href = urljoin(page_url or EAAAccountingAdapter.base_url, str(link.get("href") or ""))
            match = re.search(r"/arc/jobs/([a-z0-9][a-z0-9-]{3,})/?$", href, re.I)
            title = _clean(visible_text(link))
            if not match or len(title) < 6 or match.group(1).casefold() in seen:
                continue
            seen.add(match.group(1).casefold())
            card = link.find_parent("div") or link.parent
            values = [value for value in card.stripped_strings if _clean(value)]
            body = [value for value in values if _clean(value) != title]
            jobs.append(SourceJob(
                source=EAAAccountingAdapter.name,
                source_job_id=match.group(1)[:120],
                source_url=href,
                title_raw=title,
                # The card leads with the posting title and its host is named
                # inside it; nothing here asserts a school entity, so the
                # institution stays unknown rather than being guessed from the
                # surrounding prose.
                institution_raw="Unknown institution",
                description_excerpt=" ".join(body)[:1200] or None,
                captured_at=now_utc(),
                extra={"school_evidence_context": "source_listing"},
            ))
            if len(jobs) >= max_items:
                break
        return dedupe_source_jobs(jobs)

    def fetch(self):
        response = self.request(self.base_url)
        jobs = self.parse_html(response.text, response.url, self.max_items)
        reported = reported_result_total(BeautifulSoup(response.text, "html.parser"))
        complete = None if reported is None else len(jobs) >= reported
        return AdapterResponse(jobs, pages_fetched=1, listing_pages=1,
                               reported_total=reported, coverage_complete=complete)


class ANZAMAdapter(SourceAdapter):
    """Australian and New Zealand Academy of Management."""

    name = "anzam"
    adapter_name = "anzam"
    region = "Australia / New Zealand"
    base_url = "https://www.anzam.org/jobs/"
    priority = 19
    max_items = 100
    paginates = False

    _DEADLINE = re.compile(r"Deadline:\s*(.+?)(?:$|\s{2,})", re.I)
    # The board prefixes some headlines with its own furniture. "Job Posting –
    # Head of School, Management and Marketing" is a title with a label glued
    # to it, and the label is not part of what the job is called.
    _CHROME = re.compile(r"^\s*job\s+posting\s*[-–—:]\s*", re.I)

    @staticmethod
    def parse_html(html, page_url=None, max_items=100):
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()
        for card in soup.select("div.single_block"):
            link = card.find("a", href=re.compile(r"/jobs/[a-z0-9-]{6,}", re.I))
            if not link:
                continue
            href = urljoin(page_url or ANZAMAdapter.base_url, str(link.get("href") or ""))
            slug = re.search(r"/jobs/([a-z0-9-]{6,})/?$", href, re.I)
            values = [value for value in card.stripped_strings if _clean(value)]
            title = _clean(ANZAMAdapter._CHROME.sub("", values[0])) if values else ""
            if not slug or len(title) < 6 or slug.group(1).casefold() in seen:
                continue
            seen.add(slug.group(1).casefold())
            text = " ".join(values)
            deadline = ANZAMAdapter._DEADLINE.search(text)
            # The card prints "Deadline:" and the date as separate strings, so
            # the value is the token after that label rather than a regex over
            # the joined blob.
            deadline_raw = None
            for index, value in enumerate(values):
                if value.casefold().startswith("deadline") and index + 1 < len(values):
                    deadline_raw = _clean(values[index + 1])
                    break
            if deadline_raw is None and deadline:
                deadline_raw = _clean(deadline.group(1))
            body = [value for value in values[1:] if not value.casefold().startswith("deadline")]
            jobs.append(SourceJob(
                source=ANZAMAdapter.name,
                source_job_id=slug.group(1)[:120],
                source_url=href,
                title_raw=title,
                institution_raw="Unknown institution",
                description_excerpt=" ".join(body)[:1200] or None,
                deadline_raw=deadline_raw,
                captured_at=now_utc(),
                extra={"school_evidence_context": "source_listing"},
            ))
            if len(jobs) >= max_items:
                break
        return dedupe_source_jobs(jobs)

    def fetch(self):
        response = self.request(self.base_url)
        jobs = self.parse_html(response.text, response.url, self.max_items)
        return AdapterResponse(jobs, pages_fetched=1, listing_pages=1)


class EconJobMarketAdapter(SourceAdapter):
    """EconJobMarket.org listings.

    Each advertisement carries an ``#ad-NNNNN`` anchor, which is the only
    stable identifier the listing page exposes; the visible columns hold the
    rank/location line and the department/institution line.
    """

    name = "econjobmarket"
    adapter_name = "econjobmarket"
    region = "Global"
    base_url = "https://econjobmarket.org/positions"
    priority = 19
    max_items = 200
    paginates = False
    # Every advertisement here is an anchor on the one listing page, so a
    # per-posting detail pass would request that same page once per record.
    supports_detail_enrichment = False
    support_reason = ("Economics-wide board; finance and economics business appointments "
                      "are a subset filtered downstream.")

    @staticmethod
    def parse_html(html, page_url=None, max_items=200):
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()
        for card in soup.select(".card"):
            anchor = card.find("a", href=re.compile(r"#ad-(\d+)"))
            if not anchor:
                continue
            ad_id = re.search(r"#ad-(\d+)", str(anchor.get("href") or ""))
            if not ad_id or ad_id.group(1) in seen:
                continue
            # Read the fields from the DOM rather than from the concatenated
            # card text. Titles here legitimately contain commas ("Faculty
            # Positions in Economics, AI & Data Analytics"), so no regex over
            # the joined string can reliably tell the title from the trailing
            # "City, Country" -- but the markup separates them: the anchor
            # holds the title, and the place text follows it.
            title = _clean(visible_text(anchor))
            column = anchor.find_parent("div", class_="col-md-4") or anchor.parent
            tail = _clean(column.get_text(" ", strip=True))
            if title and tail.startswith(title):
                tail = tail[len(title):]
            location = None
            place = re.split(r"\(\s*map\s*\)", tail, maxsplit=1)[0]
            place = _clean(place).strip(" .,;")
            if "," in place and len(place) <= 80:
                location = place
            columns = [_clean(node.get_text(" ", strip=True))
                       for node in card.select("div.col-md-4")]
            columns = [value for value in columns if value]
            institution = _clean(columns[1]) if len(columns) > 1 else "Unknown institution"
            if not title:
                continue
            seen.add(ad_id.group(1))
            jobs.append(SourceJob(
                source=EconJobMarketAdapter.name,
                source_job_id=ad_id.group(1),
                source_url=f"{EconJobMarketAdapter.base_url}#ad-{ad_id.group(1)}",
                title_raw=title,
                institution_raw=institution or "Unknown institution",
                location_raw=location,
                description_excerpt=_clean(card.get_text(" ", strip=True))[:1200] or None,
                captured_at=now_utc(),
                extra={"school_evidence_context": "source_listing"},
            ))
            if len(jobs) >= max_items:
                break
        return dedupe_source_jobs(jobs)

    def fetch(self):
        response = self.request(self.base_url)
        jobs = self.parse_html(response.text, response.url, self.max_items)
        return AdapterResponse(jobs, pages_fetched=1, listing_pages=1,
                               notes=[self.support_reason])


__all__ = [
    "ANZAMAdapter", "EAAAccountingAdapter", "EconJobMarketAdapter",
    "TimesHigherEducationUnijobsAdapter",
]
