"""Opt-in bridge from Carnegie portal observations to the existing job market.

Registry and scan databases remain the evidence layer. Only fresh, attributable
individual postings cross this bridge; a partial batch never reconciles absence.
"""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import unquote, urlsplit, urlunsplit

from .base import AdapterError, AdapterResponse, SourceAdapter, SourceJob


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DB = ROOT / "data/faculty_jobs/carnegie_2025_recruitment_registry.db"
SCAN_DB = ROOT / "data/faculty_jobs/carnegie_2025_vacancy_scan.db"
BRIDGE_RULE = "carnegie_bridge_v1_20260920"
POOL_RE = re.compile(
    r"\b(?:pool|pools|ongoing|continuous|general application|future openings|"
    r"expression of interest|expressions of interest|evergreen)\b", re.I)
COLLECTION_RE = re.compile(
    r"\b(?:faculty positions|faculty openings|faculty opportunities|job opportunities|"
    r"employment opportunities|current vacancies|open positions|all jobs|"
    r"application form|application for employment)\b", re.I)
POOL_BODY_RE = re.compile(
    r"\b(?:applicant pool|candidate pool|adjunct pool|continuous recruitment|"
    r"ongoing recruitment|future vacancies|future openings)\b", re.I)


def _read_only(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def _canonical_url(value):
    parts = urlsplit(str(value or ""))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def _name(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def posting_scope(record):
    """Conservative gate, not a claim to classify every recruitment page."""
    raw = json.loads(record.get("raw_json") or "{}")
    title_url = record.get("title_raw", "") + " " + unquote(
        urlsplit(record.get("official_url") or "").path).replace("-", "_").replace("_", " ")
    if POOL_RE.search(title_url) or POOL_BODY_RE.search(record.get("description_excerpt") or ""):
        return "pool"
    if COLLECTION_RE.search(title_url):
        return "collection"
    if record.get("extraction_method") == "jsonld_jobposting":
        return "individual"
    detail = raw.get("detail_raw_json") or {}
    if record.get("detail_status") != "ok" or not raw.get("detail_accepted"):
        return "unknown"
    if detail.get("detail_jsonld_count") == 1 and detail.get("identity_matches"):
        return "individual"
    if detail.get("detail_jsonld_count") == 0 and detail.get("explicit_role_heading"):
        return "individual"
    return "unknown"


def promote_record(record, target, *, now=None):
    """Return (SourceJob, reason); rejected observations stay in the scan DB."""
    from services.faculty_jobs_normalizer import classify_faculty_market_role

    scope = posting_scope(record)
    if scope != "individual":
        return None, "scope_" + scope
    if not target or record.get("target_match_status") not in {
        "single_registry_target", "organization_exact"
    }:
        return None, "unresolved_institution"
    if record.get("institution_raw") and _name(record["institution_raw"]) != _name(target["institution_name"]):
        return None, "conflicting_institution"
    if len(record.get("portal_target_unitids") or []) > 1 and not record.get("institution_raw"):
        return None, "shared_portal_unresolved"
    try:
        captured = datetime.fromisoformat(record["captured_at"].replace("Z", "+00:00"))
        age = ((now or datetime.now(timezone.utc)) - captured).total_seconds()
    except (KeyError, ValueError, TypeError):
        return None, "invalid_capture_time"
    if not 0 <= age <= 24 * 3600:
        return None, "stale_observation"
    url = _canonical_url(record.get("official_url"))
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None, "invalid_official_url"
    portal_host = urlsplit(record.get("source_url") or "").hostname
    if parts.hostname != portal_host and not record.get("institution_raw"):
        return None, "external_employer_unverified"
    if re.search(r"\.(?:pdf|docx?|xlsx?)$", parts.path, re.I):
        return None, "unread_document"
    raw = json.loads(record.get("raw_json") or "{}")
    # Link context may contain other jobs and must not become discipline evidence.
    description = record.get("description_excerpt") if (
        record.get("extraction_method") == "jsonld_jobposting"
        or record.get("detail_status") == "ok"
    ) else None
    role = classify_faculty_market_role(record.get("title_raw"), description, url)
    if not role.get("eligible") or raw.get("detail_accepted") is False:
        return None, "ineligible_detail_or_role"
    stable_id = hashlib.sha256(f"{target['unitid']}|{url}".encode()).hexdigest()[:32]
    return SourceJob(
        source="carnegie_official", source_job_id=stable_id,
        source_url=record["source_url"], official_url=url,
        title_raw=record["title_raw"], institution_raw=target["institution_name"],
        department_raw=record.get("department_raw"),
        location_raw=record.get("location_raw") or ", ".join(
            str(target.get(key)) for key in ("city", "state") if target.get(key)),
        description_excerpt=description, posted_date_raw=record.get("posted_date_raw"),
        deadline_raw=record.get("deadline_raw"), salary_raw=record.get("salary_raw"),
        captured_at=record["captured_at"],
        extra={"bridge_rule": BRIDGE_RULE, "posting_scope": scope,
               "unitid": target["unitid"], "target_segment": target.get("target_segment"),
               "target_match_status": record["target_match_status"],
               "scan_record_id": record["id"], "scan_run_id": record.get("run_id"),
               "registry_website": target.get("official_website_url"),
               "location_origin": "posting" if record.get("location_raw") else "registry",
               "scanner_evidence": raw},
    ), "accepted"


def latest_observations(scan_db):
    if not Path(scan_db).is_file():
        return []
    conn = _read_only(scan_db)
    try:
        return [dict(row) for row in conn.execute("""
            SELECT o.*, p.target_unitids_json FROM vacancy_observations o
            JOIN portal_inputs p ON p.id=o.portal_input_id
            WHERE o.id IN (SELECT MAX(id) FROM vacancy_observations GROUP BY portal_url)
        """)]
    finally:
        conn.close()


def source_coverage(registry_db=None, scan_db=None):
    """Read-only coverage at school, portal and candidate-URL grains."""
    from services.carnegie_vacancy_scan import select_portals

    registry_db, scan_db = Path(registry_db or REGISTRY_DB), Path(scan_db or SCAN_DB)
    if not registry_db.is_file():
        return {"available": False, "reason": "Carnegie registry is not installed.",
                "coverage_complete": False}
    selection = select_portals(registry_db, max_portals=1000)
    conn = _read_only(registry_db)
    try:
        targets = dict(conn.execute("""SELECT COUNT(*) AS schools,
            SUM(is_r2) AS r2, SUM(is_teaching_oriented) AS teaching_proxy,
            SUM(is_r2*is_teaching_oriented) AS overlap,
            COUNT(DISTINCT website_group_key) AS website_groups
            FROM institution_recruitment_targets""").fetchone())
        discovery = {r[0]: r[1] for r in conn.execute(
            "SELECT latest_status,COUNT(*) FROM institution_recruitment_websites GROUP BY latest_status")}
    finally:
        conn.close()
    active_urls = {row["canonical_url"] for row in selection["all_portals"]}
    eligible_urls = {row["canonical_url"] for row in selection["selected"]}
    observations = [row for row in latest_observations(scan_db) if row["portal_url"] in active_urls]
    scanned = {row["portal_url"] for row in observations}
    observed_units = {unit for row in observations for unit in json.loads(row["target_unitids_json"])}
    fresh_urls = set()
    for row in observations:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(row["checked_at"].replace("Z", "+00:00"))
            if 0 <= age.total_seconds() <= 7 * 24 * 3600:
                fresh_urls.add(row["portal_url"])
        except (TypeError, ValueError):
            pass
    raw_urls = 0
    if observations:
        conn = _read_only(scan_db)
        try:
            ids = [row["id"] for row in observations]
            raw_urls = conn.execute(
                "SELECT COUNT(DISTINCT official_url) FROM vacancy_records WHERE observation_id IN ("
                + ",".join("?" for _ in ids) + ")", ids).fetchone()[0]
        finally:
            conn.close()
    return {
        "available": True, **targets, "discovery_statuses": discovery,
        "portal_records": len(selection["all_portals"]), "portal_urls": len(active_urls),
        "eligible_portal_records": selection["eligible_count"],
        "eligible_portal_urls": len(eligible_urls),
        "scanned_eligible_portal_urls": len(scanned & eligible_urls),
        "remaining_eligible_portal_urls": len(eligible_urls - scanned),
        "schools_with_portal_observation": len(observed_units),
        "portal_urls_checked_last_7d": len(fresh_urls),
        "stale_or_undated_portal_urls": len(scanned - fresh_urls),
        "latest_observation_at": max((r["checked_at"] for r in observations), default=None),
        "latest_observation_statuses": dict(Counter(r["scan_status"] for r in observations)),
        "latest_candidate_urls": raw_urls, "coverage_complete": False,
        "note": "Teaching-oriented is a registry proxy, not an official Carnegie designation. "
                "Portal visits and candidate URLs are not complete or current vacancy counts. "
                "Dynamic ATS, pools, blocked pages and unresolved schools remain outside automatic promotion.",
    }


class CarnegieOfficialAdapter(SourceAdapter):
    name = adapter_name = "carnegie_official"
    region = "North America"
    base_url = "https://carnegieclassifications.acenet.edu/"
    priority = 31
    method = "carnegie_registry_official_sites"
    enabled = False
    support_status = "opt_in"
    support_reason = "R2 and teaching-proxy official portals; bounded opt-in scan, individual postings only."
    paginates = False

    def __init__(self, *args, registry_db=None, scan_db=None, offset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.registry_db = Path(registry_db or REGISTRY_DB)
        self.scan_db = Path(scan_db or SCAN_DB)
        self.offset = offset
        self.detail_budget = 12

    def fetch(self):
        from services.carnegie_vacancy_scan import scan_vacancies, select_portals

        eligible = select_portals(self.registry_db, max_portals=1000)["selected"]
        if not eligible:
            raise AdapterError("No eligible Carnegie recruitment portals in the registry.")
        latest = {row["portal_url"]: row["checked_at"] for row in latest_observations(self.scan_db)}
        # Unvisited first, then the oldest observation. No persistent cursor can
        # silently skip a portal when the registry's deterministic order changes.
        offset = self.offset if self.offset is not None else min(
            range(len(eligible)), key=lambda i: (latest.get(eligible[i]["canonical_url"], ""), i))
        if not 0 <= offset < len(eligible):
            raise AdapterError("Carnegie offset is outside the eligible portal list.")
        batch_size = min(25, self.max_pages, len(eligible) - offset)
        result = scan_vacancies(
            self.registry_db, self.scan_db, max_portals=batch_size, offset=offset,
            timeout=self.timeout, max_detail_pages=min(2, self.detail_budget // batch_size),
            prioritize_business=True)
        conn = _read_only(self.scan_db)
        try:
            records = [dict(row) for row in conn.execute("""
                SELECT r.*, o.run_id, o.portal_url FROM vacancy_records r
                JOIN vacancy_observations o ON o.id=r.observation_id WHERE o.run_id=?
            """, (result["run_id"],))]
            pages = conn.execute("SELECT COALESCE(SUM(pages_fetched),0) FROM vacancy_observations WHERE run_id=?",
                                 (result["run_id"],)).fetchone()[0]
            readable = conn.execute("SELECT COUNT(*) FROM vacancy_observations WHERE run_id=? AND page_status='ok'",
                                    (result["run_id"],)).fetchone()[0]
        finally:
            conn.close()
        if not readable:
            raise AdapterError(f"Carnegie scan {result['run_id']}: no readable portals; {result['statuses']}")
        conn = _read_only(self.registry_db)
        try:
            targets = {r["unitid"]: dict(r) for r in conn.execute("SELECT * FROM institution_recruitment_targets")}
            portal_targets = {}
            for row in conn.execute("""
                SELECT p.canonical_url, t.unitid FROM institution_recruitment_portals p
                JOIN institution_recruitment_targets t ON t.website_group_key=p.website_group_key
                WHERE p.active=1
            """):
                portal_targets.setdefault(row["canonical_url"], set()).add(row["unitid"])
        finally:
            conn.close()
        jobs, decisions = {}, Counter()
        for record in records:
            record["portal_target_unitids"] = sorted(portal_targets.get(record["portal_url"], set()))
            job, reason = promote_record(record, targets.get(record.get("target_unitid")))
            decisions[reason] += 1
            if job:
                jobs[job.source_job_id] = job
        return AdapterResponse(
            jobs=list(jobs.values()), pages_fetched=pages,
            listing_pages=result["processed"], coverage_complete=False, reported_total=None,
            notes=[f"Carnegie scan_run={result['run_id']} offset={offset}; "
                   f"portals={result['processed']}/{len(eligible)}; promotion={dict(decisions)}; "
                   f"outcomes={result['statuses']}; no absence reconciliation."],
        )


class RecordedCarnegieAdapter(CarnegieOfficialAdapter):
    """Promote a completed scan's archived observations without rescanning."""

    def fetch(self):
        observations = latest_observations(self.scan_db)
        if not observations:
            raise AdapterError("No archived Carnegie observations are available.")
        conn = _read_only(self.registry_db)
        try:
            targets = {r["unitid"]: dict(r) for r in conn.execute("SELECT * FROM institution_recruitment_targets")}
        finally:
            conn.close()
        conn = _read_only(self.scan_db)
        jobs, decisions, pages = {}, Counter(), 0
        try:
            for observation in observations:
                pages += int(observation.get("pages_fetched") or 0)
                unitids = json.loads(observation["target_unitids_json"])
                for row in conn.execute("SELECT r.*,o.run_id,o.portal_url FROM vacancy_records r JOIN vacancy_observations o ON o.id=r.observation_id WHERE r.observation_id=?", (observation["id"],)):
                    record = dict(row)
                    record["portal_target_unitids"] = unitids
                    job, reason = promote_record(record, targets.get(record.get("target_unitid")))
                    decisions[reason] += 1
                    if job:
                        jobs[job.source_job_id] = job
        finally:
            conn.close()
        return AdapterResponse(jobs=list(jobs.values()), pages_fetched=pages,
            listing_pages=len(observations), coverage_complete=False,
            notes=[f"Archived scan promotion; portal observations={len(observations)}; decisions={dict(decisions)}; no absence reconciliation."])
