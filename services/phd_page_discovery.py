# -*- coding: utf-8 -*-
"""Find each doctoral programme's roster, job-market and placement pages.

The panel was seeded with twenty programme URLs and a note saying the rest were
"pending confirmation". That note is the thing this replaces: pending is not a
finding, and twenty rows that all say pending cannot be told apart from twenty
rows nobody has looked at.

So every programme ends in one of four states, and the difference between them
is the whole point:

``confirmed``   the page links to a roster / job-market / placement page.
``not_found``   the programme page was read and links to no such page. This is
                a fact about the programme's website. It is **not** a statement
                that the programme has no candidates on the market.
``blocked``     robots.txt refuses us. We do not know what the page says.
``unreachable`` the URL 404s or times out. Also not knowing.

Only the first is evidence. The audit already found 5 of 12 programme pages
404ing, so `unreachable` is the common case and has to stay visible rather than
collapsing into "no data".

Link classification is by the words schools actually use. A page called "Job
Market Candidates" is a JMC page; "Placement" or "Where Our Graduates Go" is a
placement page; "Current Students" or "Doctoral Students" is a roster. Nothing
is inferred from a URL that merely contains "phd".
"""

import re
import sqlite3
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from services import raw_archive
from services.faculty_jobs_sources.base import (
    AdapterError, CrawlBudgetExhaustedError, NonRetryableAdapterError,
    RobotsDisallowedError, SourceAdapter,
)

PARSER_VERSION = "phd_page_discovery/1"

KIND_ROSTER = "roster"
KIND_JMC = "jmc"
KIND_PLACEMENT = "placement"

STATUS_CONFIRMED = "confirmed"
STATUS_NOT_FOUND = "not_found"
STATUS_BLOCKED = "blocked"
STATUS_UNREACHABLE = "unreachable"

# Ordered: a link matching a stronger pattern is classified by that pattern
# first. "Job Market Candidates" is more specific than "Students", and a page
# offering both should be recorded as the job-market page.
_LINK_PATTERNS = (
    (KIND_JMC, re.compile(
        r"\bjob\s*market\b|\bjob-market\b|\bon\s+the\s+market\b|"
        r"\bmarket\s+candidates?\b|\bjmc\b", re.I)),
    (KIND_PLACEMENT, re.compile(
        r"\bplacements?\b|\bwhere\s+(?:our|they)\s+(?:graduates?|students?|alumni)\s+"
        r"(?:go|are|went)\b|\bgraduate\s+outcomes?\b|\balumni\s+placements?\b|"
        r"\bcareer\s+outcomes?\b", re.I)),
    (KIND_ROSTER, re.compile(
        r"\b(?:current|our)\s+(?:doctoral\s+|phd\s+)?students?\b|"
        r"\bdoctoral\s+students?\b|\bphd\s+students?\b|\bstudent\s+directory\b|"
        r"\bmeet\s+our\s+students?\b|\bstudent\s+profiles?\b", re.I)),
)

# Words that make a link about applying rather than about the people enrolled.
# "Prospective Students" and "Student Life" are not a roster.
_NOT_A_ROSTER_RE = re.compile(
    r"\bprospective\b|\bapply\b|\badmissions?\b|\bstudent\s+life\b|"
    r"\bfuture\s+students?\b|\bhow\s+to\s+apply\b", re.I)

# A path that puts the page under another programme level. Used only to reject
# a roster candidate, never to accept one -- "Current Students" is the right
# label on a school-wide link that leads to the undergraduate advising page.
_WRONG_PROGRAMME_LEVEL_RE = re.compile(
    r"/(?:undergrad(?:uate)?|ugrad|bachelors?|mba|emba|masters?|ms|msc|"
    r"executive[-_]?education|certificate)(?:/|$|[-_?#])", re.I)


