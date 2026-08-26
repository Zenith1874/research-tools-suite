# -*- coding: utf-8 -*-
"""Bounded adapters for public academic and business-school job boards.

These adapters intentionally consume only public HTML that is already exposed
by each source.  They do not call private APIs, submit login forms, solve
CAPTCHAs, or treat a board listing URL as an official application URL.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import replace
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base import (
    AdapterResponse,
    SourceAdapter,
    SourceJob,
    absolute_url,
    dedupe_source_jobs,
    now_utc,
    visible_text,
)


def _text(node):
    return visible_text(node) if node is not None else ""


def _attr_text(node, selector, attribute=None):
    if node is None:
        return ""
    found = node.select_one(selector)
    if not found:
        return ""
    if attribute:
        return str(found.get(attribute) or "").strip()
    return _text(found)


def _first_link(node, pattern):
    if node is None:
        return None
    for link in node.select("a[href]"):
        href = str(link.get("href") or "").strip()
        if re.search(pattern, href, re.I):
            return link
    return None


def _stable_id(source, url, fallback):
    parsed = urlparse(url or "")
    match = re.search(r"/(?:job|jobs|announcement|announcements?)/([^/?#]+)", parsed.path, re.I)
    if match:
        return match.group(1)
    digest = hashlib.sha256(f"{source}|{url}|{fallback}".encode("utf-8")).hexdigest()
    return digest[:24]


def _iso_day_month_year(value):
    """Convert an explicitly labelled European ``DD/MM/YYYY`` date."""
    match = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(20\d{2})\s*", str(value or ""))
    if not match:
        return value
    day, month, year = (int(item) for item in match.groups())
    if 1 <= day <= 31 and 1 <= month <= 12:
        return f"{year:04d}-{month:02d}-{day:02d}"
    return value


def _school_phrase(text):
    """Return only explicit school wording, never an inferred school."""
    value = " ".join(str(text or "").split())
    patterns = (
        r"\b(?:[A-Z][\w&'’.-]+\s+){0,5}(?:School|College|Faculty)\s+of\s+"
        r"(?:Business|Management|Accounting|Finance|Commerce)(?:\s+Administration)?"
        r"(?:\s+at\s+[^,.;]{2,90})?",
        r"\b(?:[A-Z][\w&'’.-]+\s+){0,3}(?:Business|Management|Commerce)\s+School"
        r"(?:\s+at\s+[^,.;]{2,90})?",
    )
    for index, pattern in enumerate(patterns):
        # Keep the first pattern's leading capitalized-word boundary strict so
        # a title fragment such as ``in Entrepreneurship`` is not swallowed;
        # the second pattern is case-insensitive for brands such as ``emlyon
        # business school``.
        match = re.search(pattern, value, re.I if index == 1 else 0)
        if match:
            phrase = match.group(0).strip(" ,;:-")
            phrase = re.sub(r"^(?:in|at|of)\s+[^,.;]{1,80}?\s+(?=[A-Za-z][\w&'’.-]*(?:\s+[A-Za-z][\w&'’.-]*){0,5}\s+(?:School|College|Faculty)\s+of\b)", "", phrase, flags=re.I)
            phrase = re.sub(r"^(?:The\s+)?UC\s+Irvine\s+", "", phrase, flags=re.I)
            return phrase.strip(" ,;:-")
    return None


def _explicit_university(text):
    """Extract an institution only when the source states a clear entity."""
    value = " ".join(str(text or "").split())
    patterns = (
        r"\b(?:University|Université|Universität|Universidade)\s+of\s+[^,.;]{2,100}",
        r"\b[A-Z][\w&'’.-]*(?:\s+[A-Z][\w&'’.-]*){0,8}\s+"
        r"(?:University|College|Institute|School of Economics and Business)\b",
    )
    candidates = []
    for pattern in patterns:
        candidates.extend(match.group(0).strip(" ,;:-") for match in re.finditer(pattern, value))
    if not candidates:
        return None
    # Prefer the longest explicit entity; a longer match generally includes
    # the campus or university qualifier rather than a short abbreviation.
    return max(candidates, key=len)


def _split_employer(employer, context=""):
    """Split an explicit business-school employer without guessing a school."""
    raw = " ".join(str(employer or "").split()).strip(" ,;:-")
    school = _school_phrase(" ".join((raw, context)))
    institution = raw
    if school and raw:
        explicit_split = None
        for pattern in (
            r"^(?P<prefix>.+?\b(?:University|College|Institute))\s+(?P<school>(?:School|College|Faculty)\s+of\s+(?:Business|Management|Accounting|Finance|Commerce)(?:\s+Administration)?)$",
            r"^(?P<prefix>.+?\bCollege)\s+of\s+(?P<field>Business|Management|Commerce)(?:\s+Administration)?$",
            r"^(?P<prefix>[^,;]{1,60}?)\s+(?P<school>College\s+of\s+Business(?:\s+Administration)?)$",
        ):
            match = re.match(pattern, raw, re.I)
            if match:
                school_value = match.groupdict().get("school") or f"College of {match.group('field')}"
                explicit_split = (match.group("prefix").strip(), school_value.strip())
                break
        if explicit_split:
            institution, school = explicit_split
        school_in_raw = _school_phrase(raw)
        if school_in_raw:
            prefix = raw[:raw.find(school_in_raw)].strip(" ,;:-")
            suffix = raw[raw.find(school_in_raw) + len(school_in_raw):].strip(" ,;:-")
            if re.match(r"^(?:at|@)\b", suffix, re.I):
                institution = re.sub(r"^(?:at|@)\s+", "", suffix, flags=re.I).strip(" ,;:-")
            elif prefix and (
                re.search(r"\b(?:University|College|Institute)\b$", prefix, re.I)
                or (
                    re.match(r"^College\s+of\s+Business", school_in_raw, re.I)
                    and len(prefix.split()) <= 3
                )
            ):
                # Keep a short employer prefix only if it is a plausible
                # institution label.  A one-word school brand remains source
                # evidence but is not silently expanded to a university.
                institution = prefix
        if institution == raw and not re.search(r"\b(?:University|College|Institute)\b", raw, re.I):
            explicit = _explicit_university(context)
            if explicit:
                institution = explicit
    if not institution:
        institution = raw or _explicit_university(context) or "Unknown institution"
    return institution, school


def _job(
    source,
    source_url,
    title,
    institution,
    *,
    location=None,
    description=None,
    school=None,
    department=None,
    posted=None,
    deadline=None,
    salary=None,
    official_url=None,
    source_job_id=None,
    school_context="posting",
    extra=None,
):
    title = " ".join(str(title or "").split()).strip()
    description = " ".join(str(description or "").split()).strip()
    institution, employer_school = _split_employer(institution, " ".join((title, description)))
    school = school or employer_school or _school_phrase(" ".join((title, description)))
    source_url = absolute_url(source_url, source_url) or source_url
    source_job_id = source_job_id or _stable_id(source, source_url, title)
    payload = {
        "board_source": source,
        "school_raw": school,
        "school_evidence_rule_version": "source_jobboard_explicit_text_v1" if school else None,
    }
    if extra:
        payload.update(extra)
    # Preserve the adapter's evidence grain even when no explicit school was
    # extracted.  This prevents a board employer label from being presented as
    # an independently verified school entity downstream.
    payload.setdefault("school_evidence_context", school_context)
    return SourceJob(
        source=source,
        source_job_id=str(source_job_id),
        source_url=source_url,
        official_url=official_url,
        title_raw=title,
        institution_raw=institution or "Unknown institution",
        school_raw=school,
        department_raw=department,
        location_raw=location,
        description_excerpt=description[:2000] or None,
        posted_date_raw=posted,
        deadline_raw=deadline,
        salary_raw=salary,
        captured_at=now_utc(),
        extra=payload,
    )


def _next_page(soup, current_url):
    for link in soup.select("a[href]"):
        label = _text(link).casefold()
        rel = " ".join(link.get("rel") or []).casefold()
        if label in {"next", "next page", "load more", "more…", "more..."} or "next" in rel:
            return urljoin(current_url, str(link.get("href") or "").strip())
    return None


def _flatten_jsonld(value):
    """Yield compact JSON-LD objects, including objects nested in ``@graph``."""
    if isinstance(value, dict):
        yield value
        if isinstance(value.get("@graph"), (dict, list)):
            yield from _flatten_jsonld(value["@graph"])
    elif isinstance(value, list):
        for item in value:
            yield from _flatten_jsonld(item)


def _jobposting_schema(soup):
    """Return the first public JobPosting object without retaining raw JSON."""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        for item in _flatten_jsonld(payload):
            types = item.get("@type")
            types = types if isinstance(types, list) else [types]
            if "JobPosting" in types:
                return item
    return None


def _markup_text(value):
    if not value:
        return None
    return _text(BeautifulSoup(str(value), "html.parser"))


def _schema_location(value):
    places = value if isinstance(value, list) else [value]
    rendered = []
    for place in places:
        if not isinstance(place, dict):
            continue
        address = place.get("address") if isinstance(place.get("address"), dict) else place
        parts = []
        for key in ("addressLocality", "addressRegion", "postalCode"):
            text = str(address.get(key) or "").strip()
            if text and text not in parts:
                parts.append(text)
        country = address.get("addressCountry")
        country = country.get("name") if isinstance(country, dict) else country
        country = str(country or "").strip()
        if country and country not in parts:
            parts.append(f"({country})" if len(country) <= 3 else country)
        if parts:
            rendered.append(", ".join(parts))
    return "; ".join(dict.fromkeys(rendered)) or None


def _schema_salary(value):
    if not isinstance(value, dict):
        return None
    currency = str(value.get("currency") or "").strip()
    amount = value.get("value")
    if isinstance(amount, dict):
        low = amount.get("minValue") or amount.get("value")
        high = amount.get("maxValue")
        unit = str(amount.get("unitText") or "").strip()
    else:
        low = value.get("minValue") or amount
        high = value.get("maxValue")
        unit = str(value.get("unitText") or "").strip()
    if low is None and high is None:
        return None
    amount_text = f"{low}-{high}" if high is not None and high != low else str(low or high)
    return " ".join(item for item in (currency, amount_text, unit) if item) or None


def _label_value(text, label):
    """Read a bounded value after a visible detail-page label."""
    labels = (
        "Employer", "Company", "Location", "Salary", "Date posted", "Posted", "Closing date", "Deadline",
        "Focus Area", "Role Type", "Role Level", "Work Mode", "Organization Type",
        "Job Function", "Job Type", "Job Duration", "Min Education", "Education Level", "Discipline", "Employment Type", "Description",
    )
    boundary = "|".join(re.escape(item) for item in labels if item.casefold() != label.casefold())
    match = re.search(
        rf"\b{re.escape(label)}\s*:?\s+(.*?)(?=\s+(?:{boundary})\b|\s+View more categories\b|\s+View less categories\b|$)",
        text, re.I,
    )
    return re.sub(r"\s+", " ", match.group(1)).strip(" ,;:-") if match else None


def _detail_institution(organization, description):
    """Prefer an explicit university named in a school description."""
    organization = " ".join(str(organization or "").split()).strip(" ,;:-")
    description = " ".join(str(description or "").split())
    if not organization:
        return None
    if not re.search(r"\b(?:business|management|commerce|accounting|finance)\s+(?:school|college)\b", organization, re.I):
        return organization
    # Many boards name the school in ``hiringOrganization`` and put the
    # parent university immediately after it in the description, e.g.
    # ``Mays Business School, Texas A&M University invites ...``.
    organization_match = re.search(re.escape(organization), description, re.I)
    if organization_match:
        suffix = description[organization_match.end():]
        parent_match = re.search(
            r"(?:^|,|\bat\s+|\bof\s+)\s*((?:The\s+)?[A-Z][^.;,]{1,90}?\b(?:University|College|Institute|Polytechnic)\b(?:\s+of\s+[A-Z][^.;,]{1,80})?)",
            suffix,
        )
        if parent_match:
            return parent_match.group(1).strip(" ,:-")[:180]
    for clause in re.split(r"[.;]", description):
        candidate = re.split(r"\bpart\s+of\b", clause, maxsplit=1, flags=re.I)[-1].strip(" ,:-")
        if re.search(r"\b(?:University|College|Institute|Polytechnic)\b", candidate, re.I):
            return candidate[:180]
    # A board may expose only a school brand (for example ``emlyon business
    # school``).  Keep that text as school evidence, but do not promote it to
    # a university/institution without an explicit parent entity.
    return None


def _detail_application_url(soup, source_url):
    source_host = urlparse(source_url or "").netloc.casefold().removeprefix("www.")
    for link in soup.select("a[href]"):
        label = _text(link).casefold()
        candidate = urljoin(source_url, str(link.get("href") or "").strip())
        host = urlparse(candidate).netloc.casefold().removeprefix("www.")
        explicit_apply = bool(re.search(r"\b(?:apply|application|submit)\b", label))
        # Some school pages use a bare ``HERE`` anchor for the official ATS.
        # Accept that shorthand only for a recognizable application host; a
        # generic ``here`` link can otherwise be a brochure or PDF.
        ats_here = bool(
            re.search(r"\bhere\b", label)
            and re.search(r"(?:workday|oraclecloud|taleo|brassring|smartrecruiters|icims|successfactors)", candidate, re.I)
        )
        if not (explicit_apply or ats_here):
            continue
        if host and host != source_host and candidate.startswith(("http://", "https://")):
            return candidate
    return None


def _parse_public_detail(html, source, detail_url):
    """Parse only structured/labeled fields from a public board detail page."""
    soup = BeautifulSoup(html, "html.parser")
    schema = _jobposting_schema(soup)
    page_text = _text(soup)
    description = _markup_text(schema.get("description")) if schema else None
    if not description:
        description = _label_value(page_text, "Description")
    description = description or page_text[:2000]
    organization = None
    if schema and isinstance(schema.get("hiringOrganization"), dict):
        organization = schema["hiringOrganization"].get("name")
    organization = organization or _label_value(page_text, "Employer") or _label_value(page_text, "Company")
    title = (schema or {}).get("title") or _text(soup.select_one("h1, h2"))
    location = _schema_location((schema or {}).get("jobLocation"))
    location = location or _label_value(page_text, "Location")
    salary = _schema_salary((schema or {}).get("baseSalary"))
    if not salary:
        salary_candidate = _label_value(page_text, "Salary")
        if salary_candidate and len(salary_candidate) <= 240 and not re.search(
            r"\b(?:will be|conditions|expected to start|students|campuses|business schools)\b",
            salary_candidate, re.I,
        ):
            salary = salary_candidate
    posted = (schema or {}).get("datePosted") or _label_value(page_text, "Date posted")
    if not posted:
        posted_match = re.search(r"\bPosted\s*:?\s*(\d{1,2}/\d{1,2}/20\d{2})\b", page_text, re.I)
        posted = posted_match.group(1) if posted_match else _label_value(page_text, "Posted")
    description_deadline = re.search(
        r"\b(?:application\s+deadline|deadline|closing\s+date|closes|apply\s+by|expires?)\s*:?\s*"
        r"(open\s+until\s+filled|rolling|\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|"
        r"[A-Z][a-z]+\s+\d{1,2}(?:,\s*20\d{2})?)",
        description or "", re.I,
    )
    deadline = description_deadline.group(1).strip() if description_deadline else _label_value(page_text, "Closing date")
    deadline = deadline or _label_value(page_text, "Deadline")
    if deadline:
        date_token = re.search(
            r"\b(?:20\d{2}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]20\d{2}|"
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
            r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s*20\d{2})?|"
            r"\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
            r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+20\d{2})\b",
            str(deadline), re.I,
        )
        if date_token and (len(str(deadline)) > 40 or not re.fullmatch(r"\s*[^\s]+\s+\d{1,2}(?:,\s*20\d{2})?\s*", str(deadline))):
            deadline = date_token.group(0)
        elif len(str(deadline)) > 180 and not re.search(r"\b(?:rolling|open\s+until\s+filled)\b", str(deadline), re.I):
            deadline = None
    education = (schema or {}).get("educationRequirements")
    if isinstance(education, dict):
        education = education.get("credentialCategory") or education.get("name")
    education = education or _label_value(page_text, "Min Education") or _label_value(page_text, "Education Level")
    school = _school_phrase(" ".join(item for item in (organization, description) if item))
    school = re.sub(r"\s+(?:at|@)\s+.*$", "", school or "", flags=re.I).strip(" ,;:-") or None
    institution = _detail_institution(organization, description)
    institution_only_school = False
    if not institution and organization and re.search(
        r"\b(?:business|management|commerce|accounting|finance)\s+(?:school|college)\b",
        organization, re.I,
    ):
        # A standalone business school (CEIBS/emlyon-style) is still an
        # explicit employing institution. Keep the same raw name for the
        # institution and school entity rather than inventing a parent
        # university or returning an unexplained Unknown.
        institution = organization
        institution_only_school = True
    if school and institution:
        school = re.sub(rf"^(?:The\s+)?{re.escape(institution)}\s+", "", school, flags=re.I)
    school = re.sub(r"^The\s+", "", school or "", flags=re.I).strip(" ,;:-") or None
    department = (
        (schema or {}).get("occupationalCategory")
        or _label_value(page_text, "Focus Area")
        or _label_value(page_text, "Job Function")
        or _label_value(page_text, "Discipline")
    )
    application_url = _detail_application_url(soup, detail_url)
    return {
        "title": " ".join(str(title or "").split()).strip(),
        "institution": " ".join(str(institution or "").split()).strip() or None,
        "institution_only_school": institution_only_school,
        "school": school,
        "department": " ".join(str(department or "").split()).strip() or None,
        "location": " ".join(str(location or "").split()).strip() or None,
        "description": description[:2000] if description else None,
        "posted": _iso_day_month_year(str(posted).strip()) if posted else None,
        "deadline": str(deadline).strip() if deadline else None,
        "valid_through": str((schema or {}).get("validThrough") or "").strip() or None,
        "salary": str(salary).strip() if salary else None,
        "official_url": application_url,
        "education": str(education).strip() if education else None,
        "schema": bool(schema),
    }


def _detail_source_job(source, detail_url, fields):
    return SourceJob(
        source=source,
        source_job_id=_stable_id(source, detail_url, fields.get("title")),
        source_url=detail_url,
        official_url=fields.get("official_url"),
        title_raw=fields.get("title") or "",
        institution_raw=fields.get("institution") or "Unknown institution",
        school_raw=fields.get("school"),
        department_raw=fields.get("department"),
        location_raw=fields.get("location"),
        description_excerpt=fields.get("description"),
        posted_date_raw=fields.get("posted"),
        deadline_raw=fields.get("deadline"),
        salary_raw=fields.get("salary"),
        captured_at=now_utc(),
        extra={
            "detail_schema": fields.get("schema", False),
            "detail_institution_explicit": bool(fields.get("institution")),
            "detail_institution_only_school": bool(fields.get("institution_only_school")),
            "detail_education": fields.get("education"),
            "detail_valid_through": fields.get("valid_through"),
            "detail_school_found": bool(fields.get("school")),
            "school_evidence_context": "structured_posting" if fields.get("school") else "unknown",
            "source_jobboard_detail_v1": True,
        },
    )


def _merge_public_detail(listing_job, detail_job):
    detail_extra = detail_job.extra if isinstance(detail_job.extra, dict) else {}
    extra = {**(listing_job.extra if isinstance(listing_job.extra, dict) else {}), **detail_extra}
    detail_schema = bool(detail_extra.get("detail_schema"))
    return replace(
        listing_job,
        official_url=detail_job.official_url or listing_job.official_url,
        title_raw=detail_job.title_raw or listing_job.title_raw,
        institution_raw=(
            detail_job.institution_raw
            if detail_extra.get("detail_institution_explicit") and detail_job.institution_raw != "Unknown institution"
            else ("Unknown institution" if detail_extra.get("detail_institution_explicit") is False else listing_job.institution_raw)
        ),
        school_raw=detail_job.school_raw or listing_job.school_raw,
        department_raw=detail_job.department_raw or listing_job.department_raw,
        location_raw=detail_job.location_raw or listing_job.location_raw,
        description_excerpt=detail_job.description_excerpt or listing_job.description_excerpt,
        posted_date_raw=detail_job.posted_date_raw or listing_job.posted_date_raw,
        # A public JobPosting schema is authoritative for a missing closing
        # date too; this prevents a stale card token from surviving replay.
        deadline_raw=(detail_job.deadline_raw if detail_schema else (detail_job.deadline_raw or listing_job.deadline_raw)),
        salary_raw=detail_job.salary_raw or listing_job.salary_raw,
        extra=extra,
    )


def _enrich_public_details(adapter, response, parser, budget):
    """Fetch a small detail-page budget; retain cards when any detail fails."""
    budget = max(0, min(len(response.jobs), int(budget or 0)))
    if not budget:
        return response
    jobs = list(response.jobs)
    used = 0
    errors = 0
    for index, job in enumerate(jobs):
        if used >= budget:
            break
        try:
            detail = adapter.request(job.source_url)
            parsed = parser(detail.text, detail.url)
            if parsed:
                jobs[index] = _merge_public_detail(job, parsed)
            used += 1
        except Exception:
            errors += 1
        if used < budget:
            time.sleep(max(0.0, float(getattr(adapter, "detail_delay", 0.35))))
    notes = list(response.notes or [])
    notes.append(f"bounded public detail enrichment: {used}/{budget} page(s) attempted")
    if errors:
        notes.append(f"{errors} public detail page(s) failed; listing records were retained")
    return AdapterResponse(dedupe_source_jobs(jobs), pages_fetched=response.pages_fetched + used, notes=notes)


class _PagedBoardAdapter(SourceAdapter):
    """Small common page loop for boards with an HTML next-page link."""

    def _fetch_pages(self, parser):
        jobs = []
        pages = 0
        url = self.base_url
        seen_urls = set()
        notes = []
        while url and pages < self.max_pages and url not in seen_urls and len(jobs) < self.max_items:
            seen_urls.add(url)
            response = self.request(url)
            pages += 1
            soup = BeautifulSoup(response.text, "html.parser")
            page_jobs = parser(soup, response.url)
            jobs.extend(page_jobs)
            next_url = _next_page(soup, response.url)
            if not page_jobs or not next_url:
                break
            url = next_url
        if len(jobs) > self.max_items:
            jobs = jobs[: self.max_items]
        return AdapterResponse(dedupe_source_jobs(jobs), pages_fetched=pages, notes=notes)


class ChronicleAdapter(_PagedBoardAdapter):
    name = "chronicle_business"
    adapter_name = "chronicle_business"
    region = "Global"
    base_url = "https://jobs.chronicle.com/jobs/business-and-management/"
    priority = 20
    max_items = 100
    detail_budget = 12
    detail_delay = 0.35

    @staticmethod
    def parse_html(html, page_url=None, max_items=100):
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        for item in soup.select("li.lister__item"):
            link = item.select_one("h3 a[href*='/job/']") or _first_link(item, r"/job/")
            title = _text(item.select_one("h3"))
            if not link or not title:
                continue
            meta = {}
            for node in item.select("li.lister__meta-item"):
                classes = " ".join(node.get("class") or [])
                meta[classes] = _text(node)
            description = _text(item.select_one(".lister__description"))
            employer = next((value for key, value in meta.items() if "recruiter" in key), "")
            location = next((value for key, value in meta.items() if "location" in key), None)
            salary = next((value for key, value in meta.items() if "salary" in key), None)
            url = urljoin(page_url or ChronicleAdapter.base_url, str(link.get("href") or "").strip())
            jobs.append(_job(
                ChronicleAdapter.name, url, title, employer or "Unknown institution",
                location=location, description=description, salary=salary,
                source_job_id=re.sub(r"^item-", "", str(item.get("id") or ""), flags=re.I) or None,
                school_context="source_employer",
            ))
            if len(jobs) >= max_items:
                break
        return dedupe_source_jobs(jobs)

    def fetch(self):
        response = self._fetch_pages(lambda soup, url: self.parse_html(soup.decode(), url, self.max_items))
        return _enrich_public_details(self, response, self.parse_detail_html, self.detail_budget)

    @staticmethod
    def parse_detail_html(html, detail_url=None):
        fields = _parse_public_detail(html, ChronicleAdapter.name, detail_url or ChronicleAdapter.base_url)
        return _detail_source_job(ChronicleAdapter.name, detail_url or ChronicleAdapter.base_url, fields) if fields.get("title") else None


class AAACareerCenterAdapter(_PagedBoardAdapter):
    name = "aaa_career_center"
    adapter_name = "aaa_career_center"
    region = "Global"
    base_url = "https://careercenter.aaahq.org/jobs"
    priority = 21
    max_items = 100
    detail_budget = 12
    detail_delay = 0.35

    @staticmethod
    def parse_html(html, page_url=None, max_items=100):
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        for item in soup.select("li.lister__item"):
            link = item.select_one("h3 a[href*='/job/']") or _first_link(item, r"/job/")
            title = _text(item.select_one("h3"))
            if not link or not title:
                continue
            meta = {}
            for node in item.select("li.lister__meta-item"):
                meta[" ".join(node.get("class") or [])] = _text(node)
            description = _text(item.select_one(".lister__description"))
            employer = next((value for key, value in meta.items() if "recruiter" in key), "")
            location = next((value for key, value in meta.items() if "location" in key), None)
            salary = next((value for key, value in meta.items() if "salary" in key), None)
            posted = next((value for key, value in meta.items() if "date" in key or "posted" in key), None)
            if not posted:
                match = re.search(r"\b(?:today|yesterday|\d+\s+days?\s+ago|\d+\s+weeks?\s+ago)\b", _text(item), re.I)
                posted = match.group(0) if match else None
            url = urljoin(page_url or AAACareerCenterAdapter.base_url, str(link.get("href") or "").strip())
            jobs.append(_job(
                AAACareerCenterAdapter.name, url, title, employer or "Unknown institution",
                location=location, description=description, salary=salary, posted=posted,
                source_job_id=re.sub(r"^item-", "", str(item.get("id") or ""), flags=re.I) or None,
                school_context="source_employer",
            ))
            if len(jobs) >= max_items:
                break
        return dedupe_source_jobs(jobs)

    def fetch(self):
        response = self._fetch_pages(lambda soup, url: self.parse_html(soup.decode(), url, self.max_items))
        return _enrich_public_details(self, response, self.parse_detail_html, self.detail_budget)

    @staticmethod
    def parse_detail_html(html, detail_url=None):
        fields = _parse_public_detail(html, AAACareerCenterAdapter.name, detail_url or AAACareerCenterAdapter.base_url)
        return _detail_source_job(AAACareerCenterAdapter.name, detail_url or AAACareerCenterAdapter.base_url, fields) if fields.get("title") else None


class POMSAdapter(SourceAdapter):
    name = "poms"
    adapter_name = "poms"
    region = "Global"
    base_url = "https://www.poms.org/opportunities"
    priority = 22
    max_items = 120

    @staticmethod
    def parse_html(html, page_url=None, max_items=120):
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            header = " ".join(_text(cell).casefold() for cell in rows[0].find_all(["th", "td"]))
            if "position" not in header or "university" not in header:
                continue
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                values = [_text(cell) for cell in cells]
                if len(values) < 3 or not values[0] or values[0].casefold() == "position":
                    continue
                link = row.select_one("a[href]")
                href = urljoin(page_url or POMSAdapter.base_url, str(link.get("href") or "").strip()) if link else page_url
                title, employer, posted = values[0], values[1], values[2]
                description = f"Position: {title}. University/employer: {employer}."
                jobs.append(_job(
                    POMSAdapter.name, href, title, employer or "Unknown institution",
                    description=description, posted=posted, source_job_id=_stable_id(POMSAdapter.name, href, title),
                    school_context="source_employer",
                ))
                if len(jobs) >= max_items:
                    return dedupe_source_jobs(jobs)
            break
        return dedupe_source_jobs(jobs)

    def fetch(self):
        response = self.request(self.base_url)
        return AdapterResponse(
            self.parse_html(response.text, response.url, self.max_items),
            pages_fetched=1,
            notes=["POMS public opportunities table includes university and industry postings; faculty-market and business-scope gates are applied downstream."],
        )


class DecisionSciencesAdapter(SourceAdapter):
    name = "decision_sciences"
    adapter_name = "decision_sciences"
    region = "Global"
    base_url = "https://decisionsciences.org/professional-growth/open-positions/"
    priority = 23
    max_items = 100

    @staticmethod
    def parse_html(html, page_url=None, max_items=100):
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        for row in soup.select("table tr"):
            cells = row.find_all(["td", "th"])
            values = [_text(cell) for cell in cells]
            if len(values) < 5 or not values[0] or values[0].casefold() == "posted":
                continue
            link = row.select_one("a[href]")
            official = urljoin(page_url or DecisionSciencesAdapter.base_url, str(link.get("href") or "").strip()) if link else None
            title = re.sub(r"\s*See Details\s*$", "", values[3], flags=re.I).strip()
            institution = values[1]
            location = values[2]
            job_type = values[4]
            area = values[5] if len(values) > 5 else ""
            description = ". ".join(item for item in (
                f"Job type: {job_type}" if job_type else "",
                f"Area of interest: {area}" if area else "",
            ) if item)
            jobs.append(_job(
                DecisionSciencesAdapter.name, page_url or DecisionSciencesAdapter.base_url,
                title, institution, location=location, description=description,
                department=area, posted=values[0], official_url=official,
                source_job_id=_stable_id(DecisionSciencesAdapter.name, official or page_url, f"{institution}|{title}|{values[0]}"),
                school_context="posting",
            ))
            if len(jobs) >= max_items:
                break
        return dedupe_source_jobs(jobs)

    def fetch(self):
        response = self.request(self.base_url)
        return AdapterResponse(self.parse_html(response.text, response.url, self.max_items), pages_fetched=1)


class SMSAdapter(_PagedBoardAdapter):
    name = "sms"
    adapter_name = "sms"
    region = "Global"
    base_url = "https://sms.careerwebsite.com/jobs"
    priority = 24
    max_items = 100
    detail_budget = 12
    detail_delay = 0.35

    @staticmethod
    def parse_html(html, page_url=None, max_items=100):
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()
        for item in soup.select("div.job-tile"):
            item_id = str(item.get("id") or "")
            if not item_id.isdigit():
                for class_name in item.get("class") or []:
                    if str(class_name).startswith("job-tile-"):
                        item_id = str(class_name).split("job-tile-", 1)[-1]
                        break
            if not item_id or not item_id.isdigit():
                continue
            if not item_id or item_id in seen:
                continue
            link = item.select_one("a[href*='/job/']")
            title_link = item.select_one(".job-title a[href*='/job/']")
            title = str(title_link.get("title") or "").strip() if title_link else ""
            if not title:
                title = str((item.select_one("input[name='job_Position']") or {}).get("value") or "").strip()
            if not title:
                title = _text(item.select_one(".job-title"))
            institution = _text(item.select_one(".job-company-row"))
            location = _text(item.select_one(".job-location"))
            posted = _text(item.select_one(".job-posted-date"))
            if not link or not title or not institution:
                continue
            seen.add(item_id)
            url = urljoin(page_url or SMSAdapter.base_url, str(link.get("href") or "").strip())
            jobs.append(_job(
                SMSAdapter.name, url, title, institution, location=location,
                description=f"Employer: {institution}. Location: {location}.",
                posted=posted, source_job_id=item_id, school_context="source_employer",
            ))
            if len(jobs) >= max_items:
                break
        return dedupe_source_jobs(jobs)

    def fetch(self):
        response = self._fetch_pages(lambda soup, url: self.parse_html(soup.decode(), url, self.max_items))
        return _enrich_public_details(self, response, self.parse_detail_html, self.detail_budget)

    @staticmethod
    def parse_detail_html(html, detail_url=None):
        fields = _parse_public_detail(html, SMSAdapter.name, detail_url or SMSAdapter.base_url)
        return _detail_source_job(SMSAdapter.name, detail_url or SMSAdapter.base_url, fields) if fields.get("title") else None


class AcademicJobsOnlineAdapter(SourceAdapter):
    name = "academic_jobs_online"
    adapter_name = "academic_jobs_online"
    region = "Global"
    base_url = "https://academicjobsonline.org/ajo/jobs"
    priority = 26
    max_items = 40

    @staticmethod
    def parse_detail_html(html, detail_url=None):
        soup = BeautifulSoup(html, "html.parser")
        page_text = _text(soup)
        heading = _text(soup.select_one("h2"))
        if not heading:
            return None
        title_match = re.search(r"Position Title:\s*(.*?)\s+Position Type:", page_text, re.I)
        location_match = re.search(r"Position Location:\s*(.*?)\s+\[\s*map\s*\]", page_text, re.I)
        subject_match = re.search(r"Subject Areas?:\s*(.*?)\s+Appl Deadline:", page_text, re.I)
        if not subject_match:
            subject_match = re.search(r"Subject Area:\s*(.*?)\s+Appl Deadline:", page_text, re.I)
        deadline_match = re.search(r"Appl Deadline:\s*(.*?)\s+\(posted", page_text, re.I)
        posted_match = re.search(r"\bposted\s+(20\d{2}/\d{2}/\d{2})", page_text, re.I)
        salary_match = re.search(r"Salary Range:\s*(.*?)(?:\s+Appl Deadline:|\s+Position Description:)", page_text, re.I)
        description_match = re.search(r"Position Description:\s*(.*?)(?:\s+Application Materials Required:|\s+Further Info:|\s+© Academic)", page_text, re.I)
        institution = heading
        school = None
        if "," in heading:
            institution, school_candidate = [part.strip() for part in heading.split(",", 1)]
            if _school_phrase(school_candidate) or re.search(r"\b(?:business|management|commerce)\b", school_candidate, re.I):
                school = school_candidate
            else:
                institution = heading
        title = title_match.group(1).strip() if title_match else heading
        subject = subject_match.group(1).strip() if subject_match else None
        description = description_match.group(1).strip() if description_match else page_text[:1800]
        source_job_id = _stable_id(AcademicJobsOnlineAdapter.name, detail_url, heading)
        return _job(
            AcademicJobsOnlineAdapter.name, detail_url or AcademicJobsOnlineAdapter.base_url,
            title, institution, school=school, department=subject,
            location=location_match.group(1).strip() if location_match else None,
            description=description, posted=posted_match.group(1) if posted_match else None,
            deadline=deadline_match.group(1).strip() if deadline_match else None,
            salary=salary_match.group(1).strip() if salary_match else None,
            source_job_id=source_job_id, school_context="posting",
        )

    @staticmethod
    def listing_urls(html, page_url=None):
        soup = BeautifulSoup(html, "html.parser")
        urls = []
        for link in soup.select("a[href^='/ajo/jobs/']"):
            href = str(link.get("href") or "").strip()
            if re.search(r"/apply(?:/|$)", href, re.I):
                continue
            full = urljoin(page_url or AcademicJobsOnlineAdapter.base_url, href)
            if full not in urls:
                urls.append(full)
        return urls

    def fetch(self):
        response = self.request(self.base_url)
        urls = self.listing_urls(response.text, response.url)[: self.max_items]
        jobs = []
        errors = 0
        for index, url in enumerate(urls):
            if index:
                time.sleep(0.15)
            try:
                detail = self.request(url)
                job = self.parse_detail_html(detail.text, detail.url)
                if job:
                    jobs.append(job)
            except Exception:
                errors += 1
        notes = ["AcademicJobsOnline listing pages are broad; downstream role and business evidence gates exclude non-business fields."]
        if errors:
            notes.append(f"{errors} bounded public detail page(s) failed; other records were retained.")
        return AdapterResponse(dedupe_source_jobs(jobs), pages_fetched=1 + len(jobs), notes=notes)


class AKADEUSAdapter(SourceAdapter):
    name = "akadeus"
    adapter_name = "akadeus"
    region = "Global"
    base_url = "https://akadeus.com/announcements"
    priority = 27
    max_items = 100
    detail_budget = 12
    detail_delay = 0.35

    @staticmethod
    def parse_html(html, page_url=None, max_items=100):
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        for box in soup.select("div.box-2"):
            link = box.select_one("a[href^='/announcement/']") or box.find_parent("a", href=True)
            title = _text(box.select_one("h2"))
            if not link or not title:
                continue
            location = _text(box.select_one("p.location"))
            discipline = _text(box.select_one("p.discipline"))
            params = [_text(item) for item in box.select("div.params p") if _text(item)]
            institution = params[0] if params else "Unknown institution"
            employment = next((item for item in params if item.casefold().startswith("employment type:")), None)
            posted = next((item.split(":", 1)[1].strip() for item in params if item.casefold().startswith("posted:")), None)
            posted = _iso_day_month_year(posted)
            description = ". ".join(item for item in (
                f"Discipline: {discipline}" if discipline else "",
                employment or "",
            ) if item)
            url = urljoin(page_url or AKADEUSAdapter.base_url, str(link.get("href") or "").strip())
            jobs.append(_job(
                AKADEUSAdapter.name, url, title, institution, location=location,
                description=description, department=discipline, posted=posted,
                source_job_id=_stable_id(AKADEUSAdapter.name, url, title),
                school_context="source_employer",
            ))
            if len(jobs) >= max_items:
                break
        return dedupe_source_jobs(jobs)

    def fetch(self):
        response = self.request(self.base_url)
        listing = AdapterResponse(
            self.parse_html(response.text, response.url, self.max_items), pages_fetched=1,
            notes=["AKADEUS exposes a public business-school/academic announcement list; premium/detail access is not required for listing capture."],
        )
        return _enrich_public_details(self, listing, self.parse_detail_html, self.detail_budget)

    @staticmethod
    def parse_detail_html(html, detail_url=None):
        fields = _parse_public_detail(html, AKADEUSAdapter.name, detail_url or AKADEUSAdapter.base_url)
        return _detail_source_job(AKADEUSAdapter.name, detail_url or AKADEUSAdapter.base_url, fields) if fields.get("title") else None


class BlockedPublicSourceAdapter(SourceAdapter):
    """Catalog-only adapter for a public endpoint that currently blocks access."""

    enabled = False
    support_status = "manual"
    method = "public_html"

    def fetch(self):
        return AdapterResponse([], pages_fetched=0, notes=[self.support_reason])


class AACSBJobConnectionAdapter(BlockedPublicSourceAdapter):
    name = "aacsb_career_connection"
    adapter_name = "aacsb_career_connection"
    region = "Global"
    base_url = "https://careerconnection.aacsb.edu/jobs"
    priority = 9
    support_reason = "Bounded public audit returned a Cloudflare challenge; no bypass or private endpoint is used."


class AMAAcademicPlacementAdapter(BlockedPublicSourceAdapter):
    name = "ama_academic_placement"
    adapter_name = "ama_academic_placement"
    region = "Global"
    base_url = "https://academicplacement.ama.org/jobs/"
    priority = 10
    support_reason = "Bounded public audit returned a Cloudflare challenge; no bypass or member/private endpoint is used."


class FMAAdapter(BlockedPublicSourceAdapter):
    name = "fma"
    adapter_name = "fma"
    region = "Global"
    base_url = "https://jobs.fma.org/"
    priority = 11
    support_reason = "Bounded public audit returned a Cloudflare challenge; no bypass or member/private endpoint is used."


class INFORMSAdapter(BlockedPublicSourceAdapter):
    name = "informs"
    adapter_name = "informs"
    region = "Global"
    base_url = "https://careercenter.informs.org/"
    priority = 12
    support_reason = "Bounded public audit returned a Cloudflare challenge; no bypass or private endpoint is used."


class HERCAdapter(BlockedPublicSourceAdapter):
    name = "herc"
    adapter_name = "herc"
    region = "Global"
    base_url = "https://main.hercjobs.org/jobs/explore"
    priority = 28
    support_reason = "The requested HERC endpoint was not a stable public listing during audit; catalogued for manual recheck rather than guessing a replacement endpoint."


class EFMDJobsAdapter(BlockedPublicSourceAdapter):
    name = "efmd_jobs"
    adapter_name = "efmd_jobs"
    region = "Global"
    base_url = "https://jobs.efmdglobal.org/"
    priority = 29
    support_reason = "The public EFMD jobs endpoint was not stably accessible during audit; no member/private endpoint or workaround is used."


__all__ = [
    "ChronicleAdapter", "AAACareerCenterAdapter", "POMSAdapter",
    "DecisionSciencesAdapter", "SMSAdapter", "AcademicJobsOnlineAdapter",
    "AKADEUSAdapter", "AACSBJobConnectionAdapter", "AMAAcademicPlacementAdapter",
    "FMAAdapter", "INFORMSAdapter", "HERCAdapter", "EFMDJobsAdapter",
]
