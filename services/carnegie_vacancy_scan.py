# -*- coding: utf-8 -*-
"""Bounded public vacancy discovery for the Carnegie 2025 registry.

The Carnegie recruitment registry records institution-level official websites
and observed recruitment entry points.  This module operates at the next
grain: one public portal-page observation and the individual faculty-market
candidate records found on that page.

It intentionally writes to a separate SQLite database.  A portal candidate is
not a vacancy, and a vacancy candidate is not automatically a production
``faculty_jobs`` record.  Robots.txt refusals, access challenges, rejected
student/staff candidates, and shared-system target ambiguity remain visible in
the isolated scan database for review.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import csv
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from services.faculty_jobs_normalizer import classify_business_scope, classify_faculty_market_role
from services.faculty_jobs_sources.base import (
    CrawlBudgetExhaustedError,
    NonRetryableAdapterError,
    RobotsDisallowedError,
    SourceAdapter,
    detail_excerpt,
    now_utc,
    reset_crawl_budgets,
    reset_robots_cache,
    visible_text,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_DB = ROOT / "data" / "faculty_jobs" / "carnegie_2025_recruitment_registry.db"
DEFAULT_SCAN_DB = ROOT / "data" / "faculty_jobs" / "carnegie_2025_vacancy_scan.db"
DEFAULT_EXPORT_CSV = ROOT / "outputs" / "carnegie_2025_vacancy_scan_20260906.csv"

VACANCY_SCAN_RULE_VERSION = "carnegie_vacancy_v12_20260920"
SCAN_SCHEMA_VERSION = 1
MAX_CANDIDATE_EVIDENCE = 300
MAX_DESCRIPTION_CHARS = 10000

BLOCKED_PAGE_RE = re.compile(
    r"(?:cloudflare|captcha|access\s+denied|verify\s+you\s+are\s+human|"
    r"robot\s+check|unusual\s+traffic|enable\s+javascript)",
    re.I,
)
STUDENT_OR_INFO_RE = re.compile(
    r"\b(?:student\s+careers?|career\s+services?|career\s+center|"
    r"student\s+employment|student\s+jobs?|alumni\s+careers?|"
    r"internships?|job\s+fair|employability|career\s+advantage|"
    r"launch\s+your\s+career|success\s+after|employment\s+experiences?|"
    r"faculty\s+directory|faculty\s+profile|our\s+people|"
    r"instructor\s+resources?|faculty\s+resources?)\b",
    re.I,
)
LOGIN_OR_SYSTEM_RE = re.compile(
    r"(?:/sso(?:/|\?|$)|/saml(?:/|\?|$)|/login(?:/|\?|$)|"
    r"/faces/(?:fusewelcome|login)|account\.interfolio\.com)",
    re.I,
)
FACULTY_SIGNAL_RE = re.compile(
    r"\b(?:faculty|academic|professor(?:s)?|lecturer(?:s)?|instructor(?:s)?|"
    r"post[- ]?doctoral|postdoc|dean|tenure[- ]track|faculty\s+recruitment)\b",
    re.I,
)
JOB_PAGE_SIGNAL_RE = re.compile(
    r"\b(?:job(?:s)?|employment|career(?:s)?|vacanc(?:y|ies)|position(?:s)?|"
    r"opening(?:s)?|recruitment|work\s+with\s+us|join\s+us|opportunit(?:y|ies))\b",
    re.I,
)
JOB_URL_RE = re.compile(
    r"(?:/(?:jobs?|postings?|positions?|vacanc(?:y|ies)|openings?)(?:/|\?|$)|"
    r"/(?:careers?|employment|recruitment?)/(?:[^/?#]+/)*[^/?#]+|"
    r"/(?:hcmUI/)?CandidateExperience/.*/job/|"
    r"/(?:job|position)/[^/?#]+|"
    r"(?:myworkdayjobs\.com|greenhouse\.io|lever\.co|icims\.com|"
    r"interfolio\.com|smartrecruiters\.com)/)",
    re.I,
)
GENERIC_LINK_RE = re.compile(
    r"^(?:view|see|read|learn\s+more|details?|apply|apply\s+now|"
    r"view\s+(?:job|position|details?)|search\s+(?:jobs?|positions?)|"
    r"browse\s+(?:jobs?|positions?))\W*$",
    re.I,
)
GENERIC_TITLE_RE = re.compile(
    r"^(?:faculty|staff|employment|employment\s+opportunities|careers?|"
    r"career\s+opportunities|job\s+listings?|job\s+posting\s+details?|"
    r"faculty\s+and\s+post\s+doc\s+positions?|faculty\s+and\s+staff(?:\s+jobs?)?|"
    r"faculty\s+recruitment|faculty\s+employment(?:\s+opportunities)?|"
    r"faculty\s+(?:careers?|openings?|job\s+postings?|positions?|"
    r"and\s+(?:post\s+doc|staff)|&\s*(?:post\s+doc|staff))|"
    r"(?:affiliate\s+faculty\s+jobs?|staff\s*&\s*full[- ]time\s+faculty\s+jobs?)|"
    r"(?:current\s+)?job\s+opportunities(?:\s+at\s+.+)?|"
    r"jobs\s+at\s+.+|faculty\s+and\s+staff(?:\s+career\s+opportunities)?|"
    r"university\s+system\s+of\s+.+|peoplesoft|campuses\s+and\s+schools|"
    r"boise\s+global\s+navigation|cookies\s+on\s+this\s+site|recent\s+searches|"
    r"last\s+modified\s+.+|home\s*[>/|»].*)$",
    re.I,
)
GENERIC_NAV_RE = re.compile(
    r"\b(?:faculty\s+directory|faculty\s+profile|our\s+people|faculty\s+resources?|"
    r"instructor\s+resources?|faculty\s+overview|campuses\s+and\s+schools|"
    r"meet\s+our\s+faculty|faculty\s+development|global\s+navigation|"
    r"last\s+modified|cookies\s+on\s+this\s+site)\b",
    re.I,
)
FILE_URL_RE = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|zip)(?:$|[?#])", re.I)
URL_ROLE_SLUG_RE = re.compile(
    r"\b(?:professor(?:s)?|lecturer(?:s)?|instructor(?:s)?|post[- ]?doc(?:toral)?|"
    r"dean|tenure[- ]?track)\b",
    re.I,
)


def _clean(value):
    if hasattr(value, "get_text"):
        value = value.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _safe_url(value, base_url):
    if isinstance(value, dict):
        value = value.get("@id") or value.get("url") or value.get("sameAs")
    if isinstance(value, list):
        value = value[0] if value else None
    if not value:
        return None
    url = urljoin(base_url, str(value).strip())
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return url


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _bounded_json(value, limit=50000):
    text = _json(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _jsonld_job_postings(soup):
    """Return public JobPosting JSON-LD objects, including objects in @graph."""
    records = []
    for node in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        try:
            value = json.loads(node.string or node.get_text())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        stack = list(value) if isinstance(value, list) else [value]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack[0:0] = item
                continue
            if not isinstance(item, dict):
                continue
            types = item.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(str(kind or "").casefold() == "jobposting" for kind in types):
                records.append(item)
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack[0:0] = graph
    return records


def _jsonld_location(value):
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        address = value.get("address") or {}
        if isinstance(address, dict):
            parts = [
                _clean(address.get(key))
                for key in ("addressLocality", "addressRegion", "addressCountry")
                if _clean(address.get(key))
            ]
            return ", ".join(parts) or None
    return _clean(value) or None


def _jsonld_salary(value):
    if not isinstance(value, dict):
        return _clean(value) or None
    currency = _clean(value.get("currency"))
    amount = value.get("value")
    if isinstance(amount, dict):
        low = amount.get("minValue")
        high = amount.get("maxValue")
        if low is not None and high is not None:
            amount = f"{low}-{high}"
        else:
            amount = low if low is not None else high
    unit = _clean(value.get("unitText"))
    return _clean(" ".join(str(item) for item in (currency, amount, unit) if item)) or None


def _organization_name(value):
    if isinstance(value, dict):
        return _clean(value.get("name")) or None
    return _clean(value) or None


def _page_title(soup):
    return _clean(soup.title)[:300] if soup.title else None


def _role(title, description, url):
    return classify_faculty_market_role(title, description, url)


def _job_candidate_from_json(item, page_url):
    title = _clean(item.get("title"))
    job_url = _safe_url(item.get("url") or item.get("mainEntityOfPage"), page_url)
    description = item.get("description")
    if description:
        description = visible_text(BeautifulSoup(str(description), "html.parser"))
    description = _clean(description)[:MAX_DESCRIPTION_CHARS] or None
    role = _role(title, description, job_url or page_url)
    organization = _organization_name(item.get("hiringOrganization"))
    occupational_category = _clean(item.get("occupationalCategory")) or None
    return {
        "candidate_url": job_url,
        "title": title,
        "institution": organization,
        "school": None,
        "department": occupational_category,
        "location": _jsonld_location(item.get("jobLocation")),
        "description": description,
        "posted": _clean(item.get("datePosted")) or None,
        "deadline": _clean(item.get("validThrough")) or None,
        "salary": _jsonld_salary(item.get("baseSalary")),
        "extraction_method": "jsonld_jobposting",
        "role": role.get("role"),
        "role_confidence": role.get("confidence"),
        "role_reason": role.get("reason"),
        "accepted": bool(role.get("eligible")),
        "rejection_reason": None if role.get("eligible") else role.get("reason"),
        "raw_json": item,
        "detail_status": "not_attempted",
    }


def _is_generic_title(title):
    """Identify collection/navigation labels that the role classifier alone can overread."""
    cleaned = _clean(title)
    if not cleaned:
        return True
    normalized = re.sub(r"\s+", " ", cleaned).strip(" -:|>")
    if GENERIC_TITLE_RE.search(normalized):
        return True
    if GENERIC_NAV_RE.search(normalized):
        return True
    if re.search(r"^apply\s+now\s+for\s+", normalized, re.I):
        return True
    if re.search(r"\b(?:faculty|adjunct)\s+pool\b|\binterest\s+form\b", normalized, re.I):
        return True
    if re.search(
        r"\bfaculty\b.*\b(?:administrative|staff)\b.*\b(?:positions?|jobs?)\b",
        normalized,
        re.I,
    ):
        return True
    if re.search(r"\bfaculty\s*[&/]\s*staff\b", normalized, re.I):
        return True
    if re.match(
        r"^(?:open|available|current|view|search|browse)\b.*\b(?:jobs?|positions?|"
        r"openings?|opportunities)\b",
        normalized,
        re.I,
    ):
        return True
    if re.search(r"\bprofessional\s+education\s+openings?\b", normalized, re.I):
        return True
    if re.search(
        r"\bfaculty\b.*\b(?:recruitment|employment|jobs?|careers?|openings?|"
        r"opportunities|positions?|post\s+doc|staff)\b",
        normalized,
        re.I,
    ):
        return True
    if re.fullmatch(r"(?:full[- ]?time|part[- ]?time)\s+faculty", normalized, re.I):
        return True
    if re.fullmatch(r"lecturers?\s*/\s*part[- ]?time\s+faculty", normalized, re.I):
        return True
    if re.match(r"^job\s+openings?\b", normalized, re.I):
        return True
    if re.search(
        r"(?:\b(?:faculty|professor|instructor|lecturer)s?\b.*\bapplication\b|"
        r"\bapplication\b.*\b(?:faculty|professor|instructor|lecturer)s?\b)",
        normalized,
        re.I,
    ):
        return True
    if re.fullmatch(r"(?:adjunct\s+)?faculty", normalized, re.I):
        return True
    return False


def _title_from_url(url):
    """Use a role-bearing URL slug as a fallback when a card exposes only its section heading."""
    path = unquote(urlsplit(url).path or "")
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return None
    slug = segments[-1]
    slug = re.sub(r"\.(?:html?|aspx?|php)$", "", slug, flags=re.I)
    if re.match(r"^(?:job[-_]?openings?|faculty[-_]?jobs?)(?:[-_]|$)", slug, re.I):
        # A collection URL may append a role word (for example,
        # ``job-openings-adjunct-instructor``) without being an individual
        # posting.
        return None
    if not URL_ROLE_SLUG_RE.search(slug.replace("-", " ")):
        return None
    if re.search(r"(?:details?|listing|search|apply|application|form|index|careers?)", slug, re.I):
        # A slug such as ``assistant-professor-accounting`` remains eligible;
        # an application or collection endpoint does not.
        if not URL_ROLE_SLUG_RE.search(slug.replace("-", " ")):
            return None
        if re.search(r"(?:apply|application|form|index|search|listing)", slug, re.I):
            return None
    title = re.sub(r"[-_]+", " ", slug)
    title = re.sub(r"\b(\w)", lambda match: match.group(1).upper(), title)
    return _clean(title)[:500] or None


def _has_explicit_role_signal(text):
    return bool(re.search(
        r"\b(?:professor(?:s)?|lecturer(?:s)?|instructor(?:s)?|post[- ]?doc(?:toral)?|"
        r"dean|tenure[- ]?track)\b",
        str(text or ""),
        re.I,
    ))


def _is_faculty_position_title(title):
    """Require more than the word ``faculty`` for a named link to be a role."""
    text = _clean(title).lstrip("+ ")
    if _has_explicit_role_signal(text):
        return True
    if _is_generic_title(text):
        return False
    return bool(
        re.search(r"\bfaculty\b", text, re.I)
        and re.search(
            r"\b(?:adjunct|clinical|full[- ]?time|part[- ]?time|accounting|"
            r"management|marketing|finance|business|nursing|mathematics|"
            r"science|education|communications?|arts?|humanities|school|college)\b",
            text,
            re.I,
        )
    )


def _looks_like_detail_url(url):
    """Return whether a generic card URL looks like an individual job endpoint."""
    parts = urlsplit(url or "")
    path = unquote(parts.path or "")
    segments = [segment for segment in path.split("/") if segment]
    for index, segment in enumerate(segments[:-1]):
        if not re.fullmatch(r"(?:jobs?|positions?|postings?|vacanc(?:y|ies)|openings?)", segment, re.I):
            continue
        tail = segments[index + 1]
        if URL_ROLE_SLUG_RE.search(" ".join(segments[index + 1:])):
            return True
        if re.fullmatch(r"\d{3,}", tail):
            return True
        if re.fullmatch(r"(?:details?|detail)", tail, re.I) and len(segments) > index + 2:
            return True
    if re.search(r"/(?:jobofferdetails|job[-_]?details|jobposting|jobdetail)\.(?:php|aspx?|jsp)", path, re.I):
        return bool(parts.query)
    if re.search(r"/(?:posting|position|vacancy|opening)[^/]*\.(?:php|aspx?|jsp)", path, re.I):
        return bool(parts.query)
    if re.search(r"/recruiting/jobs/(?:details?)/", path, re.I):
        return True
    return False


def _same_document_url(left, right):
    """Compare public documents while ignoring a client-side fragment."""
    first = urlsplit(left or "")
    second = urlsplit(right or "")
    return (
        first.scheme.casefold(), first.netloc.casefold(), first.path.rstrip("/")
    ) == (
        second.scheme.casefold(), second.netloc.casefold(), second.path.rstrip("/")
    ) and first.query == second.query


def _looks_like_job_link(label, href, title):
    text = f"{label or ''} {title or ''} {href or ''}"
    if STUDENT_OR_INFO_RE.search(text):
        return False
    if (_is_generic_title(title)
            and not _title_from_url(href or "")
            and not _looks_like_detail_url(href or "")):
        return False
    # A path under ``/employment/`` or ``/careers/`` is not sufficient by
    # itself: universities also use those paths for EEO pages, directories,
    # benefits, and collection-level recruiting information.  Require either
    # a role-bearing title or an endpoint shape that looks like one job.
    if JOB_URL_RE.search(href or "") and (
        _has_explicit_role_signal(title)
        or _is_faculty_position_title(title)
        or _looks_like_detail_url(href or "")
    ):
        return True
    if _is_faculty_position_title(title) and (
        JOB_PAGE_SIGNAL_RE.search(text) or re.search(r"\b(?:apply|application)\b", text, re.I)
    ):
        return True
    if _is_faculty_position_title(title) and GENERIC_LINK_RE.search(label or ""):
        return True
    return False


def _link_title_and_context(link):
    label = _clean(link)
    container = link.find_parent(["article", "li", "tr", "section", "div"])
    heading = container.find(["h1", "h2", "h3", "h4", "h5"]) if container else None
    heading_text = _clean(heading) if heading else ""
    # Prefer a role-bearing anchor over a generic section heading.  Pages such
    # as job-detail lists often wrap ``Assistant Professor ...`` in a card
    # whose nearest heading is only ``Job Posting Details``.
    if _has_explicit_role_signal(label) or _is_faculty_position_title(label):
        title = label
    elif heading_text and (_has_explicit_role_signal(heading_text) or _is_faculty_position_title(heading_text)):
        title = heading_text
    else:
        title = label or heading_text or _clean(link.get("aria-label"))
    context_node = container or link.parent or link
    context = detail_excerpt(context_node, max_chars=MAX_DESCRIPTION_CHARS) or None
    return title, context, label


def _job_candidate_from_link(link, page_url):
    href = _safe_url(link.get("href"), page_url)
    if not href or href.rstrip("/") == page_url.rstrip("/"):
        return None
    title, context, label = _link_title_and_context(link)
    generic_title = _is_generic_title(title)
    slug_title = _title_from_url(href)
    if slug_title and (generic_title or not FACULTY_SIGNAL_RE.search(title)):
        title = slug_title
    if not title or not _looks_like_job_link(label, href, title):
        return None
    # Do not use the surrounding page/card text to classify a named link: a
    # faculty employment page often contains unrelated staff, student, and
    # navigation language in the same container.  The title/URL is the
    # posting-level evidence; the context is retained only as an excerpt.
    role = _role(title, None, href)
    needs_detail = bool(generic_title and not slug_title)
    if needs_detail:
        # A job-detail endpoint may expose the real title only after it is
        # fetched (for example ``job-details.php?id=...``).  Keep it as
        # auditable pending evidence, but do not promote it from a generic
        # collection label without detail-page validation.
        role = {
            "eligible": 0,
            "role": "unknown",
            "confidence": "low",
            "reason": "Generic card title requires detail-page validation.",
        }
    return {
        "candidate_url": href,
        "title": title[:500],
        "institution": None,
        "school": None,
        "department": None,
        "location": None,
        "description": context,
        "posted": None,
        "deadline": None,
        "salary": None,
        "extraction_method": "explicit_job_link_url_title" if slug_title else "explicit_job_link",
        "role": role.get("role"),
        "role_confidence": role.get("confidence"),
        "role_reason": role.get("reason"),
        "accepted": bool(role.get("eligible")),
        "needs_detail": needs_detail,
        "rejection_reason": None if role.get("eligible") else role.get("reason"),
        "raw_json": {"anchor_text": label, "href": href, "context": context},
        "detail_status": "not_attempted",
    }


def _candidate_key(candidate):
    candidate_url = candidate.get("candidate_url") or ""
    if candidate_url:
        # The same posting commonly appears once as JSON-LD and once as an
        # anchor card, with slightly different visible titles.  The public
        # detail URL is the stronger identity signal in that case.
        return (candidate_url, "")
    return ("", re.sub(r"\s+", " ", str(candidate.get("title") or "")).casefold())


def parse_portal_html(html, page_url, *, max_jobs=40, prioritize_business=False):
    """Parse one readable portal page without treating page volume as coverage."""
    soup = BeautifulSoup(html or "", "html.parser")
    json_jobs = _jsonld_job_postings(soup)
    candidates = []
    seen = set()
    for item in json_jobs:
        candidate = _job_candidate_from_json(item, page_url)
        key = _candidate_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)

    link_candidates_seen = 0
    links_truncated = False
    for link in soup.find_all("a", href=True):
        if link_candidates_seen >= MAX_CANDIDATE_EVIDENCE:
            links_truncated = True
            break
        candidate = _job_candidate_from_link(link, page_url)
        if candidate is None:
            continue
        link_candidates_seen += 1
        key = _candidate_key(candidate)
        if key in seen:
            # Prefer JSON-LD because it carries structured field evidence.
            continue
        seen.add(key)
        candidates.append(candidate)

    accepted = [candidate for candidate in candidates if candidate.get("accepted")]
    needs_detail = [candidate for candidate in candidates if candidate.get("needs_detail")]
    if prioritize_business:
        # Apply the user's market preference before spending the bounded job
        # and detail budgets. Never use adjacent card text as field evidence.
        # Stable sorting preserves page order within a priority group, and the
        # complete bounded candidate list remains in its original audit order.
        for candidate in accepted:
            scope = classify_business_scope(title=candidate.get("title"))["scope"]
            candidate["selection_priority"] = (
                "business_title" if scope in {"business_school", "business_discipline"}
                else "other_title"
            )
        accepted.sort(key=lambda item: item["selection_priority"] != "business_title")
        needs_detail.sort(key=lambda item: classify_business_scope(title=item.get("title"))["scope"] not in {"business_school", "business_discipline"})
    job_budget = max(1, min(200, int(max_jobs)))
    job_budget_truncated = len(accepted) > job_budget
    accepted = accepted[:job_budget]
    text = visible_text(soup)
    signals = []
    if json_jobs:
        signals.append("jobposting_jsonld")
    if FACULTY_SIGNAL_RE.search(text):
        signals.append("faculty_language")
    if JOB_PAGE_SIGNAL_RE.search(text):
        signals.append("recruitment_language")
    return {
        "page_title": _page_title(soup),
        "candidates": candidates[:MAX_CANDIDATE_EVIDENCE],
        "candidates_seen": len(candidates),
        "accepted": accepted,
        "needs_detail": needs_detail,
        "rejected": sum(1 for candidate in candidates if not candidate.get("accepted")),
        "jobposting_jsonld": len(json_jobs),
        "candidate_truncated": bool(links_truncated or len(candidates) > MAX_CANDIDATE_EVIDENCE),
        "job_budget_truncated": job_budget_truncated,
        "page_signals": signals,
    }


def _extract_role_title(text):
    """Extract a bounded explicit role title from a generic detail-page wrapper."""
    text = _clean(text)
    patterns = (
        r"\b(?:position|job\s+title|title)\s*:?\s*"
        r"((?:(?:assistant|associate|full|clinical|visiting|adjunct|teaching|research)\s+){0,3}"
        r"(?:professor(?:s)?|lecturer(?:s)?|instructor(?:s)?|post[- ]?doc(?:toral)?|"
        r"dean|tenure[- ]?track)[^.;|]{0,120})",
        r"\b((?:(?:assistant|associate|full|clinical|visiting|adjunct|teaching|research)\s+){0,3}"
        r"(?:professor(?:s)?|lecturer(?:s)?|instructor(?:s)?|post[- ]?doc(?:toral)?|"
        r"dean|tenure[- ]?track)(?:[^.;|]{0,100}))",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        value = _clean(match.group(1))
        value = re.split(
            r"\b(?:department|responsibilities|requirements|starting\s+date|"
            r"job\s+description|position\s+summary|apply\s+now|location)\b",
            value,
            maxsplit=1,
            flags=re.I,
        )[0]
        if _has_explicit_role_signal(value):
            return value.strip(" -:;,.")[:500]
    return None


def _detail_json_candidate(html, page_url, fallback):
    soup = BeautifulSoup(html or "", "html.parser")
    json_jobs = _jsonld_job_postings(soup)
    chosen = None
    fallback_title = str(fallback.get("title") or "").casefold()
    for item in json_jobs:
        if _clean(item.get("title")).casefold() == fallback_title:
            chosen = item
            break
    chosen = chosen or (json_jobs[0] if json_jobs else None)
    if chosen:
        result = _job_candidate_from_json(chosen, page_url)
        result["detail_jsonld"] = True
        result["raw_json"] = {
            **(result.get("raw_json") or {}),
            "detail_jsonld_count": len(json_jobs),
            "identity_matches": bool(
                fallback_title and _clean(chosen.get("title")).casefold() == fallback_title
            ),
        }
        return result
    main = soup.select_one("main, article, [role='main']") or soup.body or soup
    text = visible_text(main)[:MAX_DESCRIPTION_CHARS] or None
    heading = _clean(soup.select_one("h1, h2"))
    # Site headers frequently appear before the actual posting title.  Treat a
    # heading as a detail title only when it independently names a faculty
    # market role; otherwise fall back to a labeled title in the body or the
    # already-observed card title.
    title = heading if heading and (
        _has_explicit_role_signal(heading) or _is_faculty_position_title(heading)
    ) else None
    if not title and fallback.get("needs_detail"):
        title = _extract_role_title(text)
    title = title or fallback.get("title")
    role = _role(title, text if _has_explicit_role_signal(title) else None, page_url)
    if not _has_explicit_role_signal(title):
        role = {
            "eligible": 0,
            "role": "unknown",
            "confidence": "low",
            "reason": "Detail page did not expose an explicit individual faculty-market title.",
        }
    return {
        "candidate_url": page_url,
        "title": title,
        "institution": None,
        "school": None,
        "department": None,
        "location": None,
        "description": text,
        "posted": None,
        "deadline": None,
        "salary": None,
        "extraction_method": "detail_page_text",
        "role": role.get("role"),
        "role_confidence": role.get("confidence"),
        "role_reason": role.get("reason"),
        "accepted": bool(role.get("eligible")),
        "rejection_reason": None if role.get("eligible") else role.get("reason"),
        "raw_json": {
            "detail_jsonld_count": 0,
            "explicit_role_heading": bool(
                heading and _has_explicit_role_signal(heading)
                and _clean(heading).casefold() == _clean(title).casefold()
            ),
        },
        "detail_jsonld": False,
    }


def _merge_detail(candidate, detail):
    merged = dict(candidate)
    for field in (
        "title", "institution", "school", "department", "location", "description",
        "posted", "deadline", "salary",
    ):
        if not detail.get(field):
            continue
        if field == "title" and (
            _is_generic_title(detail.get(field))
            or not (
                _has_explicit_role_signal(detail.get(field))
                or _is_faculty_position_title(detail.get(field))
            )
        ):
            # Do not replace a useful card title with a site/department
            # heading such as ``Bluffton University``.
            continue
        if detail.get(field):
            merged[field] = detail[field]
    merged["detail_status"] = "ok"
    merged["detail_role"] = detail.get("role")
    merged["detail_role_confidence"] = detail.get("role_confidence")
    merged["detail_role_reason"] = detail.get("role_reason")
    merged["detail_raw_json"] = detail.get("raw_json")
    merged["detail_accepted"] = bool(detail.get("accepted"))
    return merged


def _exception_status(error):
    message = str(error)[:500] or error.__class__.__name__
    if isinstance(error, CrawlBudgetExhaustedError):
        return "crawl_budget_exhausted", message
    if isinstance(error, RobotsDisallowedError):
        return "robots_disallowed", message
    if isinstance(error, NonRetryableAdapterError) and re.search(r"HTTP\s+(?:403|429)", message, re.I):
        return "blocked", message
    if re.search(r"HTTP\s+(?:403|429)|access\s+denied|captcha|challenge", message, re.I):
        return "blocked", message
    return "error", message


def _norm_name(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def resolve_target(candidate, target_rows):
    """Resolve only explicit organization matches or a one-target portal group."""
    linked = [dict(row) for row in target_rows]
    organization = _norm_name(candidate.get("institution"))
    exact = [row for row in linked if organization and _norm_name(row.get("institution_name")) == organization]
    if len(exact) == 1:
        return {
            "target_unitid": exact[0].get("unitid"),
            "target_match_status": "organization_exact",
            "target_unitids": [row.get("unitid") for row in linked],
        }
    if len(linked) == 1:
        return {
            "target_unitid": linked[0].get("unitid"),
            "target_match_status": "single_registry_target",
            "target_unitids": [linked[0].get("unitid")],
        }
    return {
        "target_unitid": None,
        "target_match_status": "shared_group_unresolved" if linked else "no_registry_target",
        "target_unitids": [row.get("unitid") for row in linked],
    }


@dataclass
class PortalScanResult:
    page_status: str
    scan_status: str
    portal_url: str
    final_url: str | None = None
    http_status: int | None = None
    page_title: str | None = None
    candidates_seen: int = 0
    accepted_jobs: list[dict] | None = None
    candidates: list[dict] | None = None
    rejected_candidates: int = 0
    pages_fetched: int = 0
    request_attempts: int = 0
    detail_attempts: int = 0
    detail_failures: int = 0
    complete: bool = False
    budget_truncated: bool = False
    reason: str | None = None
    evidence: dict | None = None


class CarnegieVacancyScanner(SourceAdapter):
    """Robots-aware, low-frequency scanner for already observed portal pages."""

    name = "carnegie_official_vacancy_scan"
    adapter_name = "carnegie_official_vacancy_scan"
    region = "United States"
    priority = 35
    max_items = 1000

    def __init__(self, timeout=20, delay=0.75, session=None):
        super().__init__(timeout=max(3, int(timeout)), max_pages=1, max_items=1000, session=session)
        self.delay = max(0.0, min(10.0, float(delay)))

    def _pause(self):
        if self.delay:
            import time
            time.sleep(self.delay)

    def _fetch(self, url):
        try:
            return self.request(url)
        finally:
            self._pause()

    def scan_portal(self, portal_row, target_rows, *, max_detail_pages=2, max_jobs=40,
                    prioritize_business=False):
        portal_url = portal_row["canonical_url"]
        try:
            response = self._fetch(portal_url)
        except Exception as error:
            status, reason = _exception_status(error)
            return PortalScanResult(
                page_status=status, scan_status=status, portal_url=portal_url,
                candidates=[], accepted_jobs=[], request_attempts=1, reason=reason,
            )

        final_url = getattr(response, "url", None) or portal_url
        soup = BeautifulSoup(response.text or "", "html.parser")
        text = visible_text(BeautifulSoup(response.text or "", "html.parser"))
        title = _page_title(soup)
        if BLOCKED_PAGE_RE.search(text[:6000]):
            return PortalScanResult(
                page_status="blocked", scan_status="blocked", portal_url=portal_url,
                final_url=final_url, http_status=getattr(response, "status_code", None),
                page_title=title, pages_fetched=1, request_attempts=1,
                reason="Public portal page returned a bot/access challenge.",
            )

        parsed = parse_portal_html(response.text, final_url, max_jobs=max_jobs,
                                   prioritize_business=prioritize_business)
        accepted = list(parsed["accepted"])
        detail_attempts = 0
        detail_failures = 0
        detail_budget = max(0, min(20, int(max_detail_pages)))
        detail_candidates = list(accepted)
        for candidate in parsed.get("needs_detail", []):
            if candidate not in detail_candidates:
                detail_candidates.append(candidate)
        for candidate in detail_candidates:
            if detail_attempts >= detail_budget:
                break
            candidate_url = candidate.get("candidate_url")
            if not candidate_url or _same_document_url(candidate_url, final_url):
                continue
            # Structured records with a substantial description already carry
            # enough listing evidence for the first pass; use the detail budget
            # for explicit links or sparse JSON-LD records.
            if (candidate.get("extraction_method") == "jsonld_jobposting"
                    and len(candidate.get("description") or "") >= 500):
                continue
            if FILE_URL_RE.search(candidate_url):
                candidate["detail_status"] = "not_attempted_file"
                continue
            detail_attempts += 1
            try:
                detail_response = self._fetch(candidate_url)
                detail_text = visible_text(BeautifulSoup(detail_response.text or "", "html.parser"))
                if BLOCKED_PAGE_RE.search(detail_text[:6000]):
                    raise RuntimeError("Detail page returned a bot/access challenge.")
                detail = _detail_json_candidate(detail_response.text, getattr(detail_response, "url", None) or candidate_url, candidate)
                merged = _merge_detail(candidate, detail)
                candidate.update(merged)
                if candidate.get("needs_detail") and detail.get("accepted"):
                    candidate["accepted"] = True
                    candidate["extraction_method"] = "explicit_job_link_detail_validated"
                    accepted.append(candidate)
            except Exception as error:
                detail_failures += 1
                candidate["detail_status"] = _exception_status(error)[0]
                candidate["detail_error"] = _exception_status(error)[1]

        # JSON-LD and an anchor card can still expose the same URL with
        # different titles after detail enrichment.  Keep one accepted record
        # per public URL/title identity before assigning source ids.
        unique_accepted = {}
        for candidate in accepted:
            unique_accepted[_candidate_key(candidate)] = candidate
        accepted = list(unique_accepted.values())[:max(1, min(200, int(max_jobs)))]

        for candidate in accepted:
            target = resolve_target(candidate, target_rows)
            candidate.update(target)
            candidate["source_url"] = final_url
            candidate["official_url"] = candidate.get("candidate_url") or final_url
            candidate["source_job_id"] = hashlib.sha256(
                f"{portal_row['website_group_key']}|{portal_row['canonical_url']}|"
                f"{candidate.get('candidate_url') or candidate.get('title')}".encode("utf-8")
            ).hexdigest()[:32]

        if accepted:
            scan_status = "jobs_found_partial" if detail_failures or parsed["candidate_truncated"] or parsed["job_budget_truncated"] else "jobs_found"
            reason = (
                f"Observed {len(accepted)} eligible faculty-market candidate(s) on the public portal page; "
                f"rejected {parsed['rejected']} candidate(s). This is page evidence, not a complete market denominator."
            )
        elif parsed["candidates_seen"]:
            scan_status = "no_eligible_faculty_jobs"
            reason = (
                "The public portal page was readable and exposed job-like evidence, but no individual "
                "faculty-market role passed the conservative classifier. Rejected candidates remain auditable."
            )
        else:
            scan_status = "no_faculty_jobs_observed"
            reason = (
                "The public portal page was readable, but no individual faculty-market candidate was "
                "observed in the bounded HTML/JSON-LD scan; this does not prove that the institution has no vacancy."
            )
        complete = bool(
            not detail_failures
            and not parsed["candidate_truncated"]
            and not parsed["job_budget_truncated"]
        )
        return PortalScanResult(
            page_status="ok", scan_status=scan_status, portal_url=portal_url,
            final_url=final_url, http_status=getattr(response, "status_code", None),
            page_title=title, candidates_seen=parsed["candidates_seen"],
            accepted_jobs=accepted, candidates=parsed["candidates"],
            rejected_candidates=parsed["rejected"], pages_fetched=1 + detail_attempts,
            request_attempts=1 + detail_attempts, detail_attempts=detail_attempts,
            detail_failures=detail_failures, complete=complete,
            budget_truncated=bool(parsed["candidate_truncated"] or parsed["job_budget_truncated"]),
            reason=reason,
            evidence={
                "jobposting_jsonld": parsed["jobposting_jsonld"],
                "page_signals": parsed["page_signals"],
                "candidate_truncated": parsed["candidate_truncated"],
                "job_budget_truncated": parsed["job_budget_truncated"],
                "detail_budget": detail_budget,
                "prioritize_business": bool(prioritize_business),
                "target_count": len(target_rows),
            },
        )


def portal_selection(row):
    """Return a deterministic selection decision for vacancy scanning."""
    kind = str(row.get("portal_kind") or "")
    combined = " ".join(
        str(row.get(key) or "")
        for key in ("latest_title", "canonical_url", "discovery_evidence")
    )
    if row.get("latest_page_status") != "ok":
        return {"selected": False, "score": 0, "reason": "Portal page was not readable in the registry observation."}
    if STUDENT_OR_INFO_RE.search(combined):
        return {"selected": False, "score": 0, "reason": "Student-facing, directory, or career-information page signal."}
    if LOGIN_OR_SYSTEM_RE.search(str(row.get("canonical_url") or "")) and kind == "external_ats":
        return {"selected": False, "score": 0, "reason": "Login/SSO/system landing page rather than a public vacancy listing."}

    score = {"faculty_recruitment": 100, "external_ats": 92, "central_recruitment": 68, "hr_recruitment": 58}.get(kind, 30)
    if FACULTY_SIGNAL_RE.search(combined):
        score += 30
    if JOB_PAGE_SIGNAL_RE.search(combined):
        score += 18
    if row.get("latest_jobposting_jsonld"):
        score += 40
    if JOB_URL_RE.search(str(row.get("canonical_url") or "")):
        score += 12

    if kind == "faculty_recruitment" and not FACULTY_SIGNAL_RE.search(combined):
        return {"selected": False, "score": score, "reason": "Faculty-recruitment classification lacked a current faculty/academic signal."}
    if kind == "faculty_recruitment" and not (JOB_PAGE_SIGNAL_RE.search(combined) or row.get("latest_jobposting_jsonld")):
        return {"selected": False, "score": score, "reason": "Faculty/instructor page lacked an employment, position, or vacancy signal."}
    if kind == "hr_recruitment" and not JOB_PAGE_SIGNAL_RE.search(combined) and not row.get("latest_jobposting_jsonld"):
        return {"selected": False, "score": score, "reason": "Generic HR information page without a job/position signal."}
    if kind == "central_recruitment" and not (FACULTY_SIGNAL_RE.search(combined) or JOB_PAGE_SIGNAL_RE.search(combined) or row.get("latest_jobposting_jsonld")):
        return {"selected": False, "score": score, "reason": "Central page lacked a recruitment or faculty signal."}
    return {"selected": True, "score": score, "reason": "Readable public recruitment entry selected by rule."}


def _read_only_registry(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Carnegie registry database does not exist: {path}")
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def _load_portals(registry_db):
    conn = _read_only_registry(registry_db)
    try:
        portal_rows = [dict(row) for row in conn.execute(
            """SELECT p.* FROM institution_recruitment_portals AS p
               WHERE p.active=1 ORDER BY p.website_group_key,p.canonical_url"""
        )]
        targets_by_group = {}
        for row in conn.execute(
            """SELECT website_group_key,unitid,institution_name,target_segment
               FROM institution_recruitment_targets
               ORDER BY website_group_key,institution_name,unitid"""
        ):
            targets_by_group.setdefault(row["website_group_key"], []).append(dict(row))
        return portal_rows, targets_by_group
    finally:
        conn.close()


def select_portals(registry_db=None, *, max_portals=100, offset=0, include_low_signal=False, portal_urls=None):
    """Select a deterministic, high-signal portal batch without making requests."""
    portal_rows, targets_by_group = _load_portals(registry_db or DEFAULT_REGISTRY_DB)
    decisions = []
    for row in portal_rows:
        decision = portal_selection(row)
        decisions.append({
            **row,
            **decision,
            "target_rows": targets_by_group.get(row["website_group_key"], []),
        })
    eligible = [row for row in decisions if row["selected"] or include_low_signal]
    eligible.sort(key=lambda row: (-int(row["score"]), row["website_group_key"], row["canonical_url"]))
    if portal_urls is not None:
        allowed = set(portal_urls)
        eligible = [row for row in eligible if row["canonical_url"] in allowed]
    bounded = max(1, min(1000, int(max_portals)))
    start = max(0, int(offset))
    selected = eligible[start:start + bounded]
    selection_counts = Counter(
        row["reason"] for row in decisions if not row["selected"]
    )
    return {
        "all_portals": decisions,
        "selected": selected,
        "eligible_count": len(eligible),
        "selected_count": len(selected),
        "offset": start,
        "max_portals": bounded,
        "selection_rule_version": VACANCY_SCAN_RULE_VERSION,
        "excluded_by_reason": dict(selection_counts),
        "by_kind": dict(Counter(row["portal_kind"] for row in eligible)),
        "target_institutions": len({row["unitid"] for row in selected for row in row["target_rows"]}),
    }


def connect_scan_db(scan_db=None):
    path = Path(scan_db or DEFAULT_SCAN_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_scan_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS scan_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            note TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            input_registry_db TEXT NOT NULL,
            input_registry_sha256 TEXT,
            selection_rule_version TEXT NOT NULL,
            vacancy_rule_version TEXT NOT NULL,
            requested_portals INTEGER NOT NULL DEFAULT 0,
            processed_portals INTEGER NOT NULL DEFAULT 0,
            request_attempts INTEGER NOT NULL DEFAULT 0,
            jobs_found INTEGER NOT NULL DEFAULT 0,
            selection_counts_json TEXT NOT NULL DEFAULT '{}',
            result_counts_json TEXT NOT NULL DEFAULT '{}',
            error TEXT
        );
        CREATE TABLE IF NOT EXISTS portal_selections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            registry_portal_id INTEGER,
            website_group_key TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            portal_kind TEXT NOT NULL,
            latest_page_status TEXT NOT NULL,
            latest_title TEXT,
            selection_score INTEGER NOT NULL,
            selected INTEGER NOT NULL,
            selection_reason TEXT NOT NULL,
            target_unitids_json TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY (run_id) REFERENCES scan_runs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_carnegie_vac_selection_run
            ON portal_selections(run_id, selected, selection_score);
        CREATE TABLE IF NOT EXISTS portal_inputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            selection_id INTEGER NOT NULL,
            registry_portal_id INTEGER,
            website_group_key TEXT NOT NULL,
            portal_url TEXT NOT NULL,
            portal_kind TEXT NOT NULL,
            target_unitids_json TEXT NOT NULL DEFAULT '[]',
            target_names_json TEXT NOT NULL DEFAULT '[]',
            target_segments_json TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY (run_id) REFERENCES scan_runs(id),
            FOREIGN KEY (selection_id) REFERENCES portal_selections(id)
        );
        CREATE TABLE IF NOT EXISTS vacancy_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            portal_input_id INTEGER NOT NULL,
            checked_at TEXT NOT NULL,
            portal_url TEXT NOT NULL,
            final_url TEXT,
            http_status INTEGER,
            page_status TEXT NOT NULL,
            scan_status TEXT NOT NULL,
            page_title TEXT,
            candidates_seen INTEGER NOT NULL DEFAULT 0,
            accepted_jobs INTEGER NOT NULL DEFAULT 0,
            rejected_candidates INTEGER NOT NULL DEFAULT 0,
            pages_fetched INTEGER NOT NULL DEFAULT 0,
            request_attempts INTEGER NOT NULL DEFAULT 0,
            detail_attempts INTEGER NOT NULL DEFAULT 0,
            detail_failures INTEGER NOT NULL DEFAULT 0,
            complete INTEGER NOT NULL DEFAULT 0,
            budget_truncated INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            rule_version TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES scan_runs(id),
            FOREIGN KEY (portal_input_id) REFERENCES portal_inputs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_carnegie_vac_observations_run
            ON vacancy_observations(run_id, scan_status);
        CREATE TABLE IF NOT EXISTS vacancy_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_id INTEGER NOT NULL,
            candidate_url TEXT,
            title TEXT,
            extraction_method TEXT NOT NULL,
            accepted INTEGER NOT NULL,
            rejection_reason TEXT,
            role TEXT,
            role_confidence TEXT,
            role_reason TEXT,
            description_excerpt TEXT,
            candidate_json TEXT NOT NULL DEFAULT '{}',
            captured_at TEXT NOT NULL,
            FOREIGN KEY (observation_id) REFERENCES vacancy_observations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_carnegie_vac_candidates_observation
            ON vacancy_candidates(observation_id, accepted);
        CREATE TABLE IF NOT EXISTS vacancy_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_id INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            source_job_id TEXT NOT NULL,
            website_group_key TEXT NOT NULL,
            portal_kind TEXT NOT NULL,
            source_url TEXT NOT NULL,
            official_url TEXT,
            title_raw TEXT NOT NULL,
            institution_raw TEXT,
            target_unitid INTEGER,
            target_match_status TEXT NOT NULL,
            target_unitids_json TEXT NOT NULL DEFAULT '[]',
            department_raw TEXT,
            location_raw TEXT,
            description_excerpt TEXT,
            posted_date_raw TEXT,
            deadline_raw TEXT,
            salary_raw TEXT,
            faculty_role TEXT,
            role_confidence TEXT,
            extraction_method TEXT NOT NULL,
            detail_status TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(observation_id, source_job_id),
            FOREIGN KEY (observation_id) REFERENCES vacancy_observations(id),
            FOREIGN KEY (candidate_id) REFERENCES vacancy_candidates(id)
        );
        CREATE INDEX IF NOT EXISTS idx_carnegie_vac_records_run
            ON vacancy_records(observation_id, target_match_status);
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO scan_migrations(version, applied_at, note) VALUES (?,?,?)",
        (
            SCAN_SCHEMA_VERSION,
            now_utc(),
            "Isolated Carnegie 2025 public vacancy observations; no production faculty_jobs writes.",
        ),
    )
    conn.commit()


def _file_sha256(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _insert_candidate(conn, observation_id, candidate):
    cursor = conn.execute(
        """INSERT INTO vacancy_candidates
           (observation_id,candidate_url,title,extraction_method,accepted,
            rejection_reason,role,role_confidence,role_reason,description_excerpt,
            candidate_json,captured_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            observation_id, candidate.get("candidate_url"), candidate.get("title"),
            candidate.get("extraction_method") or "unknown", int(bool(candidate.get("accepted"))),
            candidate.get("rejection_reason"), candidate.get("role"),
            candidate.get("role_confidence"), candidate.get("role_reason"),
            candidate.get("description"), _bounded_json(candidate), now_utc(),
        ),
    )
    return cursor.lastrowid


