# -*- coding: utf-8 -*-
"""Rule-based normalization for academic faculty job records.

The module keeps source text and evidence separate from normalized fields.  It
does not use an LLM, infer visa sponsorship from institution characteristics,
or convert European ranks into US ranks.
"""

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from services.faculty_jobs_rank_mapper import map_rank


DISCIPLINES = (
    "Management",
    "Organizational Behavior / HR",
    "Strategy",
    "Entrepreneurship",
    "Information Systems / MIS",
    "Business Analytics / AI",
    "Marketing",
    "Finance",
    "Accounting",
    "Operations / Supply Chain",
    "International Business",
    "General Business",
    "Other",
)

COUNTRY_ALIASES = {
    "us": ("United States", "US", "USA", "U.S.", "U.S.A.", "America"),
    "ca": ("Canada", "CA"),
    "gb": ("United Kingdom", "UK", "GB", "England", "Scotland", "Wales", "Northern Ireland"),
    "ie": ("Ireland", "IE", "Republic of Ireland"),
    "fr": ("France", "FR"),
    "de": ("Germany", "DE", "Deutschland"),
    "nl": ("Netherlands", "NL", "The Netherlands", "Holland"),
    "be": ("Belgium",),
    "ch": ("Switzerland",),
    "at": ("Austria",),
    "es": ("Spain",),
    "it": ("Italy",),
    "dk": ("Denmark",),
    "se": ("Sweden",),
    "no": ("Norway",),
    "fi": ("Finland",),
    "pt": ("Portugal",),
    "au": ("Australia",),
    "nz": ("New Zealand", "NZ"),
    "bd": ("Bangladesh", "BD"),
    "tr": ("Turkey", "Türkiye", "Turkiye", "TR"),
    "in": ("India", "IN"),
    "vn": ("Vietnam", "Viet Nam", "VN"),
    "my": ("Malaysia", "MY"),
    "th": ("Thailand", "TH"),
    "id": ("Indonesia", "ID"),
    "tw": ("Taiwan", "TW"),
    "ph": ("Philippines", "PH"),
    "pk": ("Pakistan", "PK"),
    "bn": ("Brunei Darussalam", "Brunei", "BN"),
    "mo": ("Macau SAR", "Macau", "Macao", "MO"),
    "bh": ("Bahrain", "BH"),
    "kw": ("Kuwait", "KW"),
    "om": ("Oman", "OM"),
    "jo": ("Jordan", "JO"),
    "lb": ("Lebanon", "LB"),
    "za": ("South Africa", "ZA"),
    "ng": ("Nigeria", "NG"),
    "eg": ("Egypt", "EG"),
    "ma": ("Morocco", "MA"),
    "tn": ("Tunisia", "TN"),
    "ar": ("Argentina", "AR"),
    "br": ("Brazil", "BR"),
    "cl": ("Chile", "CL"),
    "co": ("Colombia", "CO"),
    "mx": ("Mexico", "MX"),
    "pe": ("Peru", "PE"),
    "ve": ("Venezuela", "VE"),
    "cy": ("Cyprus", "CY"),
    "hr": ("Croatia", "HR"),
    "hu": ("Hungary", "HU"),
    "lt": ("Lithuania", "LT"),
    "li": ("Liechtenstein", "LI"),
    "lu": ("Luxembourg", "LU"),
    "mc": ("Monaco", "MC"),
    "pl": ("Poland", "PL"),
    "ro": ("Romania", "RO"),
    "si": ("Slovenia", "SI"),
    "ba": ("Bosnia and Herzegovina", "BA"),
    "sg": ("Singapore",),
    "hk": ("Hong Kong",),
    "cn": ("China", "Mainland China"),
    "jp": ("Japan",),
    "kr": ("South Korea", "Republic of Korea", "Korea"),
    "ae": ("United Arab Emirates", "UAE"),
    "qa": ("Qatar",),
    "sa": ("Saudi Arabia", "SA"),
    "il": ("Israel",),
}

# Country display names and ISO-2 filter values are maintained here so that
# adapters, API filters, exports, and UI controls use the same vocabulary.
COUNTRY_OPTIONS = tuple(
    {"code": code.upper(), "label": aliases[0]}
    for code, aliases in COUNTRY_ALIASES.items()
)
_COUNTRY_DISPLAY_TO_CODE = {
    alias.casefold(): code
    for code, aliases in COUNTRY_ALIASES.items()
    for alias in aliases
}
# ``CA`` is ambiguous in a location card (Canada versus California).  The
# location parser resolves state/province evidence first; API filters still
# treat the standalone code as Canada through ``country_code_for``.
_UNAMBIGUOUS_CODE_ALIASES = set(COUNTRY_ALIASES) - {"ca"}
REGION_GROUPS = {
    "United States": "United States",
    "Canada": "Canada",
    "United Kingdom": "Europe",
    "Ireland": "Europe",
    "France": "Europe",
    "Germany": "Europe",
    "Netherlands": "Europe",
    "Belgium": "Europe",
    "Switzerland": "Europe",
    "Austria": "Europe",
    "Spain": "Europe",
    "Italy": "Europe",
    "Denmark": "Europe",
    "Sweden": "Europe",
    "Norway": "Europe",
    "Finland": "Europe",
    "Portugal": "Europe",
    "Australia": "Australia / New Zealand",
    "New Zealand": "Australia / New Zealand",
    "Turkey": "Europe",
    "India": "Asia-Pacific",
    "Vietnam": "Asia-Pacific",
    "Malaysia": "Asia-Pacific",
    "Thailand": "Asia-Pacific",
    "Indonesia": "Asia-Pacific",
    "Taiwan": "Asia-Pacific",
    "Philippines": "Asia-Pacific",
    "Pakistan": "Asia-Pacific",
    "Brunei Darussalam": "Asia-Pacific",
    "Macau SAR": "Asia-Pacific",
    "Bangladesh": "Asia-Pacific",
    "Singapore": "Asia-Pacific",
    "Hong Kong": "Asia-Pacific",
    "China": "Asia-Pacific",
    "Japan": "Asia-Pacific",
    "South Korea": "Asia-Pacific",
    "United Arab Emirates": "Middle East",
    "Qatar": "Middle East",
    "Saudi Arabia": "Middle East",
    "Israel": "Middle East",
    "Bahrain": "Middle East",
    "Kuwait": "Middle East",
    "Oman": "Middle East",
    "Jordan": "Middle East",
    "Lebanon": "Middle East",
    "South Africa": "Africa",
    "Nigeria": "Africa",
    "Egypt": "Africa",
    "Morocco": "Africa",
    "Tunisia": "Africa",
    "Argentina": "Latin America",
    "Brazil": "Latin America",
    "Chile": "Latin America",
    "Colombia": "Latin America",
    "Mexico": "Latin America",
    "Peru": "Latin America",
    "Venezuela": "Latin America",
    "Cyprus": "Europe",
    "Croatia": "Europe",
    "Hungary": "Europe",
    "Lithuania": "Europe",
    "Liechtenstein": "Europe",
    "Luxembourg": "Europe",
    "Monaco": "Europe",
    "Poland": "Europe",
    "Romania": "Europe",
    "Slovenia": "Europe",
    "Bosnia and Herzegovina": "Europe",
}

STATE_PROVINCE_ALIASES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
    "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
    "Alberta": "AB", "British Columbia": "BC", "Manitoba": "MB", "New Brunswick": "NB",
    "Newfoundland and Labrador": "NL", "Nova Scotia": "NS", "Ontario": "ON",
    "Prince Edward Island": "PE", "Quebec": "QC", "Saskatchewan": "SK",
}

# A small, centrally maintained set of unambiguous city hints handles public
# listing cards that omit the country while the adapter has a broad regional
# fallback.  State/province evidence and explicit country text take priority.
# Two-letter codes that are simultaneously a US state or Canadian province code
# and an ISO country code. A bare token like "CO" in a US location card means
# Colorado far more often than Colombia, and reading it as a country put
# University of Denver in Colombia and University of Tennessee in Tunisia.
_STATE_COUNTRY_CODE_COLLISIONS = frozenset(
    code.casefold() for code in {value.upper() for value in STATE_PROVINCE_ALIASES.values()}
    if code.casefold() in set(COUNTRY_ALIASES)
)
# Place names that merely end in a country name. "New Mexico" is a US state;
# matching the trailing "Mexico" recorded Albuquerque postings as Mexican.
_COUNTRY_ALIAS_FALSE_MATCHES = {
    "mexico": (r"\bnew\s+mexico\b",),
    "america": (r"\b(?:north|south|central|latin)\s+america\b",),
}


def _alias_match_is_a_different_place(alias, lower):
    """True when every hit for ``alias`` sits inside a larger, different name."""
    patterns = _COUNTRY_ALIAS_FALSE_MATCHES.get(alias.casefold())
    if not patterns:
        return False
    escaped = re.escape(alias.casefold())
    spans = [match.span() for match in re.finditer(rf"(?<!\w){escaped}(?!\w)", lower)]
    if not spans:
        return False
    excluded = []
    for pattern in patterns:
        excluded.extend(match.span() for match in re.finditer(pattern, lower))
    return all(
        any(start >= low and end <= high for low, high in excluded)
        for start, end in spans
    )


CITY_COUNTRY_HINTS = {
    "dublin": "ie",
    "auckland": "nz",
    "dhaka": "bd",
    # Explicit city evidence used by the current jobs.ac.uk cards.  This is
    # deliberately a finite alias list, not a blanket source-to-GB fallback.
    "london": "gb",
    "city of london": "gb",
    "oxford": "gb",
    "leeds": "gb",
    "sheffield": "gb",
    "liverpool": "gb",
    "leicester": "gb",
    "edinburgh": "gb",
    "aberdeen": "gb",
    "cirencester": "gb",
    "broadstairs": "gb",
    "riyadh": "sa",
    "jeddah": "sa",
    "thuwal": "sa",
}

INSTITUTION_COUNTRY_HINTS = {
    "king abdullah university of science and technology": "sa",
    "kaust": "sa",
    "brigham young university hawaii": "us",
    "hawaii brigham young university hawaii": "us",
    # These are institution-level disambiguators for otherwise ambiguous
    # board location tokens such as ``Toronto, CA`` (CA can mean California)
    # or listings that expose only a city/country code.  They supplement,
    # rather than replace, explicit country text in the location field.
    "university of toronto": "ca",
    "university of toronto st george campus": "ca",
    "university of toronto mississauga utm": "ca",
    "university of toronto scarborough utsc": "ca",
    "university of auckland": "nz",
    "the university of auckland": "nz",
    "lebanese american university": "lb",
    "university of macau": "mo",
    # The Shenzhen campus is in mainland China. Without the campus-specific
    # suffix, the parent Chinese University of Hong Kong must remain HK.
    "chinese university of hong kong shenzhen": "cn",
}

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source", "src"}


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_name(value):
    value = clean_text(value).casefold().replace("&", " and ")
    value = re.sub(r"[’'`.]", "", value)
    value = re.sub(r"[^\w\s-]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def country_code_for(value):
    """Return a canonical upper-case ISO-2 code for a display/code value."""
    text = clean_text(value)
    if not text:
        return None
    lower = text.casefold()
    if lower in COUNTRY_ALIASES:
        return lower.upper()
    if lower in _COUNTRY_DISPLAY_TO_CODE:
        return _COUNTRY_DISPLAY_TO_CODE[lower].upper()
    for alias, code in _COUNTRY_DISPLAY_TO_CODE.items():
        if len(alias) > 2 and re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", lower):
            if alias == "america" and re.search(r"\b(?:north|south|central)\s+america\b", lower):
                continue
            return code.upper()
    return None


def country_from_text(value):
    """Public, conservative country detector used by APIs and repair code."""
    return (_country_from_text(value) or "").upper() or None


def normalize_url(value):
    value = clean_text(value)
    if not value:
        return None
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return value.rstrip("/")
    query = []
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered.startswith("utm_") or lowered in _TRACKING_PARAMS:
            continue
        query.append((key, item))
    hostname = (parts.hostname or "").lower()
    netloc = hostname
    if parts.port and parts.port not in (80, 443):
        netloc += f":{parts.port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/").rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))


