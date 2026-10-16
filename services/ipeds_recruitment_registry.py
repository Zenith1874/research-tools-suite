# -*- coding: utf-8 -*-
"""IPEDS-seeded discovery of official university recruitment portals.

This module keeps the IPEDS institution seed separate from the existing AACSB
roster and from the faculty-job observation database.  The seed is one row per
IPEDS institution (UNITID); website requests are de-duplicated by normalized
official-site host, because several IPEDS reporting units can share one
university website.

The scanner only follows links exposed by an official homepage, honours the
robots policy implemented by the shared public-source adapter, and records
portal discovery separately from vacancy evidence.  A page that is blocked,
unreadable, or has no discoverable recruitment link is never recorded as
evidence that the institution has no jobs.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from services.faculty_jobs_sources.base import (
    AdapterError,
    CrawlBudgetExhaustedError,
    RobotsDisallowedError,
    SourceAdapter,
    now_utc,
    reset_crawl_budgets,
    reset_robots_cache,
    visible_text,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = ROOT / "data" / "academic_market.db"
DEFAULT_REGISTRY_DB = ROOT / "data" / "faculty_jobs" / "ipeds_doctoral_recruitment_registry.db"
DEFAULT_EXPORT_CSV = ROOT / "outputs" / "ipeds_doctoral_recruitment_registry_20260905.csv"
DEFAULT_DATA_YEAR = 2023
REGISTRY_SCHEMA_VERSION = 1
DISCOVERY_RULE_VERSION = "ipeds_doctoral_recruitment_v12_20260905"
TARGET_CARNEGIE_CODES = (15, 16, 17)
CARNEGIE_LABELS = {
    15: "Doctoral Universities: Very High Research Activity (R1)",
    16: "Doctoral Universities: High Research Activity (R2)",
    17: "Doctoral/Professional Universities",
}
OUTLYING_AREA_CODES = frozenset({"PR", "VI", "GU", "AS", "MP"})


FACULTY_LINK_RE = re.compile(
    r"\b(?:faculty\s+(?:jobs?|positions?|recruitment|opportunities|vacancies?)|"
    r"academic\s+(?:jobs?|positions?|recruitment|vacancies?)|"
    r"professor(?:s)?\s+(?:jobs?|positions?|openings?)|"
    r"(?:assistant|associate|full|clinical|visiting|teaching|research)\s+"
    r"professor|postdoctoral?|lecturer(?:s)?|instructor(?:s)?)\b",
    re.I,
)
STRONG_FACULTY_LINK_RE = re.compile(
    r"\b(?:faculty\s+(?:jobs?|positions?|recruitment|opportunities|vacancies?)|"
    r"academic\s+(?:jobs?|positions?|recruitment|vacancies?)|"
    r"professor(?:s)?\s+(?:jobs?|positions?|openings?)|"
    r"faculty\s+search(?:es)?|faculty\s+hiring)\b",
    re.I,
)
CENTRAL_RECRUITMENT_RE = re.compile(
    r"\b(?:career(?:s)?|employment|job(?:s)?\s+opportunities?|job(?:s)?\s+"
    r"openings?|vacanc(?:y|ies)|work\s+with\s+us|join\s+(?:our\s+team|the\s+team)|"
    r"human\s+resources?|\bHR\b|recruitment|recruiting)\b",
    re.I,
)
HR_RE = re.compile(r"\b(?:human\s+resources?|\bHR\b)\b", re.I)
EXCLUDED_STUDENT_RE = re.compile(
    r"\b(?:student[\s-]+career(?:s)?|career[\s-]+services?|career[\s-]+center|"
    r"career[\s-]+development|career[\s-]+success|career[\s-]+calling|"
    r"career[\s-]+fit|career[\s-]+outcomes?|career[\s-]+support|"
    r"career[\s-]+preparation|career[\s-]+advis(?:ing|ement)|"
    r"career[\s-]+resources?|career[\s-]+tools?[\s-]+and[\s-]+resources?|"
    r"career[\s-]+ready|"
    r"career\s+counsel(?:ing|lor)?|student[\s-]+employment|"
    r"student[\s-]+jobs?|internships?|internship\s+fair|alumni[\s-]+career(?:s)?|"
    r"experiential\s+learning|career\s+(?:101|workshop)|career\s+fair|"
    r"work[\s-]+study|employment[\s-]+resource|apprenticeship|"
    r"career\s+(?:and\s+)?(?:professional\s+)?(?:development|success|advancement|"
    r"readiness|closet|bridge)|professional\s+(?:development|success)|"
    r"career\s+academy|career\s+and\s+student\s+employment|"
    r"(?:admitted|current)\s+students?|off[\s-]+campus\s+employers?|"
    r"(?:fraternity|sorority)\s+recruitment)\b",
    re.I,
)
EXCLUDED_DIRECTORY_RE = re.compile(
    r"\b(?:faculty\s+directory|staff\s+directory|faculty\s+experts?|"
    r"faculty\s+expertise\s+search|expertise\s*(?:&|and)\s*faculty\s+search|"
    r"faculty\s+resources?|faculty\s+handbook|"
    r"faculty\s+senate)\b",
    re.I,
)
JOB_PATH_RE = re.compile(
    r"/(?:jobs?|careers?|employment|recruit(?:ment|ing)?|vacanc(?:y|ies)|"
    r"positions?|postings?|work-with-us)(?:/|\?|$)",
    re.I,
)
CENTRAL_PATH_RE = re.compile(
    r"/(?:jobs?|careers?|employment|recruit(?:ment|ing)?|vacanc(?:y|ies)|"
    r"positions?|postings?|human-resources?|hr)(?:/|\?|$)",
    re.I,
)
HR_INFORMATION_RE = re.compile(
    r"\b(?:title\s+ix|sexual\s+misconduct|employee\s+benefits?|payroll|"
    r"employee\s+handbook|hr\s+forms?|human\s+resources?\s+polic(?:y|ies)|"
    r"non[-\s]?discrimination|compliance|professional\s+development|training|"
    r"benefits?|wellness|campus\s+conduct|forms?|retirement|calendar|"
    r"current\s+employees?|human\s+resources?\s+staff|faculty\s+staff\s+resources?)\b",
    re.I,
)
NEWS_OR_EVENT_PATH_RE = re.compile(
    r"/(?:news(?:room|[-_][^/?#]+)?|story|stories|events?|agenda|announcement|"
    r"press(?:[-_][^/?#]+)?|blog|featuredevents|calendar)(?:/|\?|$)|"
    r"/media/(?:press|news)(?:[-_/][^/?#]+)?(?:/|\?|$)|"
    r"/20\d{2}/\d{1,2}/\d{1,2}/",
    re.I,
)
DIRECTORY_LABEL_RE = re.compile(r"\bdirector(?:y|ies)\b", re.I)
CONTENT_SUBDOMAIN_RE = re.compile(r"^(?:news|stories?|blog|blogs|calendar|events?)\.", re.I)
NON_RECRUITMENT_LABEL_RE = re.compile(
    r"\b(?:course\s+syllabi|instructor\s+information|course\s+schedule|"
    r"career\s+(?:fair|preparation|outcomes?|support|advis(?:ing|ement)|"
    r"resources?|ready|success|fit|calling|development)|"
    r"employment\s+resource|work[\s-]+study|"
    r"(?:human\s+resources?|HR)\s+(?:system|portal|login)|"
    r"(?:employee\s+)?benefits?|retirement\s+plans?|"
    r"(?:human\s+resources?|HR)\s+(?:calendar|staff|forms?)|"
    r"(?:non[-\s]?discrimination|sexual\s+misconduct|title\s+ix))\b",
    re.I,
)
ACADEMIC_PROGRAM_PATH_RE = re.compile(
    r"/(?:[^/?#]*[-_])?(?:programs?|academics?|degrees?|majors?|colleges?|"
    r"schools?|courses?|certificates?|admissions?|curriculum|areas?[-_]of[-_]interest)"
    r"(?:[-_/.]|\?|$)",
    re.I,
)
STUDENT_SUPPORT_PATH_RE = re.compile(
    r"/(?:students?|student[-_](?:life|services?|experience|employment)|"
    r"career[-_](?:services?|center|development|success|advancement|readiness|"
    r"resources?|preparation|outcomes?|support)|"
    r"(?:fraternity|sorority))(?:[-_/]|\?|$)",
    re.I,
)
SEARCH_PATH_RE = re.compile(r"/(?:site[-_]?search|search)(?:/|\?|$)", re.I)
INTERNAL_SYSTEM_PATH_RE = re.compile(r"/(?:hrsys|login)(?:/|\?|$)", re.I)
STUDENT_SUPPORT_HOST_RE = re.compile(
    r"^(?:careerconnections?|careercenter|careerservices|ocpd)\.", re.I
)
NON_RECRUITMENT_PAGE_TITLE_RE = re.compile(
    r"\b(?:career\s+(?:and\s+)?student\s+employment(?:\s+services?)?|"
    r"student\s+(?:career|employment)\s+services?|career\s+(?:services?|"
    r"center|development|success|advancement|readiness))\b",
    re.I,
)
ATS_HOST_RE = re.compile(
    r"(?:myworkdayjobs\.com|wd\d+\.myworkdayjobs\.com|greenhouse\.io|"
    r"lever\.co|interfolio\.com|jobs\.smartrecruiters\.com|taleo\.net|"
    r"icims\.com|peopleadmin\.com|pageuppeople\.com|successfactors\.com|"
    r"oraclecloud\.com|ultipro\.com|ukg\.com)",
    re.I,
)
EXTERNAL_JOB_HOST_RE = re.compile(
    r"(?:\bjobs?\.|\bcareers?\.|\bemployment\.|\bhr\.|"
    r"recruit(?:ment|ing)?\.)",
    re.I,
)
BLOCKED_PAGE_RE = re.compile(
    r"(?:access\s+denied|verify\s+you\s+are\s+human|captcha|"
    r"unusual\s+traffic|robot\s+check|cf-chl-|incapsula|enable\s+javascript)",
    re.I,
)
FILE_SUFFIX_RE = re.compile(
    r"\.(?:pdf|docx?|xlsx?|pptx?|zip|jpg|jpeg|png|gif|svg|mp3|mp4)(?:$|\?)",
    re.I,
)


@dataclass(frozen=True)
class SiteScanResult:
    """One bounded observation of one de-duplicated official website."""

    website_group_key: str
    checked_at: str
    official_website_url: str | None
    homepage_status: str
    homepage_http_status: int | None
    homepage_final_url: str | None
    homepage_title: str | None
    overall_status: str
    candidates_seen: int
    portals: tuple[dict, ...]
    pages_fetched: int
    request_attempts: int
    discovery_complete: bool
    candidate_truncated: bool
    reason: str | None


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _short(value, limit=500):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] if text else None


def normalize_public_url(value, *, keep_query=False):
    """Return a safe HTTP(S) URL, adding HTTPS to IPEDS bare hostnames."""
    raw = str(value or "").strip()
    if not raw:
        return None
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        if parts.username or parts.password:
            return None
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname.lower().rstrip(".")
    netloc = host
    if port is not None and port not in {80, 443}:
        netloc = f"{netloc}:{port}"
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    query = parts.query if keep_query else ""
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def canonical_host(value):
    """Normalize a website host for request de-duplication."""
    url = normalize_public_url(value)
    if not url:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    try:
        port = parts.port
    except ValueError:
        return None
    if port is not None and port not in {80, 443}:
        host = f"{host}:{port}"
    return host or None


def _canonical_link(base_url, href):
    raw = str(href or "").strip()
    if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    target = urljoin(base_url, raw)
    return normalize_public_url(target, keep_query=True)


def _is_same_page(url, base_url):
    left = normalize_public_url(url, keep_query=True)
    right = normalize_public_url(base_url, keep_query=True)
    if not left or not right:
        return False
    if left == right:
        return True
    left_parts = urlsplit(left)
    right_parts = urlsplit(right)
    return bool(
        not left_parts.query and not right_parts.query
        and left_parts.netloc.lower() == right_parts.netloc.lower()
        and left_parts.path.lower() in {"", "/", "/index.html", "/index.htm", "/index.php", "/home"}
        and right_parts.path.lower() in {"", "/", "/index.html", "/index.htm", "/index.php", "/home"}
    )


def _is_external_job_host(url, official_host):
    host = canonical_host(url) or ""
    if _same_site_host(host, official_host):
        return False
    return bool(ATS_HOST_RE.search(host) or EXTERNAL_JOB_HOST_RE.search(host))


def _same_site_host(host, official_host):
    """Treat an official subdomain as part of the seeded institution site."""
    left = str(host or "").lower().rstrip(".")
    right = str(official_host or "").lower().rstrip(".")
    return bool(left and right and (
        left == right or left.endswith("." + right) or right.endswith("." + left)
    ))


def _portal_kind(text, url):
    combined = f"{text} {url}"
    host = canonical_host(url) or ""
    if ATS_HOST_RE.search(host):
        return "external_ats"
    if STRONG_FACULTY_LINK_RE.search(combined) or FACULTY_LINK_RE.search(combined):
        return "faculty_recruitment"
    if HR_RE.search(combined):
        return "hr_recruitment"
    return "central_recruitment"


def discover_portal_candidates(soup, base_url):
    """Find and score public recruitment links exposed by an official page.

    The result is a candidate catalogue, not a claim that the linked page is
    the institution's sole or current hiring system.  Student career pages,
    faculty directories, and generic resources are explicitly rejected.
    """
    official_host = canonical_host(base_url)
    scored = {}
    for anchor in soup.find_all("a", href=True):
        url = _canonical_link(base_url, anchor.get("href"))
        if not url or _is_same_page(url, base_url):
            continue
        if FILE_SUFFIX_RE.search(url):
            continue
        text = _short(anchor.get_text(" ", strip=True), 240) or ""
        combined = f"{text} {unquote(url)}"
        text_tokens = re.findall(r"[\w’'-]+", text)
        strong_faculty = bool(STRONG_FACULTY_LINK_RE.search(combined))
        faculty = bool(FACULTY_LINK_RE.search(combined))
        central_text = bool(CENTRAL_RECRUITMENT_RE.search(text))
        central_path = bool(CENTRAL_PATH_RE.search(url))
        # A URL such as ``/career-development/`` contains the word career but
        # is normally a student-support page.  Treat URL text as a central
        # recruitment signal only when the path is an exact recruitment
        # segment; ordinary words in the anchor text remain eligible.
        central = bool(central_text or central_path)
        ats = bool(ATS_HOST_RE.search(canonical_host(url) or ""))
        job_path = bool(JOB_PATH_RE.search(url))
        if EXCLUDED_STUDENT_RE.search(combined) and not strong_faculty:
            continue
        if STUDENT_SUPPORT_PATH_RE.search(url) and not (strong_faculty or ats):
            continue
        if STUDENT_SUPPORT_HOST_RE.search(canonical_host(url) or "") and not (strong_faculty or ats):
            continue
        if INTERNAL_SYSTEM_PATH_RE.search(url) and not (strong_faculty or ats):
            continue
        # Directory/expertise search pages are informational even when the
        # word "faculty" appears next to "search"; this exclusion therefore
        # takes precedence over the broad faculty-search signal.
        if EXCLUDED_DIRECTORY_RE.search(combined):
            continue
        if DIRECTORY_LABEL_RE.search(text) and not re.search(
            r"\b(?:job(?:s)?|employment|career(?:s)?|vacanc(?:y|ies)|"
            r"recruit(?:ment|ing)?|position(?:s)?|faculty|academic)\b",
            text,
            re.I,
        ):
            continue
        if HR_INFORMATION_RE.search(combined) and not re.search(
            r"\b(?:job(?:s)?|employment|career(?:s)?|vacanc(?:y|ies)|"
            r"recruit(?:ment|ing)?|position(?:s)?|faculty\s+(?:job|position))\b",
            text,
            re.I,
        ):
            continue
        if NON_RECRUITMENT_LABEL_RE.search(text) and not re.search(
            r"\b(?:job(?:s)?|employment\s+opportunities?|career(?:s)?\s+opportunities?|"
            r"vacanc(?:y|ies)|recruit(?:ment|ing)?|faculty\s+(?:job|position))\b",
            text,
            re.I,
        ):
            continue
        if SEARCH_PATH_RE.search(url) and not (strong_faculty or ats):
            continue
        if ACADEMIC_PROGRAM_PATH_RE.search(url) and not (strong_faculty or ats):
            continue
        # News stories, event listings, and long marketing snippets often
        # contain words such as "career" or "professor" without linking to a
        # hiring system.  Recruitment navigation labels are short; a long
        # sentence is admitted only for a clearly labelled faculty/ATS link.
        if len(text_tokens) > 12 and not (strong_faculty or ats):
            continue
        if (
            NEWS_OR_EVENT_PATH_RE.search(url)
            or CONTENT_SUBDOMAIN_RE.search(canonical_host(url) or "")
        ) and not (strong_faculty or ats or job_path):
            continue
        if not (strong_faculty or faculty or central or ats or job_path):
            continue
        same_site = _same_site_host(canonical_host(url), official_host)
        if not same_site and not _is_external_job_host(url, official_host):
            continue
        score = 0
        if strong_faculty:
            score += 100
        elif faculty:
            score += 70
        if ats:
            score += 55
        if central:
            score += 45
        if job_path:
            score += 25
        if not same_site:
            score += 10
        # An explicit generic employment link is useful, but a bare word
        # "career" from a student-facing navigation bar is lower confidence.
        if not strong_faculty and not ats and not job_path and text.casefold() in {
            "career", "careers", "employment", "jobs", "job opportunities",
        }:
            score -= 10
        if score < 35:
            continue
        item = {
            "portal_url": url,
            "canonical_url": url,
            "portal_kind": _portal_kind(combined, url),
            "anchor_text": text or None,
            "discovery_method": "official_homepage_link",
            "discovery_evidence": _short(f"{text} -> {url}", 500),
            "confidence": "observed",
            "score": score,
            "page_status": "not_checked",
            "http_status": None,
            "final_url": None,
            "page_title": None,
            "jobposting_jsonld": 0,
            "page_signals": [],
        }
        previous = scored.get(url)
        if previous is None or item["score"] > previous["score"]:
            scored[url] = item
    return sorted(scored.values(), key=lambda item: (-item["score"], item["canonical_url"]))


def _blocked_text(text):
    return bool(BLOCKED_PAGE_RE.search(str(text or "")[:6000]))


def _jsonld_jobposting_count(soup):
    count = 0

    def visit(value):
        nonlocal count
        if isinstance(value, dict):
            type_value = value.get("@type")
            if (isinstance(type_value, str) and type_value.casefold() == "jobposting") or (
                isinstance(type_value, list)
                and any(str(item).casefold() == "jobposting" for item in type_value)
            ):
                count += 1
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text() or ""
        try:
            visit(json.loads(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            if re.search(r"[\"']@type[\"']\s*:\s*[\"']JobPosting", raw, re.I):
                count += 1
    return count


def inspect_html_response(response):
    """Return bounded, non-HTML evidence from a fetched public page."""
    soup = BeautifulSoup(response.text or "", "html.parser")
    # ``visible_text`` removes script/style nodes in place, so inspect JSON-LD
    # before deriving the visible page text.
    jobposting_count = _jsonld_jobposting_count(soup)
    text = visible_text(soup)
    blocked = _blocked_text(text)
    signals = []
    if FACULTY_LINK_RE.search(text):
        signals.append("faculty_or_academic_language")
    if CENTRAL_RECRUITMENT_RE.search(text):
        signals.append("recruitment_language")
    if jobposting_count:
        signals.append("jobposting_jsonld")
    return {
        "page_status": "blocked" if blocked else "ok",
        "http_status": getattr(response, "status_code", None),
        "final_url": normalize_public_url(getattr(response, "url", None), keep_query=True),
        "page_title": _short(soup.title.get_text(" ", strip=True) if soup.title else None, 300),
        "jobposting_jsonld": jobposting_count,
        "page_signals": signals,
    }


def _exception_status(error):
    message = _short(error, 400) or error.__class__.__name__
    if isinstance(error, CrawlBudgetExhaustedError):
        return "crawl_budget_exhausted", message
    if isinstance(error, RobotsDisallowedError):
        return "robots_disallowed", message
    if re.search(r"HTTP\s+(?:403|429)|access\s+denied|captcha|challenge", message, re.I):
        return "blocked", message
    return "error", message


class RecruitmentSiteScanner(SourceAdapter):
    """Bounded official-site scanner using the shared robots-aware adapter."""

    name = "ipeds_recruitment_registry"
    adapter_name = "ipeds_recruitment_registry"
    region = "United States"
    priority = 35
    max_items = 1000

    def __init__(self, timeout=20, delay=0.75, session=None):
        super().__init__(timeout=max(3, int(timeout)), max_pages=1, max_items=1000,
                         session=session)
        self.delay = max(0.0, min(10.0, float(delay)))

    def _pause(self):
        if self.delay:
            time.sleep(self.delay)

    def _request_page(self, url):
        try:
            response = self.request(url)
            self._pause()
            return response, None
        except Exception as error:  # the status is persisted by the caller
            self._pause()
            return None, error

    def scan_site(self, website_row, *, max_portals=3):
        group_key = website_row["website_group_key"]
        checked_at = now_utc()
        official_url = website_row["official_website_url"]
        max_portals = max(1, min(12, int(max_portals)))
        if not official_url:
            return SiteScanResult(
                group_key, checked_at, None, "no_official_website", None, None, None,
                "no_official_website", 0, tuple(), 0, 0, False, False,
                "IPEDS seed did not expose an official website.",
            )

        homepage, home_error = self._request_page(official_url)
        if home_error is not None:
            status, reason = _exception_status(home_error)
            return SiteScanResult(
                group_key, checked_at, official_url, status, None, None, None,
                status, 0, tuple(), 0, 1, False, False, reason,
            )

        homepage_info = inspect_html_response(homepage)
        if homepage_info["page_status"] == "blocked":
            return SiteScanResult(
                group_key, checked_at, official_url, "blocked",
                homepage_info["http_status"], homepage_info["final_url"],
                homepage_info["page_title"], "blocked", 0, tuple(), 1, 1,
                False, False, "Official homepage returned a public access challenge.",
            )

        base_url = homepage_info["final_url"] or official_url
        soup = BeautifulSoup(homepage.text or "", "html.parser")
        candidates = discover_portal_candidates(soup, base_url)
        selected = candidates[:max_portals]
        portal_results = []
        for candidate in selected:
            item = dict(candidate)
            portal_page, portal_error = self._request_page(candidate["canonical_url"])
            if portal_error is not None:
                status, reason = _exception_status(portal_error)
                item.update(page_status=status, reason=reason)
            else:
                page_info = inspect_html_response(portal_page)
                if (
                    page_info["page_status"] == "ok"
                    and NON_RECRUITMENT_PAGE_TITLE_RE.search(page_info["page_title"] or "")
                ):
                    continue
                item.update(page_info)
            portal_results.append(item)

        candidate_truncated = len(candidates) > len(selected)
        page_statuses = {item["page_status"] for item in portal_results}
        unreadable = page_statuses.intersection(
            {"blocked", "robots_disallowed", "crawl_budget_exhausted", "error"}
        )
        if not candidates or not portal_results:
            overall = "no_portal_link"
            if candidates:
                reason = (
                    "Official homepage exposed candidate link(s), but the selected page title(s) "
                    "indicated student-facing career services rather than employee recruitment."
                )
            else:
                reason = "Official homepage was readable, but no public recruitment link met the discovery rule."
        elif candidate_truncated or unreadable:
            overall = "portals_found_partial"
            reason = (
                "Portal candidates were observed, but the bounded candidate/page budget was not fully readable."
            )
        else:
            overall = "portals_found"
            reason = "Official homepage exposed recruitment portal candidate(s), and selected pages were readable."
        complete = bool(
            homepage_info["page_status"] == "ok"
            and not candidate_truncated
            and not unreadable
        )
        return SiteScanResult(
            group_key, checked_at, official_url, "ok",
            homepage_info["http_status"], homepage_info["final_url"],
            homepage_info["page_title"], overall, len(candidates),
            tuple(portal_results), 1 + len(portal_results), 1 + len(portal_results),
            complete, candidate_truncated, reason,
        )


def registry_connect(db_path=None):
    path = Path(db_path or DEFAULT_REGISTRY_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_registry_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS registry_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            note TEXT
        );

        CREATE TABLE IF NOT EXISTS registry_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            data_year INTEGER,
            seed_scope TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            requested_count INTEGER NOT NULL DEFAULT 0,
            processed_count INTEGER NOT NULL DEFAULT 0,
            request_attempts INTEGER NOT NULL DEFAULT 0,
            result_counts_json TEXT NOT NULL DEFAULT '{}',
            source_db TEXT,
            rule_version TEXT,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS institution_recruitment_websites (
            website_group_key TEXT PRIMARY KEY,
            representative_unitid INTEGER NOT NULL,
            official_website_url TEXT,
            official_host TEXT,
            linked_institution_count INTEGER NOT NULL DEFAULT 0,
            first_seeded_at TEXT NOT NULL,
            last_seeded_at TEXT NOT NULL,
            latest_status TEXT NOT NULL DEFAULT 'seeded',
            latest_checked_at TEXT,
            latest_http_status INTEGER,
            latest_portals_found INTEGER NOT NULL DEFAULT 0,
            latest_reason TEXT
        );

        CREATE TABLE IF NOT EXISTS institution_recruitment_targets (
            unitid INTEGER PRIMARY KEY,
            data_year INTEGER NOT NULL,
            institution_name TEXT NOT NULL,
            state TEXT NOT NULL,
            control INTEGER,
            carnegie_basic INTEGER NOT NULL,
            carnegie_label TEXT NOT NULL,
            official_website_raw TEXT,
            official_website_url TEXT,
            official_host TEXT,
            website_group_key TEXT,
            seed_scope TEXT NOT NULL,
            seed_source TEXT NOT NULL,
            source_release_id INTEGER,
            seeded_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (website_group_key)
                REFERENCES institution_recruitment_websites(website_group_key)
        );
        CREATE INDEX IF NOT EXISTS idx_recruitment_targets_carnegie
            ON institution_recruitment_targets(carnegie_basic, state);
        CREATE INDEX IF NOT EXISTS idx_recruitment_targets_website
            ON institution_recruitment_targets(website_group_key);

        CREATE TABLE IF NOT EXISTS institution_recruitment_portals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            website_group_key TEXT NOT NULL,
            portal_url TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            origin_host TEXT,
            portal_kind TEXT NOT NULL,
            discovery_method TEXT NOT NULL,
            discovery_evidence TEXT,
            confidence TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            latest_page_status TEXT NOT NULL DEFAULT 'not_checked',
            latest_http_status INTEGER,
            latest_final_url TEXT,
            latest_title TEXT,
            latest_jobposting_jsonld INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            UNIQUE (website_group_key, canonical_url),
            FOREIGN KEY (website_group_key)
                REFERENCES institution_recruitment_websites(website_group_key)
        );
        CREATE INDEX IF NOT EXISTS idx_recruitment_portals_group
            ON institution_recruitment_portals(website_group_key, active);

        CREATE TABLE IF NOT EXISTS institution_recruitment_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            website_group_key TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            official_website_url TEXT,
            homepage_status TEXT NOT NULL,
            homepage_http_status INTEGER,
            homepage_final_url TEXT,
            overall_status TEXT NOT NULL,
            candidates_seen INTEGER NOT NULL DEFAULT 0,
            portals_found INTEGER NOT NULL DEFAULT 0,
            pages_fetched INTEGER NOT NULL DEFAULT 0,
            request_attempts INTEGER NOT NULL DEFAULT 0,
            discovery_complete INTEGER NOT NULL DEFAULT 0,
            candidate_truncated INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            rule_version TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES registry_runs(id),
            FOREIGN KEY (website_group_key)
                REFERENCES institution_recruitment_websites(website_group_key)
        );
        CREATE INDEX IF NOT EXISTS idx_recruitment_observations_group
            ON institution_recruitment_observations(website_group_key, checked_at);
        CREATE INDEX IF NOT EXISTS idx_recruitment_observations_status
            ON institution_recruitment_observations(overall_status, checked_at);
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO registry_migrations(version, applied_at, note) VALUES (?,?,?)",
        (REGISTRY_SCHEMA_VERSION, now_utc(),
         "IPEDS 2023 R1/R2/Doctoral-Professional official recruitment portal registry."),
    )
    conn.commit()


def _source_connect(path):
    source = Path(path)
    conn = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def seed_registry(source_db=None, registry_db=None, *, data_year=DEFAULT_DATA_YEAR,
                  include_outlying_areas=False):
    """Seed the derived registry from the public IPEDS HD table.

    Existing source rows and registry history are preserved.  Re-running the
    seed updates the current target metadata but does not delete old portal
    observations.
    """
    source_path = Path(source_db or DEFAULT_SOURCE_DB)
    registry_path = Path(registry_db or DEFAULT_REGISTRY_DB)
    source = _source_connect(source_path)
    conn = registry_connect(registry_path)
    ensure_registry_schema(conn)
    started = now_utc()
    scope = "IPEDS_2023_US_50_STATES_DC"
    if include_outlying_areas:
        scope = "IPEDS_2023_US_PLUS_OUTLYING_AREAS"
    run_id = conn.execute(
        """INSERT INTO registry_runs
           (mode,data_year,seed_scope,started_at,status,source_db,rule_version)
           VALUES (?,?,?,?,?,?,?)""",
        ("seed", data_year, scope, started, "running", str(source_path), DISCOVERY_RULE_VERSION),
    ).lastrowid
    try:
        clauses = ["data_year = ?", "carnegie_basic IN (15,16,17)", "state IS NOT NULL"]
        args = [data_year]
        if not include_outlying_areas:
            clauses.append("state NOT IN ('PR','VI','GU','AS','MP')")
        rows = source.execute(
            """SELECT unitid,institution_name,state,control,carnegie_basic,website,release_id
               FROM ipeds_institutions WHERE """ + " AND ".join(clauses) +
            " ORDER BY carnegie_basic,institution_name,unitid", args,
        ).fetchall()
        seeded_at = now_utc()
        representatives = {}
        prepared = []
        for row in rows:
            official_url = normalize_public_url(row["website"])
            host = canonical_host(official_url) if official_url else None
            group_key = host
            prepared.append((row, official_url, host, group_key))
            if group_key:
                rank = (int(row["carnegie_basic"]), str(row["institution_name"]).casefold(), int(row["unitid"]))
                previous = representatives.get(group_key)
                if previous is None or rank < previous[0]:
                    representatives[group_key] = (rank, row, official_url, host)

        with conn:
            for group_key, (_, row, official_url, host) in representatives.items():
                conn.execute(
                    """INSERT INTO institution_recruitment_websites
                       (website_group_key,representative_unitid,official_website_url,official_host,
                        linked_institution_count,first_seeded_at,last_seeded_at)
                       VALUES (?,?,?,?,0,?,?)
                       ON CONFLICT(website_group_key) DO UPDATE SET
                         representative_unitid=excluded.representative_unitid,
                         official_website_url=excluded.official_website_url,
                         official_host=excluded.official_host,
                         last_seeded_at=excluded.last_seeded_at""",
                    (group_key, row["unitid"], official_url, host, seeded_at, seeded_at),
                )
            for row, official_url, host, group_key in prepared:
                conn.execute(
                    """INSERT INTO institution_recruitment_targets
                       (unitid,data_year,institution_name,state,control,carnegie_basic,carnegie_label,
                        official_website_raw,official_website_url,official_host,website_group_key,
                        seed_scope,seed_source,source_release_id,seeded_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(unitid) DO UPDATE SET
                         data_year=excluded.data_year,institution_name=excluded.institution_name,
                         state=excluded.state,control=excluded.control,carnegie_basic=excluded.carnegie_basic,
                         carnegie_label=excluded.carnegie_label,official_website_raw=excluded.official_website_raw,
                         official_website_url=excluded.official_website_url,official_host=excluded.official_host,
                         website_group_key=excluded.website_group_key,seed_scope=excluded.seed_scope,
                         seed_source=excluded.seed_source,source_release_id=excluded.source_release_id,
                         updated_at=excluded.updated_at""",
                    (row["unitid"], row["data_year"] if "data_year" in row.keys() else data_year,
                     row["institution_name"], row["state"], row["control"], row["carnegie_basic"],
                     CARNEGIE_LABELS.get(row["carnegie_basic"], "Unknown Carnegie class"), row["website"],
                     official_url, host, group_key, scope, "IPEDS HD C21BASIC", row["release_id"],
                     seeded_at, seeded_at),
                )
            conn.execute(
                """UPDATE institution_recruitment_websites AS w
                   SET linked_institution_count = (
                       SELECT COUNT(*) FROM institution_recruitment_targets AS t
                       WHERE t.website_group_key=w.website_group_key AND t.seed_scope=?
                   )""",
                (scope,),
            )
            target_count = len(prepared)
            website_count = conn.execute(
                """SELECT COUNT(*) FROM institution_recruitment_websites
                   WHERE linked_institution_count > 0"""
            ).fetchone()[0]
            missing_website_count = conn.execute(
                """SELECT COUNT(*) FROM institution_recruitment_targets
                   WHERE seed_scope=? AND official_website_url IS NULL""", (scope,)
            ).fetchone()[0]
            result = {
                "target_count": target_count,
                "website_group_count": website_count,
                "missing_official_website": missing_website_count,
                "duplicate_website_records": max(0, target_count - website_count - missing_website_count),
                "data_year": data_year,
                "seed_scope": scope,
                "registry_db": str(registry_path),
            }
            conn.execute(
                """UPDATE registry_runs SET finished_at=?,status='ok',requested_count=?,
                   processed_count=?,result_counts_json=? WHERE id=?""",
                (now_utc(), target_count, target_count, _json(result), run_id),
            )
        return result
    except Exception as error:
        conn.execute(
            "UPDATE registry_runs SET finished_at=?,status='failed',error=? WHERE id=?",
            (now_utc(), _short(error, 1000), run_id),
        )
        conn.commit()
        raise
    finally:
        source.close()
        conn.close()


def _record_site_scan(conn, result: SiteScanResult, *, run_id):
    seen_urls = {portal["canonical_url"] for portal in result.portals}
    for portal in result.portals:
        now = result.checked_at
        conn.execute(
            """INSERT INTO institution_recruitment_portals
               (website_group_key,portal_url,canonical_url,origin_host,portal_kind,discovery_method,
                discovery_evidence,confidence,first_seen_at,last_seen_at,latest_page_status,
                latest_http_status,latest_final_url,latest_title,latest_jobposting_jsonld)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(website_group_key,canonical_url) DO UPDATE SET
                 portal_url=excluded.portal_url,origin_host=excluded.origin_host,
                 portal_kind=excluded.portal_kind,discovery_method=excluded.discovery_method,
                 discovery_evidence=excluded.discovery_evidence,confidence=excluded.confidence,
                 last_seen_at=excluded.last_seen_at,latest_page_status=excluded.latest_page_status,
                 latest_http_status=excluded.latest_http_status,latest_final_url=excluded.latest_final_url,
                 latest_title=excluded.latest_title,latest_jobposting_jsonld=excluded.latest_jobposting_jsonld,
                 active=1""",
            (result.website_group_key, portal["portal_url"], portal["canonical_url"],
             canonical_host(portal["canonical_url"]), portal["portal_kind"],
             portal["discovery_method"], portal["discovery_evidence"], portal["confidence"],
             now, now, portal.get("page_status", "not_checked"), portal.get("http_status"),
             portal.get("final_url"), portal.get("page_title"), int(portal.get("jobposting_jsonld") or 0)),
        )
    # A readable, non-truncated homepage and candidate set is the only point
    # at which an older portal can be marked inactive.  Blocked pages and
    # bounded partial observations must not retire evidence merely because it
    # was not visible in that run.
    if result.discovery_complete:
        if seen_urls:
            placeholders = ",".join("?" for _ in seen_urls)
            conn.execute(
                """UPDATE institution_recruitment_portals SET active=0
                   WHERE website_group_key=? AND canonical_url NOT IN ("""
                + placeholders + ")",
                [result.website_group_key, *sorted(seen_urls)],
            )
        else:
            conn.execute(
                """UPDATE institution_recruitment_portals SET active=0
                   WHERE website_group_key=?""", (result.website_group_key,)
            )
    evidence = {
        "homepage_title": result.homepage_title,
        "candidate_urls": [
            {
                "url": portal.get("canonical_url"),
                "kind": portal.get("portal_kind"),
                "anchor_text": portal.get("anchor_text"),
                "score": portal.get("score"),
                "page_status": portal.get("page_status"),
                "http_status": portal.get("http_status"),
                "final_url": portal.get("final_url"),
                "page_title": portal.get("page_title"),
                "jobposting_jsonld": portal.get("jobposting_jsonld", 0),
                "page_signals": portal.get("page_signals", []),
                "reason": portal.get("reason"),
            }
            for portal in result.portals
        ],
        "rule_version": DISCOVERY_RULE_VERSION,
        "note": "Portal discovery evidence is not vacancy evidence.",
    }
    conn.execute(
        """INSERT INTO institution_recruitment_observations
           (run_id,website_group_key,checked_at,official_website_url,homepage_status,
            homepage_http_status,homepage_final_url,overall_status,candidates_seen,portals_found,
            pages_fetched,request_attempts,discovery_complete,candidate_truncated,reason,
            evidence_json,rule_version)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, result.website_group_key, result.checked_at, result.official_website_url,
         result.homepage_status, result.homepage_http_status, result.homepage_final_url,
         result.overall_status, result.candidates_seen, len(result.portals), result.pages_fetched,
         result.request_attempts, int(result.discovery_complete), int(result.candidate_truncated),
         result.reason, _json(evidence), DISCOVERY_RULE_VERSION),
    )
    conn.execute(
        """UPDATE institution_recruitment_websites
           SET latest_status=?,latest_checked_at=?,latest_http_status=?,latest_portals_found=?,
               latest_reason=? WHERE website_group_key=?""",
        (result.overall_status, result.checked_at, result.homepage_http_status, len(result.portals),
         result.reason, result.website_group_key),
    )


