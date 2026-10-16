# -*- coding: utf-8 -*-
"""PhD programme pages: the panel registry and the four layers it feeds.

The audit found what makes this hard. Of twelve business doctoral programmes
probed, five hand-guessed URLs 404'd -- there is no URL convention to template
-- and of the seven reachable pages, **none** published an expected graduation
year. So this is deliberately not an automated crawler. It is a registry of
pages a person found, plus a snapshot mechanism that stores what those pages
said at a point in time.

The urgency is not the parsing. Job-market-candidate pages are replaced by the
next cohort every autumn and the previous year is not archived anywhere. A page
not captured in the 2026-27 cycle is gone. Capturing it badly now beats parsing
it perfectly in 2028, so the snapshot stores raw HTML first and treats
extraction as a separate, revisable step.

Four layers, kept apart because conflating them is the easiest way to invent a
candidate supply:

  ``current_student``      enrolled; says nothing about entering the market
  ``near_graduation``      an estimated window, never an exact year
  ``explicit_jmc``         the school itself said "job market candidate"
  ``placement_observed``   where someone actually went

Only the third is a statement about the market, and only when the school made
it. A programme listing twenty students has twenty students, not twenty
candidates.

Privacy: names are stored only where a page publishes them and only to let a
later snapshot recognise the same person; the aggregates this module exposes
are counts. No ranking, no per-person scoring.
"""

import hashlib
import re
from datetime import datetime, timezone

# What a page is. Recorded per source so a snapshot knows what it captured.
PAGE_ROSTER = "roster"
PAGE_JMC = "jmc"
PAGE_PLACEMENT = "placement"
PAGE_KINDS = (PAGE_ROSTER, PAGE_JMC, PAGE_PLACEMENT)

# The four layers. Ordered from weakest claim to strongest.
LAYER_CURRENT = "current_student"
LAYER_NEAR_GRADUATION = "near_graduation"
LAYER_EXPLICIT_JMC = "explicit_jmc"
LAYER_PLACEMENT = "placement_observed"
LAYERS = (LAYER_CURRENT, LAYER_NEAR_GRADUATION, LAYER_EXPLICIT_JMC, LAYER_PLACEMENT)

# Median years from doctoral program start to degree, SED 2023 table 8-16,
# business fields. Used to give a near-graduation *window*, never a year.
SED_MEDIAN_YEARS_TO_DOCTORATE = 5.0
NEAR_GRADUATION_WINDOW = (4, 7)

# Only these phrases make a page an explicit statement about the market.
_EXPLICIT_JMC_RE = re.compile(
    r"\bjob\s*market\s*candidate", re.I)