def _local_calendar_date(value):
    """Return the calendar day an instant falls on for this workstation.

    ``captured_at`` is a UTC instant, but a board rendering "3 days ago"
    counts calendar days in its own timezone, not in UTC.  Taking ``.date()``
    straight off the UTC value silently shifts every relative date forward by
    one whenever the capture happens after local evening, because UTC has
    already rolled over.  Converting to the local day first keeps the anchor
    on the same calendar day a reader here would see.  Relative dates stay
    inherently +/- 1 day precise: the source timezone is not published.
    """
    if value.tzinfo is None:
        return value.date()
    return value.astimezone().date()


def _reference_date(reference_date=None, reference_year=None):
    if isinstance(reference_date, datetime):
        return _local_calendar_date(reference_date)
    if isinstance(reference_date, date):
        return reference_date
    text = clean_text(reference_date)
    if text:
        try:
            return _local_calendar_date(
                datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                pass
    try:
        return date(int(reference_year), 1, 1) if reference_year else date.today()
    except (TypeError, ValueError):
        return date.today()


def parse_date(value, reference_year=None, reference_date=None):
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"\([^)]*\)", "", text).strip()
    reference = _reference_date(reference_date, reference_year)
    # Structured JobPosting fields commonly use an ISO timestamp rather than
    # a date-only value (for example ``2026-07-30T04:00:00.000Z``).  Preserve
    # the calendar date without treating the time suffix as free text.
    iso = re.match(r"^(20\d{2}-\d{2}-\d{2})(?:[Tt]\d{2}:\d{2}.*)?$", text)
    if iso:
        try:
            return datetime.strptime(iso.group(1), "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None
    if re.search(r"\btoday\b", text, re.I):
        return reference.isoformat()
    if re.search(r"\byesterday\b", text, re.I):
        return (reference - timedelta(days=1)).isoformat()
    relative = re.fullmatch(r"(\d+)\s+(day|days|week|weeks)\s+ago", text, re.I)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2).casefold()
        days = amount * (7 if unit.startswith("week") else 1)
        return (reference - timedelta(days=days)).isoformat()
    patterns = (
        "%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y",
        "%d %B %Y", "%d %b %Y", "%d %B, %Y", "%d %b, %Y",
        "%d %m %Y", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y",
        "%m.%d.%Y", "%d.%m.%Y",
    )
    for pattern in patterns:
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    if reference and re.fullmatch(r"\d{1,2} [A-Za-z]{3,9}", text):
        for pattern in ("%d %B", "%d %b"):
            try:
                candidate = datetime.strptime(f"{text} {reference.year}", f"{pattern} %Y").date()
                candidates = []
                for year in (reference.year - 1, reference.year, reference.year + 1):
                    try:
                        candidates.append(candidate.replace(year=year))
                    except ValueError:
                        # February 29 is not valid in every candidate year.
                        continue
                # Pick the nearest plausible date.  This handles a December
                # capture with a January closing date without silently forcing
                # every year-less date into the current calendar year.
                return min(candidates, key=lambda item: abs((item - reference).days)).isoformat()
            except ValueError:
                pass
    found = re.search(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", text)
    if found:
        try:
            return datetime(int(found.group(1)), int(found.group(2)), int(found.group(3))).date().isoformat()
        except ValueError:
            return None
    # Cards frequently prefix a valid date with a field label.  Search only
    # known date shapes, never an arbitrary number in a description.
    for pattern in (
        r"\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b",
        r"\b\d{1,2}[/.-]\d{1,2}[/.-]20\d{2}\b",
        r"\b\d{1,2}\s+[A-Za-z]{3,9}(?:,?\s+20\d{2})?\b",
        r"\b[A-Za-z]{3,9}\s+\d{1,2}(?:,?\s+20\d{2})?\b",
    ):
        found = re.search(pattern, text)
        if found:
            candidate_text = found.group(0).strip()
            # Do not recurse when the embedded-date pattern matched the
            # complete input (for example ``6 days``).  Relative date text is
            # handled above; an unsupported token must resolve to unknown,
            # not consume the whole ingestion run with RecursionError.
            if candidate_text.casefold() == text.casefold():
                continue
            parsed = parse_date(candidate_text, reference_year=reference_year,
                                reference_date=reference_date)
            if parsed:
                return parsed
    return None


_DEADLINE_KEYWORD_RE = re.compile(
    r"\b(?:application\s+deadline|deadline|closing\s+date|closing|closes|"
    r"apply\s+by|applications?\s+(?:are\s+)?due|expires?)\b", re.I
)
_POSTED_KEYWORD_RE = re.compile(
    r"\b(?:posting\s+date|date\s+placed|posted(?:\s+on)?|captured\s+at)\b", re.I
)
_OPEN_FILLED_RE = re.compile(
    r"\b(?:open\s+until\s+filled|until\s+(?:the\s+)?positions?\s+(?:is|are)\s+filled|"
    r"until\s+filled|open[- ]ended)\b",
    re.I,
)


def _positive_open_until_filled(text):
    """Return the affirmative open-ended marker, ignoring ``...: No``."""
    value = clean_text(text)
    for match in _OPEN_FILLED_RE.finditer(value):
        after = value[match.end():match.end() + 18]
        before = value[max(0, match.start() - 24):match.start()]
        if re.match(r"\s*[:=-]\s*(?:no|false|0)\b", after, re.I):
            continue
        if re.search(r"\b(?:no|not)\s*$", before, re.I):
            continue
        return match
    return None


def _positive_rolling(text):
    """Return explicit rolling wording, excluding a negated statement."""
    value = clean_text(text)
    for match in re.finditer(r"\brolling\b", value, re.I):
        before = value[max(0, match.start() - 24):match.start()]
        if re.search(r"\b(?:no|not)\s*$", before, re.I):
            continue
        return match
    return None


def _bounded_deadline_evidence(raw, description):
    """Keep a short keyword-centered evidence snippet for mode-only dates."""
    for source in (clean_text(raw), clean_text(description)):
        if not source:
            continue
        marker = _DEADLINE_KEYWORD_RE.search(source) or re.search(
            r"\b(?:rolling|open[- ]ended|open\s+until\s+filled|until\s+filled)\b",
            source, re.I,
        )
        if marker:
            start = max(0, marker.start() - 40)
            return source[start:marker.end() + 220][:300]
    return (clean_text(raw) or clean_text(description))[:300] or None


def _deadline_details(value, description="", reference_date=None):
    raw = clean_text(value)
    desc = clean_text(description)

    # A locally qualified date such as "Application Deadline: October 1,
    # 2026 (Applications accepted until filled or closed)" is not a confirmed
    # hard close. Keep the dated wording as evidence; never turn a review or
    # preferred date into automatic expiry. Distant boilerplate is excluded.
    for text in (raw, desc):
        text = unicodedata.normalize("NFKC", text)
        qualified = re.search(r"\b(?:application deadline|priority deadline|first consideration|review of applications)[^.!?]{0,230}\b(?:accepted|open|opened|remain(?:s)? open)\s+until\s+(?:the\s+position\s+is\s+)?filled\b", text, re.I)
        if qualified and _positive_open_until_filled(text[qualified.start():qualified.end() + 20]):
            return {"date": None, "mode": "open_until_filled", "evidence": qualified.group()[:300],
                    "reason": "Dated application/review wording explicitly qualified as open until filled; hard closing date unconfirmed."}

    # Some JSON-LD adapters historically supplied ``validThrough`` as the
    # deadline field.  If the visible posting explicitly says the role stays
    # open until filled, a bare ISO expiry is not application-deadline
    # evidence.  Labeled closing/deadline text below still takes precedence.
    if raw and not _DEADLINE_KEYWORD_RE.search(raw) and _positive_open_until_filled(desc):
        return {"date": None, "mode": "open_until_filled", "evidence": _bounded_deadline_evidence(raw, desc),
                "reason": "Visible open-until-filled wording supersedes an unlabeled structured expiry."}

    # A structured deadline field may contain a keyword plus a date, or a bare
    # date.  A posting/date-placed field is explicitly rejected.
    if raw:
        if _POSTED_KEYWORD_RE.search(raw) and not _DEADLINE_KEYWORD_RE.search(raw):
            return {"date": None, "mode": "unknown", "evidence": None,
                    "reason": "Posting/date-placed text is not deadline evidence."}
        match = _DEADLINE_KEYWORD_RE.search(raw)
        window = raw[match.end():match.end() + 180] if match else raw
        parsed = parse_date(window, reference_date=reference_date)
        if parsed:
            return {"date": parsed, "mode": "fixed", "evidence": window[:300],
                    "reason": "Parsed from the explicit deadline field."}

    # Description fallback is keyword-scoped.  In particular, an unrelated
    # ``Posting date 2026-08-21`` cannot populate a deadline.
    for match in _DEADLINE_KEYWORD_RE.finditer(desc):
        window = desc[match.start():match.end() + 180]
        parsed = parse_date(window, reference_date=reference_date)
        # A dated start of review under an "APPLICATION DEADLINE" heading is
        # not a hard close when the same field explicitly stays open until
        # filled (for example CSU Long Beach's individual faculty postings).
        review_context = desc[match.start():match.end() + 360]
        before_date = re.split(r"\d", window, maxsplit=1)[0]
        if parsed and _positive_open_until_filled(review_context) and re.search(
            r"\b(?:review\s+(?:of\s+)?applications?\s+(?:to\s+)?begin|"
            r"review\s+(?:begins?|starts?)|first\s+consideration|"
            r"preferred\s+(?:consideration|application\s+deadline)|priority\s+consideration)\b",
            before_date, re.I,
        ):
            return {"date": None, "mode": "open_until_filled", "evidence": review_context[:300],
                    "reason": "A review/priority date is not the closing date; explicitly open until filled."}
        if parsed:
            return {"date": parsed, "mode": "fixed", "evidence": window[:300],
                    "reason": "Parsed near an explicit deadline/closing keyword."}
        if _positive_open_until_filled(window):
            return {"date": None, "mode": "open_until_filled", "evidence": window[:300],
                    "reason": "Explicit open-until-filled wording near deadline field."}
        if _positive_rolling(window):
            return {"date": None, "mode": "rolling", "evidence": window[:300],
                    "reason": "Explicit rolling wording near deadline field."}

    # Mode-only evidence is evaluated after all explicit deadline keywords.
    # This matters for ATS text such as ``Application Deadline: 09/15/2026
    # Open Until Filled: No``: the negative flag must not override the fixed
    # deadline, and a positive marker must not hide a date found above.
    if _positive_open_until_filled(raw) or _positive_open_until_filled(desc):
        return {"date": None, "mode": "open_until_filled", "evidence": _bounded_deadline_evidence(raw, desc),
                "reason": "Explicit open-until-filled wording."}
    if _positive_rolling(raw) or _positive_rolling(desc) or re.search(r"\bno fixed deadline\b", f"{raw} {desc}", re.I):
        return {"date": None, "mode": "rolling", "evidence": _bounded_deadline_evidence(raw, desc),
                "reason": "Explicit rolling/no-fixed-deadline wording."}
    return {"date": None, "mode": "unknown", "evidence": None,
            "reason": "No explicit deadline, closing, expiry, or rolling evidence."}


def parse_deadline(value, description="", reference_date=None, return_details=False):
    result = _deadline_details(value, description, reference_date=reference_date)
    if return_details:
        return result
    # Preserve the small public return contract used by existing callers/tests.
    return {"date": result["date"], "mode": result["mode"]}


def parse_salary(value):
    raw = clean_text(value)
    if not raw:
        return {"raw": None, "min": None, "max": None, "currency": None, "period": None}
    upper = raw.upper()
    currency = None
    for code in ("USD", "CAD", "GBP", "EUR", "CHF", "AUD", "NZD", "SGD", "HKD", "CNY"):
        if re.search(rf"\b{code}\b", upper):
            currency = code
            break
    if currency is None:
        for symbol, code in (("$", "USD"), ("£", "GBP"), ("€", "EUR"), ("CHF", "CHF")):
            if symbol in raw:
                currency = code
                break
    numbers = []
    for match in re.findall(r"(?<![A-Za-z])\d{1,3}(?:[,.]\d{3})*(?:\.\d+)?\s*[kKmM]?", raw):
        token = match.replace(",", "").replace(" ", "")
        multiplier = 1
        if token[-1:].lower() == "k":
            multiplier, token = 1000, token[:-1]
        elif token[-1:].lower() == "m":
            multiplier, token = 1000000, token[:-1]
        try:
            numbers.append(float(token) * multiplier)
        except ValueError:
            pass
    period = None
    if re.search(r"per month|monthly|/month", lower := raw.casefold()):
        period = "monthly"
    elif re.search(r"per annum|per year|annual|yearly|/year", lower):
        period = "annual"
    if len(numbers) >= 2:
        low, high = min(numbers[:2]), max(numbers[:2])
    elif numbers and currency:
        low = high = numbers[0]
    else:
        low = high = None
    return {"raw": raw, "min": low, "max": high, "currency": currency, "period": period}


def _country_from_text(text, fallback=None):
    original = clean_text(text)
    lower = original.casefold()
    # Structured location fields sometimes contain only an ISO-2 country
    # token (for example ``CN`` or ``AE``). Accept unambiguous codes here;
    # ``CA`` remains deliberately excluded because a bare CA can mean either
    # Canada or California and must be resolved with state/province evidence.
    if re.fullmatch(r"[A-Za-z]{2}", original):
        code_token = original.casefold()
        # A bare token that is also a US state or Canadian province code is not
        # country evidence on its own: reading "CO" as Colombia put University
        # of Denver in South America, and "TN" as Tunisia put Knoxville in
        # North Africa. Those tokens must fall through to state/province
        # parsing instead.
        if (code_token in _UNAMBIGUOUS_CODE_ALIASES
                and code_token not in _STATE_COUNTRY_CODE_COLLISIONS):
            return code_token
    for code, aliases in COUNTRY_ALIASES.items():
        # Two-letter tokens such as CA/ON/US are ambiguous in location cards;
        # state/province parsing below must get the first chance to classify
        # them. Full country names remain case-insensitive evidence, while ISO
        # codes are accepted only when the source visibly presents an
        # uppercase code. This prevents French ``de`` in ``Université de ...``
        # from being mistaken for Germany (DE).
        if any(len(alias) > 2 and re.search(rf"(?<!\w){re.escape(alias.casefold())}(?!\w)", lower) for alias in aliases):
            matched_alias = next((alias for alias in aliases if len(alias) > 2 and re.search(rf"(?<!\w){re.escape(alias.casefold())}(?!\w)", lower)), None)
            # Skip when every hit for the alias sits inside a larger place name
            # that is not this country: "New Mexico" is a US state, and reading
            # its trailing "Mexico" recorded Albuquerque postings as Mexican.
            if matched_alias and _alias_match_is_a_different_place(matched_alias, lower):
                continue
            return code
        if (code in _UNAMBIGUOUS_CODE_ALIASES
                and code not in _STATE_COUNTRY_CODE_COLLISIONS) and any(
            len(alias) <= 2 and re.search(rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])", original)
            for alias in aliases
        ):
            if code == "id" and re.search(r"\b(?:job|requisition|position|posting|request)\s+id\b", original, re.I):
                continue
            # Long job descriptions contain administrative tokens such as
            # ``Job ID 278518``.  That ``ID`` is not evidence of Indonesia;
            # bare ISO codes in prose require a location/country context or a
            # short structured location value.
            if len(original) > 80 and not re.search(
                rf"(?:country|location|campus|based\s+in|,|\()\s*{re.escape(code)}\b",
                original, re.I,
            ):
                continue
            return code
    fallback_code = country_code_for(fallback)
    return fallback_code.casefold() if fallback_code else None


