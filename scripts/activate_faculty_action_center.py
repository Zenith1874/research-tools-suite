"""Prepare immutable requirements evidence, rehearse, and explicitly activate it.

Preparation only reads collected pages. --apply requires integrity checks and
a unique backup before migration. No network requests are made by this script.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services import faculty_jobs_requirements as req
from services import raw_archive
from services.faculty_jobs_actions import PREFERRED_QUERY, ACTION_VIEWS
from services.faculty_jobs_service import ensure_faculty_jobs_tables, build_faculty_job_summary, _record_derived_repair_provenance
from services.faculty_jobs_write_guard import preflight, postflight, open_read_only, guarded_write, discover_private_tables


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def prepare(collections, output, latest_per_job_url=False):
    records = []
    for collection in map(Path, collections):
        manifest = json.loads((collection / "manifest.json").read_text(encoding="utf-8"))
        jobs = {job["id"]: job for job in manifest["jobs"]}
        for line in (collection / "reads.jsonl").read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            item["parser_version"] = req.PARSER_VERSION
            if item.get("raw_path"):
                raw_path = collection / item["raw_path"]
                body = gzip.decompress(raw_path.read_bytes())
                if hashlib.sha256(body).hexdigest() != item["content_hash"]:
                    raise ValueError("Collected blob hash changed")
                parsed = req.parse_posting(body.decode("utf-8"), jobs[item["job_id"]], item.get("final_url") or item["source_url"], item["source_kind"])
                item.update({k: v for k, v in parsed.items() if k != "text"})
                item["raw_path"] = raw_path.resolve().relative_to(ROOT).as_posix()
            else:
                item["fields"] = req.empty_fields("blocked" if item["status"] == "blocked" else "not_read")
            records.append(item)
    if latest_per_job_url:
        newest = {}
        for item in records:
            key = (item["job_id"], item["source_kind"], item["source_url"])
            if key not in newest or item["captured_at"] > newest[key]["captured_at"]:
                newest[key] = item
        records = list(newest.values())
    result = {"prepared_at": now(), "parser_version": req.PARSER_VERSION,
              "parser_sha256": hashlib.sha256((ROOT / "services/faculty_jobs_requirements.py").read_bytes()).hexdigest(),
              "parser_dependencies": {"services/faculty_jobs_normalizer.py": hashlib.sha256((ROOT / "services/faculty_jobs_normalizer.py").read_bytes()).hexdigest()},
              "collections": [str(Path(x).resolve().relative_to(ROOT)) for x in collections], "records": records}
    save_new(output, result)
    print(json.dumps({"prepared_records": len(records), "unique_jobs": len({x["job_id"] for x in records}),
                      "status_counts": dict(Counter(x["status"] for x in records))}), flush=True)


def fingerprints(conn):
    tables = sorted(set(discover_private_tables(conn)) | {"source_job_records", "job_sources", "source_record_decisions", "institutions", "institution_career_links"})
    results = {}
    for name in tables + ["jobs"]:
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{name}")')]
        if name == "jobs":
            columns = [x for x in columns if x not in {"deadline_mode", "updated_at"}]
        selected = ",".join('"' + x + '"' for x in columns)
        digest, count = hashlib.sha256(), 0
        for row in conn.execute(f'SELECT {selected} FROM "{name}" ORDER BY rowid'):
            digest.update(json.dumps(tuple(row), ensure_ascii=False, default=str, separators=(",", ":")).encode())
            digest.update(b"\n")
            count += 1
        results[name] = {"rows": count, "sha256": digest.hexdigest()}
    return results


def key_for(item):
    return hashlib.sha256(json.dumps({k: item.get(k) for k in ("job_id", "source_url", "captured_at", "content_hash", "parser_version")}, sort_keys=True).encode()).hexdigest()


def apply(db, staging, report, rehearsal_from=None):
    db = Path(db)
    if Path(report).exists():
        raise ValueError("Refusing to overwrite an existing report")
    payload = json.loads(Path(staging).read_text(encoding="utf-8"))
    actual_hash = hashlib.sha256((ROOT / "services/faculty_jobs_requirements.py").read_bytes()).hexdigest()
    if payload["parser_sha256"] != actual_hash:
        raise ValueError("Parser changed since preparation; create a new staged artifact")
    for name, expected_hash in payload.get("parser_dependencies", {}).items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected_hash:
            raise ValueError("Parser dependency changed since preparation; create a new staged artifact")
    if rehearsal_from:
        if db.exists():
            raise ValueError("Rehearsal must use a new DB path")
        source = open_read_only(rehearsal_from)
        destination = sqlite3.connect(db)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
    inventory = preflight(db, "faculty_action_center")
    before_conn = open_read_only(db)
    try:
        before = fingerprints(before_conn)
        old_modes = {row["id"]: (row["deadline_mode"], row["updated_at"]) for row in before_conn.execute("SELECT id,deadline_mode,updated_at FROM jobs")}
    finally:
        before_conn.close()
    imported, repaired = 0, []
    with guarded_write():
        ensure_faculty_jobs_tables(db)
        conn = sqlite3.connect(db, timeout=60)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                for item in payload["records"]:
                    if conn.execute("SELECT 1 FROM job_requirement_reads WHERE observation_key=?", (key_for(item),)).fetchone():
                        continue
                    body = gzip.decompress((ROOT / item["raw_path"]).read_bytes()) if item.get("raw_path") else None
                    if body is not None and hashlib.sha256(body).hexdigest() != item["content_hash"]:
                        raise ValueError("Raw blob changed after preparation")
                    observed = raw_archive.record_observation(conn, kind="detail", source_url=item["source_url"], payload=body,
                        http_status=item.get("http_status"), parser_version=item["parser_version"],
                        note=f"Priority requirements job_id={item['job_id']}; {item['status']}; {item.get('reason','')}",
                        observed_at=item["captured_at"])
                    imported += req.import_read(conn, item, observed["observation_id"])
                # Only a successfully read, matched official posting can correct
                # the derived deadline mode. Historical dates/text stay intact.
                for row in conn.execute("SELECT j.id,j.deadline_mode,r.fields_json,r.source_url FROM jobs j JOIN job_requirement_current r ON r.job_id=j.id WHERE j.deadline_mode='fixed' AND r.status='ok' AND r.identity_verified=1 AND r.source_kind='official_posting'").fetchall():
                    fields = json.loads(row["fields_json"])
                    mode = fields["recruitment_mode"]
                    if mode["status"] != "supported" or mode["value"] != "open_until_filled" or fields["hard_deadline"]["status"] == "supported":
                        continue
                    reason = f"Verified official posting explicitly stays open until filled. {mode['quote']} Source: {row['source_url']}"
                    conn.execute("UPDATE jobs SET deadline_mode='open_until_filled',updated_at=? WHERE id=?", (now(), row["id"]))
                    _record_derived_repair_provenance(conn, row["id"], "deadline_mode", "open_until_filled", reason)
                    conn.execute("INSERT INTO faculty_job_repair_audit (observed_at,action,job_id,old_value,new_value,reason) VALUES (?,?,?,?,?,?)",
                        (now(), "verified_official_deadline_mode", row["id"], row["deadline_mode"], "open_until_filled", reason))
                    repaired.append(row["id"])
                after = fingerprints(conn)
                if before != after:
                    raise ValueError("Protected source, identity, job, or private contents changed; transaction rolled back")
                changed = [row["id"] for row in conn.execute("SELECT id,deadline_mode,updated_at FROM jobs") if old_modes[row["id"]] != (row["deadline_mode"], row["updated_at"])]
                if sorted(changed) != sorted(repaired):
                    raise ValueError("Deadline changes exceeded the verified allowlist")
        finally:
            conn.close()
    after_inventory = postflight(db, inventory)
    summary = build_faculty_job_summary(db, PREFERRED_QUERY)["summary"]
    result = {"completed_at": now(), "db": str(db), "staging": str(staging), "imported_reads": imported,
              "deadline_mode_repair_ids": repaired, "protected_content_unchanged": before == after,
              "before_fingerprints": before, "after_fingerprints": after, "postflight": after_inventory,
              "cohort_count": summary["matching_records"], "action_counts": summary["action_counts"]}
    save_new(report, result)
    print(json.dumps({k: result[k] for k in ("imported_reads", "deadline_mode_repair_ids", "protected_content_unchanged", "cohort_count", "action_counts")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", nargs="+")
    parser.add_argument("--latest-per-job-url", action="store_true",
                        help="during preparation, retain only the newest observation for an exact job/source URL")
    parser.add_argument("--output")
    parser.add_argument("--db", default=str(ROOT / "data/faculty_jobs.db"))
    parser.add_argument("--staging")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report")
    parser.add_argument("--rehearsal-from")
    args = parser.parse_args()
    if args.prepare:
        if not args.output:
            parser.error("--prepare requires a new --output path")
        prepare(args.prepare, args.output, args.latest_per_job_url)
    elif args.apply and args.staging and args.report:
        apply(args.db, args.staging, args.report, args.rehearsal_from)
    else:
        parser.error("Use --prepare with --output, or explicitly --apply with --staging and --report")
