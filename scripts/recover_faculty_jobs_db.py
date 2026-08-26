#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a repaired Academic Career database from a validated base backup.

This is deliberately a copy-on-write recovery tool.  It never opens the
production database for writing and refuses to overwrite the output path.
The source database is read with ``text_factory=bytes`` so one malformed text
cell cannot make the rest of the salvage unreadable.  The validated base
backup remains the authority for the original 148 jobs and private state;
newer AACSB-derived rows and histories are copied from the post-scan snapshot.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import sys


ALLOWED_DERIVED_QUALITY = {"accepted", "quarantined"}
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _q(name):
    return '"' + str(name).replace('"', '""') + '"'


class Recovery:
    def __init__(self, base: Path, damaged: Path, output: Path):
        self.base = base
        self.damaged = damaged
        self.output = output
        self.decode_replacements = 0
        self.warnings: list[str] = []
        self.job_map: dict[int, int] = {}
        self.source_map: dict[int, int] = {}
        self.institution_map: dict[int, int] = {}
        self.school_map: dict[int, int] = {}
        self.source_rows: list[dict] = []
        self.damaged_rows: dict[str, list[dict]] = {}

    def _decode(self, value):
        if not isinstance(value, bytes):
            return value
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            self.decode_replacements += 1
            return value.decode("utf-8", "replace")

    def _row(self, row):
        return {key: self._decode(row[key]) for key in row.keys()}

    def _read_table(self, conn, table):
        try:
            rows = [self._row(row) for row in conn.execute(f"SELECT * FROM {_q(table)} NOT INDEXED")]
            self.damaged_rows[table] = rows
            return rows
        except sqlite3.Error as exc:
            self.warnings.append(f"could not salvage {table}: {exc}")
            self.damaged_rows[table] = []
            return []

    @staticmethod
    def _columns(conn, table):
        return [row[1] for row in conn.execute(f"PRAGMA table_info({_q(table)})")]

    def _prepare_target(self):
        if self.output.exists():
            raise RuntimeError(f"Refusing to overwrite existing output: {self.output}")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.base, self.output)
        from services.faculty_jobs_service import ensure_faculty_jobs_tables

        ensure_faculty_jobs_tables(str(self.output))

    @staticmethod
    def _target_row(conn, table, key, value):
        return conn.execute(
            f"SELECT * FROM {_q(table)} WHERE {_q(key)}=? LIMIT 1", (value,)
        ).fetchone()

    def _update_by_id(self, dst, table, data, transforms=None):
        """Update or insert one row with an integer ``id`` primary key."""
        transforms = transforms or {}
        columns = self._columns(dst, table)
        data = {key: transforms.get(key, lambda value: value)(data.get(key)) for key in columns if key in data}
        if "id" not in data or data["id"] is None:
            return None
        row_id = data["id"]
        existing = dst.execute(f"SELECT 1 FROM {_q(table)} WHERE id=?", (row_id,)).fetchone()
        if existing:
            update = [key for key in columns if key != "id" and key in data]
            if update:
                dst.execute(
                    f"UPDATE {_q(table)} SET " + ",".join(f"{_q(key)}=?" for key in update) + " WHERE id=?",
                    [data[key] for key in update] + [row_id],
                )
            return row_id
        insert = [key for key in columns if key in data]
        try:
            dst.execute(
                f"INSERT INTO {_q(table)} ({','.join(_q(key) for key in insert)}) VALUES ({','.join('?' for _ in insert)})",
                [data[key] for key in insert],
            )
            return row_id
        except sqlite3.IntegrityError as exc:
            self.warnings.append(f"{table} id={row_id} not inserted: {exc}")
            return None

    def _sync_sources(self, dst, rows):
        target_by_name = {
            row["name"]: row["id"] for row in dst.execute("SELECT id,name FROM sources")
        }
        for row in rows:
            name = row.get("name")
            if not name:
                continue
            target_id = target_by_name.get(name)
            if target_id is None:
                data = dict(row)
                try:
                    target_id = self._update_by_id(dst, "sources", data)
                except sqlite3.IntegrityError:
                    target_id = None
                if target_id is None:
                    found = dst.execute("SELECT id FROM sources WHERE name=?", (name,)).fetchone()
                    target_id = found[0] if found else None
                if target_id is not None:
                    target_by_name[name] = target_id
            else:
                data = dict(row)
                data["id"] = target_id
                self._update_by_id(dst, "sources", data)
            if target_id is not None:
                self.source_map[int(row["id"])] = int(target_id)

    def _sync_institutions(self, dst, rows):
        columns = self._columns(dst, "institutions")
        by_id = {row["id"]: row for row in dst.execute("SELECT id,normalized_name FROM institutions")}
        by_norm = {row["normalized_name"]: row["id"] for row in dst.execute("SELECT id,normalized_name FROM institutions")}
        for row in rows:
            source_id = row.get("id")
            norm = row.get("normalized_name")
            same_id = source_id in by_id and by_id[source_id]["normalized_name"] == norm
            target_id = source_id if same_id else by_norm.get(norm)
            data = {key: row.get(key) for key in columns if key in row}
            if target_id is None:
                try:
                    dst.execute(
                        f"INSERT INTO institutions ({','.join(_q(key) for key in data)}) VALUES ({','.join('?' for _ in data)})",
                        list(data.values()),
                    )
                    target_id = data["id"]
                except sqlite3.IntegrityError:
                    found = dst.execute("SELECT id FROM institutions WHERE normalized_name=?", (norm,)).fetchone()
                    if found:
                        target_id = found[0]
                    else:
                        # The two databases may have assigned different
                        # numeric IDs as AACSB entities were appended.  Keep
                        # the row with a fresh local ID instead of dropping a
                        # valid institution because an unrelated base row
                        # occupies the damaged snapshot's ID.
                        insert_data = {key: value for key, value in data.items() if key != "id"}
                        dst.execute(
                            f"INSERT INTO institutions ({','.join(_q(key) for key in insert_data)}) VALUES ({','.join('?' for _ in insert_data)})",
                            list(insert_data.values()),
                        )
                        target_id = dst.execute("SELECT last_insert_rowid()").fetchone()[0]
            elif same_id:
                # The pre-scan backup is authoritative for existing entities;
                # AACSB website scans may carry a noisy footer-derived country
                # and must not overwrite it during recovery.
                pass
            else:
                # A newly derived duplicate with the same normalized name is
                # an alias candidate, not authority to overwrite the
                # validated base entity (for example, a noisy country parsed
                # from a faculty-page footer).
                self.warnings.append(f"institution id={source_id} merged to existing normalized entity id={target_id} without overwriting base evidence")
            if target_id is not None:
                self.institution_map[int(source_id)] = int(target_id)
                by_id[int(source_id)] = {"id": int(target_id), "normalized_name": norm}
                if norm:
                    by_norm[norm] = int(target_id)

    def _sync_schools(self, dst, rows):
        columns = self._columns(dst, "business_schools")
        by_id = {row["id"]: row for row in dst.execute("SELECT id,normalized_name,institution_id FROM business_schools")}
        by_key = {(row["institution_id"], row["normalized_name"]): row["id"] for row in dst.execute("SELECT id,normalized_name,institution_id FROM business_schools")}
        for row in rows:
            source_id = row.get("id")
            institution_id = self.institution_map.get(int(row["institution_id"]))
            if institution_id is None:
                self.warnings.append(f"business school id={source_id} has no institution mapping")
                continue
            norm = row.get("normalized_name")
            same_id = (
                source_id in by_id
                and by_id[source_id]["normalized_name"] == norm
                and by_id[source_id]["institution_id"] == institution_id
            )
            target_id = source_id if same_id else by_key.get((institution_id, norm))
            data = {key: row.get(key) for key in columns if key in row}
            data["institution_id"] = institution_id
            if target_id is None:
                try:
                    dst.execute(
                        f"INSERT INTO business_schools ({','.join(_q(key) for key in data)}) VALUES ({','.join('?' for _ in data)})",
                        list(data.values()),
                    )
                    target_id = data["id"]
                except sqlite3.IntegrityError:
                    found = dst.execute(
                        "SELECT id FROM business_schools WHERE institution_id=? AND normalized_name=?",
                        (institution_id, norm),
                    ).fetchone()
                    if found:
                        target_id = found[0]
                    else:
                        insert_data = {key: value for key, value in data.items() if key != "id"}
                        dst.execute(
                            f"INSERT INTO business_schools ({','.join(_q(key) for key in insert_data)}) VALUES ({','.join('?' for _ in insert_data)})",
                            list(insert_data.values()),
                        )
                        target_id = dst.execute("SELECT last_insert_rowid()").fetchone()[0]
            elif same_id:
                # Existing school entities and their accreditation evidence
                # come from the validated base; only genuinely new entities
                # are inserted below.
                pass
            if target_id is not None:
                self.school_map[int(source_id)] = int(target_id)
                by_id[int(source_id)] = {"id": int(target_id), "normalized_name": norm, "institution_id": institution_id}
                by_key[(institution_id, norm)] = int(target_id)

    def _insert_jobs(self, dst, rows, aacsb_job_ids):
        target_columns = self._columns(dst, "jobs")
        current_by_id = {int(row["id"]): row for row in rows if row.get("id") is not None}
        self.job_map.update({int(row["id"]): int(row["id"]) for row in dst.execute("SELECT id FROM jobs")})
        for source_job_id in sorted(aacsb_job_ids):
            row = current_by_id.get(int(source_job_id))
            if row is None:
                self.warnings.append(f"AACSB job id={source_job_id} was not readable from damaged jobs table")
                continue
            target_id = int(source_job_id)
            if dst.execute("SELECT 1 FROM jobs WHERE id=?", (target_id,)).fetchone():
                self.job_map[target_id] = target_id
                continue
            data = {key: row.get(key) for key in target_columns if key in row}
            data["id"] = target_id
            if data.get("institution_id") is not None:
                data["institution_id"] = self.institution_map.get(int(data["institution_id"]))
            if data.get("school_id") is not None:
                data["school_id"] = self.school_map.get(int(data["school_id"]))
            quality = data.get("derived_quality")
            data["derived_quality"] = quality if quality in ALLOWED_DERIVED_QUALITY else "quarantined"
            columns = [key for key in target_columns if key in data]
            try:
                dst.execute(
                    f"INSERT INTO jobs ({','.join(_q(key) for key in columns)}) VALUES ({','.join('?' for _ in columns)})",
                    [data[key] for key in columns],
                )
                self.job_map[target_id] = target_id
            except sqlite3.IntegrityError as exc:
                canonical = data.get("canonical_key")
                existing = dst.execute("SELECT id FROM jobs WHERE canonical_key=?", (canonical,)).fetchone() if canonical else None
                if existing:
                    self.job_map[target_id] = int(existing[0])
                    self.warnings.append(f"AACSB job id={target_id} restored to existing canonical job id={existing[0]}")
                else:
                    raise RuntimeError(f"could not restore AACSB job id={target_id}: {exc}")

    def _upsert_by_keys(self, dst, table, row, keys, transforms=None):
        transforms = transforms or {}
        columns = self._columns(dst, table)
        data = {key: transforms.get(key, lambda value: value)(row.get(key)) for key in columns if key in row}
        if any(key not in data for key in keys):
            return
        where = " AND ".join(f"{_q(key)}=?" for key in keys)
        existing = dst.execute(f"SELECT * FROM {_q(table)} WHERE {where} LIMIT 1", [data[key] for key in keys]).fetchone()
        if existing:
            existing_id = existing["id"] if "id" in existing.keys() else None
            update = [key for key in columns if key not in keys and key != "id" and key in data]
            if update:
                dst.execute(
                    f"UPDATE {_q(table)} SET " + ",".join(f"{_q(key)}=?" for key in update) + f" WHERE {where}",
                    [data[key] for key in update] + [data[key] for key in keys],
                )
            return existing_id
        insert = [key for key in columns if key in data and key != "id"]
        try:
            dst.execute(
                f"INSERT INTO {_q(table)} ({','.join(_q(key) for key in insert)}) VALUES ({','.join('?' for _ in insert)})",
                [data[key] for key in insert],
            )
        except sqlite3.IntegrityError as exc:
            self.warnings.append(f"{table} key={tuple(data[key] for key in keys)} not inserted: {exc}")
        return None

    def _remap(self, table, row):
        data = dict(row)
        if "job_id" in data and data["job_id"] is not None:
            data["job_id"] = self.job_map.get(int(data["job_id"]))
        if "possible_job_id" in data and data["possible_job_id"] is not None:
            data["possible_job_id"] = self.job_map.get(int(data["possible_job_id"]))
        if "merged_into_job_id" in data and data["merged_into_job_id"] is not None:
            data["merged_into_job_id"] = self.job_map.get(int(data["merged_into_job_id"]))
        if "source_id" in data and data["source_id"] is not None:
            data["source_id"] = self.source_map.get(int(data["source_id"]))
        if "school_id" in data and data["school_id"] is not None:
            data["school_id"] = self.school_map.get(int(data["school_id"]))
        if "directory_school_id" in data and data["directory_school_id"] is not None:
            data["directory_school_id"] = int(data["directory_school_id"])
        if "linked_business_school_id" in data and data["linked_business_school_id"] is not None:
            data["linked_business_school_id"] = self.school_map.get(int(data["linked_business_school_id"]))
        return data

    def run(self):
        self._prepare_target()
        damaged = sqlite3.connect(f"file:{self.damaged}?mode=ro&cache=private", uri=True, timeout=3)
        damaged.text_factory = bytes
        damaged.row_factory = sqlite3.Row
        for table in (
            "sources", "institutions", "business_schools", "school_evidence", "jobs",
            "source_job_records", "job_sources", "job_field_provenance", "job_status_history",
            "faculty_job_repair_audit", "possible_duplicates", "institution_aliases",
            "job_scope_overrides", "school_tier_overrides", "aacsb_directory_schools",
            "aacsb_scan_history", "aacsb_scan_runs", "ingestion_runs", "source_coverage_history",
            "application_events", "user_job_state", "saved_searches", "saved_search_alerts",
        ):
            self._read_table(damaged, table)

        damaged_sources = self.damaged_rows["sources"]
        aacsb_source_ids = {int(row["id"]) for row in damaged_sources if row.get("name") == "aacsb_official"}
        aacsb_links = [row for row in self.damaged_rows["job_sources"] if int(row.get("source_id") or -1) in aacsb_source_ids]
        aacsb_job_ids = {int(row["job_id"]) for row in aacsb_links}

        dst = sqlite3.connect(self.output, timeout=10)
        dst.row_factory = sqlite3.Row
        dst.execute("PRAGMA foreign_keys=ON")
        try:
            with dst:
                self._sync_sources(dst, damaged_sources)
                self._sync_institutions(dst, self.damaged_rows["institutions"])
                self._sync_schools(dst, self.damaged_rows["business_schools"])
                self._insert_jobs(dst, self.damaged_rows["jobs"], aacsb_job_ids)

                # Preserve all source records and source links, including the
                # original seven sources.  The validated base supplies any
                # row that was unreadable in the damaged jobs table.
                for row in self.damaged_rows["source_job_records"]:
                    data = dict(row)
                    data["source_id"] = self.source_map.get(int(data.get("source_id") or -1))
                    if data.get("source_id") is not None:
                        self._upsert_by_keys(dst, "source_job_records", data, ("source_id", "source_job_id"))
                for row in self.damaged_rows["job_sources"]:
                    data = self._remap("job_sources", row)
                    if data.get("source_id") is not None and data.get("job_id") is not None:
                        self._upsert_by_keys(dst, "job_sources", data, ("source_id", "source_job_id"))

                for table in ("school_evidence", "aacsb_directory_schools"):
                    for row in self.damaged_rows[table]:
                        self._update_by_id(dst, table, self._remap(table, row))
                for row in self.damaged_rows["aacsb_scan_history"]:
                    self._update_by_id(dst, "aacsb_scan_history", row)
                for row in self.damaged_rows["aacsb_scan_runs"]:
                    self._update_by_id(dst, "aacsb_scan_runs", row)

                for table in ("job_field_provenance", "job_status_history", "faculty_job_repair_audit", "possible_duplicates"):
                    for row in self.damaged_rows[table]:
                        if table == "job_field_provenance":
                            # Sixteen rows in the damaged snapshot contain
                            # AACSB scan-history columns shifted into this
                            # table (checked_at appears as field_name and a
                            # website appears as source_id).  The proper
                            # history table has the same observations, so do
                            # not turn those malformed rows into provenance.
                            valid_fields = {
                                "salary_raw", "deadline_date", "deadline_mode", "location", "country",
                                "institution", "title_raw", "track_type", "visa_status",
                                "discipline_primary", "rank_normalized", "official_url",
                            }
                            if (
                                not isinstance(row.get("job_id"), int)
                                or not isinstance(row.get("source_id"), int)
                                or row.get("field_name") not in valid_fields
                                or not isinstance(row.get("captured_at"), str)
                            ):
                                self.warnings.append(f"skipped malformed job_field_provenance id={row.get('id')}")
                                continue
                        data = self._remap(table, row)
                        if "job_id" in data and data["job_id"] is None and row.get("job_id") is not None:
                            continue
                        if "possible_job_id" in data and data["possible_job_id"] is None:
                            continue
                        self._update_by_id(dst, table, data)

                for row in self.damaged_rows["institution_aliases"]:
                    self._update_by_id(dst, "institution_aliases", row)
                for row in self.damaged_rows["job_scope_overrides"]:
                    data = self._remap("job_scope_overrides", row)
                    if data.get("job_id") is not None:
                        self._upsert_by_keys(dst, "job_scope_overrides", data, ("job_id",))
                for row in self.damaged_rows["school_tier_overrides"]:
                    data = self._remap("school_tier_overrides", row)
                    if data.get("school_id") is not None:
                        self._upsert_by_keys(dst, "school_tier_overrides", data, ("school_id",))

                for row in self.damaged_rows["ingestion_runs"]:
                    data = self._remap("ingestion_runs", row)
                    if data.get("source_id") in set(self.source_map.values()):
                        self._update_by_id(dst, "ingestion_runs", data)
                for row in self.damaged_rows["source_coverage_history"]:
                    self._update_by_id(dst, "source_coverage_history", row)

                for row in self.damaged_rows["application_events"]:
                    data = self._remap("application_events", row)
                    if data.get("job_id") is not None:
                        self._update_by_id(dst, "application_events", data)
                for row in self.damaged_rows["user_job_state"]:
                    data = self._remap("user_job_state", row)
                    if data.get("job_id") is not None:
                        self._upsert_by_keys(dst, "user_job_state", data, ("job_id",))
                for row in self.damaged_rows["saved_searches"]:
                    self._update_by_id(dst, "saved_searches", row)
                for row in self.damaged_rows["saved_search_alerts"]:
                    data = self._remap("saved_search_alerts", row)
                    if data.get("job_id") is not None:
                        self._upsert_by_keys(dst, "saved_search_alerts", data, ("search_id", "job_id"))

                # The damaged snapshot predates the centralized country
                # alias replay in migration 18.  Run that deterministic local
                # repair once after copied directory rows have been restored.
                from services.faculty_jobs_service import _repair_aacsb_directory_location_evidence
                _repair_aacsb_directory_location_evidence(dst)
                from services.faculty_jobs_service import _quarantine_aacsb_explicit_nonbusiness_jobs
                _quarantine_aacsb_explicit_nonbusiness_jobs(dst)

                dst.execute(
                    "INSERT INTO faculty_job_repair_audit (observed_at,action,old_value,new_value,reason) VALUES (?,?,?,?,?)",
                    (_now(), "database_recovery", json.dumps({"damaged_db": str(self.damaged), "base_db": str(self.base)}),
                     json.dumps({"aacsb_jobs": len(aacsb_job_ids), "source_records": len(self.damaged_rows["source_job_records"])}),
                     "Copy-on-write recovery after quick_check/foreign_key_check failure; original DB/WAL/SHM retained in a raw snapshot."),
                )
                for table in (
                    "jobs", "source_job_records", "job_sources", "institutions", "business_schools",
                    "school_evidence", "job_field_provenance", "job_status_history", "faculty_job_repair_audit",
                    "possible_duplicates", "institution_aliases", "aacsb_directory_schools", "aacsb_scan_history",
                    "aacsb_scan_runs", "ingestion_runs", "source_coverage_history", "application_events",
                    "saved_searches", "saved_search_alerts",
                ):
                    if dst.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        if "id" in self._columns(dst, table):
                            max_id = dst.execute(f"SELECT MAX(id) FROM {_q(table)}").fetchone()[0]
                            if max_id is not None:
                                updated = dst.execute(
                                    "UPDATE sqlite_sequence SET seq=? WHERE name=?",
                                    (int(max_id), table),
                                ).rowcount
                                if not updated:
                                    dst.execute(
                                        "INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)",
                                        (table, int(max_id)),
                                    )
            dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            dst.close()
            damaged.close()

        verify = sqlite3.connect(f"file:{self.output}?mode=ro&cache=private", uri=True)
        quick = verify.execute("PRAGMA quick_check").fetchone()[0]
        fk = verify.execute("PRAGMA foreign_key_check").fetchall()
        summary = {
            "output": str(self.output),
            "quick_check": quick,
            "foreign_key_violations": len(fk),
            "aacsb_source_links": len(aacsb_links),
            "aacsb_unique_jobs": len(aacsb_job_ids),
            "decode_replacements": self.decode_replacements,
            "warnings": self.warnings,
        }
        for table in ("jobs", "source_job_records", "job_sources", "aacsb_directory_schools", "aacsb_scan_history", "faculty_job_repair_audit", "application_events", "user_job_state"):
            try:
                summary[table] = verify.execute(f"SELECT COUNT(*) FROM {_q(table)}").fetchone()[0]
            except sqlite3.Error:
                pass
        verify.close()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if quick != "ok" or fk:
            raise RuntimeError("recovered candidate failed SQLite integrity verification")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="validated pre-scan database backup")
    parser.add_argument("--damaged", required=True, type=Path, help="read-only damaged database snapshot")
    parser.add_argument("--output", required=True, type=Path, help="new candidate database path; must not exist")
    args = parser.parse_args()
    for path in (args.base, args.damaged):
        if not path.exists():
            parser.error(f"missing input database: {path}")
    try:
        Recovery(args.base, args.damaged, args.output).run()
    except Exception as exc:
        print(f"recovery failed: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