def country_display(code):
    code = str(code or "").lower()
    aliases = COUNTRY_ALIASES.get(code)
    return aliases[0] if aliases else None


def _clean_location_text(value):
    text = clean_text(value)
    text = re.sub(r"^work\s+locations?\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"^location\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"^location\s+(?=[A-Z][A-Za-z .'-]+$)", "", text, flags=re.I)
    text = re.sub(r"^number\s+of\s+offers?\s*:\s*\d+\s*,?\s*", "", text, flags=re.I)
    text = re.sub(r"\bnumber\s+of\s+offers?\s*:\s*\d+\s*,?\s*", "", text, flags=re.I)
    if re.fullmatch(r"(?:location|work locations?)?\s*(?:number of offers?\s*:\s*\d+)?", text, re.I):
        return ""
    if text.casefold() in {"outside north america", "outside europe", "worldwide", "remote", "various locations", "multiple locations", "not specified"}:
        return ""
    return text.strip(" ,;|-—")


def _recover_location_from_text(description, institution=None):
    text = clean_text(description)
    if not text:
        return ""
    match = re.search(
        r"work\s+locations?\s*:\s*(.*?)(?=research\s+field|researcher\s+profile|"
        r"funding\s+programme|application\s+deadline|$)", text, re.I,
    )
    if match:
        return _clean_location_text(match.group(1))
    match = re.search(r"(?:location|based in)\s*:\s*([^.;]{2,100})", text, re.I)
    if match:
        candidate = _clean_location_text(match.group(1))
        if candidate and not re.search(r"salary|date placed|posting date", candidate, re.I):
            return candidate
    return ""


def parse_location(location_raw, source_region=None, institution_text=None, description=None,
                   region_is_board_default=False):
    """Parse a posting's location.

    ``source_region`` carries two very different things. When a posting exposes
    its own country field it is evidence and is honoured. When it is only the
    job board's registered region -- ``region_is_board_default=True`` -- it says
    where the board is, not where the job is, and must not become the country.
    """
    raw = _clean_location_text(location_raw)
    recovered = _recover_location_from_text(description, institution_text) if not raw else ""
    if recovered:
        raw = recovered
    multiple_locations = bool(re.match(r"^multiple\s+locations?\b", raw, re.I))
    evidence = "location_raw" if raw and location_raw else None
    state = None
    # ``Washington D.C.`` contains the full state name ``Washington`` as a
    # substring.  Resolve the federal district before scanning named states,
    # otherwise the generic alias loop incorrectly emits WA.
    dc_pattern = (
        r"(?<!\w)Washington\s*,?\s*"
        r"(?:D\.?\s*C\.?|Dist\.?\s+(?:of\s+)?Columbia)(?!\w)"
    )
    dc_match = re.search(dc_pattern, raw, re.I)
    state_scan_raw = re.sub(dc_pattern, "District of Columbia", raw, flags=re.I)
    if dc_match:
        state = "DC"
    # Prefer named provinces/states over two-letter tokens.  In particular,
    # ``Toronto, Ontario, CA`` contains both Ontario and the ambiguous CA
    # country token; the named province must win.
    if state is None:
        for name, abbreviation in STATE_PROVINCE_ALIASES.items():
            if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", state_scan_raw, re.I):
                state = abbreviation
                break
    if state is None:
        for name, abbreviation in STATE_PROVINCE_ALIASES.items():
            if re.search(rf"[, ]{abbreviation}(?:[, ]|$)", raw):
                state = abbreviation
                break
    state_candidates = {
        abbreviation for name, abbreviation in STATE_PROVINCE_ALIASES.items()
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", state_scan_raw, re.I)
        or re.search(rf"[, ]{abbreviation}(?:[, ]|$)", state_scan_raw)
    }
    canadian_state_codes = {
        value for name, value in STATE_PROVINCE_ALIASES.items()
        if name in {
            "Alberta", "British Columbia", "Manitoba", "New Brunswick",
            "Newfoundland and Labrador", "Nova Scotia", "Ontario",
            "Prince Edward Island", "Quebec", "Saskatchewan",
        }
    }
    code = _country_from_text(raw)
    # A Canadian province is stronger evidence than the ambiguous ``CA``
    # token used by structured job boards for the country.  This must happen
    # before the US-state fallback below; otherwise Toronto, Ontario, CA is
    # incorrectly normalized to California/United States.
    if state in canadian_state_codes:
        code = "ca"
        evidence = "state_province"
    us_state_codes = {value for name, value in STATE_PROVINCE_ALIASES.items() if name not in {
        "Alberta", "British Columbia", "Manitoba", "New Brunswick", "Newfoundland and Labrador",
        "Nova Scotia", "Ontario", "Prince Edward Island", "Quebec", "Saskatchewan",
    }}
    if not code and state in us_state_codes:
        code = "us"
        evidence = "state_province"
    institution_hint = None
    if institution_text:
        normalized_institution = normalize_name(institution_text)
        for hint, hint_code in INSTITUTION_COUNTRY_HINTS.items():
            if normalized_institution == hint or re.search(rf"\b{re.escape(hint)}\b", normalized_institution):
                institution_hint = hint_code
                break
    # A known institution hint can resolve a location code collision, but it
    # must not override an explicit named country (for example a hypothetical
    # institution alias that conflicts with a clearly reported location).
    # The only intentional override here is US + state CA, where the source
    # has supplied the ambiguous California token and the institution is a
    # known Canadian university.
    if institution_hint and (not code or (code == "us" and state == "CA" and institution_hint != "us")):
        code = institution_hint
        evidence = "institution_hint"
        if code != "us" and state == "CA":
            state = None
    if not code:
        for candidate_text, candidate_evidence in (
            (institution_text, "institution_text"),
            (description, "description_text"),
        ):
            code = _country_from_text(candidate_text)
            if code:
                evidence = candidate_evidence
                break
    # AKADEUS and several institutional feeds publish ``Country / City`` (and
    # occasionally ``Country / City / City``). The country prefix is evidence,
    # not part of the city display. Keep the full raw value for provenance and
    # use the first listed city as the primary structured city.
    slash_parts = [clean_text(item) for item in raw.split("/") if clean_text(item)] if raw else []
    slash_prefix_code = country_code_for(slash_parts[0]) if len(slash_parts) > 1 else None
    if slash_prefix_code:
        code = slash_prefix_code.casefold()
        evidence = "location_raw_country_slash"
        city_text = " / ".join(slash_parts[1:])
        parts = [clean_text(item) for item in re.split(r"\s*/\s*|,", city_text)
                 if clean_text(item)]
    else:
        parts = [clean_text(item) for item in raw.split(",") if clean_text(item)] if raw else []
    city = parts[0] if parts else None
    # Parenthetical work-mode labels are not part of a geographic component.
    # Compare cleaned keys here rather than waiting until the final city trim;
    # otherwise ``United States (remote)`` survives the country-removal pass and
    # becomes the rightmost "city".
    part_keys = [
        normalize_name(re.sub(r"\s*\([^)]{1,60}\)$", "", item).strip())
        for item in parts
    ]
    duplicate_state_city = bool(
        state and len(part_keys) > 1 and part_keys[0] == part_keys[1]
    )
    if code and parts:
        code_name = country_display(code)
        city_state_aliases = {
            normalize_name(alias) for alias in COUNTRY_ALIASES.get(code, ())
        }
        city_state_prefix = bool(
            code in {"hk", "sg", "mo", "mc"}
            and part_keys
            and part_keys[0] in city_state_aliases
        )
        removable = {
            normalize_name(code_name), normalize_name(code), normalize_name(institution_text),
        }
        if state:
            removable.add(normalize_name(state))
            removable.update(
                normalize_name(name) for name, abbreviation in STATE_PROVINCE_ALIASES.items()
                if abbreviation == state
            )
        if state == "DC":
            removable.update({normalize_name("Dist. Columbia"), normalize_name("Dist. of Columbia")})
        # A component that is empty once its parenthetical is stripped -- a
        # detail page's trailing ``(US)`` -- carries no place name at all, so
        # it must never become the city. It used to survive this filter only
        # because ``normalize_name(None)`` is also empty, which meant the right
        # answer depended on whether an institution name happened to be passed.
        remaining = [
            item for item, key in zip(parts, part_keys)
            if key and key not in removable
        ]
        # Some public boards expose only an ISO country token (for example
        # ``CN`` or ``AE``). That token is country evidence, not a city.
        if city_state_prefix:
            # Boards may publish a city-state followed by its broader region,
            # for example ``Macau, China``.  The first component is both the
            # jurisdiction and the city; the broader label must not become the
            # structured city merely because it is the rightmost component.
            city = parts[0]
        elif len(parts) == 1 and (
            part_keys[0] == normalize_name(code)
            or part_keys[0] == normalize_name(code_name)
        ):
            # City-state jurisdictions legitimately use the same display for
            # both levels. Keep the visible city while still stripping any
            # work-mode suffix below.
            city = parts[0] if code in {"hk", "sg", "mo", "mc"} else None
        elif part_keys[0] == normalize_name(code_name):
            city = remaining[-1] if remaining else None
        elif not slash_prefix_code and remaining:
            # Ordinary board locations are ordered from local to broad, but a
            # card may prefix an organizational/campus qualifier:
            # ``College of Business, Main Campus, Portales, NM``.  The last
            # non-country/non-state component is the actual city.  Slash-form
            # ``Country / City / City`` values deliberately keep the first city
            # above, because those are parallel locations rather than nesting.
            city = remaining[-1]
        else:
            city = parts[0]
    if city:
        city = re.sub(r"\s*\([^)]{1,60}\)$", "", city).strip(" ,;|-—") or None
    if city:
        city = re.sub(
            r"^(?:(?:main|north|south|east|west|downtown)\s+)?campus\s*[-–—:]\s*",
            "", city, flags=re.I,
        )
        city = re.sub(r"\s+campus$", "", city, flags=re.I).strip(" ,;|-—") or None
    if multiple_locations:
        # A flattened card can concatenate several cities/states without a
        # delimiter (for example New York followed by Washington, DC). The
        # schema has one city/state slot, so expose the honest aggregate label
        # and retain a state only when every visible location agrees on it.
        city = "Multiple Locations"
        state = next(iter(state_candidates)) if len(state_candidates) == 1 else None
        evidence = "location_raw_multiple"
    city_is_washington_dc = bool(
        city and state == "DC" and normalize_name(city) == normalize_name("Washington")
    )
    if (city and not duplicate_state_city and not city_is_washington_dc
            and normalize_name(city) in {normalize_name(name) for name in STATE_PROVINCE_ALIASES}):
        city = None
    if city and re.search(r"(?:\b(?:street|road|avenue|allee|boulevard)\b|\b\w*(?:laan|weg|straat)\b)", city, re.I) and re.search(r"\d", city):
        city = None
    if city and not code:
        code = CITY_COUNTRY_HINTS.get(normalize_name(city))
        if code:
            evidence = "city_hint"
    source_code = country_code_for(source_region)
    if not code and source_code:
        if region_is_board_default:
            # The board's registered region is where the board is, not where the
            # job is. AIS is registered as United States, so its Portuguese
            # posting -- "... Professor (open rank) at NovaSBE" -- was stamped
            # US, hiding it from a Portugal filter and surfacing it under the
            # wrong country. Leave the country Unknown and say why.
            evidence = "source_region_only_unknown_country"
        else:
            code = source_code.casefold()
            evidence = "source_region_country"
    country = country_display(code)
    if code:
        region_group = REGION_GROUPS.get(country, "Other")
    elif region_is_board_default:
        # A board's registered region is no more posting evidence than its
        # registered country.  Keeping ``United States`` here while clearing
        # the country made the US region KPI disagree with country=US and put a
        # NovaSBE posting in the American market summary.
        region_group = "Other"
    else:
        region_group = source_region if source_region in REGION_GROUPS.values() else "Other"
    if city and state and city.upper() == state:
        city = None
    return {
        "location_raw": raw or None,
        "country": country,
        "country_code": code.upper() if code else None,
        "region_group": region_group,
        "state_province": state,
        "city": city,
        "location_evidence": evidence,
    }