def scan_registry(registry_db=None, *, max_websites=25, offset=0, include_checked=False,
                  timeout=20, delay=0.75, max_portals=3, only_hosts=None, progress=None):
    """Scan a resumable batch of unique official websites in the registry."""
    registry_path = Path(registry_db or DEFAULT_REGISTRY_DB)
    conn = registry_connect(registry_path)
    ensure_registry_schema(conn)
    bounded = max(1, min(1000, int(max_websites)))
    start_offset = max(0, int(offset))
    conditions = ["w.official_website_url IS NOT NULL"]
    args = []
    requested_hosts = [str(item).strip() for item in (only_hosts or []) if str(item).strip()]
    if requested_hosts:
        placeholders = ",".join("?" for _ in requested_hosts)
        conditions.append(f"w.website_group_key IN ({placeholders})")
        args.extend(requested_hosts)
    if not include_checked:
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM institution_recruitment_observations o "
            "WHERE o.website_group_key=w.website_group_key AND o.rule_version=?)"
        )
        args.append(DISCOVERY_RULE_VERSION)
    rows = conn.execute(
        """SELECT w.* FROM institution_recruitment_websites AS w
           WHERE """ + " AND ".join(conditions) +
        " ORDER BY w.website_group_key LIMIT ? OFFSET ?", args + [bounded, start_offset],
    ).fetchall()
    started = now_utc()
    run_id = conn.execute(
        """INSERT INTO registry_runs
           (mode,data_year,seed_scope,started_at,status,requested_count,source_db,rule_version)
           VALUES (?,?,?,?,?,?,?,?)""",
        ("scan", DEFAULT_DATA_YEAR, "IPEDS_2023_US_50_STATES_DC", started, "running",
         len(rows), None, DISCOVERY_RULE_VERSION),
    ).lastrowid
    conn.commit()
    reset_robots_cache()
    reset_crawl_budgets()
    scanner = RecruitmentSiteScanner(timeout=timeout, delay=delay)
    counts = {}
    processed = requests = 0
    try:
        for index, row in enumerate(rows, start=1):
            try:
                result = scanner.scan_site(row, max_portals=max_portals)
            except Exception as error:
                status, reason = _exception_status(error)
                result = SiteScanResult(
                    row["website_group_key"], now_utc(), row["official_website_url"], status,
                    None, None, None, status, 0, tuple(), 0, 1, False, False, reason,
                )
            with conn:
                _record_site_scan(conn, result, run_id=run_id)
            processed += 1
            requests += result.request_attempts
            counts[result.overall_status] = counts.get(result.overall_status, 0) + 1
            if progress:
                progress({
                    "index": index,
                    "total": len(rows),
                    "website_group_key": row["website_group_key"],
                    "representative_unitid": row["representative_unitid"],
                    "status": result.overall_status,
                    "portals_found": len(result.portals),
                    "pages_fetched": result.pages_fetched,
                    "reason": result.reason,
                })
        result_summary = {
            "requested": len(rows),
            "processed": processed,
            "request_attempts": requests,
            "statuses": counts,
            "offset": start_offset,
            "include_checked": bool(include_checked),
            "max_portals": max_portals,
            "rule_version": DISCOVERY_RULE_VERSION,
        }
        conn.execute(
            """UPDATE registry_runs SET finished_at=?,status='ok',processed_count=?,
               request_attempts=?,result_counts_json=? WHERE id=?""",
            (now_utc(), processed, requests, _json(result_summary), run_id),
        )
        conn.commit()
        return result_summary
    except Exception as error:
        conn.execute(
            """UPDATE registry_runs SET finished_at=?,status='failed',processed_count=?,
               request_attempts=?,result_counts_json=?,error=? WHERE id=?""",
            (now_utc(), processed, requests, _json(counts), _short(error, 1000), run_id),
        )
        conn.commit()
        raise
    finally:
        conn.close()


