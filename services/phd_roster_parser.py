# -*- coding: utf-8 -*-
"""Read the people off a programme's job-market or placement page.

There is no shared markup across business schools, so this is a registry of
parsers written against pages that were actually fetched and read -- not a
generic scraper that would quietly return nothing on a layout it does not
understand.

**The rule the whole module exists for: a page we could not parse reports a
count of ``None``, never 0.** Stanford's job-market page lists six candidates;
Kelley's is a JavaScript shell whose candidate list is fetched after load; and
Stanford's ``/placement`` is a landing page with no per-person records at all.
Those three are completely different facts, and writing 0 for the last two
would turn "we cannot read this" into "this programme has nobody on the
market" -- the single most damaging mistake this dataset could make.

So every page ends in one of four states:

``parsed``        people were extracted; the count means something.
``js_rendered``   the list is loaded by script; the HTML is an empty shell.
``no_records``    the page was read and carries no per-person records. It is a
                  landing or navigation page, not a roster.
``unrecognised``  we have no parser for this layout.

Names are used to derive a stable internal key and then discarded -- the
pipeline stores ``person_key`` and never the name.
"""

import html as html_module
import re
from urllib.parse import urlparse

STATUS_PARSED = "parsed"
STATUS_JS_RENDERED = "js_rendered"
STATUS_NO_RECORDS = "no_records"
STATUS_UNRECOGNISED = "unrecognised"

# Markers of a list assembled in the browser. Their presence means the HTML we
# hold is not the page a person sees.
_JS_SHELL_MARKERS = (
    "cardloaderHolder", "cardfilter-results", "__NEXT_DATA__",
    "data-react-class", "ng-app", "v-cloak",
)

# Headings that sit above candidates without describing one. "Placement
# Directors" is a real <h2> on Stanford's page, and taking the nearest heading
# blindly would file a candidate under it as their field of study.
_NOT_A_FIELD_RE = re.compile(
    r"placement\s+director|jump\s+to|contact|social\s+media|"
    r"^\s*(?:overview|resources|news)\s*$", re.I)


def _text(fragment):
    return html_module.unescape(re.sub(r"<[^>]+>", "", fragment or "")).strip()


def looks_like_js_shell(html):
    return any(marker in (html or "") for marker in _JS_SHELL_MARKERS)


def _sections(html):
    """(offset, heading text) for every ``h2`` that could name a field.

    ``h2`` only. Candidate names are themselves ``h3`` headings, so including
    ``h3`` made each candidate the "field of study" of the next one down the
    page -- Samuel Pertl's field came out as "Abigail Bergman".
    """
    found = []
    for match in re.finditer(r"<h2[^>]*>(.*?)</h2>", html, re.S):
        title = " ".join(_text(match.group(1)).split())
        if title and not _NOT_A_FIELD_RE.search(title):
            found.append((match.start(), title))
    return found


def _field_for(sections, position):
    field = None
    for offset, title in sections:
        if offset < position:
            field = title
        else:
            break
    return field


def parse_stanford_gsb(html, url):
    """Stanford GSB job-market candidates.

    The candidate is the ``h3.views-field-title`` anchor, and it points into
    ``/students/``. Each block also lists faculty advisors, whose links point
    into ``/faculty-research/faculty/`` -- so the school's own URL taxonomy
    separates the person on the market from the professors supervising them.
    Reading names out of the block without that distinction would have
    recorded 28 advisors as job-market candidates.
    """
    pattern = re.compile(
        r'<h3[^>]*class="[^"]*views-field-title[^"]*"[^>]*>\s*'
        r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.S)
    sections = _sections(html)
    people = []
    for match in pattern.finditer(html):
        href, name = match.group(1), " ".join(_text(match.group(2)).split())
        if not name or "/students/" not in href:
            continue
        people.append({
            "name": name,
            "field": _field_for(sections, match.start()),
            "profile_url": href,
            "evidence": "listed on the programme's job-market-candidates page",
        })
    return people


# Host fragment -> (parser, page kinds it handles).
PARSERS = (
    ("gsb.stanford.edu", parse_stanford_gsb, ("jmc",)),
)


def _parser_for(url, page_kind):
    host = (urlparse(url).hostname or "").lower()
    for fragment, parser, kinds in PARSERS:
        if fragment in host and page_kind in kinds:
            return parser, f"{parser.__name__}"
    return None, None


def parse(html, url, page_kind):
    """Extract people, or say precisely why we could not.

    ``count`` is ``None`` for every status but ``parsed``. A caller that stores
    it must keep it null rather than coercing to zero.
    """
    result = {"people": [], "count": None, "parser": None,
              "status": STATUS_UNRECOGNISED, "note": None, "url": url,
              "page_kind": page_kind}

    if looks_like_js_shell(html):
        result.update(
            status=STATUS_JS_RENDERED,
            note=("the candidate list is assembled in the browser; the HTML we "
                  "hold is a shell and says nothing about how many people are "
                  "listed"))
        return result

    parser, name = _parser_for(url, page_kind)
    if parser is None:
        result["note"] = (
            f"no parser for {urlparse(url).hostname} at page kind {page_kind}; "
            "the page is archived and can be re-read when one is written")
        return result

    people = parser(html, url)
    result["parser"] = name
    if people:
        result.update(people=people, count=len(people), status=STATUS_PARSED)
        return result

    result.update(
        status=STATUS_NO_RECORDS,
        note=("the page was read and carries no per-person records -- a landing "
              "or navigation page rather than a roster. Not evidence that the "
              "programme has nobody on the market"))
    return result


__all__ = ["PARSERS", "STATUS_JS_RENDERED", "STATUS_NO_RECORDS", "STATUS_PARSED",
           "STATUS_UNRECOGNISED", "looks_like_js_shell", "parse",
           "parse_stanford_gsb"]