_DISCIPLINE_RULES = (
    ("Information Systems / MIS", ("information systems", "mis", "management information systems", "business information systems", "digital business")),
    ("Business Analytics / AI", ("business analytics", "business intelligence", "artificial intelligence", "machine learning", "data analytics", "data science")),
    ("Organizational Behavior / HR", ("organizational behavior", "organisational behaviour", "human resources", "human resource management", "organizational psychology", "employment relations", "industrial relations", "employee relations", "future of work", "work and organisation", "work and organization", "labour relations", "labor relations")),
    ("Operations / Supply Chain", ("operations management", "supply chain", "operations and supply", "logistics")),
    ("Entrepreneurship", ("entrepreneurship", "entrepreneurial")),
    ("International Business", ("international business", "global business")),
    ("Strategy", ("strategic management", "strategy", "organization theory", "organisation theory")),
    ("Marketing", ("marketing", "consumer behavior", "consumer behaviour")),
    ("Finance", ("finance", "financial economics", "financial markets", "financial systems", "real estate", "insurance", "risk management")),
    ("Accounting", ("accounting", "accountancy")),
    ("Economics", ("economics", "economic analysis", "econometrics")),
    ("Business Law / Ethics", ("business law", "business ethics", "public law")),
    ("Public Administration", ("public administration", "mpa program")),
    ("Hospitality / Tourism", ("hospitality", "tourism", "event management")),
    ("Management", ("management", "business administration", "business school", "business")),
)

# ``discipline_primary`` answers which subject terms appear in a posting.  It
# does not answer whether the posting belongs in the business-school market.
# Keep that boundary separate so a medical, architecture, or software role is
# not included merely because it came from a faculty-oriented job board.
BUSINESS_SCOPES = (
    "business_school",
    "business_discipline",
    "non_business",
    "non_academic",
    "unknown",
)

FACULTY_MARKET_ROLES = (
    "faculty",
    "academic_leadership",
    "postdoc",
    "research_academic",
    "student_role",
    "staff_role",
    "listing_page",
    "unknown",
)

# The market-role gate is deliberately separate from business-subject
# classification.  An AACSB school can advertise graduate-assistant, work-study
# and ordinary staff jobs; accreditation or a business-school label must never
# turn those records into faculty positions.
_GENERIC_JOB_COLLECTION_RE = re.compile(
    r"^(?:search\s+)?(?:full[- ]time\s+|part[- ]time\s+|adjunct\s+|pt\s+)?"
    r"faculty(?:\s*(?:&|and)\s*instructor)?\s+"
    r"(?:jobs?|job\s+openings?|openings?|positions?|opportunities|vacancies)\.?$|"
    r"^faculty\s*\((?:full|part)[- ]time\)$|^faculty\s+vacancies\.?$|"
    # "Faculty Positions in <field>" is one advertisement for openings in a
    # field, not a directory of adverts -- EconJobMarket publishes those with
    # a stable ad id. Only a trailing generic word keeps the collection
    # reading: "Faculty Positions in Various Departments".
    r"^faculty\s+positions\s+in\s+(?:various|multiple|several|all)\b",
    re.I,
)
_NON_VACANCY_PAGE_RE = re.compile(
    r"^(?:dean(?:['’]s)?\s+message|message\s+from\s+(?:the\s+)?dean|"
    r"faculty\s*(?:&|and)\s*research|academic\s+affairs|"
    r"faculty\s+development\s+program(?:me)?|honorary\s+professor)\.?$|"
    r"\bfaculty\s+opportunities\b.*\b(?:colleges?|schools?)\b|"
    r"\b(?:tenure[- ]track|visiting)\s+and\s+.*\bfaculty\s+positions\b",
    re.I,
)
_GENERIC_COLLECTION_URL_RE = re.compile(
    r"[?&](?:jobFamilyGroup|jobCategory|category|search|filter)="
    r"|/(?:jobs?|careers?|postings?)/(?:search|searchresults?|listing)(?:/|\?|$)",
    re.I,
)
_STUDENT_ROLE_RE = re.compile(
    r"\b(?:graduate|teaching|student|undergraduate)\s+assistant\b|"
    r"\bfederal\s+work[- ]study\b|\bwork[- ]study\b|\bstudent\s+worker\b|"
    r"\b(?:graduate|student)\s+(?:intern|internship|trainee)\b|"
    r"\bresident\s+assistant\b",
    re.I,
)
_STAFF_ROLE_RE = re.compile(
    r"\b(?:executive|administrative|program|office|department|laboratory|lab|"
    r"research\s+administrative)\s+assistant\b|"
    r"\b(?:coordinator|administrator|recruiter|programmer|developer|engineer|"
    r"analyst|accountant|product\s+manager|product\s+designer|project\s+manager|"
    r"operations\s+manager|business\s+manager|"
    r"research\s+(?:associate|scientist))\b|"
    # University-wide administration is not a faculty-market vacancy.  The
    # hyphenated spelling is the common one in Canadian postings and never
    # matched the whitespace-only pattern.
    r"\bvice[-\s]?president\b|\b(?:provost|chancellor|rector)\b|"
    r"\b(?:transitional\s+|interim\s+)?president\b(?!\s*(?:['’]s)?\s*(?:chair|professor))|"
    r"\bvice[-\s]?doyen",
    re.I,
)
_PROFESSOR_ROLE_RE = re.compile(
    # ``professorship(s)`` is how a post is named when the advert counts posts
    # rather than describing a person: "Two tenure-track Assistant
    # professorships".
    r"\bprofessors?\b|\bprofessorships?\b|\bprofesseure?s?\b|"
    r"\bmaître\s+de\s+conférences\b", re.I)
_TEACHING_ROLE_RE = re.compile(
    r"\b(?:lecturers?|instructors?|faculty|readers?)\b|\bchargée?s?\s+de\s+cours\b", re.I)
_LEADERSHIP_ROLE_RE = re.compile(
    r"\b(?:(?:associate|assistant|vice|interim|acting|founding|executive)\s+)?dean\b|"
    r"\bdepartment\s+(?:chair(?:person)?|head)\b|"
    r"\bchair(?:person)?\s*(?:,|of\s+(?:the\s+)?)\s*"
    r"(?:department|school|faculty|college)\b|\bdoyen(?:ne)?s?\b",
    re.I,
)
_POSTDOC_ROLE_RE = re.compile(r"\bpost[- ]?doc(?:toral)?\b", re.I)
_RESEARCH_ACADEMIC_ROLE_RE = re.compile(
    r"\b(?:research|teaching)\s+fellows?\b",
    re.I,
)
_OPEN_RANK_RE = re.compile(r"\bopen[- ]rank\b", re.I)
# A tenure-track or tenured opening is a faculty vacancy even when the title
# names no professor or lecturer: "Tenure-track Positions in Accounting and
# Corporate Finance" says what it is without using either noun.
_TENURE_POSITION_RE = re.compile(
    r"\b(?:tenure[- ]track|tenured|tenure[- ]stream)\b[^.]{0,40}?"
    r"\b(?:positions?|openings?|vacanc(?:y|ies)|appointments?|posts?)\b|"
    r"\b(?:positions?|openings?|vacanc(?:y|ies)|appointments?|posts?)\b[^.]{0,40}?"
    r"\b(?:tenure[- ]track|tenured|tenure[- ]stream)\b",
    re.I,
)


