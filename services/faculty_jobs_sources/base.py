# -*- coding: utf-8 -*-
"""Adapter primitives and low-frequency public HTTP fetching."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import logging
import re
import threading
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


LOG = logging.getLogger(__name__)
USER_AGENT = (
    "research-tools-suite/academic-career (+local research workstation; "
    "respectful low-frequency public-page fetch)"
)
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class AdapterError(RuntimeError):
    """An adapter failed without making the other adapters fail."""


class NonRetryableAdapterError(AdapterError):
    """A public HTTP response should not be retried by the adapter layer."""


class RobotsDisallowedError(NonRetryableAdapterError):
    """The origin's robots.txt refuses this path for this crawler.

    This is a policy outcome, not a transport failure.  It must stay
    distinguishable from an error so a refused page is never recorded as
    evidence that a school has no vacancy.
    """


class CrawlBudgetExhaustedError(RobotsDisallowedError):
    """The origin asks for a pace slower than a run can wait out.

    Also a policy outcome rather than a transport failure: the pages beyond the
    budget were not refused by the board, they were left unread by us.  Like a
    disallow, it must never be recorded as evidence that a board holds nothing.
    """


ROBOTS_TIMEOUT = 10
# How long a single request will wait on a declared Crawl-delay.  Sleeping an
# hour inside a scheduled run would hold the global update lock, so the wait
# itself is capped here.
MAX_CRAWL_DELAY = 30.0
# What the cap does NOT do is license us to ignore the declared pace.  An origin
# asking for one request an hour (sms.careerwebsite.com publishes
# "Crawl-delay: 3600" under ``User-agent: *``, commented "Force the crawl delay
# for all bots to be one hour") gets at most this many requests per update run.
# The default schedule is one run a day, so one request per run is well inside
# what that board asked for, where spacing 13 requests 30s apart was not.
SLOW_ORIGIN_REQUESTS_PER_RUN = 1
_ROBOTS_CACHE = {}
_ROBOTS_LOCK = threading.Lock()
_LAST_FETCH = {}
_SLOW_ORIGIN_USED = {}


def reset_crawl_budgets():
    """Start a new run's per-origin budget for slow-paced origins."""
    with _ROBOTS_LOCK:
        _SLOW_ORIGIN_USED.clear()


def _consume_slow_origin_budget(origin, declared):
    """Allow a bounded number of requests to an origin we cannot pace properly."""
    with _ROBOTS_LOCK:
        used = _SLOW_ORIGIN_USED.get(origin, 0)
        if used >= SLOW_ORIGIN_REQUESTS_PER_RUN:
            raise CrawlBudgetExhaustedError(
                f"{origin} asks for Crawl-delay={declared}s; this run already used its "
                f"{SLOW_ORIGIN_REQUESTS_PER_RUN}-request budget for that origin"
            )
        _SLOW_ORIGIN_USED[origin] = used + 1


def _origin(url):
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else None


def _load_robots(session, origin, timeout):
    """Fetch and parse one origin's robots.txt.

    Follows RFC 9309 reachability rules: a 4xx means no rules are published
    and crawling is allowed, while an unreachable origin (5xx or a transport
    failure) is treated as a full disallow rather than an excuse to proceed.
    Returns ``None`` when the origin publishes no usable rules.
    """
    url = urljoin(origin + "/", "robots.txt")
    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        raise RobotsDisallowedError(
            f"robots.txt unreachable at {url}: {exc}") from exc
    if 400 <= response.status_code < 500:
        return None
    if response.status_code >= 500:
        raise RobotsDisallowedError(
            f"robots.txt returned HTTP {response.status_code} at {url}")
    parser = RobotFileParser()
    parser.parse((response.text or "").splitlines())
    return parser


