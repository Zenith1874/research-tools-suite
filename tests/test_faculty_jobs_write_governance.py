# -*- coding: utf-8 -*-
"""Nothing migrates a database without a backup behind it.

Two ways that rule was broken here. A --dry-run that only meant to report
called ensure and migrated production unbacked. And ten read endpoints called
ensure to open the database, so any page load against an older file applied
every pending migration -- triggered by a browser, with no backup and no record
of who asked.

The order is the contract: read-only check, inventory, backup, then migrate.
"""

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

from services.faculty_jobs_service import (
    FACULTY_JOBS_SCHEMA_VERSION, FacultyJobsSchemaOutOfDate,
    build_faculty_job_summary, build_faculty_jobs_payload, build_job_market_analytics,
    ensure_faculty_jobs_tables,
)
from services.faculty_jobs_write_guard import (
    FacultyJobsWriteGuardRequired, PRESERVED_TABLES, discover_private_tables,
    postflight, preflight, table_counts,
)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ReadPathTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.dir.name) / "old.db"
        conn = sqlite3.connect(str(self.db))
        conn.execute("PRAGMA user_version=5")
        conn.execute("CREATE TABLE placeholder(a)")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.dir.cleanup()

    def test_a_read_refuses_an_old_schema_rather_than_migrating_it(self):
        before_hash, before_version = sha256(self.db), 5
        for reader in (build_faculty_jobs_payload, build_faculty_job_summary,
                       build_job_market_analytics):
            with self.assertRaises(FacultyJobsSchemaOutOfDate, msg=reader.__name__):
                reader(str(self.db), {})
        after = sqlite3.connect(f"file:{self.db.as_posix()}?mode=ro", uri=True)
        try:
            version = after.execute("PRAGMA user_version").fetchone()[0]
        finally:
            after.close()
        self.assertEqual(before_version, version, "a GET must not migrate")
        self.assertEqual(before_hash, sha256(self.db), "a GET must not write at all")

    def test_the_refusal_says_what_to_do(self):
        with self.assertRaises(FacultyJobsSchemaOutOfDate) as caught:
            build_faculty_jobs_payload(str(self.db), {})
        message = str(caught.exception)
        self.assertIn("write-mode", message)
        self.assertIn("backup", message)

    def test_a_missing_production_database_is_not_created_by_a_read(self):
        import services.faculty_jobs_service as faculty_service

        missing = Path(self.dir.name) / "missing-production.db"
        with patch.object(faculty_service, "FACULTY_DB_PATH", missing):
            with self.assertRaises(FacultyJobsSchemaOutOfDate) as caught:
                faculty_service.build_faculty_jobs_payload(str(missing), {})
        self.assertIn("missing", str(caught.exception))
        self.assertFalse(missing.exists(), "a read must not create production storage")


class WriteGuardTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)

    def tearDown(self):
        self.dir.cleanup()

    def test_the_backup_exists_before_any_migration_could_run(self):
        inventory = preflight(self.db, "test", echo=lambda *_: None)
        backups = sorted((Path(self.db).parent / "backups").glob("*.pre.db"))
        self.assertEqual(1, len(backups))
        self.assertGreater(backups[0].stat().st_size, 0)
        self.assertIn("preserved_counts", inventory)

    def test_the_manifest_records_sidecars_and_a_checksum(self):
        preflight(self.db, "test", echo=lambda *_: None)
        manifests = sorted((Path(self.db).parent / "backups").glob("*.manifest.json"))
        self.assertEqual(1, len(manifests))
        import json
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        for key in ("backup_sha256", "wal", "shm", "preserved_counts",
                    "private_counts", "private_tables"):
            self.assertIn(key, manifest, key)

    def test_private_tables_are_discovered_rather_than_listed_by_hand(self):
        # user_job_state was reported as "private state: 0" for several runs
        # because it was simply absent from a hand-written constant.
        conn = sqlite3.connect(self.db)
        try:
            discovered = discover_private_tables(conn)
        finally:
            conn.close()
        self.assertIn("user_job_state", discovered)

    def test_a_backup_never_overwrites_an_earlier_one(self):
        first = sorted((Path(self.db).parent / "backups").glob("*.pre.db"))
        preflight(self.db, "test", echo=lambda *_: None)
        preflight(self.db, "test", echo=lambda *_: None)
        after = sorted((Path(self.db).parent / "backups").glob("*.pre.db"))
        self.assertGreater(len(after), len(first))
        self.assertEqual(len(after), len(set(path.name for path in after)))

    def test_postflight_refuses_a_run_that_lost_preserved_rows(self):
        inventory = preflight(self.db, "test", echo=lambda *_: None)
        inventory["preserved_counts"]["jobs"] = 10  # pretend ten rows existed
        with self.assertRaises(SystemExit) as caught:
            postflight(self.db, inventory, echo=lambda *_: None)
        self.assertIn("preserved rows lost", str(caught.exception))

    def test_postflight_refuses_a_run_that_lost_private_rows(self):
        conn = sqlite3.connect(self.db)
        try:
            # The saved state references a job, so the job has to exist: the
            # guard refuses to run against a database that already fails its
            # foreign-key check, which is the behaviour we want everywhere else.
            conn.execute(
                "INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,status,"
                "first_seen_at,last_seen_at,created_at,updated_at) "
                "VALUES (1,'k1','Assistant Professor','assistant professor','open',"
                "'2026-08-29T00:00:00Z','2026-08-29T00:00:00Z',"
                "'2026-08-29T00:00:00Z','2026-08-29T00:00:00Z')")
            conn.execute(
                "INSERT INTO user_job_state (job_id,state,saved_at,updated_at) "
                "VALUES (1,'saved','2026-08-29T00:00:00Z','2026-08-29T00:00:00Z')")
            conn.commit()
        finally:
            conn.close()
        inventory = preflight(self.db, "test", echo=lambda *_: None)
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("DELETE FROM user_job_state")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(SystemExit) as caught:
            postflight(self.db, inventory, echo=lambda *_: None)
        self.assertIn("private state lost", str(caught.exception))

    def test_postflight_rejects_a_schema_that_drifts_from_the_ledger(self):
        inventory = preflight(self.db, "test", echo=lambda *_: None)
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("PRAGMA user_version=999")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(SystemExit) as caught:
            postflight(self.db, inventory, echo=lambda *_: None)
        self.assertIn("migration ledger", str(caught.exception))

    def test_the_preserved_inventory_covers_the_evidence_tables(self):
        for table in ("jobs", "source_job_records", "job_sources",
                      "job_field_provenance", "job_status_history",
                      "faculty_job_repair_audit", "job_detail_fetches"):
            self.assertIn(table, PRESERVED_TABLES, table)

    def test_a_direct_production_service_writer_is_rejected_before_ensure(self):
        # Use a fixture as the pretend production path so this test cannot
        # touch the real private database. The guard must fire before the
        # writer reaches ensure_faculty_jobs_tables or opens a write connection.
        import services.faculty_jobs_service as faculty_service

        before_hash = sha256(self.db)
        with patch.object(faculty_service, "FACULTY_DB_PATH", Path(self.db)):
            with self.assertRaises(FacultyJobsWriteGuardRequired):
                faculty_service.update_faculty_jobs(
                    self.db, source_names=["ais"], adapters=[]
                )
        self.assertEqual(before_hash, sha256(self.db))



class ScriptSweepTests(unittest.TestCase):
    """Every script that writes production goes through the guard."""

    SCRIPTS = ROOT / "scripts"

    # Writes to a new file it refuses to overwrite and never opens production
    # for writing, so the guard would have nothing to protect.
    COPY_ON_WRITE = {"recover_faculty_jobs_db.py"}

    # Anything that reaches the database through one of these has committed to
    # writing it.
    WRITE_CALLS = ("update_faculty_jobs(", "ensure_faculty_jobs_tables(",
                   "repair_faculty_jobs_database(", "scan_aacsb_official_websites(",
                   "update_aacsb_directory(", "run_detail_enrichment(")

    def writing_scripts(self):
        for path in sorted(self.SCRIPTS.glob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.name in self.COPY_ON_WRITE:
                continue
            if any(call in text for call in self.WRITE_CALLS):
                yield path, text

    def test_at_least_the_known_writers_are_found(self):
        # A sweep that silently matches nothing passes forever.
        names = {path.name for path, _ in self.writing_scripts()}
        for expected in ("update_faculty_jobs.py", "enrich_job_details.py",
                         "import_higheredjobs_snapshot.py", "rescan_aacsb_websites.py"):
            self.assertIn(expected, names, expected)

    def test_every_writing_script_takes_a_backup_first(self):
        for path, text in self.writing_scripts():
            self.assertIn("preflight", text,
                          f"{path.name} writes production without a backup")
            self.assertIn("postflight", text,
                          f"{path.name} writes production without a post-check")

    def test_the_backup_is_taken_before_the_write(self):
        # The order is the contract: a script that migrates first has already
        # destroyed the state its backup was meant to capture.
        for path, text in self.writing_scripts():
            first_guard = text.index("preflight(")
            writes = [text.index(call) for call in self.WRITE_CALLS if call in text]
            self.assertLess(first_guard, min(writes),
                            f"{path.name} writes before it backs up")

if __name__ == "__main__":
    unittest.main()