def registry_summary(registry_db=None):
    """Return compact counts for status reports and smoke-test verification."""
    path = Path(registry_db or DEFAULT_REGISTRY_DB)
    if not path.exists():
        return {"exists": False, "registry_db": str(path)}
    conn = registry_connect(path)
    try:
        ensure_registry_schema(conn)
        target_count = conn.execute("SELECT COUNT(*) FROM institution_recruitment_targets").fetchone()[0]
        group_count = conn.execute(
            "SELECT COUNT(*) FROM institution_recruitment_websites WHERE linked_institution_count > 0"
        ).fetchone()[0]
        portal_count = conn.execute("SELECT COUNT(*) FROM institution_recruitment_portals WHERE active=1").fetchone()[0]
        observation_count = conn.execute("SELECT COUNT(*) FROM institution_recruitment_observations").fetchone()[0]
        by_carnegie = [dict(row) for row in conn.execute(
            """SELECT carnegie_basic,carnegie_label,COUNT(*) AS institutions,
                      SUM(official_website_url IS NOT NULL) AS with_official_website
               FROM institution_recruitment_targets GROUP BY carnegie_basic,carnegie_label
               ORDER BY carnegie_basic"""
        )]
        by_status = [dict(row) for row in conn.execute(
            """SELECT overall_status AS status,COUNT(*) AS observations
               FROM institution_recruitment_observations GROUP BY overall_status ORDER BY status"""
        )]
        return {
            "exists": True,
            "registry_db": str(path),
            "targets": target_count,
            "website_groups": group_count,
            "active_portals": portal_count,
            "observations": observation_count,
            "by_carnegie": by_carnegie,
            "by_status": by_status,
            "rule_version": DISCOVERY_RULE_VERSION,
        }
    finally:
        conn.close()