def robots_policy(session, url, timeout=ROBOTS_TIMEOUT):
    """Return the cached robots parser for ``url``'s origin (may be None)."""
    origin = _origin(url)
    if not origin:
        return None
    with _ROBOTS_LOCK:
        if origin in _ROBOTS_CACHE:
            cached = _ROBOTS_CACHE[origin]
            if isinstance(cached, RobotsDisallowedError):
                raise cached
            return cached
    try:
        parser = _load_robots(session, origin, timeout)
    except RobotsDisallowedError as exc:
        with _ROBOTS_LOCK:
            _ROBOTS_CACHE[origin] = exc
        raise
    with _ROBOTS_LOCK:
        _ROBOTS_CACHE[origin] = parser
    return parser


def reset_robots_cache():
    """Clear the per-origin robots cache (used by tests and long runs)."""
    with _ROBOTS_LOCK:
        _ROBOTS_CACHE.clear()
        _LAST_FETCH.clear()


def space_requests(origin, delay):
    """Wait only for the remainder of ``delay`` since this origin was last hit.

    Sleeping before every request would pay the full delay even for the first
    call and for origins that have been idle; the interval that matters is the
    one between two consecutive requests to the same host.
    """
    if not origin or delay <= 0:
        return 0.0
    with _ROBOTS_LOCK:
        last = _LAST_FETCH.get(origin)
        waited = 0.0 if last is None else max(0.0, delay - (time.monotonic() - last))
    if waited:
        time.sleep(waited)
    with _ROBOTS_LOCK:
        _LAST_FETCH[origin] = time.monotonic()
    return waited


@dataclass(frozen=True)
class SourceJob:
    source: str
    source_job_id: str
    source_url: str
    official_url: str | None = None
    title_raw: str = ""
    institution_raw: str = ""
    school_raw: str | None = None
    department_raw: str | None = None
    location_raw: str | None = None
    description_excerpt: str | None = None
    posted_date_raw: str | None = None
    deadline_raw: str | None = None
    salary_raw: str | None = None
    captured_at: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class AdapterResponse:
    jobs: list[SourceJob]
    pages_fetched: int = 0
    notes: list[str] = field(default_factory=list)
    # What the board says it holds, when it says so ("1 - 25 Results of 53").
    # Without this an adapter that can only read the first page looks like full
    # coverage, and every count derived from it overstates the market.
    reported_total: int | None = None
    # False when the adapter knows it could not reach every advertised result.
    coverage_complete: bool | None = None
    # How many *listing* pages were read. ``pages_fetched`` counts every request
    # an adapter made, so detail-page enrichment inflates it: a source that read
    # one listing page and opened twelve job pages records 13 there. Reading
    # that as pagination reach is wrong in exactly the direction that hides a
    # first-page-only harvest, so the listing count is kept separately.
    listing_pages: int | None = None

    def __post_init__(self):
        if self.listing_pages is None:
            self.listing_pages = self.pages_fetched