def classify_faculty_market_role(title=None, description=None, official_url=None):
    """Classify whether a source record is an individual faculty-market job.

    ``eligible`` is intentionally binary for the default public market view.
    Unknown and collection-page records remain available in ``scope=all`` but
    do not silently enter the faculty market.
    """
    title_text = clean_text(title)
    description_text = clean_text(description)
    if not title_text:
        return {
            "eligible": 0, "role": "unknown", "confidence": "low",
            "reason": "No title evidence was available for a faculty-market role.",
        }
    if (
        re.match(r"^https?://", title_text, re.I)
        or _GENERIC_JOB_COLLECTION_RE.search(title_text)
        or _NON_VACANCY_PAGE_RE.search(title_text)
        or _GENERIC_COLLECTION_URL_RE.search(str(official_url or ""))
    ):
        return {
            "eligible": 0, "role": "listing_page", "confidence": "high",
            "reason": "Title is a generic job collection/search page rather than an individual vacancy.",
        }

    # A dean/department-head search is an academic-leadership market, not the
    # faculty-job market this default view promises. It remains visible under
    # scope=all. This check precedes professor wording so "Dean and Professor"
    # is not promoted merely because the office carries a faculty title.
    if _LEADERSHIP_ROLE_RE.search(title_text):
        return {
            "eligible": 0, "role": "academic_leadership", "confidence": "high",
            "reason": "Title is an academic-leadership search (dean, department chair, or department head), retained outside the default faculty market.",
        }
    # Explicit professorial wording wins over phrases such as ``Research
    # Assistant Professor``; the latter is a professor, not a student RA.
    if (_PROFESSOR_ROLE_RE.search(title_text) or _OPEN_RANK_RE.search(title_text)
            or _TENURE_POSITION_RE.search(title_text)):
        return {
            "eligible": 1, "role": "faculty", "confidence": "high",
            "reason": "Title contains an explicit professor, open-rank, or tenure-track faculty signal.",
        }
    if _STUDENT_ROLE_RE.search(title_text):
        return {
            "eligible": 0, "role": "student_role", "confidence": "high",
            "reason": "Title is a graduate/student assistant, work-study, trainee, or internship role.",
        }
    if _POSTDOC_ROLE_RE.search(title_text):
        return {
            "eligible": 1, "role": "postdoc", "confidence": "high",
            "reason": "Title contains an explicit postdoctoral signal.",
        }
    if _STAFF_ROLE_RE.search(title_text):
        return {
            "eligible": 0, "role": "staff_role", "confidence": "high",
            "reason": "Title is an administrative, technical, or professional staff role.",
        }
    if _TEACHING_ROLE_RE.search(title_text):
        return {
            "eligible": 1, "role": "faculty", "confidence": "high",
            "reason": "Title contains an explicit lecturer/instructor/faculty/reader signal.",
        }
    if _RESEARCH_ACADEMIC_ROLE_RE.search(title_text):
        return {
            "eligible": 1, "role": "research_academic", "confidence": "medium",
            "reason": "Title contains an explicit academic research-fellow/associate/scientist signal.",
        }

    # Description evidence can rescue a terse title such as an endowed award,
    # but only when a bounded appointment phrase explicitly names a supported
    # faculty role.  Generic page chrome is not enough.
    description_window = description_text[:1200]
    if re.search(
        r"\b(?:appoint(?:ment|ed)|position|vacancy)\b.{0,180}"
        r"\b(?:professor|lecturer|faculty|postdoc(?:toral)?|research\s+fellow)\b",
        description_window,
        re.I,
    ):
        return {
            "eligible": 1, "role": "faculty", "confidence": "medium",
            "reason": "Bounded posting text explicitly describes a faculty/postdoctoral appointment.",
        }
    return {
        "eligible": 0, "role": "unknown", "confidence": "low",
        "reason": "No explicit individual faculty or postdoctoral role was found.",
    }

_BUSINESS_SCHOOL_RE = re.compile(
    r"\b(?:business school|school of business|college of business|faculty of business|"
    r"school of management|college of management|faculty of management|department of business|"
    r"college of business administration|"
    r"darla moore|\bdmsb\b|collins college of business)\b",
    re.I,
)
_BUSINESS_DISCIPLINE_RE = re.compile(
    r"\b(?:management information systems|information systems|business information systems|"
    r"\bmis\b|\bcmis\b|business systems|business analytics|business intelligence|"
    r"applied statistics and business analytics|organizational behavior|organisational behaviour|"
    r"human resources?|human resource management|strategic management|entrepreneurship|"
    r"international business|marketing|finance|accounting|business law|legal studies|"
    r"insurance|risk management|real estate|operations management|supply chain|"
    r"logistics|transportation\s+(?:management|logistics)|general business|"
    r"business administration|business management|management|"
    r"management science|decision sciences?|organi[sz]ational studies|business)\b",
    re.I,
)
_NON_BUSINESS_RE = re.compile(
    r"\b(?:emergency medicine|pathology|pediatrics?|social work|poetry|landscape architecture|"
    r"orthodontics|architecture|biology|biotechnology|medicine|nursing|chemistry|physics|"
    r"sociology|psychology|computer science|electrical engineering|mechanical engineering|"
    r"radiopharmaceutical|radiochemical|pharmacy|pharmaceutical|chiropractic|cosmetology|"
    r"dental(?:\s+hygiene)?|dentistry|graphic design|studio art|fine arts?|journalism|"
    r"nurse\s+practitioner|\bnurse\b|"
    r"mass communication|recreation|swim(?:ming)?|health sciences?|educational administration|"
    r"aviation(?:\s+science)?|biostatistics?|manufacturing\s+engineering|chemical\s+engineering|"
    r"biological\s+engineering|civil\s+engineering|aerospace\s+engineering|"
    r"computer\s+engineering|engineering\s+technology|biological|robotics?|"
    r"geographic\s+information\s+systems?|\bgis\b|social\s+sciences?|"
    r"agricultur(?:e|al)|agronomy|animal\s+(?:science|waste)|farm\s+animal|"
    r"food\s+(?:and\s+)?resource|\bag[- ]food\b|resources?\s+economics|"
    r"pain\s+management|paralegal|professor\s+of\s+law|law\s+school|"
    r"(?:school|college)\s+of\s+law|"
    r"culinary(?:\s+arts?)?|bak(?:ing|ery)|pastry|literature|languages?|"
    r"materials?\s+science|epidemiolog(?:y|ical)|implementation\s+science|"
    # Fields observed in the unclassified bucket on 2026-08-26.  Each one was
    # taken from an actual posting title, not guessed, so the list stays
    # auditable against the records that motivated it.
    r"archaeolog(?:y|ical)|anthropolog(?:y|ical)|indigenous\s+studies|"
    r"library\s+(?:science|technolog(?:y|ies))|librarian(?:ship)?|"
    r"(?:urban|community|regional)\s+planning|public\s+health|health\s+policy|"
    r"mental\s+health|forestr(?:y|ies)|forest\s+sciences?|kinesiolog(?:y|ical)|"
    r"linguistics?|theolog(?:y|ical)|divinity|musicolog(?:y|ical)|"
    # LIU's music technology/production role mentions entrepreneurship but
    # explicitly requires recording-arts training, not a business discipline.
    r"music\s*,?\s*technology|recording\s+arts|"
    r"veterinary(?:\s+medicine)?|mathematics|"
    r"teacher\s+education|educational\s+leadership|curriculum\s+and\s+instruction|"
    r"\bk-?12\b|francophone\s+studies|"
    # French-language equivalents: University Affairs publishes bilingually and
    # an English-only field list left every French posting unclassified.
    r"santé\s+publique|sciences?\s+forestières?|sociologie|médecine|"
    r"bibliothèques?|lettres\s+et\s+communication|"
    r"génie(?:\s+\w+)?|sciences?\s+infirmières?|psychologie|anthropologie)\b",
    re.I,
)
_AMBIGUOUS_MANAGEMENT_FIELD_RE = re.compile(
    r"\b(?:construction|sport(?:s)?|health\s+(?:care|services?|policy)(?:\s+policy)?(?:\s+and)?|public\s+administration|"
    r"public|emergency(?:\s+and\s+security)?|security|concrete\s+industry|hospitality|tourism)\s+management\b|"
    r"\bmanagement\s+(?:programs?\s+)?(?:in\s+)?(?:construction|sport(?:s)?|health\s+care|hospitality|tourism)\b",
    re.I,
)
_NON_BUSINESS_UNIT_RE = re.compile(
    r"\b(?:college|school|faculty)\s+of\s+(?:arts?(?:\s*(?:&|and)\s*sciences?)?|"
    r"social\s+(?:and|&)\s+behavioral\s+sciences?|sciences?|engineering|"
    r"medicine|health\s+sciences?|education|law)|\bseaver\s+college\b",
    re.I,
)