class _Links(HTMLParser):
    """Anchors, as (href, text). Stdlib only, like the rest of the parsers."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._text).split())
            if text:
                self.links.append((self._href, text))
            self._href = None
            self._text = []


class _Discovery(SourceAdapter):
    """A bare adapter, used only for its robots and retry policy.

    Subclassed rather than reimplemented because these are arbitrary university
    websites, not boards we chose: the origin's own published rules should
    decide, and that logic already exists and is tested.
    """

    name = "phd_page_discovery"
    adapter_name = "phd_page_discovery"
    respect_robots = True

    def fetch(self):
        raise NotImplementedError("discovery drives request() directly")


def classify_link(href, text):
    """Which kind of page a link points at, or None.

    Judged on the link's own words: a URL containing "phd" says nothing about
    whether the page lists people, so the href is never positive evidence. It
    is used once, as a veto. Kelley's programme page carries a school-wide
    "Current Students" link pointing at ``/undergraduate/advising/``, and
    recording that as the doctoral roster would have attached undergraduate
    advising to the PhD panel.
    """
    label = " ".join((text or "").split())
    if not label:
        return None
    for kind, pattern in _LINK_PATTERNS:
        if pattern.search(label):
            if kind == KIND_ROSTER:
                if _NOT_A_ROSTER_RE.search(label):
                    return None
                if _WRONG_PROGRAMME_LEVEL_RE.search(href or ""):
                    return None
            return kind
    return None


def find_pages(html, base_url):
    """Roster / JMC / placement URLs linked from a programme page.

    Same-host only. A programme page linking to a national job-market listing
    elsewhere is not that programme publishing its own candidates.
    """
    parser = _Links()
    try:
        parser.feed(html or "")
    except Exception:  # noqa: BLE001 - a malformed page yields what it parsed
        pass
    base_host = (urlparse(base_url).hostname or "").lower().lstrip("www.")
    found = {}
    for href, text in parser.links:
        kind = classify_link(href, text)
        if not kind or kind in found:
            continue
        absolute = urljoin(base_url, href)
        scheme = urlparse(absolute).scheme
        if scheme not in ("http", "https"):
            continue
        host = (urlparse(absolute).hostname or "").lower().lstrip("www.")
        if base_host and host and not (host == base_host
                                       or host.endswith("." + base_host)
                                       or base_host.endswith("." + host)):
            continue
        found[kind] = {"url": absolute, "link_text": text}
    return found


def discover_programme(conn, row, adapter, *, archive=True):
    """Read one programme page and record what it links to.

    Returns a dict describing the outcome. Never raises for a page we could
    not read: not reading a page is a result, and it has to be stored as one.
    """
    url = row["program_url"]
    outcome = {"id": row["id"], "institution": row["institution_name"],
               "found": {}, "status": None, "note": None, "http_status": None}
    if not url:
        outcome["status"] = STATUS_UNREACHABLE
        outcome["note"] = "no programme URL recorded"
        return outcome

    try:
        response = adapter.request(url)
    except (RobotsDisallowedError, CrawlBudgetExhaustedError) as exc:
        outcome["status"] = STATUS_BLOCKED
        outcome["note"] = str(exc)[:280]
        return outcome
    except (NonRetryableAdapterError, AdapterError) as exc:
        outcome["status"] = STATUS_UNREACHABLE
        outcome["note"] = str(exc)[:280]
        return outcome
    except Exception as exc:  # noqa: BLE001 - transport failure is an outcome
        outcome["status"] = STATUS_UNREACHABLE
        outcome["note"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        return outcome

    body = response.text or ""
    outcome["http_status"] = getattr(response, "status_code", None)

    content_hash = None
    if archive:
        # Archive before parsing. These pages change every admissions cycle and
        # the parser will change too; the bytes are what cannot be re-fetched.
        try:
            content_hash = raw_archive.record_observation(
                conn, kind=raw_archive.KIND_ROSTER, source_url=url, payload=body,
                http_status=outcome["http_status"], parser_version=PARSER_VERSION)
        except Exception as exc:  # noqa: BLE001 - storage must not lose the read
            outcome["note"] = f"archive failed: {exc!r}"

    found = find_pages(body, url)
    outcome["found"] = found
    outcome["content_hash"] = content_hash
    outcome["status"] = STATUS_CONFIRMED if found else STATUS_NOT_FOUND
    if not found:
        outcome["note"] = ("programme page read; it links to no roster, job-market "
                           "or placement page. This describes the website, not "
                           "whether the programme has candidates on the market.")
    return outcome


def discover(conn, *, limit=None, sleep=1.0, echo=None, adapter=None, archive=True):
    """Walk the panel, recording what each programme page links to."""
    echo = echo or (lambda *_a, **_k: None)
    adapter = adapter or _Discovery(timeout=20)
    rows = conn.execute("""
        SELECT id, institution_name, program, program_url, status
        FROM phd_program_sources ORDER BY institution_name
    """).fetchall()
    if limit:
        rows = rows[:limit]

    results = []
    for row in rows:
        outcome = discover_programme(conn, row, adapter, archive=archive)
        results.append(outcome)
        found = outcome["found"]
        conn.execute("""
            UPDATE phd_program_sources
               SET roster_url = COALESCE(?, roster_url),
                   jmc_url = COALESCE(?, jmc_url),
                   placement_url = COALESCE(?, placement_url),
                   status = ?, last_checked = ?, notes = ?
             WHERE id = ?
        """, (
            (found.get(KIND_ROSTER) or {}).get("url"),
            (found.get(KIND_JMC) or {}).get("url"),
            (found.get(KIND_PLACEMENT) or {}).get("url"),
            outcome["status"], raw_archive.now_utc(),
            outcome["note"] or (
                "confirmed: " + ", ".join(sorted(found)) if found else None),
            row["id"],
        ))
        echo(f"  {str(row['institution_name'])[:34]:36}{outcome['status']:13}"
             f"{', '.join(sorted(found)) or '-'}")
        if sleep:
            import time
            time.sleep(float(sleep))
    conn.commit()

    by_status = {}
    for outcome in results:
        by_status[outcome["status"]] = by_status.get(outcome["status"], 0) + 1
    by_kind = {}
    for outcome in results:
        for kind in outcome["found"]:
            by_kind[kind] = by_kind.get(kind, 0) + 1
    return {
        "programmes": len(results),
        "by_status": by_status,
        "pages_found": by_kind,
        "results": results,
        "note": ("`not_found` means the programme's own page links to no such "
                 "page. `blocked` and `unreachable` mean we do not know what it "
                 "says. None of the three is evidence about how many candidates "
                 "a programme has on the market."),
    }


__all__ = ["KIND_JMC", "KIND_PLACEMENT", "KIND_ROSTER", "STATUS_BLOCKED",
           "STATUS_CONFIRMED", "STATUS_NOT_FOUND", "STATUS_UNREACHABLE",
           "classify_link", "discover", "discover_programme", "find_pages"]