def _insert_record(conn, observation_id, candidate_id, portal_row, candidate):
    conn.execute(
        """INSERT INTO vacancy_records
           (observation_id,candidate_id,source_job_id,website_group_key,portal_kind,
            source_url,official_url,title_raw,institution_raw,target_unitid,
            target_match_status,target_unitids_json,department_raw,location_raw,
            description_excerpt,posted_date_raw,deadline_raw,salary_raw,faculty_role,
            role_confidence,extraction_method,detail_status,captured_at,raw_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            observation_id, candidate_id, candidate["source_job_id"],
            portal_row["website_group_key"], portal_row["portal_kind"],
            candidate.get("source_url") or portal_row["canonical_url"],
            candidate.get("official_url"), candidate.get("title") or "",
            candidate.get("institution"), candidate.get("target_unitid"),
            candidate.get("target_match_status") or "unknown",
            _json(candidate.get("target_unitids") or []), candidate.get("department"),
            candidate.get("location"), candidate.get("description"),
            candidate.get("posted"), candidate.get("deadline"), candidate.get("salary"),
            candidate.get("role"), candidate.get("role_confidence"),
            candidate.get("extraction_method") or "unknown",
            candidate.get("detail_status") or "not_attempted", now_utc(),
            _bounded_json(candidate),
        ),
    )


def scan_vacancies(registry_db=None, scan_db=None, *, max_portals=100, offset=0,
                   include_low_signal=False, timeout=20, delay=0.75,
                   max_detail_pages=2, max_jobs=40, progress=None,
                   prioritize_business=False, portal_urls=None):
    """Run one bounded, auditable public vacancy scan into an isolated DB."""
    registry_path = Path(registry_db or DEFAULT_REGISTRY_DB)
    scan_path = Path(scan_db or DEFAULT_SCAN_DB)
    selection = select_portals(
        registry_path, max_portals=max_portals, offset=offset,
        include_low_signal=include_low_signal,
        portal_urls=portal_urls,
    )
    conn = connect_scan_db(scan_path)
    ensure_scan_schema(conn)
    run_id = conn.execute(
        """INSERT INTO scan_runs
           (started_at,status,input_registry_db,input_registry_sha256,
            selection_rule_version,vacancy_rule_version,requested_portals,
            selection_counts_json)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            now_utc(), "running", str(registry_path), _file_sha256(registry_path),
            VACANCY_SCAN_RULE_VERSION, VACANCY_SCAN_RULE_VERSION,
            selection["selected_count"], _json({
                "all_portals": len(selection["all_portals"]),
                "eligible_count": selection["eligible_count"],
                "excluded_by_reason": selection["excluded_by_reason"],
                "by_kind": selection["by_kind"],
                "offset": selection["offset"],
                "max_portals": selection["max_portals"],
                "prioritize_business": bool(prioritize_business),
            }),
        ),
    ).lastrowid
    conn.commit()

    selection_ids = {}
    selected_keys = {
        (row["website_group_key"], row["canonical_url"])
        for row in selection["selected"]
    }
    processed = request_attempts = jobs_found = 0
    counts = Counter()
    try:
        with conn:
            for row in selection["all_portals"]:
                cursor = conn.execute(
                    """INSERT INTO portal_selections
                       (run_id,registry_portal_id,website_group_key,canonical_url,
                        portal_kind,latest_page_status,latest_title,selection_score,
                        selected,selection_reason,target_unitids_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id, row.get("id"), row["website_group_key"], row["canonical_url"],
                        row["portal_kind"], row.get("latest_page_status") or "unknown",
                        row.get("latest_title"), int(row["score"]),
                        int((row["website_group_key"], row["canonical_url"]) in selected_keys),
                        row["reason"],
                        _json([target.get("unitid") for target in row["target_rows"]]),
                    ),
                )
                selection_ids[(row["website_group_key"], row["canonical_url"])] = cursor.lastrowid
        reset_robots_cache()
        reset_crawl_budgets()
        scanner = CarnegieVacancyScanner(timeout=timeout, delay=delay)
        selected_rows = selection["selected"]
        for index, row in enumerate(selected_rows, start=1):
            selection_id = selection_ids[(row["website_group_key"], row["canonical_url"])]
            target_rows = row["target_rows"]
            with conn:
                cursor = conn.execute(
                    """INSERT INTO portal_inputs
                       (run_id,selection_id,registry_portal_id,website_group_key,
                        portal_url,portal_kind,target_unitids_json,target_names_json,
                        target_segments_json)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id, selection_id, row.get("id"), row["website_group_key"],
                        row["canonical_url"], row["portal_kind"],
                        _json([target.get("unitid") for target in target_rows]),
                        _json([target.get("institution_name") for target in target_rows]),
                        _json([target.get("target_segment") for target in target_rows]),
                    ),
                )
                portal_input_id = cursor.lastrowid
            try:
                result = scanner.scan_portal(
                    row, target_rows, max_detail_pages=max_detail_pages, max_jobs=max_jobs,
                    prioritize_business=prioritize_business,
                )
            except Exception as error:
                status, reason = _exception_status(error)
                result = PortalScanResult(
                    page_status=status, scan_status=status, portal_url=row["canonical_url"],
                    candidates=[], accepted_jobs=[], request_attempts=1, reason=reason,
                )
            checked_at = now_utc()
            with conn:
                cursor = conn.execute(
                    """INSERT INTO vacancy_observations
                       (run_id,portal_input_id,checked_at,portal_url,final_url,http_status,
                        page_status,scan_status,page_title,candidates_seen,accepted_jobs,
                        rejected_candidates,pages_fetched,request_attempts,detail_attempts,
                        detail_failures,complete,budget_truncated,reason,evidence_json,rule_version)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id, portal_input_id, checked_at, result.portal_url, result.final_url,
                        result.http_status, result.page_status, result.scan_status,
                        result.page_title, result.candidates_seen, len(result.accepted_jobs or []),
                        result.rejected_candidates, result.pages_fetched, result.request_attempts,
                        result.detail_attempts, result.detail_failures, int(result.complete),
                        int(result.budget_truncated), result.reason, _json(result.evidence or {}),
                        VACANCY_SCAN_RULE_VERSION,
                    ),
                )
                observation_id = cursor.lastrowid
                candidate_ids = {}
                for candidate in result.candidates or []:
                    candidate_ids[_candidate_key(candidate)] = _insert_candidate(
                        conn, observation_id, candidate
                    )
                for candidate in result.accepted_jobs or []:
                    candidate_id = candidate_ids.get(_candidate_key(candidate))
                    if candidate_id is None:
                        candidate_id = _insert_candidate(conn, observation_id, candidate)
                    _insert_record(conn, observation_id, candidate_id, row, candidate)
            processed += 1
            request_attempts += result.request_attempts
            jobs_found += len(result.accepted_jobs or [])
            counts[result.scan_status] += 1
            if progress:
                progress({
                    "index": index, "total": len(selected_rows),
                    "website_group_key": row["website_group_key"],
                    "portal_kind": row["portal_kind"], "url": row["canonical_url"],
                    "status": result.scan_status, "jobs_found": len(result.accepted_jobs or []),
                    "requests": result.request_attempts,
                })
        result_summary = {
            "requested": len(selected_rows), "processed": processed,
            "request_attempts": request_attempts, "jobs_found": jobs_found,
            "statuses": dict(counts), "offset": selection["offset"],
            "max_portals": selection["max_portals"],
            "max_detail_pages": max_detail_pages, "max_jobs": max_jobs,
            "prioritize_business": bool(prioritize_business),
            "selection_rule_version": VACANCY_SCAN_RULE_VERSION,
            "vacancy_rule_version": VACANCY_SCAN_RULE_VERSION,
            "scan_db": str(scan_path), "run_id": run_id,
        }
        conn.execute(
            """UPDATE scan_runs SET finished_at=?,status='ok',processed_portals=?,
               request_attempts=?,jobs_found=?,result_counts_json=? WHERE id=?""",
            (now_utc(), processed, request_attempts, jobs_found, _json(result_summary), run_id),
        )
        conn.commit()
        return {**result_summary, "selection": {
            "all_portals": len(selection["all_portals"]),
            "eligible_count": selection["eligible_count"],
            "target_institutions": selection["target_institutions"],
            "by_kind": selection["by_kind"],
            "excluded_by_reason": selection["excluded_by_reason"],
        }}
    except Exception as error:
        conn.execute(
            """UPDATE scan_runs SET finished_at=?,status='failed',processed_portals=?,
               request_attempts=?,jobs_found=?,error=? WHERE id=?""",
            (now_utc(), processed, request_attempts, jobs_found, str(error)[:1000], run_id),
        )
        conn.commit()
        raise
    finally:
        conn.close()


def scan_summary(scan_db=None):
    path = Path(scan_db or DEFAULT_SCAN_DB)
    if not path.exists():
        return {"exists": False, "scan_db": str(path)}
    conn = connect_scan_db(path)
    try:
        ensure_scan_schema(conn)
        latest = conn.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
        statuses = [dict(row) for row in conn.execute(
            """SELECT scan_status AS status,COUNT(*) AS observations
               FROM vacancy_observations GROUP BY scan_status ORDER BY scan_status"""
        )]
        return {
            "exists": True, "scan_db": str(path),
            "runs": conn.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0],
            "observations": conn.execute("SELECT COUNT(*) FROM vacancy_observations").fetchone()[0],
            "vacancy_candidates": conn.execute("SELECT COUNT(*) FROM vacancy_candidates").fetchone()[0],
            "vacancy_records": conn.execute("SELECT COUNT(*) FROM vacancy_records").fetchone()[0],
            "statuses": statuses,
            "latest_run": dict(latest) if latest else None,
            "rule_version": VACANCY_SCAN_RULE_VERSION,
            "note": "Records are public-page observations in an isolated database; they are not yet production faculty_jobs rows or a complete labor-market denominator.",
        }
    finally:
        conn.close()


def export_scan_csv(
    scan_db=None,
    output_path=None,
    *,
    run_id=None,
    run_ids=None,
    deduplicate=False,
    overwrite=False,
):
    scan_path = Path(scan_db or DEFAULT_SCAN_DB)
    target_path = Path(output_path or DEFAULT_EXPORT_CSV)
    if target_path.resolve() == scan_path.resolve():
        raise ValueError("CSV output must not overwrite the scan database")
    if target_path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {target_path}. Pass overwrite=True to replace it.")
    conn = connect_scan_db(scan_path)
    try:
        ensure_scan_schema(conn)
        if run_id is not None and run_ids is not None:
            raise ValueError("Pass either run_id or run_ids, not both")
        normalized_run_ids = None
        if run_ids is not None:
            normalized_run_ids = sorted({int(value) for value in run_ids})
            if not normalized_run_ids:
                raise ValueError("run_ids must contain at least one run id")
        if run_id is None and normalized_run_ids is None:
            latest = conn.execute("SELECT id FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
            run_id = latest[0] if latest else None
        if run_id is None and normalized_run_ids is None:
            rows = []
        else:
            query = """SELECT r.*,o.run_id,o.checked_at,o.scan_status,o.page_status,o.page_title,
                              o.portal_url,o.final_url,o.http_status,
                              p.portal_kind,p.website_group_key,p.target_unitids_json AS portal_target_unitids,
                              p.target_names_json AS portal_target_names,
                              p.target_segments_json AS portal_target_segments
                       FROM vacancy_records r
                       JOIN vacancy_observations o ON o.id=r.observation_id
                       JOIN portal_inputs p ON p.id=o.portal_input_id
                       WHERE o.run_id IN ({}) ORDER BY r.id"""
            selected_ids = normalized_run_ids or [int(run_id)]
            placeholders = ",".join("?" for _ in selected_ids)
            rows = conn.execute(query.format(placeholders), selected_ids).fetchall()
            if normalized_run_ids is not None and deduplicate:
                # Prefer the latest observation when two official portals
                # expose the same public posting (e.g., a jobs index and an
                # individual department entry).
                unique = {}
                for row in rows:
                    key = row["official_url"] or row["source_job_id"]
                    current = unique.get(key)
                    if current is None or (row["run_id"], row["id"]) > (
                        current["run_id"], current["id"]
                    ):
                        unique[key] = row
                rows = sorted(unique.values(), key=lambda row: row["id"])
        fields = [
            "run_id", "observation_id", "source_job_id", "website_group_key", "portal_kind",
            "portal_url", "final_url", "http_status", "page_status", "scan_status",
            "page_title", "target_unitid", "target_match_status", "target_unitids_json",
            "portal_target_names", "portal_target_segments", "title_raw", "institution_raw",
            "department_raw", "location_raw", "description_excerpt", "posted_date_raw",
            "deadline_raw", "salary_raw", "faculty_role", "role_confidence",
            "extraction_method", "detail_status", "source_url", "official_url", "captured_at",
            "raw_json",
        ]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))
        return {
            "scan_db": str(scan_path), "output_csv": str(target_path),
            "run_id": run_id,
            "run_ids": normalized_run_ids,
            "deduplicated": bool(normalized_run_ids is not None and deduplicate),
            "rows": len(rows),
            "rule_version": VACANCY_SCAN_RULE_VERSION,
        }
    finally:
        conn.close()


__all__ = [
    "DEFAULT_EXPORT_CSV", "DEFAULT_REGISTRY_DB", "DEFAULT_SCAN_DB",
    "VACANCY_SCAN_RULE_VERSION", "CarnegieVacancyScanner", "connect_scan_db",
    "ensure_scan_schema", "export_scan_csv", "parse_portal_html", "portal_selection",
    "resolve_target", "scan_summary", "scan_vacancies", "select_portals",
]
