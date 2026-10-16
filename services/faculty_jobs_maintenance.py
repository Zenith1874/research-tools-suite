"""Bounded recurring employer evidence refresh and auditable discipline repairs."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from services.faculty_jobs_actions import PREFERRED_QUERY
from services.faculty_jobs_write_guard import discover_private_tables, open_read_only, write_guard_active

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "data" / "faculty_jobs" / "requirements_runs"
OVERRIDE_PATH = ROOT / "data" / "faculty_jobs" / "official_posting_urls.json"


def parse_time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
    except (ValueError, TypeError):
        return None


def career_jobs(db):
    """Read both complete cohorts through the same public filter implementation."""
    from services.faculty_jobs_service import build_faculty_jobs_payload
    jobs = {}
    counts = {}
    for view in ("r2_teaching", "r1"):
        offset = 0
        while True:
            payload = build_faculty_jobs_payload(db, {**PREFERRED_QUERY, "career_view": view,
                "limit": 200, "offset": offset})
            counts[view] = payload["pagination"]["total"]
            for job in payload["jobs"]:
                jobs[job["id"]] = job
            if not payload["pagination"]["has_more"]:
                break
            offset += len(payload["jobs"])
    return list(jobs.values()), counts


def due_queue(jobs, *, now=None, refresh_days=7, retry_days=7, force=False):
    """Urgent dates and new unread jobs first; failed hosts receive backoff."""
    now = now or datetime.now(timezone.utc)
    queued = []
    for job in jobs:
        req = job.get("requirements") or {}
        attempt = req.get("latest_attempt") or {}
        latest = parse_time(attempt.get("captured_at") or req.get("captured_at"))
        success = parse_time(job.get("last_verified_at"))
        mode = attempt.get("status") or req.get("status") or "not_read"
        interval = retry_days if mode != "ok" else refresh_days
        timing = job.get("timing") or {}
        dates = [str(timing[k]) for k in ("review_date", "hard_deadline") if timing.get(k)]
        urgent = any(now.date().isoformat() <= d <= (now + timedelta(days=14)).date().isoformat() for d in dates)
        if not force and latest and now - latest < timedelta(days=interval):
            continue
        if force or not success or now - success >= timedelta(days=refresh_days) or urgent:
            # All jobs rotate, including adjuncts. Worth-review is an explicit
            # priority within this queue, never a restriction on coverage.
            rank = (not urgent, "worth_review" not in job.get("actions", []),
                    success is not None, latest.isoformat() if latest else "", job["id"])
            queued.append((rank, job))
    return [job for _, job in sorted(queued, key=lambda item: item[0])]


def load_overrides(path=OVERRIDE_PATH):
    if not Path(path).exists():
        return {}
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(k): v if isinstance(v, str) else v["url"] for k, v in value.items()}


def protected_hashes(conn, allowed_job_columns=()):
    tables = set(discover_private_tables(conn)) | {
        "source_job_records", "job_sources", "source_record_decisions", "institutions", "institution_career_links", "jobs"}
    result = {}
    for table in sorted(tables):
        columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
        if table == "jobs":
            columns = [c for c in columns if c not in allowed_job_columns]
        digest = hashlib.sha256()
        count = 0
        for row in conn.execute('SELECT ' + ','.join('"' + c + '"' for c in columns) + f' FROM "{table}" ORDER BY rowid'):
            digest.update(json.dumps(tuple(row), ensure_ascii=False, default=str, separators=(",", ":")).encode())
            digest.update(b"\n")
            count += 1
        result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def refresh_requirements(db, *, max_jobs=24, max_pages=48, timeout=15, force=False,
                         output=None, override_path=OVERRIDE_PATH, progress=None):
    """Collect public text, then append evidence under the caller's write guard."""
    from scripts.enrich_faculty_priority import collect
    from services import faculty_jobs_requirements as req, raw_archive
    from services.faculty_jobs_service import _require_guarded_production_write
    _require_guarded_production_write(db)
    jobs, cohort_counts = career_jobs(db)
    queue = due_queue(jobs, force=force)
    selected = queue[:max(0, min(1000, int(max_jobs)))]
    if not selected:
        return {"cohorts": cohort_counts, "due": len(queue), "attempted": 0, "imported": 0, "statuses": {}}
    output = Path(output) if output else RUN_ROOT / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    gathered = collect(output, max_pages=max_pages, timeout=timeout,
        overrides=load_overrides(override_path), jobs=selected,
        query={**PREFERRED_QUERY, "career_view": "r2_teaching,r1"}, progress=progress)
    conn = sqlite3.connect(db, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    imported = 0
    try:
        before = protected_hashes(conn)
        with conn:
            for item in gathered["reads"]:
                body = gzip.decompress((output / item["raw_path"]).read_bytes()) if item.get("raw_path") else None
                if body is not None and hashlib.sha256(body).hexdigest() != item["content_hash"]:
                    raise ValueError("Captured evidence hash changed before import")
                observation = raw_archive.record_observation(conn, kind="detail", source_url=item["source_url"],
                    payload=body, http_status=item.get("http_status"), parser_version=item["parser_version"],
                    observed_at=item["captured_at"], note=f"Recurring requirements refresh job_id={item['job_id']}; {item['status']}")
                imported += req.import_read(conn, item, observation["observation_id"])
            if before != protected_hashes(conn):
                raise ValueError("Requirements refresh changed protected contents; rolled back")
    finally:
        conn.close()
    result = {"completed_at": datetime.now(timezone.utc).isoformat(), "cohorts": cohort_counts,
              "due": len(queue), "attempted": len(selected), "imported": imported,
              "statuses": gathered["summary"]["status_counts"], "collection": str(output),
              "protected_contents_unchanged": True}
    with (output / "refresh-result.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    return result


def discipline_repair_plan(db):
    from services.faculty_jobs_normalizer import classify_disciplines
    jobs, counts = career_jobs(db)
    changes = []
    for job in jobs:
        derived = classify_disciplines(job.get("department"), job["title_raw"], job.get("description_excerpt"))
        old, new = {}, {}
        if derived["primary"] != job.get("discipline_primary") or derived["secondary"] != job.get("discipline_secondary", []):
            old.update(discipline_primary=job["discipline_primary"],
                discipline_secondary_json=job.get("discipline_secondary_json", "[]"), classification_reason=job.get("classification_reason"))
            new.update(discipline_primary=derived["primary"],
                discipline_secondary_json=json.dumps(derived["secondary"], ensure_ascii=False), classification_reason=derived["reason"])
        evidence = job.get("requirements") or {}
        contract = evidence.get("fields", {}).get("appointment_contract") or {}
        if evidence.get("source_kind") == "official_posting" and evidence.get("status") == "ok" and evidence.get("identity_verified") and contract.get("status") == "supported" and job.get("track_type") == "unknown":
            old["track_type"] = job["track_type"]
            new["track_type"] = contract["value"]
        if new:
            changes.append({"job_id": job["id"], "title": job["title_raw"], "old": old, "new": new,
                "contract_quote": contract.get("quote"), "contract_source": evidence.get("source_url")})
    return {"cohorts": counts, "changes": changes, "rule": "vacancy_subject_v1_20261002"}


def apply_discipline_repairs(db, plan):
    from services.faculty_jobs_service import _require_guarded_production_write, _record_derived_repair_provenance, now_utc
    _require_guarded_production_write(db)
    allowed = {"discipline_primary", "discipline_secondary_json", "classification_reason", "track_type", "updated_at"}
    conn = sqlite3.connect(db, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        before = protected_hashes(conn, allowed)
        with conn:
            for change in plan["changes"]:
                current = conn.execute("SELECT * FROM jobs WHERE id=?", (change["job_id"],)).fetchone()
                if {k: current[k] for k in change["old"]} != change["old"]:
                    raise ValueError(f"Job {change['job_id']} changed since repair preview")
                new = change["new"]
                if not set(new) <= allowed - {"updated_at"}:
                    raise ValueError("Repair plan contains a non-allowlisted field")
                conn.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in new) + ",updated_at=? WHERE id=?",
                    (*new.values(), now_utc(), change["job_id"]))
                for field, value in new.items():
                    _record_derived_repair_provenance(conn, change["job_id"], field, value,
                        f"{plan['rule']}; original title: {change['title']}; {new.get('classification_reason') or change.get('contract_quote')}; {change.get('contract_source') or ''}")
                    if field == "track_type" and change.get("contract_source"):
                        conn.execute("UPDATE job_field_provenance SET source_url=? WHERE id=(SELECT MAX(id) FROM job_field_provenance WHERE job_id=? AND field_name=?)",
                            (change["contract_source"], change["job_id"], field))
                conn.execute("INSERT INTO faculty_job_repair_audit(observed_at,action,job_id,old_value,new_value,reason) VALUES(?,?,?,?,?,?)",
                    (now_utc(), plan["rule"], change["job_id"], json.dumps(change["old"]),
                     json.dumps(new), f"Vacancy title evidence: {change['title']}"))
            if before != protected_hashes(conn, allowed):
                raise ValueError("Discipline repairs changed non-allowlisted contents; rolled back")
        return {"changed_jobs": len(plan["changes"]), "protected_contents_unchanged": True}
    finally:
        conn.close()


def scheduled_career_update(db, *, source_names=None, timeout=15, max_pages=3,
                            requirement_jobs=24, portal_batch=25):
    """Run source discovery and current posting evidence in the existing job slot."""
    from services.faculty_jobs_service import update_faculty_jobs
    from services.faculty_jobs_sources.carnegie import CarnegieOfficialAdapter
    listings = update_faculty_jobs(db, source_names=source_names, timeout=timeout, max_pages=max_pages)
    result = {**listings, "listings": listings}
    # An explicitly source-limited UI update is kept source-limited. Scheduled
    # runs rotate across Carnegie even though its legacy opt-in flag is false.
    if source_names is None and portal_batch:
        try:
            adapter = CarnegieOfficialAdapter()
            result["official_portals"] = update_faculty_jobs(db, source_names=[adapter.name],
                adapters=[adapter], timeout=timeout, max_pages=min(25, portal_batch))
        except Exception as exc:
            result["official_portals"] = {"ok": False, "error": str(exc)[:500]}
    result["discipline_repairs"] = apply_discipline_repairs(db, discipline_repair_plan(db))
    result["requirements"] = refresh_requirements(db, max_jobs=requirement_jobs,
        max_pages=requirement_jobs * 3, timeout=min(15, timeout))
    return result
