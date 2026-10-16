# -*- coding: utf-8 -*-
"""Synthetic, offline coverage for the Academic Career P2 local workflows."""

import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from services.faculty_jobs_school_service import list_institution_aliases
from services.faculty_jobs_service import (
    build_faculty_job_sources,
    build_job_market_analytics,
    ensure_faculty_jobs_tables,
    list_possible_duplicates,
    list_saved_search_alerts,
    list_saved_searches,
    mark_saved_search_alerts_seen,
    resolve_possible_duplicate,
    run_saved_search_alerts,
    save_institution_alias,
    save_saved_search,
    update_faculty_jobs,
)
from services.faculty_jobs_sources.base import SourceJob
from tests.test_faculty_jobs_schema import FakeAdapter


class P2FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "faculty_jobs.db"
        ensure_faculty_jobs_tables(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def _jobs(self):
        deadline = (date.today() + timedelta(days=60)).strftime("%d %B %Y")
        return [
            SourceJob(
                source="ais", source_job_id="p2-a", source_url="https://board.example/p2-a",
                official_url="https://example.edu/jobs/p2-a", title_raw="Assistant Professor of Finance",
                institution_raw="Example University", location_raw="New York, NY",
                description_excerpt=f"Tenure-track. Application deadline: {deadline}. Salary: $100,000 per year.",
                posted_date_raw="Posting date: 1 August 2026", captured_at="2026-08-23T00:00:00Z",
            ),
            SourceJob(
                source="ais", source_job_id="p2-b", source_url="https://board.example/p2-b",
                official_url="https://example.edu/jobs/p2-b", title_raw="Assistant Professor of Marketing",
                institution_raw="Example University", location_raw="Boston, MA",
                description_excerpt=f"Tenure-track. Application deadline: {deadline}. Salary: $101,000 per year.",
                posted_date_raw="Posting date: 1 August 2026", captured_at="2026-08-23T00:00:00Z",
            ),
        ]

    def _load_jobs(self):
        update_faculty_jobs(self.db, source_names=["ais"], adapters=[FakeAdapter([self._jobs()])])

    def test_schema_v14_and_repeated_initialization(self):
        ensure_faculty_jobs_tables(self.db)
        conn = sqlite3.connect(self.db)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"saved_searches", "saved_search_alerts"}.issubset(tables))
        duplicate_columns = {row[1] for row in conn.execute("PRAGMA table_info(possible_duplicates)")}
        self.assertTrue({"resolution", "resolved_at", "resolution_reason", "merged_into_job_id"}.issubset(duplicate_columns))
        self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=14").fetchone()[0])
        self.assertEqual("ok", conn.execute("PRAGMA quick_check").fetchone()[0])
        self.assertEqual([], conn.execute("PRAGMA foreign_key_check").fetchall())
        conn.close()

    def test_saved_search_alert_is_local_bounded_and_idempotent(self):
        self._load_jobs()
        result = save_saved_search(self.db, {"name": "Finance only", "query": {"country": "US", "discipline": "Finance"}})
        self.assertEqual(1, result["alert_run"]["runs"][0]["new_alert_count"])
        self.assertEqual(1, len(list_saved_search_alerts(self.db)["alerts"]))
        self.assertEqual(0, run_saved_search_alerts(self.db)["runs"][0]["new_alert_count"])
        alert_id = list_saved_search_alerts(self.db)["alerts"][0]["id"]
        mark_saved_search_alerts_seen(self.db, [alert_id])
        self.assertIsNotNone(list_saved_search_alerts(self.db)["alerts"][0]["seen_at"])
        self.assertEqual(1, list_saved_searches(self.db)["saved_searches"][0]["match_count"])
        with self.assertRaises(ValueError):
            save_saved_search(self.db, {"name": "Bad", "query": {"country": "Atlantis"}})

    def test_duplicate_reject_keeps_jobs_and_records_and_audit(self):
        self._load_jobs()
        conn = sqlite3.connect(self.db)
        ids = [row[0] for row in conn.execute("SELECT id FROM jobs ORDER BY id")]
        conn.execute(
            "INSERT INTO possible_duplicates (job_id,possible_job_id,confidence,match_basis,created_at) VALUES (?,?,?,?,?)",
            (ids[0], ids[1], 0.91, "fuzzy_review_only", "2026-08-24T00:00:00Z"),
        )
        duplicate_id = conn.execute("SELECT id FROM possible_duplicates").fetchone()[0]
        conn.commit(); conn.close()
        result = resolve_possible_duplicate(self.db, duplicate_id, {"action": "reject", "reason": "Different disciplines and cities are distinct roles."})
        self.assertEqual("rejected", result["resolution"])
        conn = sqlite3.connect(self.db)
        self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
        self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM source_job_records").fetchone()[0])
        self.assertEqual("rejected", conn.execute("SELECT resolution FROM possible_duplicates WHERE id=?", (duplicate_id,)).fetchone()[0])
        self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_repair_audit WHERE action='duplicate_review'").fetchone()[0])
        conn.close()

    def test_exact_official_url_merge_preserves_source_records(self):
        self._load_jobs()
        conn = sqlite3.connect(self.db)
        ids = [row[0] for row in conn.execute("SELECT id FROM jobs ORDER BY id")]
        conn.execute("UPDATE jobs SET official_url=? WHERE id IN (?,?)", ("https://example.edu/jobs/same", ids[0], ids[1]))
        conn.execute(
            "INSERT INTO possible_duplicates (job_id,possible_job_id,confidence,match_basis,created_at) VALUES (?,?,?,?,?)",
            (ids[0], ids[1], 1.0, "manual_exact_url", "2026-08-24T00:00:00Z"),
        )
        duplicate_id = conn.execute("SELECT id FROM possible_duplicates").fetchone()[0]
        conn.commit(); conn.close()
        result = resolve_possible_duplicate(self.db, duplicate_id, {"action": "merge", "reason": "Both records carry the same official application URL."})
        self.assertEqual(1, result["canonical_job_id"])
        conn = sqlite3.connect(self.db)
        self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
        self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM source_job_records").fetchone()[0])
        self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM job_sources").fetchone()[0])
        self.assertEqual([], conn.execute("PRAGMA foreign_key_check").fetchall())
        self.assertGreaterEqual(conn.execute("SELECT COUNT(*) FROM faculty_job_repair_audit WHERE action='manual_duplicate_merge'").fetchone()[0], 1)
        conn.close()

    def test_alias_ledger_and_analytics_coverage_are_evidence_labeled(self):
        self._load_jobs()
        save_institution_alias(self.db, {"alias": "Example U", "canonical_name": "Example University", "reason": "Official spelling was reviewed locally."})
        aliases = list_institution_aliases(self.db)["aliases"]
        self.assertEqual("example u", aliases[0]["alias_normalized"])
        sources = build_faculty_job_sources(self.db)["sources"]
        self.assertIn("field_coverage", sources[0])
        self.assertIn("deadline_or_rolling", sources[0]["field_coverage"])
        # "confirmed" is reserved for evidence a person or the source asserted;
        # these are what our own rules accepted, which is a weaker claim.
        self.assertIn("rule_accepted_jobs", sources[0])
        self.assertIn("review_only_jobs", sources[0])
        self.assertIn("acceptance_rate_percent", sources[0])
        self.assertNotIn("precision_proxy_percent", sources[0],
                         "acceptance is not precision; nothing was checked against truth")
        self.assertIn("completeness_state", sources[0])
        self.assertIn("scan_outcomes", sources[0])
        self.assertIn("whole academic labor market", build_faculty_job_sources(self.db)["interpretation"])
        analytics = build_job_market_analytics(self.db, {'scope': 'business'})["analytics"]
        self.assertTrue(analytics["discipline_observed_coverage"])
        self.assertIn("interpretation", analytics["discipline_observed_coverage"][0])
        self.assertIn("insufficient_history", analytics["history_status"])