def classify_business_scope(
    department=None,
    title=None,
    description=None,
    institution=None,
    school=None,
    source=None,
    school_is_posting_evidence=True,
    faculty_role=None,
):
    """Classify inclusion in the business-school market without deleting data.

    The strictest evidence is an explicit business school/college/department
    or a populated ``school`` field.  Business subject terms are retained as
    a lower-confidence ``business_discipline`` class when the school is not
    exposed by the public listing.  Generic faculty records and non-academic
    jobs remain ``unknown``/``non_academic`` and are excluded from the default
    business view.
    """
    title_text = clean_text(title)
    department_text = clean_text(department)
    description_text = clean_text(description)
    institution_text = clean_text(institution)
    school_text = clean_text(school)
    title_department = " ".join(item for item in (title_text, department_text) if item)
    role = faculty_role or classify_faculty_market_role(title_text, description_text)
    if not role.get("eligible"):
        if role.get("role") in {"student_role", "staff_role", "listing_page"}:
            return {
                "scope": "non_academic",
                "confidence": role.get("confidence") or "low",
                "reason": role.get("reason") or "No eligible faculty-market role was established.",
            }
        # An unrecognised role is not a reason to throw away field evidence we
        # do have.  A posting that names a non-business academic field is known
        # not to be a business vacancy, which is strictly more informative than
        # "unknown".  Both are excluded from the default market either way, so
        # this sharpens the audit view without widening it.
        if _NON_BUSINESS_RE.search(title_department):
            return {
                "scope": "non_business", "confidence": "medium",
                "reason": "Role was not identified, but the title/department names a "
                          "non-business academic field.",
            }
        return {
            "scope": "unknown",
            "confidence": role.get("confidence") or "low",
            "reason": role.get("reason") or "No eligible faculty-market role was established.",
        }

    # A named non-business field in the title/department outranks a roster or
    # parent-school association.  This prevents a university-wide career page
    # from assigning Pharmacy, Computer Science or Cosmetology to its AACSB
    # business school.
    if _NON_BUSINESS_RE.search(title_department):
        return {
            "scope": "non_business", "confidence": "high",
            "reason": "Title or department matched an explicit non-business academic field.",
        }

    explicit_business_unit = bool(_BUSINESS_SCHOOL_RE.search(" ".join(item for item in (
        title_text, department_text, institution_text,
        school_text if school_is_posting_evidence else "",
    ) if item)))
    if _AMBIGUOUS_MANAGEMENT_FIELD_RE.search(title_department) and not explicit_business_unit:
        return {
            "scope": "non_business", "confidence": "high",
            "reason": "An ambiguous management field was not tied to an explicit business school/college/faculty.",
        }

    primary_unit_text = " ".join(item for item in (
        title_text, department_text, institution_text,
        school_text if school_is_posting_evidence else "",
    ) if item)
    if _NON_BUSINESS_UNIT_RE.search(primary_unit_text):
        return {
            "scope": "non_business", "confidence": "high",
            "reason": "A primary posting field named an explicit non-business school/college/faculty.",
        }

    if school_is_posting_evidence and school_text and _BUSINESS_SCHOOL_RE.search(school_text):
        return {
            "scope": "business_school", "confidence": "high",
            "reason": f"Explicit business-school evidence in school field: {school_text[:240]}",
        }
    primary_text = primary_unit_text
    if _BUSINESS_SCHOOL_RE.search(primary_text):
        return {
            "scope": "business_school", "confidence": "high",
            "reason": "Explicit business-school/college/department evidence in a primary posting field: "
                      + (_BUSINESS_SCHOOL_RE.search(primary_text).group(0)[:240]),
        }

    if _BUSINESS_DISCIPLINE_RE.search(title_department):
        return {
            "scope": "business_discipline", "confidence": "medium",
            "reason": "Title or department matched a business discipline, but the business school was not verified.",
        }

    # Source cards often expose the department only in the excerpt.  Require
    # an explicit field phrase before using description-only evidence so a
    # broad category such as ``Business/A`` does not create a false positive.
    description_field = re.search(
        r"(?:department|school|college|faculty|division|program|categories?)\s*[:/-]?\s*.{0,160}",
        description_text,
        re.I,
    )
    if description_field:
        field_text = description_field.group(0)
        if _NON_BUSINESS_RE.search(field_text):
            return {
                "scope": "non_business", "confidence": "high",
                "reason": "Captured department/category evidence matched a non-business academic field.",
            }
        if _BUSINESS_DISCIPLINE_RE.search(field_text):
            return {
                "scope": "business_discipline", "confidence": "medium",
                "reason": "Captured department/category evidence matched a business discipline; school not verified.",
            }

    if _NON_BUSINESS_RE.search(description_text[:1200]):
        return {
            "scope": "non_business", "confidence": "medium",
            "reason": "Bounded posting text matched a non-business field without stronger business-unit evidence.",
        }
    return {
        "scope": "unknown", "confidence": "low",
        "reason": "Insufficient explicit business-school or business-discipline evidence.",
    }