_ON_THE_MARKET_RE = re.compile(
    r"\bon\s+the\s+(?:job\s+)?market\b|\bplacement\s+candidate\b|"
    r"\bjob\s+market\s+paper\b", re.I)


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_tables(conn):
    """Registry and snapshot tables. Idempotent."""
    # Discovered, not templated. The audit's 42% 404 rate on guessed URLs is
    # why this is a table a person fills rather than a pattern.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS phd_program_sources (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            institution_name TEXT NOT NULL,
            institution_id INTEGER,
            program        TEXT NOT NULL,
            field          TEXT,
            program_url    TEXT,
            roster_url     TEXT,
            jmc_url        TEXT,
            placement_url  TEXT,
            carnegie_basic INTEGER,
            source_type    TEXT NOT NULL DEFAULT 'manual',
            status         TEXT NOT NULL DEFAULT 'active',
            last_checked   TEXT,
            notes          TEXT,
            UNIQUE (institution_name, program)
        )
    """)
    # One row per page per capture. content_hash lets an unchanged page cost
    # one archive blob while still recording that we looked.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS phd_page_snapshots (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            program_source_id INTEGER NOT NULL,
            page_kind      TEXT NOT NULL,
            market_cycle   TEXT NOT NULL,
            source_url     TEXT NOT NULL,
            observed_at    TEXT NOT NULL,
            http_status    INTEGER,
            content_hash   TEXT,
            candidate_count INTEGER,
            parser_status  TEXT NOT NULL,
            parser_note    TEXT,
            FOREIGN KEY (program_source_id) REFERENCES phd_program_sources(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_phd_snapshot_cycle "
                 "ON phd_page_snapshots(market_cycle, page_kind)")
    # People, only where a page published them, and only as an internal id in
    # anything aggregated. The layer column is the whole point of the table.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS phd_person_observations (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id    INTEGER NOT NULL,
            person_key     TEXT NOT NULL,
            display_name   TEXT,
            layer          TEXT NOT NULL,
            field          TEXT,
            entry_year     INTEGER,
            market_window_start INTEGER,
            market_window_end   INTEGER,
            placement_institution TEXT,
            placement_kind TEXT,
            evidence       TEXT,
            confidence     TEXT NOT NULL,
            FOREIGN KEY (snapshot_id) REFERENCES phd_page_snapshots(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_phd_person_layer "
                 "ON phd_person_observations(layer, field)")


def person_key(institution, name):
    """A stable internal id. Public aggregates never expose the name."""
    basis = f"{(institution or '').strip().casefold()}|{(name or '').strip().casefold()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def register_program(conn, institution_name, program, **fields):
    """Record a programme whose pages a person located."""
    columns = ["institution_name", "program"] + list(fields)
    values = [institution_name, program] + list(fields.values())
    placeholders = ",".join("?" for _ in columns)
    updates = ",".join(f"{c}=excluded.{c}" for c in fields)
    conn.execute(f"""
        INSERT INTO phd_program_sources ({','.join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(institution_name, program) DO UPDATE SET {updates or 'program=program'}
    """, values)
    return conn.execute(
        "SELECT id FROM phd_program_sources WHERE institution_name=? AND program=?",
        (institution_name, program)).fetchone()[0]


def classify_layer(text, *, page_kind):
    """Which layer a page's mention of a person supports.

    A roster page listing students supports ``current_student`` and nothing
    stronger, whatever the page is called. Only the school's own words --
    "job market candidate", "on the market" -- reach ``explicit_jmc``.
    """
    body = text or ""
    if _EXPLICIT_JMC_RE.search(body) or _ON_THE_MARKET_RE.search(body):
        return LAYER_EXPLICIT_JMC, "the page names them a job-market candidate"
    if page_kind == PAGE_PLACEMENT:
        return LAYER_PLACEMENT, "listed on the programme's placement page"
    return LAYER_CURRENT, (
        "listed as an enrolled student; enrolment is not market participation")


def market_window(entry_year):
    """A window, not a year.

    No page in the audit's sample published an expected graduation date, so
    this is derived from SED's median 5.0 years to doctorate. A window is the
    honest shape: a point estimate would look like something the school said.
    """
    if not entry_year:
        return None, None
    low, high = NEAR_GRADUATION_WINDOW
    return int(entry_year) + low, int(entry_year) + high


def record_snapshot(conn, program_source_id, page_kind, market_cycle, source_url, *,
                    http_status=None, content_hash=None, candidate_count=None,
                    parser_status="captured", parser_note=None, observed_at=None):
    """Record that a page was captured. Parsing is a separate, later step."""
    if page_kind not in PAGE_KINDS:
        raise ValueError(f"unknown page kind {page_kind!r}; expected {PAGE_KINDS}")
    cursor = conn.execute("""
        INSERT INTO phd_page_snapshots
          (program_source_id, page_kind, market_cycle, source_url, observed_at,
           http_status, content_hash, candidate_count, parser_status, parser_note)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (program_source_id, page_kind, market_cycle, source_url,
          observed_at or now_utc(), http_status, content_hash, candidate_count,
          parser_status, parser_note))
    conn.execute("UPDATE phd_program_sources SET last_checked=? WHERE id=?",
                 (observed_at or now_utc(), program_source_id))
    return cursor.lastrowid


def pipeline_summary(conn, market_cycle=None):
    """Counts by layer. Never a supply figure.

    Each layer is reported on its own. Adding them would produce a number that
    looks like candidate supply and is not one: the same person can appear as
    an enrolled student and as an explicit candidate, and neither tells us
    about the people competing from other countries or from postdocs.
    """
    where = "WHERE s.market_cycle = ?" if market_cycle else ""
    args = (market_cycle,) if market_cycle else ()
    rows = conn.execute(f"""
        SELECT p.layer, COUNT(DISTINCT p.person_key) AS people,
               COUNT(DISTINCT s.program_source_id) AS programs
        FROM phd_person_observations p
        JOIN phd_page_snapshots s ON s.id = p.snapshot_id
        {where}
        GROUP BY p.layer
    """, args).fetchall()
    by_layer = {row["layer"]: {"people": row["people"], "programs": row["programs"]}
                for row in rows}
    coverage = conn.execute(f"""
        SELECT COUNT(DISTINCT program_source_id) AS programs_captured,
               COUNT(*) AS snapshots,
               SUM(CASE WHEN parser_status='captured' THEN 1 ELSE 0 END) AS unparsed
        FROM phd_page_snapshots s {where.replace('s.', '')}
    """, args).fetchone()
    registered = conn.execute(
        "SELECT COUNT(*) FROM phd_program_sources WHERE status='active'").fetchone()[0]
    return {
        "market_cycle": market_cycle,
        "programs_registered": registered,
        "programs_captured": coverage["programs_captured"] or 0,
        "snapshots": coverage["snapshots"] or 0,
        "snapshots_not_yet_parsed": coverage["unparsed"] or 0,
        "by_layer": {layer: by_layer.get(layer, {"people": 0, "programs": 0})
                     for layer in LAYERS},
        "not_a_supply": (
            "Layers are reported separately and must not be summed. Enrolment is "
            "not market participation; an explicit job-market-candidate count "
            "covers only programmes that publish one and only US programmes in "
            "this panel, so it is a floor on one slice of the competition, not a "
            "candidate supply."),
        "coverage_note": (
            f"{coverage['programs_captured'] or 0} of {registered} registered "
            "programmes captured this cycle. Systematic tracking begins 2026-27; "
            "earlier cycles were not captured and cannot be reconstructed."),
    }


__all__ = [
    "LAYERS", "LAYER_CURRENT", "LAYER_EXPLICIT_JMC", "LAYER_NEAR_GRADUATION",
    "LAYER_PLACEMENT", "NEAR_GRADUATION_WINDOW", "PAGE_JMC", "PAGE_KINDS",
    "PAGE_PLACEMENT", "PAGE_ROSTER", "SED_MEDIAN_YEARS_TO_DOCTORATE",
    "classify_layer", "ensure_tables", "market_window", "person_key",
    "pipeline_summary", "record_snapshot", "register_program",
]
