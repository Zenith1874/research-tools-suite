# -*- coding: utf-8 -*-
"""A* publication footprint as school evidence.

School tiers were 920 T4, 291 Unclassified, 1 T3, 1 T2, 0 T1. The ladder in
``classify_business_school`` is evidence-driven, and the only evidence the
database held at scale was AACSB accreditation -- which lands every school on
T4 by definition. The research signal it wants (``UTD24_publication_footprint``,
``FT50_publication_footprint``, ``recognized_research_ranking``) had no source.

The suite already owns one: 136k ABDC A* articles whose OpenAlex authorships now
carry institution identities. This module links a faculty-market institution to
that corpus by exact normalized name and records the observed article count as
evidence, so the existing tier rules can use it. It does not compute a tier and
does not rank anything.

The link is by exact normalized name only. Fuzzy institution matching would put
one school's publication record on another's page, which is worse than leaving
the tier unclassified.
"""

from datetime import datetime, timezone
import re
import sqlite3

EVIDENCE_TYPE = "astar_publication_footprint"
# Below the threshold the observation is still recorded, under a separate type,
# so it shows on the school page without counting as a research signal in the
# tier ladder. Any confidence above "none" would otherwise promote a school
# with a single incidental co-authorship.
EVIDENCE_TYPE_BELOW_THRESHOLD = "astar_publication_footprint_observed"
SOURCE_NAME = "A* Research Radar (OpenAlex authorships)"
# Below this the count is indistinguishable from incidental co-authorship at the
# corpus coverage reached so far.
HIGH_RESEARCH_MIN_ARTICLES = 25


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_institution(value):
    """Conservative name key. Exact matches only -- no fuzzy institution joins."""
    text = (value or "").casefold()
    # Spaces matter: a bare replacement turns "A&M" into "aandm", which then
    # fails to match the spelled-out "A and M" form.
    text = re.sub(r"&", " and ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^the ", "", text)


def astar_institution_index(astar_conn):
    """Map normalized institution name -> (ror, openalex_id, article_count).

    One OpenAlex institution can appear under several display-name variants; the
    variant with the most observed articles wins, so a stray spelling cannot
    shadow the main record.
    """
    index = {}
    for name, ror, openalex_id, articles in astar_conn.execute("""
        SELECT institution_display_name, MIN(institution_ror), institution_openalex_id,
               COUNT(DISTINCT article_id)
        FROM astar_article_affiliations
        WHERE institution_openalex_id!='' AND institution_display_name IS NOT NULL
        GROUP BY institution_openalex_id
    """):
        key = normalize_institution(name)
        if not key:
            continue
        if key not in index or articles > index[key][2]:
            index[key] = (ror, openalex_id, articles)
    return index


def astar_coverage(astar_conn):
    """What fraction of the corpus the counts are drawn from.

    Every number this module produces is a floor until the affiliation backfill
    finishes, and the covered years are not uniform, so the caveat travels with
    the evidence rather than living only in a status document.
    """
    total = astar_conn.execute("SELECT COUNT(*) FROM astar_articles").fetchone()[0]
    checked = astar_conn.execute(
        "SELECT COUNT(*) FROM astar_articles WHERE affiliation_status IS NOT NULL").fetchone()[0]
    years = [row[0] for row in astar_conn.execute("""
        SELECT publication_year FROM astar_articles
        WHERE publication_year IS NOT NULL AND affiliation_status IS NOT NULL
        GROUP BY publication_year
        HAVING COUNT(*) * 1.0 / (SELECT COUNT(*) FROM astar_articles a2
                                 WHERE a2.publication_year=astar_articles.publication_year) >= 0.5
        ORDER BY publication_year
    """)]
    return {
        "articles_total": total,
        "articles_checked": checked,
        "checked_pct": round(100.0 * checked / total, 2) if total else 0.0,
        "covered_years": years,
        "window": f"{years[0]}-{years[-1]}" if years else "none",
    }