class FacultyJobP2SecurityRouteTests(unittest.TestCase):
    def test_private_p2_routes_reject_when_private_policy_denies(self):
        import http.client
        import json
        import server
        import threading

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
        try:
            with patch.object(server, "_faculty_jobs_private_access_allowed", return_value=False):
                for path in ("/api/faculty-jobs/saved-searches", "/api/faculty-jobs/alerts", "/api/faculty-jobs/duplicates", "/api/institution-aliases"):
                    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=20)
                    conn.request("GET", path)
                    response = conn.getresponse(); payload = json.loads(response.read().decode("utf-8")); conn.close()
                    self.assertEqual(403, response.status, path)
                    self.assertEqual("academic_career_local_only", payload.get("code"), path)
        finally:
            httpd.shutdown(); httpd.server_close(); thread.join(timeout=5)


class FacultyJobsUiBoundaryTests(unittest.TestCase):
    def test_all_scope_copy_does_not_call_excluded_rows_role_eligible(self):
        script = (Path(__file__).resolve().parents[1] / "static" / "faculty_jobs.js").read_text(encoding="utf-8")
        self.assertIn("const auditView = currentScope === 'all';", script)
        self.assertIn("observed source records, including excluded roles", script)
        self.assertIn("Observed source catalogue (audit)", script)


if __name__ == "__main__":
    unittest.main()