class SourceAdapter:
    name = "base"
    region = "Other"
    base_url = ""
    adapter_name = "base"
    priority = 50
    method = "public_html"
    enabled = True
    support_status = "enabled"
    support_reason = ""
    default_page_size = 25
    max_items = 50
    respect_robots = True
    # Whether this adapter can actually reach a second page. Most boards here
    # are read single-page: looping without a working page parameter would only
    # re-fetch the first one. Declaring it keeps "we read one page" distinct
    # from "we read everything" in the source health payload.
    paginates = False

    def __init__(self, timeout=20, max_pages=1, max_items=None, session=None):
        self.timeout = max(3, int(timeout))
        self.max_pages = max(1, int(max_pages))
        self.max_items = max_items if max_items is not None else self.max_items
        self.session = session or requests.Session()
        self._crawl_delay_noted = {}
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.8",
        })

    def fetch(self):
        raise NotImplementedError

    def robots_agent(self):
        """The token robots.txt rules are matched against for this crawler."""
        return USER_AGENT.split("/")[0] or "*"

    def check_robots(self, url):
        """Refuse a URL the origin's robots.txt disallows.

        The adapter layer reaches arbitrary institution websites, not just the
        job boards chosen by hand, so the origin's own published rules decide
        what may be fetched.  A refusal raises ``RobotsDisallowedError`` and is
        recorded; it is never downgraded to a silent skip.
        """
        if not self.respect_robots:
            return
        url_origin = _origin(url)
        parser = robots_policy(self.session, url, timeout=min(self.timeout, ROBOTS_TIMEOUT))
        if parser is None:
            return
        agent = self.robots_agent()
        if not parser.can_fetch(agent, url):
            raise RobotsDisallowedError(f"robots.txt disallows {url} for {agent}")
        try:
            declared = parser.crawl_delay(agent)
        except (AttributeError, ValueError):
            declared = None
        if declared:
            declared = max(0.0, float(declared))
            if declared > MAX_CRAWL_DELAY:
                # We cannot sleep this out inside a run, so we take the pace
                # seriously the other way: a hard request budget for the origin.
                # Capping the wait alone would have let one run spend 13
                # requests on a board that asked for one an hour.
                if not self._crawl_delay_noted.get(url_origin):
                    LOG.warning(
                        "robots.txt at %s asks for Crawl-delay=%ss; capping the wait at %ss "
                        "and this run at %s request(s) to that origin",
                        url_origin, declared, MAX_CRAWL_DELAY, SLOW_ORIGIN_REQUESTS_PER_RUN)
                    self._crawl_delay_noted[url_origin] = declared
                _consume_slow_origin_budget(url_origin, declared)
            # An origin asking for a slower pace outranks our own default.
            space_requests(url_origin, min(MAX_CRAWL_DELAY, declared))

    def request(self, url, *, params=None, data=None, method="GET"):
        """GET/POST public pages with bounded retries and backoff."""
        target = url
        if params:
            try:
                target = requests.Request(method, url, params=params).prepare().url
            except Exception:
                target = url
        self.check_robots(target)
        last_error = None
        for attempt in range(3):
            try:
                response = self.session.request(
                    method, url, params=params, data=data, timeout=self.timeout,
                    allow_redirects=True,
                )
                if response.status_code in RETRY_STATUS and attempt < 2:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = min(12.0, max(0.5, float(retry_after))) if retry_after else 2 ** attempt
                    except ValueError:
                        delay = 2 ** attempt
                    time.sleep(delay)
                    continue
                if response.status_code >= 400:
                    error = f"HTTP {response.status_code} from {url}"
                    if response.status_code not in RETRY_STATUS:
                        raise NonRetryableAdapterError(error)
                    raise AdapterError(error)
                response.encoding = response.encoding or "utf-8"
                return response
            except NonRetryableAdapterError:
                raise
            except (requests.RequestException, AdapterError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise AdapterError(str(last_error) if last_error else f"request failed: {url}")


_RESULT_TOTAL_RE = re.compile(
    r"\b\d[\d,]*\s*[-–]\s*\d[\d,]*\s+(?:results?|jobs?|vacancies)\s+of\s+(\d[\d,]*)"
    r"|\bof\s+(\d[\d,]*)\s+(?:results?|jobs?|vacancies)\b"
    r"|\b(\d[\d,]*)\s+(?:results?|jobs?|vacancies)\s+found\b",
    re.I,
)


def reported_result_total(soup):
    """The result count a board prints, when it prints one.

    Boards say things like "1 - 25 Results of 53" or "128 jobs found". Reading
    it is the only way to tell a fully harvested source from one where we only
    ever see the first page: without it both look identical, and every count
    derived from the source silently claims completeness it does not have.
    Returns None when the board publishes no total, which is not the same claim
    as having read everything.
    """
    match = _RESULT_TOTAL_RE.search(soup.get_text(" ", strip=True))
    if not match:
        return None
    value = next((group for group in match.groups() if group), None)
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def visible_text(node):
    if node is None:
        return ""
    for unwanted in node.find_all(["script", "style", "noscript", "svg"]):
        unwanted.decompose()
    return re.sub(r"\s+", " ", unescape(node.get_text(" ", strip=True))).strip()


def first_text(node, selectors):
    if node is None:
        return None
    for selector in selectors:
        found = node.select_one(selector)
        text = visible_text(found)
        if text:
            return text
    return None


def absolute_url(base, value):
    return urljoin(base, (value or "").strip()) if value else None


def extract_date_attr(node, selectors):
    text = first_text(node, selectors)
    if text:
        return text
    return None


def detail_excerpt(node, max_chars=2000):
    text = visible_text(node)
    return text[:max_chars] if text else None


def dedupe_source_jobs(jobs):
    seen = set()
    out = []
    for job in jobs:
        key = (job.source, job.source_job_id or job.source_url)
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def parse_http_date(value):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def extract_jsonld(soup):
    """Return compact JSON-LD job objects without retaining raw page content."""
    import json
    records = []
    for node in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        try:
            value = json.loads(node.string or node.get_text())
        except (TypeError, ValueError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict) and item.get("@type") in ("JobPosting", ["JobPosting"]):
                records.append(item)
    return records


def adapter_catalog():
    """Instantiate the adapters lazily so importing the service stays cheap."""
    from .ais import AISAdapter
    from .euraxess import EuraxessAdapter
    from .higheredjobs import HigherEdJobsAdapter
    from .insidehighered import InsideHigherEdAdapter
    from .jobs_ac_uk import JobsAcUkAdapter
    from .university_affairs import UniversityAffairsAdapter
    from .aom import AOMAdapter
    from .carnegie import CarnegieOfficialAdapter
    from .association_boards import (
        ANZAMAdapter,
        EAAAccountingAdapter,
        EconJobMarketAdapter,
        TimesHigherEducationUnijobsAdapter,
    )
    from .source_jobboards import (
        AACSBJobConnectionAdapter,
        AMAAcademicPlacementAdapter,
        AFAFinanceAdapter,
        AMSMarketingAdapter,
        AcademicJobsOnlineAdapter,
        AAACareerCenterAdapter,
        AKADEUSAdapter,
        ChronicleAdapter,
        DecisionSciencesAdapter,
        EFMDJobsAdapter,
        FMAAdapter,
        HERCAdapter,
        INFORMSAdapter,
        POMSAdapter,
        SMSAdapter,
    )

    return [
        AOMAdapter(),
        AISAdapter(),
        HigherEdJobsAdapter(),
        InsideHigherEdAdapter(),
        UniversityAffairsAdapter(),
        EuraxessAdapter(),
        JobsAcUkAdapter(),
        ChronicleAdapter(),
        AAACareerCenterAdapter(),
        AFAFinanceAdapter(),
        AMSMarketingAdapter(),
        TimesHigherEducationUnijobsAdapter(),
        EconJobMarketAdapter(),
        EAAAccountingAdapter(),
        ANZAMAdapter(),
        POMSAdapter(),
        DecisionSciencesAdapter(),
        SMSAdapter(),
        AcademicJobsOnlineAdapter(),
        AKADEUSAdapter(),
        AACSBJobConnectionAdapter(),
        AMAAcademicPlacementAdapter(),
        FMAAdapter(),
        INFORMSAdapter(),
        HERCAdapter(),
        EFMDJobsAdapter(),
        CarnegieOfficialAdapter(),
    ]


__all__ = [
    "AdapterError", "NonRetryableAdapterError", "RobotsDisallowedError",
    "AdapterResponse", "SourceAdapter", "SourceJob", "USER_AGENT",
    "absolute_url", "adapter_catalog", "dedupe_source_jobs", "detail_excerpt",
    "extract_jsonld", "first_text", "now_utc", "reset_robots_cache",
    "robots_policy", "space_requests", "visible_text",
]
