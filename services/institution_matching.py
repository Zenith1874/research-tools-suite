# -*- coding: utf-8 -*-
"""Match employer names from official files to institutions we already know.

The problem is small and specific. PERM writes employers as the form received
them -- ``THE PENNSYLVANIA STATE UNIVERSITY``, ``EMBRYRIDDLE AERONAUTICAL
UNIVERSITY``, ``UNIVERSITY OF WASHINGTON  MICHAEL G. FOSTER SCHOOL OF
BUSINESS`` -- while ``institutions`` holds ``Pennsylvania State University``.
The existing ``normalize_name`` casefolds and strips punctuation but keeps a
leading "the" and keeps hyphens, so none of those three match.

Two rules shape everything here.

**Every match records how it was made.** An exact normalised hit and a match
made after dropping a campus suffix are different claims. They live in the same
table with a ``method`` and a ``confidence``, so an analysis that only trusts
the strong ones can say so, and a wrong match can be found and undone by the
rule that produced it rather than one row at a time.

**Nothing unmatched disappears.** Anything the rules cannot place goes to
``institution_match_queue`` with its occurrence count, so the queue is ordered
by how much it costs to leave it unresolved. A silent zero would look exactly
like a dataset with no academic employers in it.

No fuzzy scoring. Edit distance over institution names produces confident
nonsense -- "University of Miami" and "University of Milan" are two edits apart
-- and a wrong institution attributed with sponsorship history is worse than an
honest gap.
"""

import json
import re
import sqlite3
from datetime import datetime, timezone

# What produced a match, strongest first. The order is also the search order.
METHOD_EXACT = "exact_normalized"
METHOD_ALIAS = "known_alias"
METHOD_LEGAL = "legal_entity_prefix"
METHOD_PUNCTUATION = "punctuation_variant"
METHOD_CORE = "core_name"
METHOD_CAMPUS = "campus_suffix_stripped"
METHOD_MANUAL = "manual"

CONFIDENCE_BY_METHOD = {
    METHOD_EXACT: "verified",
    METHOD_ALIAS: "verified",
    METHOD_LEGAL: "verified",
    METHOD_PUNCTUATION: "observed",
    METHOD_CORE: "observed",
    METHOD_CAMPUS: "derived",
    METHOD_MANUAL: "verified",
}

EXTERNAL_PERM_EMPLOYER = "perm_employer"
EXTERNAL_LCA_EMPLOYER = "lca_employer"
EXTERNAL_PERM_PHD = "perm_phd_institution"
EXTERNAL_IPEDS = "ipeds_unitid"

# Words that carry no identity. "The University of Texas" and "University of
# Texas" are the same institution; "the" is not part of the name.
_LEADING_ARTICLES = re.compile(r"^(?:the)\s+", re.I)

# A school or college named inside an employer string. PERM often appends it:
# "UNIVERSITY OF WASHINGTON  MICHAEL G. FOSTER SCHOOL OF BUSINESS". The
# university is the employer; the school is a detail.
# Anchored on two or more spaces, which is how DOL separates the appended
# school from the employer. Without that anchor the pattern eats the
# university's own name: "University of Washington ... School of Business"
# collapsed to "University of", which would then match every "University of"
# in the table.
_SCHOOL_SUFFIX = re.compile(
    r"\s{2,}(?:[\w.'-]+\s+){0,4}"
    r"(?:school|college|institute|center|centre)\s+of\s+[\w\s&'-]+$", re.I)

# Campus qualifiers that identify a site rather than a different institution.
# Stripping one is a weaker claim, recorded as such.
_CAMPUS_SUFFIX = re.compile(
    r"\s*[-–,]\s*(?:main\s+campus|[a-z]+\s+campus|campus)$", re.I)

# System-level wrappers. "University of Wisconsin System" is not a campus.
_SYSTEM_SUFFIX = re.compile(r"\s+system$", re.I)

