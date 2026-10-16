# -*- coding: utf-8 -*-
"""Evidence-first school enrichment and comparison helpers."""

from datetime import datetime, timezone
import json
import re
import os
import sqlite3
from urllib.parse import urlparse

from services.faculty_jobs_normalizer import country_code_for, normalize_name
from services.faculty_jobs_query import default_market_where


SCHOOL_TIERS = ("T1", "T2", "T3", "T4", "Unclassified")
UNIVERSITY_LEVELS = ("R1", "R2", "RCU", "Other", "Unknown")
EVIDENCE_TYPES = (
    "official_business_school_page", "Carnegie", "AACSB", "EQUIS", "AMBA", "business_phd_program", "U15",
    "Russell_Group", "LERU", "German_U15", "recognized_research_ranking",
    "UTD24_publication_footprint", "FT50_publication_footprint",
    "official_research_profile", "verified_manual_override",
)


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json(value, default):
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or "")
        return parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def evidence_for_school(conn, school_id):
    rows = conn.execute("""
        SELECT id, evidence_type, value, source_name, source_url, source_date,
               verified_at, confidence, notes, is_current, valid_from, valid_to
        FROM school_evidence WHERE school_id=? ORDER BY verified_at DESC, id DESC
    """, (school_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["current"] = bool(item.get("is_current", 1))
        result.append(item)
    return result


ASTAR_FOOTPRINT_LABEL = "Observed A* Publication Footprint"
_ASTAR_EVIDENCE_TYPES = ("astar_publication_footprint", "astar_publication_footprint_observed")


def astar_footprint_for_school(conn, school_id, evidence=None):
    """The school's A* publication footprint, presented as its own observation.

    This is shown next to the tier, never folded into it. The count is a floor:
    it is drawn from whatever share of the A* corpus has been affiliation-
    backfilled so far, and the covered years are not uniform, so the payload
    carries the coverage alongside the number rather than leaving a reader to
    assume it is a complete publication record.

    Returns None when the school has no linked A* identity, which is the honest
    answer for a school this database has not matched to the corpus.
    """
    rows = evidence if evidence is not None else evidence_for_school(conn, school_id)
    row = next((item for item in rows
                if item.get("evidence_type") in _ASTAR_EVIDENCE_TYPES
                and int(item.get("is_current", 1) or 0) == 1), None)
    if not row:
        return None
    try:
        articles = int(str(row.get("value") or "0"))
    except (TypeError, ValueError):
        articles = 0
    note = str(row.get("notes") or "")
    coverage_pct = None
    window = None
    match = re.search(r"([\d.]+)%\s+affiliation coverage", note)
    if match:
        try:
            coverage_pct = float(match.group(1))
        except ValueError:
            coverage_pct = None
    window_match = re.search(r"at least half covered:\s*([0-9]{4}-[0-9]{4}|none)", note)
    if window_match:
        window = window_match.group(1)
    counts_toward_tier = (
        row.get("evidence_type") == "astar_publication_footprint"
        and os.environ.get("FACULTY_ASTAR_TIER_SIGNAL") == "1"
    )
    return {
        "label": ASTAR_FOOTPRINT_LABEL,
        "articles": articles,
        "coverage_pct": coverage_pct,
        "covered_window": window,
        "source_name": row.get("source_name"),
        "source_url": row.get("source_url"),
        "observed_at": row.get("verified_at"),
        "meets_research_threshold": row.get("evidence_type") == "astar_publication_footprint",
        # Say plainly whether this number moved the tier, so the page never
        # implies a promotion that did not happen.
        "counts_toward_tier": counts_toward_tier,
        "explanation": (
            f"{articles} distinct ABDC A* article(s) list at least one author at this "
            f"institution, observed from "
            + (f"{coverage_pct}% of the A* corpus" if coverage_pct is not None
               else "the A* corpus")
            + (f" (years at least half covered: {window})" if window else "")
            + ". This is a floor, not a complete publication record, and it is not an "
              "official ranking. "
            + ("It is counted as a research signal in the tier ladder because "
               "FACULTY_ASTAR_TIER_SIGNAL=1 is set."
               if counts_toward_tier else
               "It does not affect this school's tier.")
        ),
    }


def _confidence(value):
    value = str(value or "").casefold()
    return {"high": 1.0, "medium": 0.7, "low": 0.4}.get(value, 0.0)


def classify_business_school(conn, school_id):
    """Classify only from explicit evidence or a separately logged override."""
    override = conn.execute("""
        SELECT tier, reason, source_url, created_at, updated_at
        FROM school_tier_overrides WHERE school_id=?
        ORDER BY updated_at DESC LIMIT 1
    """, (school_id,)).fetchone()
    evidence = evidence_for_school(conn, school_id)
    if override and override["tier"] in SCHOOL_TIERS:
        return {
            "tier": override["tier"], "score": None, "confidence": "High",
            "reason": "Manual override recorded locally with an explicit reason.",
            "manual_override": True, "evidence": evidence,
            "override": dict(override),
        }

    verified = [item for item in evidence
                if int(item.get("is_current", 1) or 0) == 1
                and _confidence(item.get("confidence")) > 0]
    types = {str(item.get("evidence_type") or "") for item in verified}
    # astar_publication_footprint is deliberately NOT in this set. It is shown
    # on its own as an Observed A* Publication Footprint with its coverage, and
    # it does not move a school's tier: a derived count from a partially
    # backfilled corpus is not the same kind of claim as a recognised ranking.
    # Set FACULTY_ASTAR_TIER_SIGNAL=1 to opt in explicitly.
    research_types = {"UTD24_publication_footprint", "FT50_publication_footprint",
                      "recognized_research_ranking"}
    if os.environ.get("FACULTY_ASTAR_TIER_SIGNAL") == "1":
        research_types.add("astar_publication_footprint")
    high_research = bool(types & research_types)
    phd = "business_phd_program" in types
    accreditation = bool(types & {"AACSB", "EQUIS", "AMBA"})
    research_network = bool(types & {"U15", "Russell_Group", "LERU", "German_U15", "Carnegie"})
    if high_research and phd and accreditation:
        tier, score, confidence = "T1", 90, "High"
    elif phd and accreditation and research_network:
        tier, score, confidence = "T2", 75, "Medium"
    elif high_research and accreditation and os.environ.get("FACULTY_ASTAR_TIER_SIGNAL") == "1":
        # Opt-in only. Without it the ladder cannot move past T4 for most
        # schools, because T3 and above require business_phd_program evidence
        # that exists for 3 of 1,029 schools with no available source. That is a
        # real limitation, but promoting on a derived publication count is a
        # judgement about what a tier means, so it stays the operator's call.
        tier, score, confidence = "T2", 70, "Medium"
    elif phd and accreditation:
        tier, score, confidence = "T3", 60, "Medium"
    elif accreditation:
        tier, score, confidence = "T4", 40, "Low"
    else:
        tier, score, confidence = "Unclassified", None, "Low"
    reasons = []
    if high_research: reasons.append("verified publication/ranking evidence")
    if high_research and not phd: reasons.append("no business PhD evidence available for this school")
    if phd: reasons.append("verified business PhD evidence")
    if accreditation: reasons.append("verified accreditation evidence")
    if research_network: reasons.append("verified research-network or Carnegie evidence")
    reason = "; ".join(reasons) if reasons else "Insufficient verified evidence; no tier assigned."
    return {"tier": tier, "score": score, "confidence": confidence,
            "reason": reason, "manual_override": False, "evidence": evidence,
            "override": None}


def refresh_school_classification(conn, school_id):
    result = classify_business_school(conn, school_id)
    conn.execute("""
        UPDATE business_schools
        SET business_research_tier=?, business_research_tier_score=?,
            business_research_tier_confidence=?, last_verified_at=?
        WHERE id=?
    """, (result["tier"], result["score"], result["confidence"], now_utc(), school_id))
    return result


def list_schools(db_path, query=None, limit=50, offset=0):
    query = query or {}
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        # The explorer is an observed-job directory. Exclude orphaned school
        # rows left by a corrected institution/location normalization rather
        # than presenting a duplicate institution with zero linked jobs.
        # Keep the job predicate in one grouped relation.  The previous
        # correlated EXISTS/COUNT/MAX subqueries were logically correct but
        # could make SQLite repeatedly choose the single-column market
        # eligibility index; on the production catalogue this made the
        # explorer endpoint appear hung.  One aggregation is both clearer
        # and bounded by the number of accepted market jobs.
        job_where = default_market_where("j")
        job_stats_select = """
            j.school_id,
            COUNT(*) AS observed_jobs,
            COUNT(*) AS current_openings,
            MAX(j.last_seen_at) AS jobs_last_seen
        """
        job_stats_args = []
        region = str(query.get("region") or "").strip()
        if region:
            job_stats_select += ", MAX(CASE WHEN j.region_group=? THEN 1 ELSE 0 END) AS has_region"
            job_stats_args.append(region)
        else:
            job_stats_select += ", 1 AS has_region"
        job_stats_cte = f"""
            WITH job_stats AS (
                SELECT {job_stats_select}
                FROM jobs j
                WHERE {job_where}
                GROUP BY j.school_id
            )
        """
        clauses = ["bs.is_current=1", "js.observed_jobs > 0", "js.has_region=1"]
        args = []
        text = str(query.get("q") or "").strip()
        if text:
            like = f"%{text}%"
            clauses.append("(i.official_name LIKE ? OR bs.official_name LIKE ? OR i.city LIKE ? OR i.country LIKE ?)")
            args.extend([like] * 4)
        country = str(query.get("country") or "").strip()
        if country:
            code = country_code_for(country)
            if code:
                clauses.append("i.country_code=?")
                args.append(code)
            else:
                clauses.append("1=0")
        tier = str(query.get("school_tier") or "").strip()
        if tier:
            clauses.append("bs.business_research_tier=?")
            args.append(tier)
        level = str(query.get("university_level") or "").strip()
        if level:
            clauses.append("i.university_research_level=?")
            args.append(level)
        for field, column in (("aacsb", "bs.aacsb"), ("equis", "bs.equis"), ("amba", "bs.amba"), ("doctoral_business_program", "bs.doctoral_business_program")):
            if str(query.get(field) or "").lower() in {"1", "true", "yes"}:
                clauses.append(f"{column}=1")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        from_sql = f"""
            FROM business_schools bs
            JOIN institutions i ON i.id=bs.institution_id AND i.is_current=1
            JOIN job_stats js ON js.school_id=bs.id
            {where}
        """
        count = conn.execute(f"""
            {job_stats_cte}
            SELECT COUNT(*) {from_sql}
        """, job_stats_args + args).fetchone()[0]
        rows = conn.execute(f"""
            {job_stats_cte}
            SELECT bs.*, i.official_name AS university_name, i.city, i.country,
                   i.country_code, i.university_research_level,
                   js.current_openings, js.jobs_last_seen,
                   CASE WHEN EXISTS (SELECT 1 FROM school_evidence se WHERE se.school_id=bs.id AND se.is_current=1)
                        THEN 'verified_school_evidence'
                        WHEN EXISTS (SELECT 1 FROM school_tier_overrides sto WHERE sto.school_id=bs.id)
                        THEN 'manual_school_override'
                        ELSE 'linked_school_entity' END AS evidence_status
            {from_sql} ORDER BY js.current_openings DESC, bs.official_name LIMIT ? OFFSET ?
        """, job_stats_args + args + [max(1, min(200, int(limit))), max(0, int(offset))]).fetchall()
        schools = []
        for row in rows:
            item = dict(row)
            # One extra lookup per listed school so the directory can show the
            # footprint without the reader having to open each school.
            item["astar_footprint"] = astar_footprint_for_school(conn, item["id"])
            schools.append(item)
        return {"ok": True, "schools": schools,
                "pagination": {"total": count, "limit": limit, "offset": offset}}
    finally:
        conn.close()


def school_detail(db_path, school_id):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(f"""
            SELECT bs.*, i.official_name AS university_name, i.normalized_name AS university_normalized_name,
                   i.country, i.country_code, i.state_province, i.city, i.institution_url,
                   i.university_research_level, i.university_research_level_system,
                   i.research_memberships_json, i.carnegie_class, i.u15_member,
                   (SELECT COUNT(*) FROM jobs j WHERE j.school_id=bs.id AND {default_market_where('j')}) AS current_openings
            FROM business_schools bs JOIN institutions i ON i.id=bs.institution_id
            WHERE bs.id=? AND bs.is_current=1 AND i.is_current=1
        """, (school_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "school not found"}
        classification = classify_business_school(conn, school_id)
        jobs = [dict(item) for item in conn.execute(f"""
            SELECT id, title_raw, discipline_primary, country, city, deadline_date,
                   deadline_mode, last_seen_at, status, official_url
            FROM jobs
            WHERE school_id=? AND {default_market_where()}
            ORDER BY first_seen_at DESC LIMIT 100
        """, (school_id,)).fetchall()]
        from services.faculty_jobs_lifecycle import lifecycle_fields
        for job in jobs:
            job.update(lifecycle_fields(job))
        result = dict(row)
        if classification.get("manual_override"):
            evidence_status = "manual_school_override"
            evidence_label = "Manual school classification override; independent verification not claimed"
        elif classification["evidence"]:
            evidence_status = "verified_school_evidence"
            evidence_label = "Verified school evidence"
        else:
            evidence_status = "linked_school_entity"
            evidence_label = "Linked local school entity; independent verification unavailable"
        result.update({
            "evidence": classification["evidence"], "classification": classification, "jobs": jobs,
            "evidence_status": evidence_status,
            "evidence_status_label": evidence_label,
            # Presented beside the tier, never inside it.
            "astar_footprint": astar_footprint_for_school(
                conn, school_id, classification["evidence"]),
        })
        return {"ok": True, "school": result}
    finally:
        conn.close()


def compare_schools(db_path, ids):
    ids = [int(item) for item in ids if str(item).isdigit()][:5]
    return {"ok": True, "schools": [detail for item in ids for detail in [school_detail(db_path, item).get("school")] if detail]}


def save_institution_alias(db_path, payload):
    """Store a local, auditable institution alias without changing raw jobs."""
    alias = str(payload.get("alias") or "").strip()
    canonical = str(payload.get("canonical_name") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    source_url = str(payload.get("source_url") or "").strip() or None
    if len(alias) < 3 or len(canonical) < 3 or len(reason) < 10:
        raise ValueError("alias, canonical_name, and a reason are required")
    if source_url and urlparse(source_url).scheme not in {"http", "https"}:
        raise ValueError("source_url must be http or https")
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        now = now_utc()
        conn.execute("""
            INSERT INTO institution_aliases
              (alias_normalized,canonical_name,reason,source_url,created_at,updated_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(alias_normalized) DO UPDATE SET canonical_name=excluded.canonical_name,
              reason=excluded.reason, source_url=excluded.source_url, updated_at=excluded.updated_at
        """, (normalize_name(alias), canonical, reason[:2000], source_url, now, now))
        conn.commit()
        return {"ok": True, "alias": alias, "canonical_name": canonical, "private": True}
    finally:
        conn.close()


def list_institution_aliases(db_path, limit=200):
    """Return local alias decisions for the private management UI.

    These rows are normalization metadata only.  They do not rewrite a raw
    source record and are intentionally not exposed through the public school
    directory.
    """
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        bounded = max(1, min(500, int(limit)))
        rows = conn.execute(
            "SELECT id, alias_normalized, canonical_name, reason, source_url, created_at, updated_at "
            "FROM institution_aliases ORDER BY updated_at DESC, id DESC LIMIT ?",
            (bounded,),
        ).fetchall()
        return {"ok": True, "aliases": [dict(row) for row in rows], "private": True}
    finally:
        conn.close()


def add_evidence(db_path, school_id, payload):
    evidence_type = str(payload.get("evidence_type") or "").strip()
    value = str(payload.get("value") or "").strip()
    source_url = str(payload.get("source_url") or "").strip()
    if evidence_type not in EVIDENCE_TYPES:
        raise ValueError("unsupported evidence_type")
    if not value or not source_url or urlparse(source_url).scheme not in {"http", "https"}:
        raise ValueError("value and a valid source_url are required")
    confidence = str(payload.get("confidence") or "medium").lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute("SELECT 1 FROM business_schools WHERE id=?", (school_id,)).fetchone():
            raise ValueError("school not found")
        now = now_utc()
        conn.execute("""
            INSERT INTO school_evidence
              (school_id,evidence_type,value,source_name,source_url,source_date,verified_at,confidence,notes)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (school_id, evidence_type, value, payload.get("source_name") or "Manual official-source entry",
              source_url, payload.get("source_date"), now, confidence, str(payload.get("notes") or "")[:1000]))
        result = refresh_school_classification(conn, school_id)
        conn.commit()
        return {"ok": True, "classification": result}
    finally:
        conn.close()


def save_override(db_path, school_id, payload):
    tier = str(payload.get("tier") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    source_url = str(payload.get("source_url") or "").strip()
    if tier not in SCHOOL_TIERS or tier == "Unclassified":
        raise ValueError("tier must be T1, T2, T3, or T4 for an override")
    if len(reason) < 10 or urlparse(source_url).scheme not in {"http", "https"}:
        raise ValueError("override requires a reason and source_url")
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute("SELECT 1 FROM business_schools WHERE id=?", (school_id,)).fetchone():
            raise ValueError("school not found")
        now = now_utc()
        conn.execute("""
            INSERT INTO school_tier_overrides (school_id,tier,reason,source_url,created_at,updated_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(school_id) DO UPDATE SET tier=excluded.tier, reason=excluded.reason,
              source_url=excluded.source_url, updated_at=excluded.updated_at
        """, (school_id, tier, reason[:2000], source_url, now, now))
        result = refresh_school_classification(conn, school_id)
        conn.commit()
        return {"ok": True, "classification": result, "manual_override": True}
    finally:
        conn.close()


__all__ = ["SCHOOL_TIERS", "UNIVERSITY_LEVELS", "EVIDENCE_TYPES", "list_schools", "school_detail", "compare_schools", "add_evidence", "save_override", "save_institution_alias", "list_institution_aliases", "classify_business_school", "refresh_school_classification"]
