#!/usr/bin/env python3
"""Dry-run or repair the two audited historical IHE Macau school entities.

The command is intentionally fail-closed.  It derives the expected school from
the retained IHE excerpt, verifies the complete active-IHE mismatch set, and
allows only the two source identities audited in
IHE_HISTORICAL_ENTITY_REMEDIATION_PLAN.md.  ``--apply`` uses the repository's
production write guard and one immediate transaction; the default is read-only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.faculty_jobs_normalizer import normalize_name  # noqa: E402
from services.faculty_jobs_sources.base import now_utc  # noqa: E402
from services.faculty_jobs_sources.insidehighered import InsideHigherEdAdapter  # noqa: E402
from services.faculty_jobs_write_guard import (  # noqa: E402
    guarded_write,
    open_read_only,
    postflight,
    preflight,
)


PRODUCTION_DB = ROOT / "data" / "faculty_jobs.db"
TARGET_INSTITUTION_ID = 862
TARGET_SCHOOL_ID = 749
TARGET_SCHOOL_NAME = "Faculty of Business Administration"
REPAIR_TAG = "ihe_historical_entity_remediation"


@dataclass(frozen=True)
class TargetSpec:
    source_job_id: str
    job_id: int
    old_school_id: int
    old_school_name: str


PRODUCTION_TARGETS = (
    TargetSpec(
        "3540011", 380, 1486,
        "Economics DFBE Faculty of Business Administration",
    ),
    TargetSpec(
        "3540012", 379, 1485,
        "Economics Faculty of Business Administration",
    ),
)


def _row_dict(row):
    return dict(row) if row is not None else None


def _entity_usage(conn, school_id):
    row = conn.execute(
        """
        SELECT bs.id,bs.official_name,bs.institution_id,bs.aliases_json,
               bs.is_current,bs.merged_into_id,
               (SELECT COUNT(*) FROM jobs j WHERE j.school_id=bs.id) AS job_count,
               (SELECT COUNT(*) FROM school_evidence se
                WHERE se.school_id=bs.id) AS evidence_count,
               (SELECT COUNT(*) FROM school_evidence se
                WHERE se.school_id=bs.id AND se.is_current=1) AS current_evidence_count,
               (SELECT COUNT(*) FROM school_tier_overrides sto
                WHERE sto.school_id=bs.id) AS override_count,
               (SELECT COUNT(*) FROM aacsb_directory_schools ads
                WHERE ads.linked_business_school_id=bs.id) AS directory_count,
               (SELECT COUNT(*) FROM aacsb_directory_schools ads
                WHERE ads.linked_business_school_id=bs.id AND ads.active=1)
                 AS active_directory_count,
               (SELECT COUNT(*) FROM entity_resolution_queue erq
                WHERE erq.entity_type='school' AND erq.entity_id=bs.id)
                 AS queue_count
        FROM business_schools bs
        WHERE bs.id=?
        """,
        (school_id,),
    ).fetchone()
    return _row_dict(row)


def _active_ihe_school_mismatches(conn, source_id):
    rows = conn.execute(
        """
        SELECT j.id AS job_id,j.institution_id,j.school_id,js.source_job_id,
               sjr.short_excerpt,j.description_excerpt
        FROM jobs j
        JOIN job_sources js
          ON js.job_id=j.id AND js.source_id=? AND js.active=1
        JOIN source_job_records sjr
          ON sjr.source_id=js.source_id AND sjr.source_job_id=js.source_job_id
        ORDER BY j.id,js.source_job_id
        """,
        (source_id,),
    ).fetchall()
    mismatches = []
    for row in rows:
        excerpt = row["short_excerpt"] or row["description_excerpt"] or ""
        school_name = InsideHigherEdAdapter._detail_school(excerpt)
        if not school_name or row["institution_id"] is None:
            continue
        matches = conn.execute(
            """
            SELECT id,official_name
            FROM business_schools
            WHERE institution_id=? AND normalized_name=? AND is_current=1
            ORDER BY id
            """,
            (row["institution_id"], normalize_name(school_name)),
        ).fetchall()
        if len(matches) == 1 and row["school_id"] != matches[0]["id"]:
            mismatches.append({
                "source_job_id": row["source_job_id"],
                "job_id": row["job_id"],
                "current_school_id": row["school_id"],
                "expected_school_id": matches[0]["id"],
                "expected_school_name": matches[0]["official_name"],
            })
    return mismatches


def inspect_connection(
    conn,
    targets=PRODUCTION_TARGETS,
    *,
    target_institution_id=TARGET_INSTITUTION_ID,
    target_school_id=TARGET_SCHOOL_ID,
    target_school_name=TARGET_SCHOOL_NAME,
):
    """Return a fail-closed inspection at the active-IHE source-link grain."""
    errors = []
    source = conn.execute(
        "SELECT id,name,enabled FROM sources WHERE name='inside_higher_ed'"
    ).fetchone()
    if not source:
        return {
            "valid": False,
            "state": "invalid",
            "errors": ["inside_higher_ed source row is missing"],
            "targets": [],
        }
    source_id = int(source["id"])
    target_entity = _entity_usage(conn, target_school_id)
    if not target_entity:
        errors.append(f"target school {target_school_id} is missing")
    else:
        if target_entity["official_name"] != target_school_name:
            errors.append("target school name changed")
        if int(target_entity["institution_id"]) != int(target_institution_id):
            errors.append("target school institution changed")
        if int(target_entity["is_current"] or 0) != 1:
            errors.append("target school is not current")
        if int(target_entity["current_evidence_count"] or 0) < 1:
            errors.append("target school has no current school evidence")
        if int(target_entity["active_directory_count"] or 0) < 1:
            errors.append("target school has no active AACSB directory link")

    target_rows = []
    job_positions = []
    old_positions = []
    for spec in targets:
        rows = conn.execute(
            """
            SELECT j.id AS job_id,j.title_raw,j.institution_id,j.school_id,
                   j.school_evidence_context,j.business_scope,j.status,
                   j.deadline_date,j.salary_raw,j.updated_at,
                   js.source_job_id,js.source_url,
                   sjr.short_excerpt,sjr.structured_extraction
            FROM job_sources js
            JOIN jobs j ON j.id=js.job_id
            JOIN source_job_records sjr
              ON sjr.source_id=js.source_id AND sjr.source_job_id=js.source_job_id
            WHERE js.source_id=? AND js.source_job_id=? AND js.active=1
            """,
            (source_id, spec.source_job_id),
        ).fetchall()
        if len(rows) != 1:
            errors.append(
                f"source {spec.source_job_id} has {len(rows)} active linked rows; expected 1"
            )
            continue
        row = rows[0]
        excerpt = row["short_excerpt"] or ""
        parsed_school = InsideHigherEdAdapter._detail_school(excerpt)
        current_school = conn.execute(
            "SELECT official_name,is_current,merged_into_id FROM business_schools WHERE id=?",
            (row["school_id"],),
        ).fetchone() if row["school_id"] is not None else None
        old_entity = _entity_usage(conn, spec.old_school_id)
        item = {
            "spec": asdict(spec),
            "job": _row_dict(row),
            "current_school": _row_dict(current_school),
            "parsed_school": parsed_school,
            "old_entity": old_entity,
        }
        target_rows.append(item)
        if int(row["job_id"]) != int(spec.job_id):
            errors.append(
                f"source {spec.source_job_id} links to job {row['job_id']}; expected {spec.job_id}"
            )
        if int(row["institution_id"] or -1) != int(target_institution_id):
            errors.append(f"source {spec.source_job_id} institution changed")
        if parsed_school != target_school_name:
            errors.append(
                f"source {spec.source_job_id} parsed school is {parsed_school!r}"
            )
        if row["school_id"] not in {spec.old_school_id, target_school_id}:
            errors.append(
                f"source {spec.source_job_id} has unexpected school {row['school_id']}"
            )
        if not old_entity:
            errors.append(f"old school {spec.old_school_id} is missing")
            continue
        if old_entity["official_name"] != spec.old_school_name:
            errors.append(f"old school {spec.old_school_id} name changed")
        if int(old_entity["institution_id"]) != int(target_institution_id):
            errors.append(f"old school {spec.old_school_id} institution changed")
        for field in ("evidence_count", "override_count", "directory_count", "queue_count"):
            if int(old_entity[field] or 0) != 0:
                errors.append(
                    f"old school {spec.old_school_id} has unexpected {field}={old_entity[field]}"
                )
        job_positions.append(int(row["school_id"]))
        old_positions.append((
            int(old_entity["is_current"] or 0),
            old_entity["merged_into_id"],
            int(old_entity["job_count"] or 0),
        ))

    state = "invalid"
    old_ids = [spec.old_school_id for spec in targets]
    if len(target_rows) == len(targets):
        if (
            job_positions == old_ids
            and all(position == (1, None, 1) for position in old_positions)
        ):
            state = "s0_needs_relink_and_retire"
        elif (
            all(value == target_school_id for value in job_positions)
            and all(position == (1, None, 0) for position in old_positions)
        ):
            state = "s1_needs_retire_only"
        elif (
            all(value == target_school_id for value in job_positions)
            and all(
                position == (0, target_school_id, 0)
                for position in old_positions
            )
        ):
            state = "already_repaired"
        else:
            errors.append(
                "target jobs/entities are in a mixed state outside S0, S1, or already_repaired"
            )

    mismatches = _active_ihe_school_mismatches(conn, source_id)
    mismatch_ids = {item["source_job_id"] for item in mismatches}
    expected_ids = {spec.source_job_id for spec in targets}
    if state == "s0_needs_relink_and_retire":
        if mismatch_ids != expected_ids:
            errors.append(
                f"active IHE mismatch set is {sorted(mismatch_ids)}; expected {sorted(expected_ids)}"
            )
    elif state in {"s1_needs_retire_only", "already_repaired"}:
        if mismatch_ids:
            errors.append(
                f"unexpected active IHE mismatches remain: {sorted(mismatch_ids)}"
            )

    if errors:
        state = "invalid"
    return {
        "valid": not errors,
        "state": state,
        "errors": errors,
        "source": _row_dict(source),
        "target_entity": target_entity,
        "targets": target_rows,
        "active_ihe_mismatch_count": len(mismatches),
        "active_ihe_mismatches": mismatches,
        "proposed_job_relinks": len(targets) if state == "s0_needs_relink_and_retire" else 0,
        "proposed_entity_retires": len(targets) if state in {
            "s0_needs_relink_and_retire", "s1_needs_retire_only"
        } else 0,
    }


def apply_connection(
    conn,
    inspection,
    targets=PRODUCTION_TARGETS,
    *,
    target_school_id=TARGET_SCHOOL_ID,
    target_school_name=TARGET_SCHOOL_NAME,
):
    """Apply a previously revalidated S0/S1 inspection in the current transaction."""
    if not inspection.get("valid"):
        raise RuntimeError(f"invalid repair inspection: {inspection.get('errors')}")
    state = inspection.get("state")
    if state == "already_repaired":
        return {"state_before": state, "job_relinks": 0, "entities_retired": 0}
    if state not in {"s0_needs_relink_and_retire", "s1_needs_retire_only"}:
        raise RuntimeError(f"refusing repair from state {state}")

    observed = now_utc()
    source_id = int(inspection["source"]["id"])
    job_relinks = 0
    entities_retired = 0
    by_source = {item["spec"]["source_job_id"]: item for item in inspection["targets"]}

    for spec in targets:
        item = by_source[spec.source_job_id]
        job = item["job"]
        if int(job["school_id"]) == int(spec.old_school_id):
            changed = conn.execute(
                """
                UPDATE jobs SET school_id=?,updated_at=?
                WHERE id=? AND school_id=? AND institution_id=?
                """,
                (target_school_id, observed, spec.job_id, spec.old_school_id,
                 job["institution_id"]),
            ).rowcount
            if changed != 1:
                raise RuntimeError(f"job {spec.job_id} relink affected {changed} rows")
            conn.execute(
                """
                UPDATE job_field_provenance SET is_current=0
                WHERE job_id=? AND field_name='school_id' AND is_current=1
                """,
                (spec.job_id,),
            )
            conn.execute(
                """
                INSERT INTO job_field_provenance
                  (job_id,field_name,source_id,source_job_id,source_url,value_text,
                   evidence_text,captured_at,is_current)
                VALUES (?,?,?,?,?,?,?,?,1)
                """,
                (
                    spec.job_id, "school_id", source_id, spec.source_job_id,
                    job["source_url"], str(target_school_id),
                    "repair: current bounded IHE home-unit parser resolved "
                    f"{target_school_name}; retained source excerpt preserved",
                    observed,
                ),
            )
            conn.execute(
                """
                INSERT INTO faculty_job_repair_audit
                  (observed_at,action,job_id,source_id,source_job_id,
                   old_value,new_value,reason)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    observed, "ihe_historical_school_entity_relink", spec.job_id,
                    source_id, spec.source_job_id,
                    json.dumps({"school_id": spec.old_school_id,
                                "school_name": spec.old_school_name}, ensure_ascii=False),
                    json.dumps({"school_id": target_school_id,
                                "school_name": target_school_name}, ensure_ascii=False),
                    "Relinked one audited IHE job to the unique current same-institution "
                    "school named by the retained bounded recruiting-unit excerpt; "
                    "source records, scope, status, and private state were unchanged.",
                ),
            )
            source_count = conn.execute(
                "SELECT COUNT(DISTINCT source_id) FROM job_sources "
                "WHERE job_id=? AND active=1",
                (spec.job_id,),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO job_status_history
                  (job_id,observed_at,status,deadline,salary_raw,title_raw,
                   source_count,change_reason)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    spec.job_id, observed, job["status"], job["deadline_date"],
                    job["salary_raw"], job["title_raw"], source_count,
                    "ihe_historical_school_entity_relink",
                ),
            )
            job_relinks += 1

        retired = conn.execute(
            """
            UPDATE business_schools
            SET is_current=0,merged_into_id=?,updated_at=?
            WHERE id=? AND is_current=1 AND merged_into_id IS NULL
              AND institution_id=?
              AND NOT EXISTS (SELECT 1 FROM jobs WHERE school_id=business_schools.id)
              AND NOT EXISTS (SELECT 1 FROM school_evidence WHERE school_id=business_schools.id)
              AND NOT EXISTS (SELECT 1 FROM school_tier_overrides WHERE school_id=business_schools.id)
              AND NOT EXISTS (SELECT 1 FROM aacsb_directory_schools
                              WHERE linked_business_school_id=business_schools.id)
            """,
            (target_school_id, observed, spec.old_school_id, job["institution_id"]),
        ).rowcount
        if retired != 1:
            raise RuntimeError(
                f"old school {spec.old_school_id} retirement affected {retired} rows"
            )
        conn.execute(
            """
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,source_id,source_job_id,
               old_value,new_value,reason)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                observed, "ihe_historical_school_entity_retire", None,
                source_id, spec.source_job_id,
                json.dumps({"school_id": spec.old_school_id,
                            "school_name": spec.old_school_name,
                            "is_current": 1}, ensure_ascii=False),
                json.dumps({"school_id": spec.old_school_id,
                            "is_current": 0,
                            "merged_into_id": target_school_id}, ensure_ascii=False),
                "Retired the now-unreferenced contaminated historical school row; "
                "the old label remains on the historical entity and was not copied "
                "into the survivor aliases.",
            ),
        )
        entities_retired += 1

    return {
        "state_before": state,
        "job_relinks": job_relinks,
        "entities_retired": entities_retired,
    }


def inspect_database(db_path, targets=PRODUCTION_TARGETS, **kwargs):
    conn = open_read_only(db_path)
    try:
        return inspect_connection(conn, targets, **kwargs)
    finally:
        conn.close()


def _write_output(path, payload):
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path:
        destination = Path(path).resolve()
        if destination.exists():
            raise RuntimeError(f"refusing to overwrite evidence file: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=PRODUCTION_DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    db_path = args.db.resolve()

    initial = inspect_database(db_path)
    if not initial["valid"]:
        _write_output(args.output, {"ok": False, "mode": "dry-run", "inspection": initial})
        return 2
    if not args.apply:
        _write_output(args.output, {"ok": True, "mode": "dry-run", "inspection": initial})
        return 0
    if initial["state"] == "already_repaired":
        _write_output(args.output, {
            "ok": True, "mode": "apply", "result": "already_repaired",
            "inspection": initial,
        })
        return 0

    backup_dir = db_path.parent / "backups"
    before_backups = set(backup_dir.glob(f"*{REPAIR_TAG}*")) if backup_dir.exists() else set()
    inventory = preflight(str(db_path), REPAIR_TAG)
    with guarded_write():
        conn = sqlite3.connect(str(db_path), timeout=60)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            locked = inspect_connection(conn)
            if not locked["valid"] or locked["state"] != initial["state"]:
                raise RuntimeError(
                    "repair state changed between preflight and write lock: "
                    f"before={initial['state']} locked={locked['state']} "
                    f"errors={locked.get('errors')}"
                )
            changes = apply_connection(conn, locked)
            after_locked = inspect_connection(conn)
            if not after_locked["valid"] or after_locked["state"] != "already_repaired":
                raise RuntimeError(
                    f"post-repair transaction state invalid: {after_locked}"
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    post = postflight(str(db_path), inventory)
    after_backups = set(backup_dir.glob(f"*{REPAIR_TAG}*"))
    created_backups = sorted(str(path) for path in after_backups - before_backups)
    final = inspect_database(db_path)
    payload = {
        "ok": True,
        "mode": "apply",
        "database": str(db_path),
        "state_before": initial["state"],
        "changes": changes,
        "state_after": final["state"],
        "created_backup_artifacts": created_backups,
        "preflight_inventory": inventory,
        "postflight": post,
        "inspection_after": final,
    }
    _write_output(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