def ensure_link_columns(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(institutions)")}
    if "ror" not in columns:
        conn.execute("ALTER TABLE institutions ADD COLUMN ror TEXT")
    if "openalex_institution_id" not in columns:
        conn.execute("ALTER TABLE institutions ADD COLUMN openalex_institution_id TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_institutions_ror ON institutions(ror)")


def refresh_astar_school_evidence(conn, astar_conn):
    """Link institutions to the A* corpus and record the footprint as evidence.

    Re-runnable: the counts grow as the affiliation backfill proceeds. The
    prior observation rows are retained as historical evidence and only the
    latest observation is current.
    """
    ensure_link_columns(conn)
    index = astar_institution_index(astar_conn)
    coverage = astar_coverage(astar_conn)
    note = (f"Observed distinct A* articles with at least one authorship at this institution. "
            f"Derived from the A* corpus at {coverage['checked_pct']}% affiliation coverage "
            f"(years at least half covered: {coverage['window']}). This is a floor, not a "
            f"complete publication record, and it is not an official ranking.")
    stamp = now_utc()

    linked = evidence_rows = above_threshold = 0
    schools = conn.execute("""
        SELECT bs.id AS school_id, i.id AS institution_id, i.official_name
        FROM business_schools bs JOIN institutions i ON i.id=bs.institution_id
        WHERE bs.is_current=1 AND i.official_name IS NOT NULL
    """).fetchall()
    # Keep prior observations as historical evidence. The affiliation
    # backfill is a moving snapshot, so deleting yesterday's count would make
    # the research trail impossible to audit. Only the latest rows are marked
    # current; the school service ignores superseded rows for classification.
    conn.execute(
        "UPDATE school_evidence SET is_current=0, valid_to=? "
        "WHERE evidence_type IN (?,?) AND is_current=1",
        (stamp, EVIDENCE_TYPE, EVIDENCE_TYPE_BELOW_THRESHOLD),
    )
    for row in schools:
        match = index.get(normalize_institution(row["official_name"]))
        if not match:
            continue
        ror, openalex_id, articles = match
        conn.execute(
            "UPDATE institutions SET ror=COALESCE(?,ror), openalex_institution_id=? WHERE id=?",
            (ror, openalex_id, row["institution_id"]))
        linked += 1
        if articles < 1:
            continue
        above = articles >= HIGH_RESEARCH_MIN_ARTICLES
        conn.execute("""
            INSERT INTO school_evidence
              (school_id,evidence_type,value,source_name,source_url,source_date,
               verified_at,confidence,notes,is_current,valid_from)
            VALUES (?,?,?,?,?,?,?,?,?,1,?)
        """, (row["school_id"],
              EVIDENCE_TYPE if above else EVIDENCE_TYPE_BELOW_THRESHOLD,
              str(articles), SOURCE_NAME,
              f"https://openalex.org/{openalex_id}", stamp[:10], stamp,
              ("High" if articles >= 4 * HIGH_RESEARCH_MIN_ARTICLES else "Medium")
              if above else "Low",
              note if above else note + f" Below the {HIGH_RESEARCH_MIN_ARTICLES}-article "
              "threshold, so it is recorded but does not count as a research signal.",
              stamp))
        evidence_rows += 1
        if above:
            above_threshold += 1
    return {"institutions_linked": linked, "evidence_rows": evidence_rows,
            "above_threshold": above_threshold,
            "astar_institutions_indexed": len(index), "coverage": coverage}


def open_astar(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


__all__ = [
    "EVIDENCE_TYPE", "HIGH_RESEARCH_MIN_ARTICLES", "SOURCE_NAME",
    "EVIDENCE_TYPE_BELOW_THRESHOLD",
    "astar_coverage", "astar_institution_index", "ensure_link_columns",
    "normalize_institution", "open_astar", "refresh_astar_school_evidence",
]
