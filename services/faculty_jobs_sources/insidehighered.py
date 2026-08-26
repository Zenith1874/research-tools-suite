# -*- coding: utf-8 -*-
"""Inside Higher Ed Careers public listing adapter."""

import json
import re
import time
from dataclasses import replace
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .base import (
    AdapterResponse, SourceAdapter, SourceJob, dedupe_source_jobs, detail_excerpt,
    extract_jsonld, now_utc, visible_text,
)


ACADEMIC_TERMS = re.compile(
    r"professor|lecturer|faculty|research|postdoc|dean|academic affairs|business school|"
    r"organizational|information systems|management",
    re.I,
)

# Persist the parser rule that produced a posting-level school value. Older
# normalized source records did not distinguish a vacancy's home unit from a
# later collaborator or cross-appointment.
IHE_SCHOOL_EVIDENCE_RULE_VERSION = "ihe_school_v2"


class InsideHigherEdAdapter(SourceAdapter):
    name = "inside_higher_ed"
    adapter_name = "inside_higher_ed"
    # Inside Higher Ed is a global board.  The search query is deliberately
    # explicit about the user's business-faculty use case; downstream scope
    # classification still decides whether a result belongs in the default
    # business view.
    region = "Global"
    base_url = "https://careers.insidehighered.com/jobs/?keywords=assistant+professor+business"
    search_query = "assistant professor business"
    priority = 18
    # The public result set currently spans 42 pages / roughly 838 matches.
    # Keep this bounded and require an explicit max_pages value greater than
    # one for a full pagination run; the normal scheduler remains one page.
    max_items = 1000
    page_delay = 0.35
    detail_budget = 12
    detail_delay = 0.35

    @classmethod
    def _page_url(cls, page):
        """Build the public numbered result URL without dropping the query."""
        if int(page) <= 1:
            return cls.base_url
        parts = urlsplit(cls.base_url)
        path = parts.path.rstrip("/") + f"/{int(page)}/"
        return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))

    @staticmethod
    def _usable_location(value):
        """Reject department/school labels that a listing card mislabels as location."""
        text = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:-")
        if not text:
            return None
        if re.fullmatch(
            r"(?:the\s+)?(?:college|school|faculty)\s+of\s+business(?:\s+administration)?",
            text, re.I,
        ):
            return None
        return text

    @staticmethod
    def _credible_institution(value):
        """Return whether a candidate contains enough organization evidence.

        IHE's listing template sometimes exposes only the last word of the
        employer (``University``/``College``) in the company slot.  Those
        values must not win over a bounded excerpt fallback.  This helper is
        intentionally conservative: an unknown or incomplete employer is
        preferable to inventing an institution from nearby card chrome.
        """
        text = re.sub(r"\s+", " ", str(value or "")).strip(" ,:-")
        if not text:
            return False
        if text.casefold() in {
            "university", "college", "institute", "polytechnic", "school",
            "community college", "state university", "technical college",
            "college of business", "school of business",
        }:
            return False
        if re.search(
            r"\b(?:general description|job title|full/part time|regular/temporary|"
            r"job id|screen reader|view details|save)\b", text, re.I,
        ):
            return False
        if not re.search(r"\b(?:university|college|institute|polytechnic)\b", text, re.I):
            return False
        return len(text.split()) >= 2

    @staticmethod
    def _clean_institution_value(value, location_hint=None):
        """Trim card chrome/location prefixes from an explicit employer value."""
        text = re.sub(r"\s+", " ", str(value or "")).strip(" ,:-")
        if not text:
            return None
        if location_hint:
            location = re.sub(r"\s+", " ", str(location_hint or "")).strip(" ,:-")
            if location and text.casefold().startswith(location.casefold() + " "):
                tail = text[len(location):].strip(" ,:-")
                # Do not turn legitimate employers such as ``Augusta
                # University`` or ``Kennesaw State University`` into the
                # generic value ``University``/``State University`` merely
                # because the city is also a prefix.  Strip a location only
                # when the remaining phrase is itself a credible employer.
                if InsideHigherEdAdapter._credible_institution(tail):
                    text = tail
        # A detail employer can concatenate a department before the actual
        # university (``Health Sciences The Ohio State University``).
        the_positions = [match.start() for match in re.finditer(r"\bThe\s+", text)]
        if the_positions:
            suffix = text[the_positions[-1]:].strip(" ,:-")
            if re.search(r"\b(?:University|College|Institute|Polytechnic)\b", suffix):
                text = suffix
        text = re.split(
            r"\s+(?:General\s+Description|Description|Job\s+Title|Full/Part\s+Time|"
            r"Regular/Temporary|View|Save)\b",
            text, maxsplit=1, flags=re.I,
        )[0].strip(" ,:-")
        text = re.sub(
            r"^(.+?\bUniversity)\s+(?:School|College|Faculty)\s+of\b.*$",
            r"\1", text, flags=re.I,
        ).strip(" ,:-")
        # Card templates can repeat a complete employer around a department
        # or location token.  Collapse exact token-level repetition before
        # trying to interpret the organization marker.
        tokens = text.split()
        for size in range(1, len(tokens) // 2 + 1):
            if tokens[:size] == tokens[size:size * 2]:
                remainder = tokens[size * 2:]
                if not remainder or " ".join(remainder).casefold() in {"the", "a", "an"}:
                    text = " ".join(tokens[:size])
                    break
        # A clipped company label may precede the full employer, e.g.
        # ``Community College Austin Community College`` or
        # ``State University Kennesaw State University``.  Remove the
        # generic prefix only when another complete organization follows.
        text = re.sub(
            r"^(?:Community|Technical)\s+College\s+(?=[A-Z].*\bCollege\b)",
            "", text,
        ).strip(" ,:-")
        text = re.sub(
            r"^State\s+University\s+(?=[A-Z].*\bUniversity\b)",
            "", text,
        ).strip(" ,:-")
        # Common portal labels can precede a real college name.  Remove them
        # only when another organization marker remains, so legitimate names
        # such as ``College of New Jersey`` are untouched.
        text = re.sub(
            r"^(?:College|School|Faculty|State\s+Recruiting\s+Loc)\s+"
            r"(?=[A-Z].*\b(?:University|College|Institute|Polytechnic)\b)",
            "", text, flags=re.I,
        ).strip(" ,:-")
        return text or None

    @staticmethod
    def _institution_from_text(text, title="", location_hint=None):
        """Recover an explicit organization phrase, never a location label."""
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        if title:
            value = value.replace(title, " ")
        # IHE cards often concatenate the employer with the next UI label:
        # ``The Ohio State University Screen reader users`` or
        # ``Lebanese American University Disciplines: Management``.  The old
        # lookahead required whitespace before ``$`` and therefore rejected a
        # valid institution at the end of the excerpt.  Keep the boundary
        # explicit and include the labels used by both listing and detail
        # templates.
        stop = r"(?=\s+(?:Job|Title|Requisition|Department|Position|Number|Work|Location|Type|Categories|View|Save|Chair|Assistant|Associate|Full|Professor|Lecturer|Postdoctoral|Research|Part|Time|Regular|Temporary|Extended|No|Screen|For|If|Disciplines|Campuses|Starting|Employer|Institution)\b|$)"
        patterns = (
            re.compile(r"\b(?:University|College|Institute|Polytechnic)"
                       r"(?:\s+(?:of|at|and|the)\s+[A-Z][A-Za-z0-9.&'’\-]+|\s+[A-Z][A-Za-z0-9.&'’\-]+){0,6}" + stop),
            re.compile(r"\b(?:[A-Z][A-Za-z0-9.&'’\-]+\s+){1,5}"
                       r"(?:University|College|Institute|Polytechnic)"
                       r"(?:\s+(?:of|at|and|the)\s+[A-Z][A-Za-z0-9.&'’\-]+|\s+[A-Z][A-Za-z0-9.&'’\-]+){0,5}" + stop),
        )
        candidates = []
        metadata = re.compile(
            r"\s+(?:Job|Title|Requisition|Department|Position|Number|Work|Location|Type|"
            r"Categories|View|Save|Chair|Assistant|Associate|Full|Professor|Lecturer|"
            r"Postdoctoral|Research|Extended|No|DACI)\b.*$",
            re.I,
        )
        leading_location = re.compile(
            r"^(?:Atlanta|Lexington|Greenville|Gainesville|Stanford|Columbia|Augusta|"
            r"Amarillo|Edwardsville|Tuen\s+Mun|Hong\s+Kong|[A-Z]{2})\s+",
            re.I,
        )
        for pattern in patterns:
            for match in pattern.finditer(value):
                candidate = re.sub(r"\s+", " ", match.group(0)).strip(" ,:-")
                candidate = metadata.sub("", candidate).strip(" ,:-")
                # Keep a possible location prefix for names such as Augusta
                # University and Kennesaw State University.  The cleaner
                # below removes it only when the suffix is an independent,
                # credible organization.
                candidate = re.sub(r"^.+?\bCampus\s+(?=(?:The\s+)?[A-Z])", "", candidate, flags=re.I).strip(" ,:-")
                candidate = InsideHigherEdAdapter._clean_institution_value(candidate, location_hint)
                if not InsideHigherEdAdapter._credible_institution(candidate):
                    continue
                candidate = re.sub(r"^(?:College\s+of\s+Business\s+Administration|Business\s+Administration)\s+", "", candidate, flags=re.I)
                candidate = re.sub(r"\s+(?:College|School|Faculty)\s+of\s+Business(?:\s+Administration)?$", "", candidate, flags=re.I).strip(" ,:-")
                candidate = re.sub(r"^University\s+(?=[A-Z].*\bUniversity\b)", "", candidate)
                # A duplicated city/state token can precede the actual
                # institution in a listing card (e.g. ``Georgia Georgia
                # Institute``).  Remove only an exact repeated first token.
                words = candidate.split()
                for size in range(1, len(words) // 2 + 1):
                    if words[:size] == words[size:size * 2] and size * 2 == len(words):
                        candidate = " ".join(words[:size])
                        words = candidate.split()
                        break
                if len(words) >= 2 and words[0].casefold() == words[1].casefold():
                    candidate = " ".join(words[1:])
                if len(words) >= 2 and re.fullmatch(r"[A-Z]{2}", words[0]) and words[1].casefold() in {"university", "college", "institute", "polytechnic"}:
                    candidate = " ".join(words[1:])
                lower = candidate.casefold()
                if not candidate or re.search(r"\b(?:school|department)\s+of\s+business\b", lower):
                    continue
                if re.fullmatch(r"(?:college|school)\s+of\s+business(?:\s+administration)?", lower):
                    continue
                # Removing a trailing business-school label can leave only a
                # department fragment (for example ``Haslam``). Do not let
                # that fragment suppress the punctuation-delimited
                # ``University of ...`` fallback below.
                if not InsideHigherEdAdapter._credible_institution(candidate):
                    continue
                candidates.append(candidate)
        # Some detail excerpts place punctuation between the university and
        # its campus/business-school suffix (for example ``The University of
        # Tennessee, Knoxville, Haslam College of Business``). The stricter
        # organization patterns above intentionally stop at punctuation, so
        # retain a bounded ``University of ...`` fallback for that common
        # explicit structure. It never treats a city or arbitrary capitalized
        # phrase as an institution.
        if not candidates:
            fallback = re.compile(
                r"\b(?:The\s+)?University\s+of\s+[A-Z][A-Za-z0-9.&'’\-]*"
                r"(?:\s+[A-Z][A-Za-z0-9.&'’\-]*){0,7}?"
                r"(?=\s*[,.;]|\s+(?:[A-Z][A-Za-z0-9.&'’\-]+\s+)?"
                r"(?:University|College|Institute|Polytechnic|School|Faculty|Department)\b|$)",
            )
            for match in fallback.finditer(value):
                candidate = re.sub(r"\s+", " ", match.group(0)).strip(" ,:-")
                candidate = re.sub(r"^The\s+", "", candidate, flags=re.I)
                candidate = InsideHigherEdAdapter._clean_institution_value(candidate, location_hint)
                if InsideHigherEdAdapter._credible_institution(candidate):
                    candidates.append(candidate)
        # Some cards concatenate a department label and organization without
        # punctuation.  These bounded explicit organization shapes recover
        # the institution while still refusing arbitrary capitalized text.
        for pattern in (
            r"\bEast\s+Carolina\s+University\b",
            r"\bSam\s+Houston\s+State\s+University\b",
            r"\bLingnan\s+University\b",
        ):
            candidates.extend(re.findall(pattern, value, re.I))
        if not candidates:
            return None
        # Prefer a complete ``University of X`` phrase over a location token
        # prepended to it; otherwise retain the longest explicit organization
        # phrase after the metadata stop words above.
        university_of = [item for item in candidates if re.match(r"^University\s+of\b", item, re.I)]
        selected = max(university_of or candidates, key=len)
        selected = InsideHigherEdAdapter._clean_institution_value(selected, location_hint)
        return selected if InsideHigherEdAdapter._credible_institution(selected) else None

    @staticmethod
    def _detail_description(soup, structured_item=None):
        """Return the public JobPosting description as normalized text.

        Detail pages expose a much better description in JSON-LD than in the
        visible card chrome.  It is used only for bounded field extraction;
        callers store a short evidence excerpt rather than the full posting.
        """
        value = (structured_item or {}).get("description") if isinstance(structured_item, dict) else None
        if not value:
            return ""
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        return visible_text(BeautifulSoup(str(value), "html.parser"))

    @staticmethod
    def _bounded_detail_excerpt(description, fallback, max_chars=2000):
        """Keep a small set of field-bearing excerpts, never full third-party text."""
        text = re.sub(r"\s+", " ", str(description or fallback or "")).strip()
        if not text:
            return None
        if len(text) <= max_chars:
            return text
        chunks = [text[:1100]]
        labels = re.compile(
            r"(?:department|school|college|salary|base salary|deadline|closing|"
            r"review of applications|starting date|start date|ph\.d|visa|sponsorship|"
            r"how to apply|application materials)", re.I,
        )
        for match in labels.finditer(text):
            start = max(0, match.start() - 90)
            end = min(len(text), match.end() + 360)
            chunk = text[start:end].strip()
            if chunk and chunk not in chunks:
                chunks.append(chunk)
            if sum(len(item) for item in chunks) >= max_chars:
                break
        excerpt = " … ".join(chunks)
        return excerpt[:max_chars]

    @staticmethod
    def _detail_field(description, pattern, limit=240):
        match = re.search(pattern, description or "", re.I)
        if not match:
            return None
        value = re.sub(r"\s+", " ", match.group(1)).strip(" \t:;-—")
        return value[:limit] or None

    @classmethod
    def _detail_deadline(cls, description):
        """Return only a deadline window supported by posting text.

        JobPosting ``validThrough`` is a board/listing expiry field.  Inside
        Higher Ed frequently sets it years in the future even when the
        employer says applications are rolling or gives no closing date.  It
        must not be promoted to an application deadline without nearby
        ``deadline``/``closing``/``apply by`` evidence in the public detail
        description.
        """
        text = re.sub(r"\s+", " ", str(description or "")).strip()
        if not text:
            return None
        cue = re.compile(
            r"\b(?:application\s+deadline|applications?\s+(?:will\s+be\s+)?accepted|"
            r"deadline|closing(?:\s+date)?|"
            r"closes|apply\s+by|expires?|posting\s+closes)\b",
            re.I,
        )
        date_signal = re.compile(
            r"\b(?:20\d{2}|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|"
            r"may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
            r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b|"
            r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
            re.I,
        )
        for match in cue.finditer(text):
            window = text[match.start():match.end() + 220]
            if re.search(
                r"until\s+(?:the\s+)?(?:position|job)\s+is\s+filled|"
                r"open\s+until\s+filled|rolling|no\s+fixed\s+deadline",
                window, re.I,
            ):
                # Preserve the explicit rolling/open-until-filled evidence;
                # the normalizer will classify the mode without inventing a
                # calendar date.
                return window[:300]
            if date_signal.search(window):
                return window[:300]
        return None

    @classmethod
    def _detail_school(cls, description):
        # Only accept explicit business-school shapes.  A generic capitalized
        # phrase is not enough to create a school entity.
        # IHE detail descriptions commonly begin with the portal label
        # ``Description`` or ``Job Description``.  That label is not part of
        # the university unit and must never leak into School Explorer.
        description = re.sub(r"\b(?:Job\s+)?Description\s+", "", description or "", count=1, flags=re.I)
        # Prefer the structured faculty/division and department metadata that
        # appears at the start of many IHE descriptions.  This prevents an
        # unrelated cross-appointment mentioned later (for example Rotman in
        # a University of Toronto Scarborough posting) from being promoted to
        # the job's primary business school.
        metadata = re.search(
            r"\bFaculty/Division:\s*(?P<division>.+?)\s+Department:\s*(?P<department>.+?)\s+Campus:\s*",
            description, re.I,
        )
        if metadata:
            for candidate in (metadata.group("division"), metadata.group("department")):
                candidate = re.sub(r"\s+Job\s+Category:.*$", "", candidate, flags=re.I).strip(" ,.;:-")
                if re.search(r"\b(?:College|School|Faculty)\s+of\s+(?:Business|Management|Commerce)\b", candidate, re.I):
                    return re.sub(r"^The\s+", "", candidate, flags=re.I).strip()
            # Structured faculty/division metadata is authoritative for the
            # primary unit.  If it names a general campus/department and does
            # not expose a business school, do not fall through to a later
            # cross-appointment mention in the free-text description.
            return None
        # A posting can name a non-business home unit in the invitation and
        # list a business school later among university collaborators.  The
        # first explicit recruiting-unit clause outranks those later names.
        # The public IHE detail excerpt is capped at 2,000 characters.  Some
        # Workday-backed postings place the recruiting unit after a long
        # application portal preamble (for example, ``Fisher College of
        # Business`` appears just beyond character 1,200).  Inspect the full
        # bounded excerpt so a real school is not downgraded to Unknown; the
        # explicit recruiting-unit and collaborator guards below still apply.
        bounded = (description or "")[:2000]
        recruiting_clause = re.search(
            r"(?P<unit>.{0,260}?)\b(?:invites?\s+(?:applications?|applicants?)|"
            r"seeks?\s+(?:applications?|applicants?|candidates?)|"
            r"is\s+accepting\s+applications?)\b",
            bounded,
            re.I,
        )
        if recruiting_clause:
            unit_text = recruiting_clause.group("unit")
            nonbusiness_unit = re.search(
                r"\b(?:school|college|faculty)\s+of\s+(?:medicine|engineering|"
                r"arts?(?:\s+(?:and|&)\s+sciences?)?|sciences?|education|"
                r"health\s+sciences?)\b|\bthayer\s+school\s+of\s+engineering\b|"
                r"\bgeisel\s+school\s+of\s+medicine\b",
                unit_text,
                re.I,
            )
            business_unit = re.search(
                r"\b(?:College|School|Faculty)\s+of\s+(?:Business|Management|Commerce)\b",
                unit_text,
                re.I,
            )
            if nonbusiness_unit and not business_unit:
                return None

        # Without structured faculty/division metadata, accept a school name
        # only near the beginning of the bounded posting or next to an explicit
        # appointment/unit cue.  A business school mentioned later as a
        # collaborator or cross-appointment is not the vacancy's home unit.
        matches = list(re.finditer(
            r"((?:The\s+)?(?:[A-Z][A-Za-z0-9.&'’\-/]+\s+){0,6}"
            r"(?:College|School|Faculty)\s+of\s+(?:Business|Management|Commerce)"
            r"(?:\s+[A-Z][A-Za-z0-9.&'’\-/]+){0,3})",
            bounded,
        ))
        match = None
        for candidate in matches:
            prefix = bounded[max(0, candidate.start() - 180):candidate.start()]
            suffix = bounded[candidate.end():candidate.end() + 180]
            local_context = prefix + candidate.group(0) + suffix
            if re.search(
                r"\b(?:cross[- ]appoint|collaborat|partner(?:ship)?|affiliat|"
                r"work(?:ing)?\s+with\s+colleagues?)\b",
                local_context,
                re.I,
            ):
                continue
            nearby_unit_cue = re.search(
                r"\b(?:faculty/division|department|appointment|position|vacancy|"
                r"join|home\s+unit|housed|based)\b.{0,80}$",
                prefix,
                re.I,
            )
            school_action = re.search(
                r"^.{0,90}\b(?:invites?\s+applications?|seeks?|is\s+accepting\s+applications?|"
                r"has\s+an?\s+(?:opening|vacancy))\b",
                suffix,
                re.I,
            )
            if candidate.start() <= 240 or nearby_unit_cue or school_action:
                match = candidate
                break
        if match is None:
            return None
        value = re.sub(r"\s+", " ", match.group(1)).strip(" ,.;:-")
        if re.search(r"[’']s\s+", value):
            value = re.split(r"[’']s\s+", value, maxsplit=1)[-1]
        value = re.sub(r"^The\s+", "", value, flags=re.I)
        return value.strip(" ,.;:-") or None

    @staticmethod
    def _structured_fields(soup):
        records = extract_jsonld(soup)
        item = records[0] if records else {}
        org = item.get("hiringOrganization") if isinstance(item, dict) else None
        if isinstance(org, dict):
            institution = org.get("name")
        else:
            institution = org if isinstance(org, str) else None
        location = item.get("jobLocation") if isinstance(item, dict) else None
        if isinstance(location, list):
            location = location[0] if location else None
        if isinstance(location, dict):
            address = location.get("address") or {}
            location = ", ".join(str(part) for part in (
                address.get("addressLocality"), address.get("addressRegion"),
                address.get("addressCountry"),
            ) if part)
        institution = InsideHigherEdAdapter._clean_institution_value(institution, location) or institution
        description = InsideHigherEdAdapter._detail_description(soup, item)
        salary = item.get("baseSalary") if isinstance(item, dict) else None
        if not salary:
            salary = InsideHigherEdAdapter._detail_field(
                description,
                r"(?:base\s+salary|salary(?:\s+range)?|compensation)\s*(?:is|of|between|range|:|-)?\s*([^.;]{3,160})",
            )
        department = InsideHigherEdAdapter._detail_field(
            description,
            r"\bDepartment\s*:\s*(.{2,180}?)(?=\s+The\s+Department\b|\s+[A-Z][A-Za-z ]{0,32}:|$)",
        )
        school = InsideHigherEdAdapter._detail_school(description)
        deadline = InsideHigherEdAdapter._detail_deadline(description)
        if isinstance(location, str) and re.fullmatch(r"[A-Z]{2}", location.strip()):
            campus = InsideHigherEdAdapter._detail_field(
                description,
                r"\bCampuses?\s*:\s*(.{2,160}?)(?=\s+(?:Starting|Start|Department|Job|The)\b|$)",
            )
            if campus:
                location = campus
        return {
            "institution": institution,
            "location": location,
            "salary": salary,
            "posted": item.get("datePosted") if isinstance(item, dict) else None,
            # ``validThrough`` is intentionally retained only as parser
            # context, never as an application deadline.  The normalized
            # deadline must come from explicit detail-text evidence.
            "deadline": deadline,
            "jobposting_schema": bool(item),
            "department": department,
            "school": school,
            "description": description,
        }

    def _enrich_detail(self, job):
        try:
            response = self.request(job.source_url)
            soup = BeautifulSoup(response.text, "html.parser")
            time.sleep(max(0.0, float(self.detail_delay)))
            fields = self._structured_fields(soup)
            institution = fields.get("institution") or self._institution_from_text(
                visible_text(soup), job.title_raw, fields.get("location"))
            location = self._usable_location(fields.get("location"))
            if not location:
                location = next((visible_text(soup.select_one(selector)) for selector in (
                    '[itemprop="jobLocation"]', '.job-location', '.lister__meta-item--location',
                ) if self._usable_location(visible_text(soup.select_one(selector)))), None)
            official = None
            for link in soup.find_all("a", href=True):
                label = visible_text(link).casefold()
                candidate = urljoin(job.source_url, link.get("href", ""))
                if "apply" in label and candidate.startswith(("http://", "https://")) and "insidehighered.com" not in candidate:
                    official = candidate
                    break
            salary = fields.get("salary")
            if isinstance(salary, dict):
                value = salary.get("value")
                if isinstance(value, dict):
                    low = value.get("minValue") or value.get("value")
                    high = value.get("maxValue")
                    currency = value.get("currency") or salary.get("currency")
                    salary = f"{low}-{high} {currency or ''}".strip() if high else f"{low} {currency or ''}".strip()
                else:
                    salary = value or salary.get("minValue")
            return replace(
                job,
                institution_raw=institution or job.institution_raw,
                # When a public JSON-LD detail page is available, an absent
                # explicit school is evidence that the listing did not expose
                # one.  Clear stale card-derived school text rather than
                # carrying a cross-appointment or UI fragment forward.
                school_raw=(fields.get("school") if fields.get("jobposting_schema") else job.school_raw),
                department_raw=fields.get("department") or job.department_raw,
                location_raw=location or self._usable_location(job.location_raw),
                salary_raw=str(salary) if salary else job.salary_raw,
                posted_date_raw=fields.get("posted") or job.posted_date_raw,
                # A valid JobPosting schema lets us clear a stale listing
                # expiry value when the detail text has no real deadline.
                # If no schema was available, preserve the listing value.
                deadline_raw=(fields.get("deadline") if fields.get("jobposting_schema") else job.deadline_raw),
                official_url=official or job.official_url,
                extra={
                    **(job.extra if isinstance(job.extra, dict) else {}),
                    "detail_schema": bool(fields.get("jobposting_schema")),
                    "detail_school_found": bool(fields.get("school")),
                    "school_evidence_context": "structured_posting" if fields.get("school") else "unknown",
                    "school_evidence_rule_version": IHE_SCHOOL_EVIDENCE_RULE_VERSION,
                },
                description_excerpt=self._bounded_detail_excerpt(
                    fields.get("description"), detail_excerpt(soup), max_chars=2000,
                ) or job.description_excerpt,
            )
        except Exception:
            # A detail failure must not discard the listing card.
            return job

    def fetch(self):
        jobs = []
        detail_budget = max(0, min(self.max_items, int(self.detail_budget)))
        detail_used = 0
        notes = []
        pages_fetched = 0
        cards_seen = 0
        reported_total = None
        page_limit = max(1, min(50, int(self.max_pages)))
        limit_reached = False
        for page in range(1, page_limit + 1):
            page_url = self._page_url(page)
            try:
                response = self.request(page_url)
            except Exception as exc:
                # The first page is required for a valid source run.  A later
                # page failure should preserve the successfully fetched prefix
                # and make the partial coverage visible to the run metadata.
                if page == 1:
                    raise
                notes.append(f"pagination stopped at page {page}: {str(exc)[:180]}")
                break
            pages_fetched += 1
            soup = BeautifulSoup(response.text, "html.parser")
            cards = soup.select("li.lister__item")
            if not cards:
                break
            cards_seen += len(cards)
            if reported_total is None:
                page_text = soup.get_text(" ", strip=True)
                total_match = re.search(r"\bFound\s+([\d,]+)\s+jobs?\b", page_text, re.I)
                if total_match:
                    reported_total = int(total_match.group(1).replace(",", ""))
            for card in cards:
                anchor = card.select_one('a[href*="/job/"]')
                if not anchor:
                    continue
                title = visible_text(anchor)
                # The public search result itself is the acquisition boundary.
                # Keep every parseable job card in the source-record/audit
                # layer; normalized business/academic scope decides what is
                # visible in the default market view.
                if not title:
                    continue
                href = urljoin(page_url, anchor.get("href", "").strip())
                match = re.search(r"/job/(\d+)/", href)
                if not match:
                    continue
                location = self._usable_location(visible_text(card.select_one(".lister__meta-item--location")))
                institution = None
                for selector in (
                    '[itemprop="hiringOrganization"] [itemprop="name"]',
                    '[itemprop="hiringOrganization"]', '.lister__meta-item--company',
                    '.lister__meta-item--employer', '.lister__item__company',
                    '[class*="institution"]', '[class*="employer"]',
                ):
                    candidate = visible_text(card.select_one(selector))
                    if candidate and candidate != location:
                        institution = candidate
                        break
                structured = self._structured_fields(card)
                missing_institution = not institution
                institution = institution or structured.get("institution") or self._institution_from_text(
                    detail_excerpt(card), title, location)
                posted = structured.get("posted") or visible_text(card.select_one(
                    '[itemprop="datePosted"], .lister__meta-item--date, .job-posted-date'
                ))
                deadline = structured.get("deadline") or visible_text(card.select_one(
                    '[itemprop="validThrough"], .job-deadline, .lister__meta-item--deadline'
                ))
                salary = structured.get("salary") or visible_text(card.select_one(
                    '[itemprop="baseSalary"], .lister__meta-item--salary, .job-salary'
                ))
                job = SourceJob(
                    source=self.name,
                    source_job_id=match.group(1),
                    source_url=href,
                    title_raw=title,
                    institution_raw=institution or "Unknown institution",
                    location_raw=location,
                    description_excerpt=detail_excerpt(card),
                    posted_date_raw=posted,
                    deadline_raw=deadline,
                    salary_raw=str(salary) if salary else None,
                    captured_at=now_utc(),
                    extra={"search_query": self.search_query},
                )
                if detail_used < detail_budget and (missing_institution or not salary):
                    job = self._enrich_detail(job)
                    detail_used += 1
                jobs.append(job)
                if len(jobs) >= self.max_items:
                    limit_reached = True
                    break
            if limit_reached:
                notes.append(f"bounded at max_items={self.max_items}")
                break
            if page < page_limit:
                time.sleep(max(0.0, float(self.page_delay)))
        unique_jobs = dedupe_source_jobs(jobs)
        if reported_total is not None:
            notes.insert(0, (
                f"public search reported {reported_total} matches; observed {cards_seen} listing cards "
                f"and retained {len(unique_jobs)} parseable job records across {pages_fetched} page(s)"
            ))
            if len(unique_jobs) < reported_total:
                notes.append(
                    "The reported search total exceeded parseable listing cards; missing cards were not "
                    "fabricated and remain outside the source-record set."
                )
        return AdapterResponse(unique_jobs, pages_fetched=pages_fetched, notes=notes)


def parse_fixture(html):
    adapter = InsideHigherEdAdapter(max_pages=1)
    adapter.detail_delay = 0
    from unittest.mock import patch
    with patch.object(adapter, "request") as request:
        request.return_value.text = html
        return adapter.fetch().jobs