def export_registry_csv(registry_db=None, output_path=None, *,
                        rule_version=DISCOVERY_RULE_VERSION, overwrite=False):
    """Export one auditable row per IPEDS target institution.

    The export keeps institution grain (UNITID), while attaching the latest
    observation for the selected discovery rule and only the portal rows
    discovered in that observation.  Historical portal rows remain available
    in SQLite but are not silently mixed into the current-rule table.
    """
    registry_path = Path(registry_db or DEFAULT_REGISTRY_DB)
    target_path = Path(output_path or DEFAULT_EXPORT_CSV)
    if target_path.resolve() == registry_path.resolve():
        raise ValueError("CSV output must not overwrite the registry database")
    if target_path.exists() and not overwrite:
        raise FileExistsError(
            f"Output already exists: {target_path}. Pass overwrite=True to replace it."
        )

    conn = registry_connect(registry_path)
    try:
        targets = conn.execute(
            """SELECT t.*,w.linked_institution_count,w.latest_status AS website_latest_status
               FROM institution_recruitment_targets AS t
               LEFT JOIN institution_recruitment_websites AS w
                 ON w.website_group_key=t.website_group_key
               ORDER BY t.carnegie_basic,t.institution_name,t.unitid"""
        ).fetchall()
        latest_observations = {}
        for row in conn.execute(
            """SELECT o.*
               FROM institution_recruitment_observations AS o
               WHERE o.rule_version=?
                 AND NOT EXISTS (
                   SELECT 1
                   FROM institution_recruitment_observations AS newer
                   WHERE newer.rule_version=o.rule_version
                     AND newer.website_group_key=o.website_group_key
                     AND (newer.checked_at>o.checked_at OR
                          (newer.checked_at=o.checked_at AND newer.id>o.id))
                 )""",
            (rule_version,),
        ):
            latest_observations[row["website_group_key"]] = row

        observation_keys = {
            (row["website_group_key"], row["checked_at"])
            for row in latest_observations.values()
        }
        portals_by_observation = {}
        if observation_keys:
            for row in conn.execute(
                """SELECT website_group_key,last_seen_at,canonical_url,portal_kind,
                          latest_page_status,confidence
                   FROM institution_recruitment_portals
                   ORDER BY website_group_key,canonical_url"""
            ):
                key = (row["website_group_key"], row["last_seen_at"])
                if key in observation_keys:
                    portals_by_observation.setdefault(key, []).append(row)

        fieldnames = [
            "unitid", "institution_name", "state", "control", "data_year",
            "carnegie_basic", "carnegie_label", "source_release_id", "seed_scope",
            "official_website_raw", "official_website_url", "official_host",
            "website_group_key", "linked_institution_count", "latest_status",
            "latest_checked_at", "homepage_status", "homepage_http_status",
            "homepage_final_url", "candidates_seen", "portals_found", "pages_fetched",
            "request_attempts", "discovery_complete", "candidate_truncated",
            "latest_reason", "scan_rule_version", "portal_urls", "portal_kinds",
            "portal_page_statuses", "portal_confidences",
        ]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        rows_written = 0
        portal_keys_written = set()
        portal_attachments_written = 0
        with target_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for target in targets:
                observation = latest_observations.get(target["website_group_key"])
                if target["official_website_url"] is None:
                    status = "missing_official_website"
                elif observation is None:
                    status = "not_scanned"
                else:
                    status = observation["overall_status"]
                portals = []
                if observation is not None:
                    portals = portals_by_observation.get(
                        (observation["website_group_key"], observation["checked_at"]), []
                    )
                portal_attachments_written += len(portals)
                portal_keys_written.update(
                    (observation["website_group_key"], item["canonical_url"])
                    for item in portals
                    if observation is not None
                )

                def joined(column):
                    return " | ".join(str(item[column]) for item in portals if item[column])

                writer.writerow({
                    "unitid": target["unitid"],
                    "institution_name": target["institution_name"],
                    "state": target["state"],
                    "control": target["control"],
                    "data_year": target["data_year"],
                    "carnegie_basic": target["carnegie_basic"],
                    "carnegie_label": target["carnegie_label"],
                    "source_release_id": target["source_release_id"],
                    "seed_scope": target["seed_scope"],
                    "official_website_raw": target["official_website_raw"],
                    "official_website_url": target["official_website_url"],
                    "official_host": target["official_host"],
                    "website_group_key": target["website_group_key"],
                    "linked_institution_count": target["linked_institution_count"],
                    "latest_status": status,
                    "latest_checked_at": observation["checked_at"] if observation else None,
                    "homepage_status": observation["homepage_status"] if observation else None,
                    "homepage_http_status": observation["homepage_http_status"] if observation else None,
                    "homepage_final_url": observation["homepage_final_url"] if observation else None,
                    "candidates_seen": observation["candidates_seen"] if observation else None,
                    "portals_found": observation["portals_found"] if observation else None,
                    "pages_fetched": observation["pages_fetched"] if observation else None,
                    "request_attempts": observation["request_attempts"] if observation else None,
                    "discovery_complete": observation["discovery_complete"] if observation else None,
                    "candidate_truncated": observation["candidate_truncated"] if observation else None,
                    "latest_reason": observation["reason"] if observation else None,
                    "scan_rule_version": observation["rule_version"] if observation else None,
                    "portal_urls": joined("canonical_url"),
                    "portal_kinds": joined("portal_kind"),
                    "portal_page_statuses": joined("latest_page_status"),
                    "portal_confidences": joined("confidence"),
                })
                rows_written += 1
        return {
            "registry_db": str(registry_path),
            "output_csv": str(target_path),
            "rows": rows_written,
            "portal_rows": len(portal_keys_written),
            "institution_portal_attachments": portal_attachments_written,
            "observed_groups": len(latest_observations),
            "rule_version": rule_version,
        }
    finally:
        conn.close()


__all__ = [
    "CARNEGIE_LABELS",
    "DEFAULT_EXPORT_CSV",
    "DEFAULT_REGISTRY_DB",
    "DEFAULT_SOURCE_DB",
    "DISCOVERY_RULE_VERSION",
    "RecruitmentSiteScanner",
    "SiteScanResult",
    "canonical_host",
    "discover_portal_candidates",
    "ensure_registry_schema",
    "export_registry_csv",
    "inspect_html_response",
    "normalize_public_url",
    "registry_connect",
    "registry_summary",
    "scan_registry",
    "seed_registry",
]