def role_title_for_discipline(title):
    """Remove trailing employer-unit names when the role already names a subject."""
    title = clean_text(title)
    title = re.sub(r"((?:College|School) of Business) (?:and|&) Economics\b", r"\1", title, flags=re.I)
    parts = re.split(r"\s+[-–—|]\s+(?=(?:department|school|college|haas|kelley|rawls|rady)\b)", title, maxsplit=1, flags=re.I)
    role = parts[0]
    specific = [label for label, terms in _DISCIPLINE_RULES if label != "Management"
                and any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", role, re.I) for term in terms)]
    if specific:
        return role
    return title


def classify_disciplines(department, title, description):
    role_title = role_title_for_discipline(title)
    role_hits = [label for label, terms in _DISCIPLINE_RULES if label != "Management"
                 and any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", role_title, re.I) for term in terms)]
    # These names describe a teaching unit or an industry niche, not evidence
    # of a general Management/IS/OBHR vacancy.
    if re.search(r"\b(?:hemp|cannabis)\b", role_title, re.I):
        return {"primary": "Sector-specific Management", "secondary": [],
                "reason": "Explicit industry-specific role title; general Management was not inferred from the school name."}
    if re.search(r"\bstudent success\b", role_title, re.I):
        return {"primary": "Other", "secondary": [],
                "reason": "Student-success teaching role; the college name does not establish a Management or Economics discipline."}
    if role_hits:
        return {"primary": role_hits[0], "secondary": role_hits[1:5],
                "reason": "Explicit vacancy-subject title takes precedence over employer-unit names and listing categories."}
    fields = [clean_text(department), role_title, clean_text(description)]
    hits = []
    # Field order is intentional: department evidence outranks title and text.
    for field_index, field in enumerate(fields):
        lower = field.casefold()
        if not lower:
            continue
        for discipline, terms in _DISCIPLINE_RULES:
            if any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", lower) for term in terms):
                if discipline not in [item[0] for item in hits]:
                    hits.append((discipline, field_index, field))
    if not hits:
        return {"primary": "Other", "secondary": [], "reason": "No configured taxonomy rule matched department, title, or description."}
    hits.sort(key=lambda item: (item[1], -len(item[2])))
    primary = hits[0][0]
    secondary = [item[0] for item in hits[1:] if item[0] != primary][:4]
    evidence = "department" if hits[0][1] == 0 else ("title" if hits[0][1] == 1 else "explicit field/description")
    return {"primary": primary, "secondary": secondary,
            "reason": f"Rule matched {evidence}; secondary matches retained separately."}


# How the appointment is worked, which is a different axis from how it is
# contracted. ``infer_track`` answers tenure/permanence and needs wording like
# "non-tenure" that adjunct advertisements almost never carry, which is why
# most of them land in ``track_type='unknown'``. An adjunct posting and a
# tenure-track posting are not competing for the same candidate, so the market
# view needs to tell them apart without either one being deleted.
#
# Only explicit wording is read. Absence of "part-time" is not evidence of a
# full-time appointment, so nothing here infers a continuing role from silence.
APPOINTMENT_TYPES = ("adjunct", "visiting", "postdoc", "full_time", "unknown")

_ADJUNCT_RE = re.compile(
    r"\badjuncts?\b|\bper[- ]course\b|\bpart[- ]time\b|\bpart time\b|"
    r"\bsessional\b|\bcasual\s+academic\b|\bsingle[- ]term\b|\bper[- ]semester\b|"
    r"\bhourly\s+(?:faculty|instructor)\b|\bpool\b(?=[^.]*\b(?:adjunct|part[- ]time)\b)",
    re.I,
)
_VISITING_APPOINTMENT_RE = re.compile(
    r"\bvisiting\b|\bvisiteur\b|\bprofesseur\s+invit", re.I)
_POSTDOC_APPOINTMENT_RE = re.compile(
    r"\bpost[- ]?doc(?:toral)?\b|\bresearch\s+fellow\b", re.I)
_FULL_TIME_RE = re.compile(r"\bfull[- ]time\b|\bfull time\b", re.I)


def infer_appointment(text):
    """Classify the appointment's working shape from explicit wording only.

    Order matters: a "Full-Time Adjunct Pool" advertisement contains both
    phrases, and the contingent half is the one that decides whether the role
    belongs in a tenure-track search. Checking ``full_time`` first would file
    every such posting alongside continuing appointments.
    """
    lower = clean_text(text).casefold()
    if _ADJUNCT_RE.search(lower):
        return "adjunct"
    if _POSTDOC_APPOINTMENT_RE.search(lower):
        return "postdoc"
    if _VISITING_APPOINTMENT_RE.search(lower):
        return "visiting"
    if _FULL_TIME_RE.search(lower):
        return "full_time"
    return "unknown"


def infer_track(text):
    lower = clean_text(text).casefold()
    # Remove explicit negations before testing the positive substring. Mixed
    # advertisements remain unknown rather than inventing a single contract.
    negative = re.compile(
        r"\b(?:non[\s\-\u2010-\u2015]*(?:tenur(?:e|ed)(?:[\s\-\u2010-\u2015]*track)?|tt)"
        r"|not(?:\s+a)?[\s\-]+tenure[\s\-]+track"
        r"|not\s+eligible\s+for\s+tenure|without\s+tenure"
        r"|teaching\s+stream|educator\s+track|clinical\s+faculty)\b"
    )
    positive = re.compile(r"\b(?:tenure[- ]track|tenure stream|tenurable)\b")
    has_negative = bool(negative.search(lower))
    remainder = negative.sub(" ", lower)
    has_positive = bool(positive.search(remainder))
    if has_negative:
        return "unknown" if has_positive else "non_tenure_track"
    if has_positive:
        return "tenure_track"
    if re.search(r"tenured appointment|already tenured|tenured position", lower):
        return "tenured"
    if re.search(r"permanent|open[- ]ended|indefinite", lower):
        return "permanent_open_ended"
    if re.search(r"non[- ]tenure|non-tenured|teaching stream|educator track|clinical faculty", lower):
        return "non_tenure_track"
    if re.search(r"fixed[- ]term|limited[- ]term|term appointment|one[- ]year term|temporary appointment|contract of", lower):
        return "fixed_term"
    return "unknown"


# Refusals are checked before offers, and the refusal patterns are the specific
# ones.  The previous order asked "eligible.*sponsorship" first, which matched
# inside "not eligible for sponsorship" and reported a school that explicitly
# refuses sponsorship as one that provides it.  For this field an inverted
# answer is worse than no answer, so negation wins every tie.
_VISA_REFUSAL_RE = re.compile(
    r"\b(?:will|can|do(?:es)?)\s*n(?:o|’|')?t\s+sponsor\b|"
    r"\bcannot\s+sponsor\b|"
    r"\bunable\s+to\s+(?:provide|offer|sponsor|take\s+over)[^.]{0,60}?(?:sponsor|visa)|"
    r"\bno\s+(?:visa\s+)?sponsorship\b|"
    r"\bnot\s+eligible\s+for\s+[^.]{0,60}?sponsorship\b|"
    r"\bineligible\s+for\s+[^.]{0,60}?sponsorship\b|"
    r"\bsponsorship\s+is\s+not\s+(?:available|offered|provided)\b|"
    r"\bwithout\s+(?:the\s+need\s+for\s+)?(?:visa\s+)?sponsorship\b|"
    r"\bauthori[sz]ed\s+to\s+work[^.]{0,80}?without\s+sponsorship\b",
    re.I,
)
# Hedged wording is not a commitment.  "May be available in limited situations"
# is real information, but reporting it as an explicit yes would mislead exactly
# the reader who depends on this field.
_VISA_HEDGE_RE = re.compile(
    r"\b(?:may|might|could)\s+be\s+(?:available|possible|considered)\b|"
    r"\bin\s+(?:very\s+)?limited\s+(?:situations|circumstances|cases)\b|"
    r"\bcase[- ]by[- ]case\b",
    re.I,
)
_VISA_OFFER_RE = re.compile(
    r"\bwill\s+sponsor\b|\bwe\s+sponsor\b|"
    r"\b(?:visa\s+)?sponsorship\s+(?:is\s+)?available\b|"
    r"\b(?:can|able\s+to|willing\s+to|happy\s+to)\s+sponsor\b|"
    r"\bsponsor(?:ship)?\s+(?:for\s+)?(?:an?\s+)?(?:h-?1b|work\s+visa)\b|"
    r"\bh-?1b\s+sponsorship\b|"
    r"\beligible\s+for\s+(?:visa\s+)?sponsorship\b",
    re.I,
)
_VISA_MENTION_RE = re.compile(
    r"\bvisa\b|\bwork\s+authori[sz]ation\b|\bright\s+to\s+work\b|\bsponsorship\b",
    re.I,
)
# Sponsorship that is funding rather than immigration. Found live: "Lecturer
# for Scholarship Sponsorship in Digital Innovation" was read as a visa
# mention, and "Scholarship sponsorship is available for doctoral students"
# matched the offer pattern outright.
_FUNDING_SPONSOR_RE = re.compile(
    r"\b(?:scholarship|studentship|fellowship|research|industry|corporate|grant|"
    r"funding|programme|program|project|event|conference|athletic|travel)\s+"
    r"sponsor(?:s|ed|ing|ship)?\b|"
    r"\bsponsored\s+(?:programs?|research|projects?|students?)\b|"
    r"\bfaculty\s+sponsor\b",
    re.I,
)
# What makes a sentence about immigration regardless of the money words in it.
_IMMIGRATION_WORD_RE = re.compile(
    r"\bvisa\b|\bwork\s+authori[sz]ation\b|\bright\s+to\s+work\b|"
    r"\bimmigration\b|\bwork\s+permit\b|\bh-?1b\b|\bpermanent\s+residen|"
    r"\bgreen\s+card\b|\bcitizen|\bnon-?immigrant\b|\bperm\b|\beb-?[12]\b",
    re.I,
)


def _is_about_immigration(sentence):
    """Does this sentence concern work authorization at all?

    A sponsorship word that is qualified as funding -- scholarship, research,
    industry -- does not make a sentence about immigration. Naming a visa,
    a permit or a status does, whatever else the sentence says.
    """
    text = str(sentence or "")
    if _IMMIGRATION_WORD_RE.search(text):
        return True
    return not _FUNDING_SPONSOR_RE.search(text)


# A hard eligibility bar, not a sponsorship policy.  "Must be a U.S. citizen"
# and "no sponsorship" are different sentences with different consequences: a
# permanent resident can accept the second and not the first.  Both were
# reported as `unknown`, which put them in the same bucket as a posting that
# never mentioned the subject at all.
_CITIZENSHIP_ONLY_RE = re.compile(
    r"\b(?:u\.?s\.?|united\s+states|american)\s+citizenship\s+(?:is\s+)?"
    r"(?:required|mandatory|a\s+requirement)\b|"
    r"\bmust\s+be\s+(?:a\s+)?(?:u\.?s\.?|united\s+states|american)\s+citizens?\b"
    r"(?!\s*(?:,|\s)*(?:or|/)\s*(?:a\s+)?(?:lawful\s+)?permanent\s+resident)|"
    r"\brestricted\s+to\s+(?:u\.?s\.?|united\s+states)\s+citizens\b",
    re.I,
)
_CITIZEN_OR_PR_RE = re.compile(
    r"\b(?:u\.?s\.?|united\s+states)?\s*citizens?\s*(?:,|\s)*(?:or|/)\s*"
    r"(?:a\s+)?(?:lawful\s+)?permanent\s+residents?\b|"
    r"\bpermanent\s+residents?\s*(?:,|\s)*(?:or|/)\s*(?:u\.?s\.?\s*)?citizens?\b|"
    r"\bgreen\s+card\s+holders?\s+or\s+(?:u\.?s\.?\s*)?citizens?\b",
    re.I,
)
# Support for permanent residency is a bigger commitment than a work visa and
# is worth separating from it: a candidate choosing between offers cares which
# one has said it will file.
_PR_SUPPORT_RE = re.compile(
    # Inflections matter here: postings say "will be supported for permanent
    # residency" far more often than "will support".
    r"\b(?:support(?:s|ed|ing)?|sponsor(?:s|ed|ing)?|assist(?:s|ed|ing)?\s+with|"
    r"file[sd]?\s+for|filing\s+for|petition(?:s|ed|ing)?\s+for)\b[^.]{0,80}?"
    r"\b(?:permanent\s+residency|permanent\s+residence|green\s+card|"
    r"labor\s+certification|perm\b|eb[-\s]?1[ab]?\b|eb[-\s]?2\b|"
    r"outstanding\s+researcher|national\s+interest\s+waiver)|"
    r"\b(?:permanent\s+residency|green\s+card)\b[^.]{0,60}?"
    r"\b(?:support(?:s|ed|ing)?|sponsor(?:s|ed|ing)?|assists?)\b",
    re.I,
)
# Programmes a posting names outright.  Recorded, never inferred: an employer
# picks an EB category after hiring, so reading one out of a job ad would be
# invention.
_VISA_PATHWAY_PATTERNS = (
    ("h1b", r"\bh[-\s]?1[-\s]?b\b"),
    ("j1", r"\bj[-\s]?1\b"),
    ("o1", r"\bo[-\s]?1\b"),
    ("tn", r"\btn\s+(?:visa|status|classification)\b"),
    ("e3", r"\be[-\s]?3\s+(?:visa|status)\b"),
    ("eb1", r"\beb[-\s]?1[ab]?\b|\boutstanding\s+researcher\b"),
    ("eb2", r"\beb[-\s]?2\b|\bnational\s+interest\s+waiver\b|\bniw\b"),
    ("perm", r"\bperm\b|\blabor\s+certification\b|\bspecial\s+handling\b"),
    ("green_card", r"\bgreen\s+card\b|\bpermanent\s+residen(?:cy|ce)\b"),
)
_VISA_PATHWAY_RES = tuple(
    (name, re.compile(pattern, re.I)) for name, pattern in _VISA_PATHWAY_PATTERNS
)
_INTERNATIONAL_WELCOME_RE = re.compile(
    r"international\s+candidates\s+welcome|"
    r"welcome\s+applications\s+from\s+international|"
    r"global\s+applicants\s+welcome|"
    r"applications\s+from\s+international\s+(?:candidates|applicants|scholars)\s+are\s+welcome",
    re.I,
)

# A negation sharing the sentence with an affirmative match. Cheap, blunt, and
# pointed at the only direction that matters: this field's failures have all
# been affirmatives read out of refusals, never the reverse.
_NEGATED_SENTENCE_RE = re.compile(
    r"\b(?:not|no|never|cannot|can\s*not|unable|ineligible|without|"
    r"n[o’']t)\b",
    re.I,
)


# Most specific first. A posting that both names a citizenship bar and mentions
# sponsorship elsewhere is answered by the bar, because that is the sentence
# that decides whether the reader may apply at all.
_VISA_RULES = (
    ("citizenship_required", lambda t: _CITIZENSHIP_ONLY_RE.search(t)),
    ("citizen_or_pr_required", lambda t: _CITIZEN_OR_PR_RE.search(t)),
    ("sponsorship_explicit_no", lambda t: _VISA_REFUSAL_RE.search(t)),
    ("permanent_residency_supported", lambda t: _PR_SUPPORT_RE.search(t)),
    ("sponsorship_explicit_yes", lambda t: _VISA_OFFER_RE.search(t)),
    ("international_candidates_welcome", lambda t: _INTERNATIONAL_WELCOME_RE.search(t)),
    ("unclear", lambda t: _VISA_MENTION_RE.search(t)),
)

# Values that are a hard bar for a candidate who needs sponsorship. Kept as
# data so the UI, the CSV and the filters cannot drift apart on which is which.
VISA_BLOCKING_STATUSES = (
    "citizenship_required", "citizen_or_pr_required", "sponsorship_explicit_no",
)
VISA_SUPPORTIVE_STATUSES = (
    "sponsorship_explicit_yes", "permanent_residency_supported",
    "international_candidates_welcome",
)
VISA_STATUSES = VISA_BLOCKING_STATUSES + VISA_SUPPORTIVE_STATUSES + ("unclear", "unknown")


def _sentence_around(text, match):
    """The sentence the match sits in, so the answer carries its own evidence."""
    if not match:
        return None
    start, end = match.span()
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    right = min(
        (index for index in (text.find(".", end), text.find("\n", end)) if index != -1),
        default=-1,
    )
    if right == -1:
        right = min(len(text), end + 200)
    quote = " ".join(text[left:right + 1].split()).strip()
    return quote[:400] or None


def visa_pathways(text):
    """Programmes the posting names outright, in a stable order."""
    cleaned = clean_text(text)
    if not cleaned:
        return []
    return [name for name, pattern in _VISA_PATHWAY_RES if pattern.search(cleaned)]


def classify_visa(text):
    """Return ``{status, evidence, pathways}`` for one posting's text.

    ``evidence`` is the sentence the decision came from, quoted, or ``None``
    when the answer is ``unknown``.  Nothing here is inferred from the
    institution, the country, or the role -- only from what the posting says.
    """
    cleaned = clean_text(text)
    if not cleaned:
        return {"status": "unknown", "evidence": None, "pathways": []}
    lower = cleaned.casefold()
    pathways = visa_pathways(cleaned)
    for status, probe in _VISA_RULES:
        match = probe(lower)
        if not match:
            continue
        # A hedged offer is not an offer.  "May be available in limited
        # circumstances" is real information and reporting it as a commitment
        # would mislead exactly the reader who depends on this field.
        if status == "sponsorship_explicit_yes" and _VISA_HEDGE_RE.search(lower):
            status = "unclear"
        sentence = _sentence_around(cleaned, match) or ""
        if not _is_about_immigration(sentence):
            # Scholarship sponsorship, sponsored research, an industry sponsor:
            # money, not work authorization. Keep looking rather than answering
            # a question this sentence never addressed.
            continue
        if status in ("permanent_residency_supported", "sponsorship_explicit_yes"):
            if _NEGATED_SENTENCE_RE.search(sentence):
                # The sentence carrying the affirmative match also carries a
                # negation. Whatever it means, it is not a commitment.
                status = "unclear"
        return {
            "status": status,
            "evidence": _sentence_around(cleaned, match),
            "pathways": pathways,
        }
    # A posting that names a programme has said something about immigration,
    # even when it never uses the words "visa" or "sponsorship" -- "J-1
    # exchange visitor status may be arranged" is not silence. It is not a
    # commitment either, so it lands in unclear with the sentence attached.
    if pathways:
        for _name, pattern in _VISA_PATHWAY_RES:
            named = pattern.search(cleaned)
            if named:
                return {"status": "unclear",
                        "evidence": _sentence_around(cleaned, named),
                        "pathways": pathways}
    return {"status": "unknown", "evidence": None, "pathways": pathways}


def infer_visa(text):
    """Backwards-compatible string form used by the existing callers."""
    return classify_visa(text)["status"]


def infer_phd(text):
    lower = clean_text(text).casefold()
    if re.search(r"ph\.d\.?\s+(?:is )?required|doctorate\s+(?:is )?required|must hold.*ph\.d", lower):
        return 1
    if re.search(r"ph\.d\.?\s+preferred|doctorate\s+preferred|ph\.d\.?\s+or equivalent", lower):
        return None
    if re.search(r"ph\.d\.?\s+not required|no doctorate required", lower):
        return 0
    return None


def parse_start(text):
    text = clean_text(text)
    year = None
    # Prefer an explicit appointment header to unrelated dated rankings or
    # policy notices. Month/day start dates and "Fall Semester of 2027" were
    # previously missed, allowing older narrative years to win.
    labelled = re.search(
        r"\b(?:(?:target\s+)?start\s+date|effective\s+date(?:\s+of\s+appointment)?)"
        r"\s*:\s*([^.;]{1,80})", text[:2000], re.I)
    explicit_date = parse_date(labelled.group(1)) if labelled else None
    purpose = re.search(
        r"\b(?:commenc(?:e|ing)|start(?:ing)?|begin(?:ning)?)\s+"
        r"(?:(?:in|during|on)\s+)?(?:the\s+)?"
        r"(?:fall|spring|summer|winter|autumn)\s+(?:(?:semester|term)\s+)?"
        r"(?:of\s+)?(20\d{2})", text, re.I)
    found = re.search(r"(?:fall|spring|summer|winter|autumn|commenc(?:e|ing)|start(?:ing)?|begin(?:ning)?)\s+(?:of\s+)?(20\d{2})", text, re.I)
    if explicit_date:
        year = int(explicit_date[:4])
    elif purpose:
        year = int(purpose.group(1))
    elif found:
        year = int(found.group(1))
    term = None
    for candidate in ("Fall", "Spring", "Summer", "Winter", "Autumn"):
        if re.search(rf"\b{candidate}\b", text, re.I):
            term = "Fall" if candidate == "Autumn" else candidate
            break
    return term, year


def hiring_cycle(first_seen_at, start_year):
    if not start_year:
        return None
    try:
        seen_year = datetime.fromisoformat(str(first_seen_at).replace("Z", "+00:00")).year
    except (TypeError, ValueError):
        try:
            seen_year = datetime.now().year
        except Exception:
            return None
    # Academic hiring often opens before the calendar year of the start term;
    # preserve the observed year rather than deriving only from start_year.
    return f"{seen_year}-{str(int(start_year))[-2:]}"


def hiring_cycle_reason(first_seen_at, start_year):
    if not start_year:
        return "No explicit start year was captured; hiring cycle remains Unknown."
    try:
        seen_year = datetime.fromisoformat(str(first_seen_at).replace("Z", "+00:00")).year
    except (TypeError, ValueError):
        seen_year = datetime.now().year
    return f"Derived from first_seen year {seen_year} and explicit start year {int(start_year)}; not inferred from start year alone."


def fingerprint_fields(institution, title, city, state, discipline, start_year):
    parts = [normalize_name(institution), normalize_name(title), normalize_name(city),
             normalize_name(state), normalize_name(discipline), str(start_year or "")]
    return "|".join(parts)


def canonical_key(official_url, fingerprint):
    url = normalize_url(official_url)
    if url and is_mergeable_official_url(url):
        return "url:" + url
    return "fp:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:40]


def is_mergeable_official_url(value):
    """Return False for generic portals that are shared by many postings."""
    url = normalize_url(value)
    if not url:
        return False
    parsed = urlsplit(url)
    path = parsed.path.casefold()
    if path.endswith("/ensup/candidats.html") or path.endswith("/candidats.html"):
        return False
    if path in {"", "/", "/apply", "/applications", "/careers"} and not parsed.query:
        return False
    if re.search(r"/(?:jobs?|postings?|careers?)/(?:search|listing|searchresults?)(?:/|$)", path):
        return False
    if path.endswith(("/search", "/listing", "/searchresults")):
        return False
    # Filtered faculty-family/category URLs are useful discovery pages, but are
    # not individual application destinations and must not be dedup identities.
    if parsed.query and re.search(r"(?:jobfamily|employment_type|position_type|query=)", parsed.query, re.I):
        if not re.search(r"/(?:job|jobs|posting|postings)/[^/]+", path):
            return False
    return True


def parse_explicit_posted_date(text, reference_date=None):
    """Parse only a date attached to a known posting/date-placed label."""
    value = clean_text(text)
    for match in re.finditer(
        r"(?:posting\s+date|date\s+placed|posted(?:\s+on)?)\s*:?[\s-]*(.{0,80})",
        value, re.I,
    ):
        candidate = parse_date(match.group(1), reference_date=reference_date)
        if candidate:
            return candidate
    return None


# The same cap as the detail parser, imported rather than repeated. These two
# numbers have to agree -- storing less here than the parser captured discards
# exactly the tail the parser was widened for, and sponsorship and
# work-authorization wording sits at the end of a posting -- and a comment
# asking a human to keep two literals in step is not a mechanism.
from services.faculty_jobs_sources.source_jobboards import (  # noqa: E402
    DETAIL_TEXT_LIMIT as DESCRIPTION_EXCERPT_LIMIT,
)


def normalize_source_job(source_job, source_region=None):
    """Convert a SourceJob-like object into DB-ready normalized fields."""
    raw_title = clean_text(getattr(source_job, "title_raw", None)) or "Untitled academic job"
    institution_raw = clean_text(getattr(source_job, "institution_raw", None)) or "Unknown institution"
    school_raw = clean_text(getattr(source_job, "school_raw", None)) or None
    department = clean_text(getattr(source_job, "department_raw", None)) or None
    description = clean_text(getattr(source_job, "description_excerpt", None))
    extra = getattr(source_job, "extra", {}) or {}
    # A country the posting itself exposes is evidence; the board's registered
    # region is only a default and must not become the job's country.
    posting_country = extra.get("country_code")
    fallback_region = posting_country or source_region
    region_is_board_default = not posting_country
    first_seen = (clean_text(getattr(source_job, "captured_at", None))
              or datetime.now(timezone.utc).replace(microsecond=0)
                 .isoformat(timespec="seconds").replace("+00:00", "Z"))
    location = parse_location(
        getattr(source_job, "location_raw", None), fallback_region,
        institution_text=institution_raw,
        region_is_board_default=region_is_board_default,
        description=None if extra.get("suppress_location_description") else description,
    )
    rank = map_rank(location["country_code"], raw_title)
    classification = classify_disciplines(department, raw_title, description)
    faculty_role = classify_faculty_market_role(
        raw_title,
        description,
        getattr(source_job, "official_url", None) or getattr(source_job, "source_url", None),
    )
    school_evidence_context = clean_text(extra.get("school_evidence_context")) or "posting"
    business_scope = classify_business_scope(
        department=department,
        title=raw_title,
        description=description,
        institution=institution_raw,
        school=school_raw,
        source=getattr(source_job, "source", None),
        school_is_posting_evidence=school_evidence_context in {
            "posting", "structured_posting", "source_employer",
        },
        faculty_role=faculty_role,
    )
    deadline = parse_deadline(
        getattr(source_job, "deadline_raw", None), description,
        reference_date=first_seen, return_details=True,
    )
    salary = parse_salary(getattr(source_job, "salary_raw", None))
    combined = " ".join(item for item in (raw_title, department or "", description) if item)
    start_term, start_year = parse_start(combined)
    # A contract stated in this vacancy's title takes precedence over general
    # department prose mentioning other faculty appointments.
    title_track = infer_track(raw_title)
    track = title_track if title_track != "unknown" else infer_track(combined)
    # One call now yields the status, the sentence it came from, and any
    # programme the posting names outright.
    visa = classify_visa(combined)
    visa_status = visa["status"]
    phd_required = infer_phd(combined)
    source_url = normalize_url(getattr(source_job, "source_url", None))
    official_url = normalize_url(getattr(source_job, "official_url", None))
    # A generic recruitment portal is useful source evidence but is not a
    # job-specific official application destination. Keep it in the preserved
    # source record; do not expose it as the job's official application URL or
    # use it as a cross-source identity.
    if official_url and not is_mergeable_official_url(official_url):
        official_url = None
    fingerprint = fingerprint_fields(institution_raw, raw_title, location["city"], location["state_province"], classification["primary"], start_year)
    return {
        "title_raw": raw_title,
        "title_normalized": normalize_name(raw_title),
        "institution_raw": institution_raw,
        "institution_normalized": normalize_name(institution_raw),
        "institution_only_school": bool(extra.get("detail_institution_only_school")),
        "school_raw": school_raw,
        "department": department,
        "discipline_primary": classification["primary"],
        "discipline_secondary_json": json.dumps(classification["secondary"], ensure_ascii=False),
        "classification_reason": classification["reason"],
        "business_scope": business_scope["scope"],
        "business_scope_confidence": business_scope["confidence"],
        "business_scope_reason": business_scope["reason"],
        "faculty_market_role": faculty_role["role"],
        "faculty_market_eligible": int(bool(faculty_role["eligible"])),
        "faculty_market_reason": faculty_role["reason"],
        "school_evidence_context": school_evidence_context,
        "school_evidence_rule_version": clean_text(extra.get("school_evidence_rule_version")) or None,
        # The board's own taxonomy label, when it publishes one ("Accounting",
        # "Business Law"). It is source-level discipline evidence and stronger
        # than anything derived from the title, so it is preserved in the
        # source record even though the derived discipline is computed
        # separately. Adapters were already setting it and it was being
        # dropped here, which lost the only categorisation the board asserted.
        "source_category": clean_text(extra.get("source_category")) or None,
        "keywords_json": json.dumps(sorted(set(re.findall(r"[A-Za-z][A-Za-z/+&-]{2,}", combined)))[:80], ensure_ascii=False),
        "rank_raw": raw_title,
        "rank_normalized": rank.rank_normalized,
        "career_stage": rank.career_stage,
        "rank_mapping_confidence": rank.confidence,
        "rank_mapping_explanation": rank.explanation,
        "track_type": track,
        # Read from the advertised title only. A description that mentions a
        # part-time MBA programme or a visiting speaker series would otherwise
        # file a tenure-track vacancy as contingent, and an inverted answer on
        # this field is worse than no answer.
        "appointment_type": infer_appointment(raw_title),
        "contract_type": track if track != "unknown" else None,
        "employment_type": "full_time" if re.search(r"full[- ]time", combined, re.I) else None,
        "contract_length": None,
        **location,
        "remote_type": "remote" if re.search(r"remote", combined, re.I) else ("hybrid" if re.search(r"hybrid", combined, re.I) else "on_site" if re.search(r"on[- ]site|onsite", combined, re.I) else "unknown"),
        "posted_date": parse_date(getattr(source_job, "posted_date_raw", None), reference_date=first_seen)
                      or parse_explicit_posted_date(description, reference_date=first_seen),
        "deadline_date": deadline["date"],
        "deadline_mode": deadline["mode"],
        "deadline_evidence": deadline.get("evidence"),
        "deadline_parse_reason": deadline.get("reason"),
        "start_term": start_term,
        "start_year": start_year,
        "salary_raw": salary["raw"],
        "salary_min": salary["min"],
        "salary_max": salary["max"],
        "salary_currency": salary["currency"],
        "salary_period": salary["period"],
        "phd_required": phd_required,
        "phd_required_by": None,
        "teaching_areas_json": json.dumps([], ensure_ascii=False),
        "research_areas_json": json.dumps([], ensure_ascii=False),
        "teaching_load_raw": None,
        # The quoted sentence, so a reader can check the call rather than
        # trust it. NULL only when the posting genuinely said nothing.
        "visa_text": visa["evidence"],
        "visa_status": visa_status,
        "visa_pathways": ",".join(visa["pathways"]) or None,
        "language_requirements": None,
        "official_url": official_url,
        "source_url": source_url,
        "description_excerpt": description[:DESCRIPTION_EXCERPT_LIMIT] if description else None,
        "fingerprint": fingerprint,
        "canonical_key": canonical_key(official_url, fingerprint),
        "captured_at": first_seen,
        "original_title": raw_title,
        "rank_evidence": raw_title,
        "track_evidence": combined[:2000],
        "visa_evidence": visa["evidence"],
    }


__all__ = [
    "DISCIPLINES", "BUSINESS_SCOPES", "FACULTY_MARKET_ROLES", "COUNTRY_ALIASES", "REGION_GROUPS", "CITY_COUNTRY_HINTS", "normalize_url", "normalize_name",
    "parse_date", "parse_deadline", "parse_salary", "parse_location", "parse_explicit_posted_date", "country_code_for", "country_from_text", "COUNTRY_OPTIONS", "classify_disciplines", "classify_business_scope",
    "classify_faculty_market_role", "infer_track", "infer_visa", "classify_visa",
    "visa_pathways", "VISA_STATUSES", "VISA_BLOCKING_STATUSES", "VISA_SUPPORTIVE_STATUSES", "normalize_source_job", "fingerprint_fields", "canonical_key", "is_mergeable_official_url",
    "hiring_cycle", "hiring_cycle_reason",
]