# The legal entity that holds the institution, not a different institution.
# "The Curators of the University of Missouri" is the University of Missouri.
_LEGAL_ENTITY_PREFIX = re.compile(
    r"^(?:the\s+)?(?:curators|regents|board\s+of\s+(?:trustees|regents|governors|"
    r"supervisors)|trustees|president\s+and\s+fellows)\s+of\s+(?:the\s+)?", re.I)


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_institution(value):
    """A comparison key for institution names.

    Deliberately more aggressive than the shared ``normalize_name``: hyphens
    become spaces so ``EMBRYRIDDLE`` and ``Embry-Riddle`` meet, and a leading
    article is dropped so ``THE PENNSYLVANIA STATE UNIVERSITY`` meets
    ``Pennsylvania State University``.
    """
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    text = text.replace("&", " and ")
    text = re.sub(r"[’'`.]", "", text)
    # Hyphens and slashes join words that are written both ways.
    text = re.sub(r"[-–—/]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    text = _LEADING_ARTICLES.sub("", text)
    return text


def core_name(value):
    """The institution without a named school, campus or system wrapper."""
    text = str(value or "").strip()
    for pattern in (_SCHOOL_SUFFIX, _SYSTEM_SUFFIX, _CAMPUS_SUFFIX):
        text = pattern.sub("", text).strip(" ,-–")
    return text


def punctuation_key(value):
    """A key that survives punctuation the source dropped or joined.

    Two patterns, both from real PERM rows and both deterministic -- the same
    name written differently, not a similarity guess:

    ``VIRGINIA POLYTECHNIC INSTITUTE  STATE UNIVERSITY``
        DOL stripped the ampersand and left a gap, so "institute and state"
        has to meet "institute state". Removing the connectors from both sides
        makes them the same key.

    ``EMBRYRIDDLE AERONAUTICAL UNIVERSITY``
        The hyphen in "Embry-Riddle" was deleted rather than turned into a
        space. Removing every space makes both sides "embryriddle...".
    """
    base = normalize_institution(value)
    if not base:
        return "", ""
    without_connectors = re.sub(r"\b(?:and|of|the)\b", " ", base)
    without_connectors = re.sub(r"\s+", " ", without_connectors).strip()
    return without_connectors, base.replace(" ", "")


def _collapse_spaces(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def build_index(faculty_conn):
    """Normalised name -> institution id, from names and recorded aliases.

    Also builds the punctuation-variant indexes. A key that two different
    institutions share is dropped from those indexes rather than resolved
    arbitrarily: "the same string with the spaces removed" is a weaker identity
    than a full name, and a collision means it is not identifying anything.
    """
    exact = {}
    alias = {}
    connectors, squashed = {}, {}

    # A variant key claimed by two ids is only a collision when those ids are
    # different institutions. This table holds duplicate rows for the same
    # school -- "Embry-Riddle Aeronautical University" appears twice -- and
    # treating that as a conflict threw away a legitimate match. Ids are
    # collected per key and resolved after the scan, when the names are known.
    variant_owners = {"connectors": {}, "squashed": {}}
    names_by_id = {}

    def note_variants(name, institution_id):
        without_connectors, no_spaces = punctuation_key(name)
        for bucket_name, key in (("connectors", without_connectors),
                                 ("squashed", no_spaces)):
            if not key or len(key) < 8:
                continue
            variant_owners[bucket_name].setdefault(key, set()).add(institution_id)

    for row in faculty_conn.execute(
            "SELECT id, official_name, normalized_name, aliases_json FROM institutions"):
        key = normalize_institution(row["official_name"])
        if key:
            exact.setdefault(key, row["id"])
        names_by_id[row["id"]] = key
        note_variants(row["official_name"], row["id"])
        stored = normalize_institution(row["normalized_name"])
        if stored:
            exact.setdefault(stored, row["id"])
        try:
            for name in json.loads(row["aliases_json"] or "[]"):
                alias_key = normalize_institution(name)
                if alias_key:
                    alias.setdefault(alias_key, row["id"])
                note_variants(name, row["id"])
        except (ValueError, TypeError):
            continue

    try:
        for row in faculty_conn.execute(
                "SELECT alias_normalized, canonical_name FROM institution_aliases"):
            key = normalize_institution(row["alias_normalized"])
            target = exact.get(normalize_institution(row["canonical_name"]))
            if key and target:
                alias.setdefault(key, target)
    except sqlite3.DatabaseError:
        pass

    # Resolve each variant key now that every name is known. Several ids
    # sharing a key is fine when they are duplicate rows for one school; the
    # lowest id wins. Two genuinely different names sharing a key means the key
    # identifies nothing, and it is dropped.
    for bucket_name, bucket in (("connectors", connectors), ("squashed", squashed)):
        for key, ids in variant_owners[bucket_name].items():
            # Duplicate rows for one school share an identical official name;
            # two different schools do not. Comparing the full normalised name
            # -- not the variant key, which is what collided in the first place
            # -- is what separates the two cases.
            distinct_names = {names_by_id.get(i) for i in ids if names_by_id.get(i)}
            if len(ids) > 1 and len(distinct_names) != 1:
                continue
            bucket[key] = min(ids)
    return {"exact": exact, "alias": alias,
            "connectors": connectors, "squashed": squashed}


def match_name(name, index):
    """Return ``(institution_id, method)`` or ``(None, None)``.

    Rules are tried strongest first and stop at the first hit. Nothing here
    scores similarity: a near-miss is left for a person, because a wrong
    institution carrying sponsorship history is worse than a gap.
    """
    exact = index["exact"]
    alias = index["alias"]
    raw = _collapse_spaces(name)
    if not raw:
        return None, None

    key = normalize_institution(raw)
    if key in exact:
        return exact[key], METHOD_EXACT
    if key in alias:
        return alias[key], METHOD_ALIAS

    # A legal holder is the institution: "The Curators of the University of
    # Missouri" is the University of Missouri.
    legal = _LEGAL_ENTITY_PREFIX.sub("", raw).strip()
    if legal and legal != raw:
        legal_key = normalize_institution(legal)
        if legal_key in exact:
            return exact[legal_key], METHOD_LEGAL
        if legal_key in alias:
            return alias[legal_key], METHOD_LEGAL

    trimmed = core_name(raw)
    if trimmed and trimmed != raw:
        trimmed_key = normalize_institution(trimmed)
        if trimmed_key in exact:
            return exact[trimmed_key], METHOD_CORE
        if trimmed_key in alias:
            return alias[trimmed_key], METHOD_ALIAS

    # Punctuation the source dropped or joined. Both keys are built the same
    # way on each side, so this matches identical names written differently --
    # it is not a similarity score.
    without_connectors, no_spaces = punctuation_key(raw)
    if without_connectors and without_connectors in index["connectors"]:
        return index["connectors"][without_connectors], METHOD_PUNCTUATION
    if no_spaces and no_spaces in index["squashed"]:
        return index["squashed"][no_spaces], METHOD_PUNCTUATION

    without_campus = normalize_institution(_CAMPUS_SUFFIX.sub("", raw))
    if without_campus and without_campus != key and without_campus in exact:
        return exact[without_campus], METHOD_CAMPUS

    return None, None


def record_match(market_conn, kind, key, name, institution_id, method):
    market_conn.execute("""
        INSERT INTO institution_matches
          (external_kind, external_key, external_name, institution_id, method,
           confidence, matched_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(external_kind, external_key) DO UPDATE SET
          institution_id=excluded.institution_id, method=excluded.method,
          confidence=excluded.confidence, matched_at=excluded.matched_at
    """, (kind, key, name, institution_id, method,
          CONFIDENCE_BY_METHOD.get(method, "observed"), now_utc()))


def queue_unmatched(market_conn, kind, key, name, occurrences, reason):
    """Park a name a person has to resolve. Never drop it."""
    market_conn.execute("""
        INSERT INTO institution_match_queue
          (external_kind, external_key, external_name, occurrences,
           first_seen_at, last_seen_at, reason)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(external_kind, external_key) DO UPDATE SET
          occurrences=excluded.occurrences, last_seen_at=excluded.last_seen_at,
          reason=excluded.reason
    """, (kind, key, name, occurrences, now_utc(), now_utc(), reason))


# Tables whose employer column resolves to an institution. Named explicitly
# rather than passed as a caller-supplied string: these names are interpolated
# into SQL, and a whitelist is the difference between a parameter and an
# injection point.
EMPLOYER_TABLES = {
    "perm_faculty_cases": EXTERNAL_PERM_EMPLOYER,
    "lca_faculty_cases": EXTERNAL_LCA_EMPLOYER,
}


def match_employers(market_conn, faculty_conn, table, echo=None):
    """Resolve one table's employers, and queue the ones the rules cannot place.

    PERM and LCA name the same universities in the same messy ways -- "The
    Curators of the University of Missouri", "UNIVERSITY OF FLORIDA" -- so they
    share the rules. They keep separate ``external_kind`` values so a queue
    entry says which dataset raised it.
    """
    if table not in EMPLOYER_TABLES:
        raise ValueError(f"not an employer table: {table}")
    external_kind = EMPLOYER_TABLES[table]
    index = build_index(faculty_conn)
    rows = market_conn.execute(f"""
        SELECT employer_name, COUNT(*) AS cases
        FROM {table} WHERE employer_name IS NOT NULL AND employer_name != ''
        GROUP BY employer_name ORDER BY cases DESC
    """).fetchall()

    matched = queued = 0
    by_method = {}
    for row in rows:
        name = row["employer_name"]
        key = normalize_institution(name)
        institution_id, method = match_name(name, index)
        if institution_id:
            record_match(market_conn, external_kind, key, name,
                         institution_id, method)
            market_conn.execute(
                f"UPDATE {table} SET institution_id=? WHERE employer_name=?",
                (institution_id, name))
            matched += 1
            by_method[method] = by_method.get(method, 0) + 1
        else:
            queue_unmatched(
                market_conn, external_kind, key, name, row["cases"],
                "no exact, alias, core-name or campus-stripped match; "
                "fuzzy scoring is deliberately not attempted")
            queued += 1
    market_conn.commit()

    cases_matched = market_conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE institution_id IS NOT NULL"
    ).fetchone()[0]
    total_cases = market_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    result = {
        "table": table,
        "distinct_employers": len(rows),
        "employers_matched": matched,
        "employers_queued": queued,
        "by_method": by_method,
        "cases_matched": cases_matched,
        "cases_total": total_cases,
        "case_match_rate": round(100.0 * cases_matched / total_cases, 1) if total_cases else 0.0,
        "note": ("Unmatched employers are queued, not dropped. Most are "
                 "institutions this project has never seen -- medical centres, "
                 "community colleges, foreign employers -- rather than failures "
                 "to recognise a business school."),
    }
    if echo:
        echo(f"  {table}: matched {matched} of {len(rows)} employers "
             f"({result['case_match_rate']}% of cases); {queued} queued")
    return result


def match_perm_employers(market_conn, faculty_conn, echo=None):
    """Resolve PERM employers. Kept as a name because callers use it."""
    return match_employers(market_conn, faculty_conn, "perm_faculty_cases", echo)


def match_lca_employers(market_conn, faculty_conn, echo=None):
    """Resolve H-1B LCA employers."""
    return match_employers(market_conn, faculty_conn, "lca_faculty_cases", echo)


def match_report(market_conn, limit=12):
    """What matched, how, and what is still waiting."""
    methods = dict(market_conn.execute(
        "SELECT method, COUNT(*) FROM institution_matches GROUP BY 1").fetchall() or [])
    queue = [dict(row) for row in market_conn.execute("""
        SELECT external_name, occurrences FROM institution_match_queue
        ORDER BY occurrences DESC LIMIT ?
    """, (limit,))]
    return {
        "matches_by_method": methods,
        "queue_size": market_conn.execute(
            "SELECT COUNT(*) FROM institution_match_queue").fetchone()[0],
        "queue_top": queue,
        "confidence_note": (
            "exact_normalized and known_alias are verified; core_name is observed "
            "(a school or system wrapper was removed); campus_suffix_stripped is "
            "derived and should be reviewed before being used to attribute "
            "sponsorship history to a specific campus."),
    }


__all__ = [
    "CONFIDENCE_BY_METHOD", "EMPLOYER_TABLES", "EXTERNAL_IPEDS",
    "EXTERNAL_LCA_EMPLOYER", "EXTERNAL_PERM_EMPLOYER",
    "EXTERNAL_PERM_PHD", "METHOD_ALIAS", "METHOD_CAMPUS", "METHOD_CORE",
    "METHOD_EXACT", "METHOD_LEGAL", "METHOD_MANUAL", "METHOD_PUNCTUATION",
    "build_index", "core_name", "match_name", "punctuation_key",
    "match_perm_employers", "match_report", "normalize_institution",
    "queue_unmatched", "record_match",
]
