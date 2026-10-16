# -*- coding: utf-8 -*-
"""The queue runner's selection rules.

The network loop is not what needs guarding here -- ``enrich_source_details``
already has its own tests. What needs guarding is which boards this thing is
willing to talk to at all. `enabled = 0` on a source is a standing decision
about a publisher, and a batch runner that quietly widened the set to
"everything with rows" would start requesting pages from a board someone
deliberately switched off.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.enrich_all_details import enabled_sources, survey
from services.faculty_jobs_service import (
    FACULTY_JOBS_SCHEMA_VERSION, ensure_faculty_jobs_tables,
)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def test_a_disabled_source_is_never_selected(self):
        self.conn.execute("UPDATE sources SET enabled=0 WHERE name='poms'")
        self.conn.commit()
        self.assertNotIn("poms", enabled_sources(self.conn))

    def test_higheredjobs_is_off_and_stays_off(self):
        # The standing instruction is not to re-read this board. It is disabled
        # in the seed; the runner must not be the thing that reopens it.
        row = self.conn.execute(
            "SELECT enabled FROM sources WHERE name='higheredjobs'").fetchone()
        self.assertEqual(0, row[0], "seed policy changed; check this is intended")
        self.assertNotIn("higheredjobs", enabled_sources(self.conn))

    def test_naming_a_disabled_source_explicitly_is_refused_not_honoured(self):
        # Passing --sources higheredjobs must fail loudly rather than silently
        # returning an empty list, which would read as "nothing owed".
        with self.assertRaises(SystemExit) as caught:
            enabled_sources(self.conn, only="higheredjobs")
        self.assertIn("higheredjobs", str(caught.exception))

    def test_an_unknown_source_name_is_a_typo_not_an_empty_run(self):
        with self.assertRaises(SystemExit):
            enabled_sources(self.conn, only="poms,pomss")

    def test_a_subset_keeps_only_what_was_asked_for(self):
        chosen = enabled_sources(self.conn, only="poms,ais")
        self.assertEqual(["ais", "poms"], sorted(chosen))

    def test_survey_refuses_a_database_on_an_older_schema(self):
        # Reporting a queue depth computed against a schema this build does not
        # understand would be a number with no meaning.
        self.conn.execute(f"PRAGMA user_version = {FACULTY_JOBS_SCHEMA_VERSION - 1}")
        self.conn.commit()
        with self.assertRaises(SystemExit) as caught:
            survey(self.db)
        self.assertIn("user_version", str(caught.exception))

    def test_survey_reads_without_migrating(self):
        before = self.conn.execute("PRAGMA user_version").fetchone()[0]
        queue = survey(self.db)
        after = sqlite3.connect(self.db).execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(before, after, "a survey must not migrate the file it reports on")
        self.assertTrue(all(count == 0 for _name, count in queue),
                        "an empty database owes no readings")


if __name__ == "__main__":
    unittest.main()
