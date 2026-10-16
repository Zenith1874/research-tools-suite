# -*- coding: utf-8 -*-
"""AACSB accredited-school roster and bounded official-site job discovery.

The AACSB roster is an accreditation directory, not a job board.  This module
keeps those two grains separate: roster records are returned as structured
school metadata, while only explicit academic JobPosting JSON-LD or clearly
labelled faculty-position links from a school's own public website become
``SourceJob`` records.

The client is intentionally opt-in.  A full roster refresh is roughly 110
public AACSB pagination requests plus one detail request per school; official
site checks are separately bounded and recorded as ``no_current_jobs``,
``not_found``, ``blocked`` or ``unknown`` when evidence is insufficient.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import re
import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from services.faculty_jobs_normalizer import classify_faculty_market_role

from .base import (AdapterError, RobotsDisallowedError, SourceAdapter, SourceJob,
                   detail_excerpt, now_utc, visible_text)


AACSB_BASE_URL = "https://www.aacsb.edu"
AACSB_DIRECTORY_URL = AACSB_BASE_URL + "/accredited"
AACSB_LOAD_ENDPOINT = AACSB_BASE_URL + "/api/member-search-page/load-members"
AACSB_CONTEXT_ITEM_ID = "b2195e79-1541-4b64-8ca9-f2e0376b47e6"
AACSB_DEFAULT_PAGES = 110
AACSB_SCAN_RULE_VERSION = "faculty_market_v3_20260827"

ACADEMIC_JOB_RE = re.compile(
    r"\b(?:assistant|associate|full|distinguished|clinical|teaching|research|practice)?\s*"
    r"(?:professor|lecturer|instructor|faculty|dean|chair|postdoc|postdoctoral|"
    r"research\s+(?:fellow|associate|scientist)|academic\s+affairs)\b",
    re.I,
)
INELIGIBLE_ROLE_RE = re.compile(
    r"\b(?:graduate|teaching|student|undergraduate)\s+assistant\b|"
    r"\bfederal\s+work[- ]study\b|\bwork[- ]study\b|\bstudent\s+worker\b|"
    r"\b(?:executive|administrative|program|office|department|laboratory|lab)\s+assistant\b|"
    r"\b(?:intern|internship|coordinator|administrator|recruiter|analyst|accountant)\b",
    re.I,
)
GENERIC_JOB_COLLECTION_RE = re.compile(
    r"^(?:search\s+)?(?:full[- ]time\s+|part[- ]time\s+|adjunct\s+|pt\s+)?"
    r"faculty(?:\s*(?:&|and)\s*instructor)?\s+"
    r"(?:jobs?|job\s+openings?|openings?|positions?|opportunities|vacancies)\.?$|"
    r"^faculty\s*\((?:full|part)[- ]time\)$|^faculty\s+vacancies\.?$",
    re.I,
)
FACULTY_PAGE_RE = re.compile(
    r"\b(?:faculty|academic\s+(?:positions?|jobs?)|professor(?:s)?|lecturer(?:s)?|"
    r"research\s+(?:positions?|jobs?)|postdoctoral|postdoc|dean(?:s)?)\b",
    re.I,
)
BUSINESS_CONTEXT_RE = re.compile(
    r"\b(?:business|management|finance|marketing|accounting|economics|"
    r"entrepreneurship|strategy|operations|supply\s+chain|information\s+systems|"
    r"organizational\s+behavior|human\s+resources|human\s+resource|commerce)\b",
    re.I,
)
# A business-school website can expose university-wide vacancies.  These
# explicit non-business fields are not accepted merely because the page URL
# contains ``business``; an explicit business-school/discipline anchor in the
# title is required to keep mixed faculty pages conservative.
NON_BUSINESS_TITLE_RE = re.compile(
    r"\b(?:sports?\s+medicine|psychology|english|nursing|biology|mathematics|"
    r"computer\s+science|counsel(?:l?or)?\s+education|occupational\s+therapy|"
    r"engineering|law|middle\s+school|elementary\s+school|medicine|"
    r"physiology|anatomy|chemistry|physics|social\s+work|public\s+health|"
    r"radiopharmaceutical|radiochemical|pharmacy|pharmaceutical|chiropractic|"
    r"cosmetology|dental(?:\s+hygiene)?|dentistry|graphic\s+design|studio\s+art|"
    r"fine\s+arts?|journalism|mass\s+communication|recreation|swim(?:ming)?|"
    r"health\s+sciences?|educational\s+administration)\b",
    re.I,
)
JOBISH_LINK_RE = re.compile(
    r"(?:/jobs?(?:/|$)|/vacanc(?:y|ies)(?:/|$)|/positions?(?:/|$)|"
    r"/employment(?:/|$)|/recruit(?:ment)?(?:/|$)|/postings?(?:/|$)|"
    r"/search(?:/|\?|$)|/listing(?:s)?(?:/|$)|/careers?/(?:[^/]+/)*[^/]+|"
    r"(?:myworkdayjobs\.com|greenhouse\.io|lever\.co|academicjobsonline\.org|"
    r"interfolio\.com|jobs\.smartrecruiters\.com))",
    re.I,
)
GENERIC_JOB_URL_RE = re.compile(
    r"/(?:jobs?|postings?|careers?)/(?:search|listing|searchresults?)(?:/|\?|$)|"
    r"/(?:search|listing|searchresults?)(?:/|\?|$)",
    re.I,
)
ACADEMIC_ROLE_LINK_RE = re.compile(
    r"\b(?:assistant|associate|full|clinical|visiting|teaching|research|adjunct|"
    r"part[- ]time|full[- ]time|professor|lecturer|instructor|postdoc|postdoctoral|dean)\b",
    re.I,
)
GENERIC_FACULTY_LINK_RE = re.compile(
    r"\b(?:view\s+and\s+apply\s+to\s+open|view\s+faculty|faculty\s*(?:&|and|/)\s*staff|"
    r"faculty\s+directory|faculty\s+resources?|faculty\s+experts?|faculty\s+overview|"
    r"faculty\s+(?:scholarship|complaints?|senate|forms?|handbook|payroll|development)|"
    r"dean(?:’|'|s)?s?\s+(?:welcome|message|list|advisory)|research\s+by\s+faculty)\b",
    re.I,
)
CAREER_LINK_RE = re.compile(
    r"\b(?:careers?|employment|vacanc(?:y|ies)|job(?:s|\s+opportunities?)?|"
    r"work\s+with\s+us|join\s+us|faculty\s+(?:positions?|jobs?)|"
    r"academic\s+(?:positions?|jobs?)|faculty\s+recruitment|academic\s+recruitment|"
    r"open\s+positions?|job\s+board)\b",
    re.I,
)
EXCLUDED_CAREER_RE = re.compile(
    r"\b(?:student\s+careers?|career\s+services?|career\s+center|alumni|"
    r"internships?|job\s+fair|employability|student\s+employment)\b",
    re.I,
)
BLOCKED_PAGE_RE = re.compile(
    r"(?:cloudflare|captcha|access\s+denied|verify\s+you\s+are\s+human|"
    r"robot\s+check|unusual\s+traffic|enable\s+javascript)",
    re.I,
)


@dataclass(frozen=True)
class AACSBDirectoryRecord:
    directory_result_id: str
    directory_url: str
    institution_name: str
    school_name: str | None
    location_raw: str | None
    directory_title: str
    roster_source_url: str
    captured_at: str
    official_website: str | None = None
    accreditation_scope: str | None = None
    detail_excerpt: str | None = None
    detail_status: str = "not_checked"


@dataclass
class OfficialSiteScan:
    website_status: str
    career_page_status: str
    job_scan_status: str
    career_page_url: str | None = None
    jobs: list[SourceJob] | None = None
    response_status: int | None = None
    reason: str | None = None
    candidates_seen: int = 0
    candidates_rejected: int = 0
    complete: bool = False
    budget_truncated: bool = False
    error_count: int = 0
    pages_fetched: int = 0


def _clean(value):
    if hasattr(value, "get_text"):
        value = value.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _safe_url(value, base=None):
    if not value:
        return None
    url = urljoin(base or AACSB_BASE_URL, str(value).strip())
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return url


def _source_hash(record):
    payload = {
        key: getattr(record, key)
        for key in ("directory_result_id", "directory_url", "institution_name", "school_name",
                    "location_raw", "official_website", "accreditation_scope")
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def parse_directory_page(html, page_url=AACSB_DIRECTORY_URL, captured_at=None):
    """Parse one public AACSB result page; exclude membership-only records."""
    soup = BeautifulSoup(html or "", "html.parser")
    captured = captured_at or now_utc()
    records = []
    for node in soup.select("a.member-search-result"):
        href = _safe_url(node.get("href"), AACSB_BASE_URL)
        # The endpoint occasionally includes a non-accredited educational
        # member as a sponsored/inserted result.  The accredited path is the
        # authoritative inclusion rule for this dataset.
        if not href or not urlsplit(href).path.startswith("/accredited/"):
            continue
        title = _clean(node.select_one(".member-search-result__title"))
        school = _clean(node.select_one(".member-search-result__text")) or None
        location = _clean(node.select_one(".member-search-result__location")) or None
        if not title:
            continue
        result_id = _clean(node.get("data-result-id")) or hashlib.sha1(href.encode("utf-8")).hexdigest()
        records.append(AACSBDirectoryRecord(
            directory_result_id=result_id,
            directory_url=href,
            institution_name=title,
            school_name=school,
            location_raw=location,
            directory_title=" ".join(item for item in (title, school) if item),
            roster_source_url=page_url,
            captured_at=captured,
        ))
    return records


def parse_directory_total(html):
    match = re.search(r"\b([\d,]+)\s+Results\b", html or "", re.I)
    return int(match.group(1).replace(",", "")) if match else None


def parse_detail_page(html, record):
    """Add only bounded structured fields from an AACSB school detail page."""
    soup = BeautifulSoup(html or "", "html.parser")
    website = None
    website_node = soup.select_one("a.educational-member-detail-body__sidebar-website[href]")
    if website_node:
        website = _safe_url(website_node.get("href"), AACSB_BASE_URL)

    accreditation_scope = None
    for section in soup.select(".educational-member-detail-body__sidebar-section"):
        heading = _clean(section.select_one(".educational-member-detail-body__sidebar-section-title"))
        if heading.casefold() != "accreditation":
            continue
        text = _clean(section)
        values = []
        if re.search(r"business\s*&\s*accounting", text, re.I):
            values.append("Business & Accounting")
        elif re.search(r"\bbusiness\b", text, re.I):
            values.append("Business")
        if re.search(r"\baccounting\b", text, re.I) and "Business & Accounting" not in values:
            values.append("Accounting")
        accreditation_scope = ", ".join(values) or text[:120] or None
        break

    description = soup.select_one(
        ".educational-member-detail-body__description, "
        ".educational-member-detail-body__content"
    )
    excerpt = detail_excerpt(description, max_chars=700) if description else None
    return replace(
        record,
        official_website=website,
        accreditation_scope=accreditation_scope or record.accreditation_scope,
        detail_excerpt=excerpt,
        detail_status="ok",
    )


def _jsonld_job_postings(soup):
    records = []
    for node in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        try:
            value = json.loads(node.string or node.get_text())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        stack = value if isinstance(value, list) else [value]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack[0:0] = item
            elif isinstance(item, dict):
                types = item.get("@type")
                types = types if isinstance(types, list) else [types]
                if any(str(kind).casefold() == "jobposting" for kind in types):
                    records.append(item)
                if isinstance(item.get("@graph"), list):
                    stack[0:0] = item["@graph"]
    return records


def _jsonld_location(value):
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        address = value.get("address") or {}
        if isinstance(address, dict):
            return ", ".join(_clean(address.get(key)) for key in (
                "addressLocality", "addressRegion", "addressCountry"
            ) if _clean(address.get(key))) or None
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


def _apply_link(soup, page_url):
    candidates = []
    for link in soup.find_all("a", href=True):
        label = _clean(link).strip("-:| ")
        href = _safe_url(link.get("href"), page_url)
        if not href:
            continue
        if re.search(r"\bapply\b|application", label, re.I):
            candidates.append(href)
    return candidates[0] if candidates else None


def _career_candidates(soup, base_url):
    scored = {}
    for link in soup.find_all("a", href=True):
        label = _clean(link)
        href = _safe_url(link.get("href"), base_url)
        if not href or href.casefold().startswith("mailto:"):
            continue
        haystack = f"{label} {href}"
        if not CAREER_LINK_RE.search(haystack) or EXCLUDED_CAREER_RE.search(haystack):
            continue
        score = 0
        if CAREER_LINK_RE.search(label):
            score += 4
        if re.search(r"(?:faculty|academic|professor|lecturer|vacanc|job)", label, re.I):
            score += 3
        if re.search(r"(?:career|employment|vacanc|job|faculty|academic)", urlsplit(href).path, re.I):
            score += 2
        scored[href] = max(score, scored.get(href, 0))
    # Keep more candidates available for an explicit deeper scan.  Callers
    # still choose the actual request budget through ``max_pages``.
    return [url for url, _ in sorted(scored.items(), key=lambda item: (-item[1], item[0]))[:8]]


def _has_business_context(record, title, description, occupational_category, page_url):
    """Require evidence that a public academic posting is business-relevant.

    An AACSB roster row alone does not prove that a generic university-wide
    ``Assistant Professor`` vacancy belongs to the business school.  A
    business discipline term in the posting/page or a business-specific
    official-site path is required before the job is ingested.
    """
    title_text = str(title or "")
    if NON_BUSINESS_TITLE_RE.search(title_text) and not BUSINESS_CONTEXT_RE.search(title_text):
        return False
    posting_text = " ".join(str(value or "") for value in (
        title, description, occupational_category,
    ))
    if BUSINESS_CONTEXT_RE.search(posting_text):
        return True
    # A business-school URL or AACSB roster row identifies the site being
    # searched, not the organizational home of a vacancy exposed by a central
    # university career portal.  Missing posting-level evidence stays missing.
    return False


def _posting_school_name(record, title, description, occupational_category=None):
    """Return a school only when the posting itself supplies the evidence."""
    text = " ".join(str(value or "") for value in (title, occupational_category, description))[:2400]
    school = _clean(record.school_name)
    if school and school.casefold() in text.casefold():
        return school
    match = re.search(
        r"\b((?:[A-Z][\w&'’.-]+\s+){0,5}(?:School|College|Faculty)\s+of\s+"
        r"(?:Business|Management|Commerce)(?:\s+Administration)?)\b",
        text,
    )
    return _clean(match.group(1)) if match else None


def _looks_like_explicit_job_link(title, href):
    """Reject ordinary faculty-directory/navigation links in fallback mode."""
    text = f"{title or ''} {href or ''}"
    if GENERIC_FACULTY_LINK_RE.search(text) or GENERIC_JOB_COLLECTION_RE.search(str(title or "")):
        return False
    if INELIGIBLE_ROLE_RE.search(str(title or "")) or GENERIC_JOB_URL_RE.search(str(href or "")):
        return False
    jobish = bool(JOBISH_LINK_RE.search(str(href or "")))
    academic_role = bool(ACADEMIC_ROLE_LINK_RE.search(str(title or "")))
    apply_word = bool(re.search(r"\b(?:apply|application|vacanc(?:y|ies)|opening(?:s)?)\b", str(title or ""), re.I))
    return (jobish and academic_role) or (jobish and apply_word and re.search(r"\bfaculty\b", str(title or ""), re.I))


class AACSBDirectoryClient(SourceAdapter):
    """Public AACSB directory client; not part of the default daily adapter run."""

    name = "aacsb_directory"
    adapter_name = "aacsb_directory"
    region = "Global"
    base_url = AACSB_DIRECTORY_URL
    priority = 30
    max_items = 1200

    def __init__(self, timeout=20, max_pages=AACSB_DEFAULT_PAGES, delay=0.45, session=None):
        super().__init__(timeout=timeout, max_pages=max_pages, max_items=1200, session=session)
        self.delay = max(0.1, float(delay))
        self.last_directory_metadata = {
            "reported_results": None,
            "raw_results_observed": 0,
            "accredited_records_observed": 0,
            "non_accredited_results_excluded": 0,
            "complete": False,
            "max_pages_requested": self.max_pages,
            "max_records": None,
            "pages_fetched": 0,
            "pagination_natural_end": False,
            "error_count": 0,
        }

    def _pause(self):
        time.sleep(self.delay)

    def fetch_directory(self, max_pages=None, max_records=None):
        max_pages = max(1, min(150, int(max_pages or self.max_pages)))
        max_records = max_records if max_records is None else max(1, min(2000, int(max_records)))
        records = []
        seen = set()
        total = None
        pages_fetched = 0
        raw_results_observed = 0
        non_accredited_excluded = 0
        stopped_by_record_budget = False
        pagination_natural_end = False
        page_budget_exhausted = False
        for page in range(1, max_pages + 1):
            response = self.request(AACSB_LOAD_ENDPOINT, params={
                "contextItemId": AACSB_CONTEXT_ITEM_ID,
                "page": page,
            })
            pages_fetched += 1
            raw_nodes = BeautifulSoup(response.text or "", "html.parser").select("a.member-search-result")
            raw_results_observed += len(raw_nodes)
            page_records = parse_directory_page(response.text, response.url, now_utc())
            non_accredited_excluded += max(0, len(raw_nodes) - len(page_records))
            if page == 1:
                total = parse_directory_total(response.text)
            for record in page_records:
                if record.directory_result_id in seen:
                    continue
                seen.add(record.directory_result_id)
                records.append(record)
                if max_records and len(records) >= max_records:
                    stopped_by_record_budget = True
                    break
            if stopped_by_record_budget:
                break
            # An individual page can contain only membership insertions; that
            # is not evidence that pagination ended. Stop on an actually empty
            # result page or once every result counted by the endpoint has been
            # observed, including excluded non-accredited members.
            if not raw_nodes or (total and raw_results_observed >= total):
                pagination_natural_end = True
                break
            self._pause()
        else:
            page_budget_exhausted = True
        self.last_directory_metadata = {
            "reported_results": total,
            "raw_results_observed": raw_results_observed,
            "accredited_records_observed": len(records),
            "non_accredited_results_excluded": non_accredited_excluded,
            "max_pages_requested": max_pages,
            "max_records": max_records,
            "pages_fetched": pages_fetched,
            "pagination_natural_end": pagination_natural_end,
            "page_budget_exhausted": page_budget_exhausted,
            "error_count": 0,
            "complete": bool(
                not stopped_by_record_budget
                and total is not None
                and raw_results_observed >= total
                and pagination_natural_end
                and not page_budget_exhausted
            ),
        }
        return records, pages_fetched, total

    def fetch_detail(self, record):
        response = self.request(record.directory_url)
        result = parse_detail_page(response.text, record)
        self._pause()
        return result

    def scan_official_site(self, record, max_pages=2, max_jobs=20):
        website = _safe_url(record.official_website)
        if not website:
            return OfficialSiteScan(
                website_status="no_official_website", career_page_status="not_found",
                job_scan_status="unknown", reason="AACSB detail page did not expose a public website.", jobs=[],
                complete=False, pages_fetched=0,
            )
        try:
            home = self.request(website)
        except RobotsDisallowedError as exc:
            # The school published rules that refuse this fetch.  Record the
            # refusal as its own outcome: it is not a transport error, and it
            # is not evidence that the school has no vacancy.
            return OfficialSiteScan(
                website_status="robots_disallowed", career_page_status="unknown",
                job_scan_status="unknown", reason=str(exc)[:300], jobs=[],
                complete=False, error_count=1, pages_fetched=0,
            )
        except Exception as exc:
            return OfficialSiteScan(
                website_status="blocked" if "HTTP 403" in str(exc) or "HTTP 429" in str(exc) else "error",
                career_page_status="unknown", job_scan_status="unknown",
                reason=str(exc)[:300], jobs=[], complete=False, error_count=1, pages_fetched=0,
            )
        self._pause()
        home_soup = BeautifulSoup(home.text or "", "html.parser")
        home_text = visible_text(home_soup)
        if BLOCKED_PAGE_RE.search(home_text[:5000]):
            return OfficialSiteScan("blocked", "unknown", "blocked", response_status=home.status_code,
                                   reason="Public website returned a bot/access challenge.", jobs=[],
                                   complete=False, pages_fetched=1)
        home_json_jobs = _jsonld_job_postings(home_soup)
        candidates = _career_candidates(home_soup, home.url)
        if re.search(r"(?:faculty|academic)\s+(?:jobs?|positions?)", urlsplit(home.url).path, re.I):
            candidates.insert(0, home.url)
        if home_json_jobs and home.url not in candidates:
            # A small number of schools publish a current JobPosting directly
            # on their institutional homepage.  Do not require a separate
            # careers navigation link before inspecting that public evidence.
            candidates.insert(0, home.url)
        if not candidates and (home_json_jobs or FACULTY_PAGE_RE.search(home_text)):
            candidates = [home.url]
        if not candidates:
            return OfficialSiteScan("ok", "not_found", "not_found", response_status=home.status_code,
                                   reason="No public faculty/academic employment entry was discovered from the official homepage.", jobs=[],
                                   complete=False, pages_fetched=1)

        all_jobs = []
        fetched = 0
        robots_refused = False
        last_reason = None
        selected_url = None
        candidates_seen = 0
        candidates_rejected = 0
        errors = 0
        blocked_seen = False
        candidate_budget = max(1, min(8, int(max_pages)))
        job_budget = max(1, min(100, int(max_jobs)))
        for candidate in candidates[:candidate_budget]:
            try:
                response = self.request(candidate)
            except RobotsDisallowedError as exc:
                robots_refused = True
                errors += 1
                last_reason = str(exc)[:300]
                continue
            except Exception as exc:
                errors += 1
                last_reason = str(exc)[:300]
                continue
            self._pause()
            fetched += 1
            selected_url = response.url or candidate
            soup = BeautifulSoup(response.text or "", "html.parser")
            # ``visible_text`` removes script/style nodes in place.  Extract
            # JSON-LD before deriving the bounded human-readable excerpt so a
            # public JobPosting script is not accidentally deleted first.
            json_jobs = _jsonld_job_postings(soup)
            text = visible_text(soup)
            if BLOCKED_PAGE_RE.search(text[:5000]):
                last_reason = "Career page returned a bot/access challenge."
                blocked_seen = True
                errors += 1
                continue
            page_jobs = []
            for item in json_jobs:
                title = _clean(item.get("title"))
                candidates_seen += 1
                explicit_job_url = _safe_url(item.get("url") or item.get("mainEntityOfPage"), response.url)
                raw_description = item.get("description")
                if raw_description:
                    raw_description = visible_text(BeautifulSoup(str(raw_description), "html.parser"))
                role = classify_faculty_market_role(title, raw_description, explicit_job_url or response.url)
                if not title or not role.get("eligible"):
                    candidates_rejected += 1
                    continue
                # A career/listing page is a source URL, not an official
                # application URL.  Keep official_url unknown unless JSON-LD
                # exposes a distinct public job-detail URL.
                job_url = explicit_job_url if explicit_job_url and explicit_job_url.rstrip("/") != response.url.rstrip("/") else None
                description = raw_description
                org = item.get("hiringOrganization")
                if isinstance(org, dict):
                    org = org.get("name")
                occupational_category = _clean(item.get("occupationalCategory")) or None
                if not _has_business_context(record, title, description, occupational_category, job_url):
                    candidates_rejected += 1
                    continue
                posting_school = _posting_school_name(
                    record, title, description, occupational_category,
                )
                source_id = hashlib.sha256(f"{record.directory_result_id}|{job_url or title}".encode("utf-8")).hexdigest()[:32]
                page_jobs.append(SourceJob(
                    source="aacsb_official", source_job_id=source_id,
                    source_url=selected_url, official_url=job_url,
                    title_raw=title, institution_raw=_clean(org) or record.institution_name,
                    school_raw=posting_school, location_raw=_jsonld_location(item.get("jobLocation")) or record.location_raw,
                    department_raw=occupational_category,
                    description_excerpt=(description[:2000] if description else None), posted_date_raw=_clean(item.get("datePosted")) or None,
                    deadline_raw=_clean(item.get("validThrough")) or None, salary_raw=_jsonld_salary(item.get("baseSalary")),
                    captured_at=now_utc(), extra={
                        "institution_url": record.official_website,
                        "school_url": record.official_website,
                        "aacsb_directory_url": record.directory_url,
                        "aacsb_target_school": record.school_name,
                        "school_evidence_context": "structured_posting" if posting_school else "aacsb_roster_target",
                    },
                ))

            # Some official career pages expose an unrelated university-wide
            # JobPosting JSON-LD object alongside a real business-school link.
            # Fall back when no accepted business posting was found, rather
            # than treating the presence of any JSON-LD as proof the page was
            # completely parsed.
            if not page_jobs:
                for link in soup.find_all("a", href=True):
                    title = _clean(link)
                    if not title or len(title) < 8:
                        continue
                    looks_candidate = bool(
                        ACADEMIC_JOB_RE.search(title)
                        or INELIGIBLE_ROLE_RE.search(title)
                        or GENERIC_JOB_COLLECTION_RE.search(title)
                        or re.search(r"\b(?:assistant|associate|work[- ]study|intern|staff)\b", title, re.I)
                    )
                    if not looks_candidate:
                        continue
                    candidates_seen += 1
                    job_url = _safe_url(link.get("href"), response.url)
                    if not job_url or job_url == response.url:
                        candidates_rejected += 1
                        continue
                    container = link.find_parent(["article", "li", "tr", "section", "div"])
                    context = detail_excerpt(container or link.parent or link, max_chars=1000)
                    role = classify_faculty_market_role(title, context, job_url)
                    if not role.get("eligible"):
                        candidates_rejected += 1
                        continue
                    if not _looks_like_explicit_job_link(title, job_url):
                        candidates_rejected += 1
                        continue
                    if not _has_business_context(record, title, context, None, job_url):
                        candidates_rejected += 1
                        continue
                    posting_school = _posting_school_name(record, title, context)
                    source_id = hashlib.sha256(f"{record.directory_result_id}|{job_url}".encode("utf-8")).hexdigest()[:32]
                    page_jobs.append(SourceJob(
                        source="aacsb_official", source_job_id=source_id,
                        source_url=selected_url, official_url=job_url,
                        title_raw=title, institution_raw=record.institution_name,
                        school_raw=posting_school, location_raw=record.location_raw,
                        description_excerpt=context, captured_at=now_utc(), extra={
                            "institution_url": record.official_website,
                            "school_url": record.official_website,
                            "aacsb_directory_url": record.directory_url,
                            "extraction_method": "explicit_faculty_link",
                            "aacsb_target_school": record.school_name,
                            "school_evidence_context": "posting" if posting_school else "aacsb_roster_target",
                        },
                    ))
            all_jobs.extend(page_jobs)
            if len(all_jobs) >= job_budget:
                break
        hit_job_budget = len(all_jobs) >= job_budget
        budget_truncated = bool(len(candidates) > candidate_budget or hit_job_budget)
        complete = bool(
            not robots_refused and not blocked_seen and errors == 0
            and not budget_truncated
            and fetched == len(candidates[:candidate_budget])
        )
        unique = {}
        for job in all_jobs:
            unique[job.source_job_id] = job
        jobs = list(unique.values())[:job_budget]
        if jobs:
            return OfficialSiteScan("ok", "found", "jobs_found", selected_url, jobs, 200,
                                   f"Found {len(jobs)} eligible business-faculty posting(s) after {fetched} public page request(s); rejected {candidates_rejected} non-eligible candidate(s).",
                                   candidates_seen, candidates_rejected, complete, budget_truncated,
                                   errors, fetched)
        if fetched:
            status = "no_eligible_business_faculty_jobs" if candidates_seen else "no_current_jobs"
            reason = ("Official employment entry was accessible, but no eligible individual "
                      "business-faculty posting was established; rejected candidates remain "
                      "outside the default market.")
            if robots_refused:
                # Part of the site was never read, so "no current jobs" would
                # overstate what was actually observed.
                status = "unknown"
                reason += " robots.txt refused at least one career page, so this scan is incomplete."
            return OfficialSiteScan("ok", "found", status, selected_url, [], 200, reason,
                                   candidates_seen, candidates_rejected, complete, budget_truncated,
                                   errors, fetched)
        if robots_refused:
            return OfficialSiteScan("robots_disallowed", "unknown", "unknown", None, [], None,
                                   last_reason or "robots.txt refused every discovered career page.",
                                   candidates_seen, candidates_rejected, False, budget_truncated,
                                   errors, fetched)
        return OfficialSiteScan("ok", "unknown", "unknown", None, [], None,
                               last_reason or "Career page could not be read.",
                               candidates_seen, candidates_rejected, False, budget_truncated,
                               errors, fetched)


__all__ = [
    "AACSB_BASE_URL", "AACSB_DIRECTORY_URL", "AACSB_CONTEXT_ITEM_ID", "AACSB_DEFAULT_PAGES",
    "AACSB_SCAN_RULE_VERSION",
    "AACSBDirectoryClient", "AACSBDirectoryRecord", "OfficialSiteScan", "parse_directory_page",
    "parse_directory_total", "parse_detail_page",
]
