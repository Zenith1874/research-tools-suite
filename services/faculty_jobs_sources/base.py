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


ROBOTS_TIMEOUT = 10
# A declared Crawl-delay is honoured up to this ceiling.  Some boards publish a
# boilerplate hour-long delay under ``User-agent: *``; blocking a scheduled run
# for that long would stall the global update lock, so the cap is applied and
# reported rather than silently dropped.
MAX_CRAWL_DELAY = 30.0
_ROBOTS_CACHE = {}
_ROBOTS_LOCK = threading.Lock()
_LAST_FETCH = {}


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
            if declared > MAX_CRAWL_DELAY and not self._crawl_delay_noted.get(url_origin):
                LOG.warning(
                    "robots.txt at %s asks for Crawl-delay=%ss; honouring the %ss ceiling",
                    url_origin, declared, MAX_CRAWL_DELAY)
                self._crawl_delay_noted[url_origin] = declared
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
    from .source_jobboards import (
        AACSBJobConnectionAdapter,
        AMAAcademicPlacementAdapter,
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
    ]


__all__ = [
    "AdapterError", "NonRetryableAdapterError", "RobotsDisallowedError",
    "AdapterResponse", "SourceAdapter", "SourceJob", "USER_AGENT",
    "absolute_url", "adapter_catalog", "dedupe_source_jobs", "detail_excerpt",
    "extract_jsonld", "first_text", "now_utc", "reset_robots_cache",
    "robots_policy", "space_requests", "visible_text",
]
