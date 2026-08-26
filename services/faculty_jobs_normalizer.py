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
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Florida": "FL",
    "Georgia": "GA", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
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
    r"\b(?:open\s+until\s+filled|until\s+(?:the\s+)?position\s+is\s+filled|"
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
        if code_token in _UNAMBIGUOUS_CODE_ALIASES:
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
            if matched_alias and matched_alias.casefold() == "america" and re.search(r"\b(?:north|south|central)\s+america\b", lower):
                continue
            return code
        if code in _UNAMBIGUOUS_CODE_ALIASES and any(
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


def parse_location(location_raw, source_region=None, institution_text=None, description=None):
    raw = _clean_location_text(location_raw)
    recovered = _recover_location_from_text(description, institution_text) if not raw else ""
    if recovered:
        raw = recovered
    evidence = "location_raw" if raw and location_raw else None
    state = None
    # ``Washington D.C.`` contains the full state name ``Washington`` as a
    # substring.  Resolve the federal district before scanning named states,
    # otherwise the generic alias loop incorrectly emits WA.
    if re.search(r"(?<!\w)Washington\s*,?\s*D\.?\s*C\.?(?!\w)", raw, re.I):
        state = "DC"
    # Prefer named provinces/states over two-letter tokens.  In particular,
    # ``Toronto, Ontario, CA`` contains both Ontario and the ambiguous CA
    # country token; the named province must win.
    if state is None:
        for name, abbreviation in STATE_PROVINCE_ALIASES.items():
            if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", raw, re.I):
                state = abbreviation
                break
    if state is None:
        for name, abbreviation in STATE_PROVINCE_ALIASES.items():
            if re.search(rf"[, ]{abbreviation}(?:[, ]|$)", raw):
                state = abbreviation
                break
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
    parts = [clean_text(item) for item in raw.split(",") if clean_text(item)] if raw else []
    city = parts[0] if parts else None
    if code and parts:
        code_name = country_display(code)
        remaining = [item for item in parts if normalize_name(item) not in {
            normalize_name(code_name), normalize_name(institution_text),
        }]
        # Some public boards expose only an ISO country token (for example
        # ``CN`` or ``AE``). That token is country evidence, not a city.
        if len(parts) == 1 and (
            parts[0].casefold() == str(code or "").casefold()
            or parts[0].casefold() == str(code_name or "").casefold()
        ):
            city = None
        elif parts[0].casefold() == str(code_name or "").casefold():
            city = remaining[-1] if remaining else None
        else:
            city = parts[0]
    if city:
        city = re.sub(r"\s*\([^)]{1,60}\)$", "", city).strip(" ,;|-—") or None
    if city and normalize_name(city) in {normalize_name(name) for name in STATE_PROVINCE_ALIASES}:
        city = None
    if city and re.search(r"(?:\b(?:street|road|avenue|allee|boulevard)\b|\b\w*(?:laan|weg|straat)\b)", city, re.I) and re.search(r"\d", city):
        city = None
    if city and not code:
        code = CITY_COUNTRY_HINTS.get(normalize_name(city))
        if code:
            evidence = "city_hint"
    source_code = country_code_for(source_region)
    if not code and source_code:
        code = source_code.casefold()
        evidence = "source_region_country"
    country = country_display(code)
    region_group = REGION_GROUPS.get(country, source_region if source_region in REGION_GROUPS.values() else "Other")
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
    ("Organizational Behavior / HR", ("organizational behavior", "organisational behaviour", "human resources", "human resource management", "organizational psychology")),
    ("Operations / Supply Chain", ("operations management", "supply chain", "operations and supply", "logistics")),
    ("Entrepreneurship", ("entrepreneurship", "entrepreneurial")),
    ("International Business", ("international business", "global business")),
    ("Strategy", ("strategic management", "strategy", "organization theory", "organisation theory")),
    ("Marketing", ("marketing", "consumer behavior", "consumer behaviour")),
    ("Finance", ("finance", "financial economics", "financial markets")),
    ("Accounting", ("accounting", "accountancy")),
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
    r"^faculty\s+positions\s+in\b",
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
    r"operations\s+manager|business\s+manager|vice\s+president|"
    r"research\s+(?:associate|scientist))\b",
    re.I,
)
_PROFESSOR_ROLE_RE = re.compile(r"\bprofessor\b", re.I)
_TEACHING_ROLE_RE = re.compile(r"\b(?:lecturer|instructor|faculty|reader)\b", re.I)
_LEADERSHIP_ROLE_RE = re.compile(r"\b(?:dean|chair(?:person)?|department\s+head)\b", re.I)
_POSTDOC_ROLE_RE = re.compile(r"\bpost[- ]?doc(?:toral)?\b", re.I)
_RESEARCH_ACADEMIC_ROLE_RE = re.compile(
    r"\b(?:research|teaching)\s+fellow\b",
    re.I,
)
_OPEN_RANK_RE = re.compile(r"\bopen[- ]rank\b", re.I)


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

    # Explicit professorial wording wins over phrases such as ``Research
    # Assistant Professor``; the latter is a professor, not a student RA.
    if _PROFESSOR_ROLE_RE.search(title_text) or _OPEN_RANK_RE.search(title_text):
        return {
            "eligible": 1, "role": "faculty", "confidence": "high",
            "reason": "Title contains an explicit professor/open-rank faculty signal.",
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
    if _LEADERSHIP_ROLE_RE.search(title_text):
        return {
            "eligible": 1, "role": "academic_leadership", "confidence": "high",
            "reason": "Title contains an explicit dean/chair/department-head signal.",
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
        "reason": "No explicit individual faculty, academic-leadership, or postdoctoral role was found.",
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
    r"business administration|business management|management)\b",
    re.I,
)
_NON_BUSINESS_RE = re.compile(
    r"\b(?:emergency medicine|pathology|pediatrics?|social work|poetry|landscape architecture|"
    r"orthodontics|architecture|biology|biotechnology|medicine|nursing|chemistry|physics|"
    r"sociology|psychology|computer science|electrical engineering|mechanical engineering|"
    r"radiopharmaceutical|radiochemical|pharmacy|pharmaceutical|chiropractic|cosmetology|"
    r"dental(?:\s+hygiene)?|dentistry|graphic design|studio art|fine arts?|journalism|"
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
    r"materials?\s+science|epidemiolog(?:y|ical)|implementation\s+science)\b",
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
        return {
            "scope": "non_academic" if role.get("role") in {"student_role", "staff_role", "listing_page"} else "unknown",
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


def classify_disciplines(department, title, description):
    fields = [clean_text(department), clean_text(title), clean_text(description)]
    hits = []
    # Field order is intentional: department evidence outranks title and text.
    for field_index, field in enumerate(fields):
        lower = field.casefold()
        if not lower:
            continue
        for discipline, terms in _DISCIPLINE_RULES:
            if any(term in lower for term in terms):
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


def infer_track(text):
    lower = clean_text(text).casefold()
    if re.search(r"tenure[- ]track|tenure stream|tenurable", lower):
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


def infer_visa(text):
    lower = clean_text(text).casefold()
    if re.search(r"will sponsor|visa sponsorship available|sponsor.*(h-?1b|work visa)|eligible.*sponsorship", lower):
        return "sponsorship_explicit_yes"
    if re.search(r"will not sponsor|no visa sponsorship|cannot sponsor|not eligible for sponsorship", lower):
        return "sponsorship_explicit_no"
    if re.search(r"international candidates welcome|welcome applications from international|global applicants welcome", lower):
        return "international_candidates_welcome"
    if re.search(r"visa|work authorization|work authorisation|right to work", lower):
        return "unclear"
    return "unknown"


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
    found = re.search(r"(?:fall|spring|summer|winter|autumn|commenc(?:e|ing)|start(?:ing)?|begin(?:ning)?)\s+(?:of\s+)?(20\d{2})", text, re.I)
    if found:
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


def normalize_source_job(source_job, source_region=None):
    """Convert a SourceJob-like object into DB-ready normalized fields."""
    raw_title = clean_text(getattr(source_job, "title_raw", None)) or "Untitled academic job"
    institution_raw = clean_text(getattr(source_job, "institution_raw", None)) or "Unknown institution"
    school_raw = clean_text(getattr(source_job, "school_raw", None)) or None
    department = clean_text(getattr(source_job, "department_raw", None)) or None
    description = clean_text(getattr(source_job, "description_excerpt", None))
    extra = getattr(source_job, "extra", {}) or {}
    fallback_region = extra.get("country_code") or source_region
    first_seen = (clean_text(getattr(source_job, "captured_at", None))
              or datetime.now(timezone.utc).replace(microsecond=0)
                 .isoformat(timespec="seconds").replace("+00:00", "Z"))
    location = parse_location(
        getattr(source_job, "location_raw", None), fallback_region,
        institution_text=institution_raw,
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
    track = infer_track(combined)
    visa_status = infer_visa(combined)
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
        "keywords_json": json.dumps(sorted(set(re.findall(r"[A-Za-z][A-Za-z/+&-]{2,}", combined)))[:80], ensure_ascii=False),
        "rank_raw": raw_title,
        "rank_normalized": rank.rank_normalized,
        "career_stage": rank.career_stage,
        "rank_mapping_confidence": rank.confidence,
        "rank_mapping_explanation": rank.explanation,
        "track_type": track,
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
        "visa_text": None,
        "visa_status": visa_status,
        "language_requirements": None,
        "official_url": official_url,
        "source_url": source_url,
        "description_excerpt": description[:2000] if description else None,
        "fingerprint": fingerprint,
        "canonical_key": canonical_key(official_url, fingerprint),
        "captured_at": first_seen,
        "original_title": raw_title,
        "rank_evidence": raw_title,
        "track_evidence": combined[:2000],
        "visa_evidence": combined[:2000] if visa_status != "unknown" else None,
    }


__all__ = [
    "DISCIPLINES", "BUSINESS_SCOPES", "FACULTY_MARKET_ROLES", "COUNTRY_ALIASES", "REGION_GROUPS", "CITY_COUNTRY_HINTS", "normalize_url", "normalize_name",
    "parse_date", "parse_deadline", "parse_salary", "parse_location", "parse_explicit_posted_date", "country_code_for", "country_from_text", "COUNTRY_OPTIONS", "classify_disciplines", "classify_business_scope",
    "classify_faculty_market_role", "infer_track", "infer_visa", "normalize_source_job", "fingerprint_fields", "canonical_key", "is_mergeable_official_url",
    "hiring_cycle", "hiring_cycle_reason",
]
