# -*- coding: utf-8 -*-
"""Re-observing a posting must not lose what an earlier reading established.

Two boards can carry the same posting. Before this policy every field was
overwritten by whichever board was read last, so a salary or an application URL
we already held could be replaced by another board's blank or by its vaguer
copy. Meanwhile the row's own last_seen_at never advanced at all: only the
source link's did, so a job seen daily looked untouched since the day it was
first ingested.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_field_policy import (
    AUTHORITATIVE, EVIDENCE, IMMUTABLE, LAST_SEEN, plan_field_updates,
)
from services.faculty_jobs_service import (
    _JOB_WRITE_COLUMNS, ensure_faculty_jobs_tables, update_faculty_jobs,
)
from services.faculty_jobs_sources.base import AdapterResponse, SourceAdapter, SourceJob

EARLY = "2026-08-01T00:00:00Z"
LATER = "2026-08-29T00:00:00Z"


def row(**fields):
    base = {field: None for field in
            AUTHORITATIVE + EVIDENCE + LAST_SEEN + IMMUTABLE}
    base.update(fields)
    return base


class PolicyTests(unittest.TestCase):
    def plan(self, current, values, same_source):
        return plan_field_updates(row(**current), values, same_source=same_source)

    def test_the_owning_source_may_withdraw_a_deadline_it_stopped_publishing(self):
        changes, reasons = self.plan({"deadline_date": "2026-09-30"},
                                     {"deadline_date": None}, same_source=True)
        self.assertIn("deadline_date", changes)
        self.assertIsNone(changes["deadline_date"])
        self.assertEqual("authoritative-same-source", reasons["deadline_date"])

    def test_another_source_may_not_blank_a_deadline_we_hold(self):
        changes, _ = self.plan({"deadline_date": "2026-09-30"},
                               {"deadline_date": None}, same_source=False)
        self.assertNotIn("deadline_date", changes)

    def test_another_source_may_fill_a_field_we_lack(self):
        changes, reasons = self.plan({"salary_raw": None},
                                     {"salary_raw": "$95,000"}, same_source=False)
        self.assertEqual("$95,000", changes["salary_raw"])
        self.assertEqual("evidence-fills-blank", reasons["salary_raw"])

    def test_another_source_may_not_replace_evidence_we_already_hold(self):
        # Two boards disagreeing about a salary is not a reason to keep
        # whichever happened to be scraped last.
        changes, _ = self.plan({"salary_raw": "$95,000 per year"},
                               {"salary_raw": "Competitive"}, same_source=False)
        self.assertNotIn("salary_raw", changes)

    def test_the_owning_source_may_correct_its_own_evidence(self):
        changes, reasons = self.plan({"salary_raw": "$95,000 per year"},
                                     {"salary_raw": "$98,000 per year"}, same_source=True)
        self.assertEqual("$98,000 per year", changes["salary_raw"])
        self.assertEqual("evidence-owner", reasons["salary_raw"])

    def test_last_seen_only_moves_forward(self):
        forward, _ = self.plan({"last_seen_at": EARLY}, {"last_seen_at": LATER},
                               same_source=True)
        self.assertEqual(LATER, forward["last_seen_at"])
        backward, _ = self.plan({"last_seen_at": LATER}, {"last_seen_at": EARLY},
                                same_source=True)
        self.assertNotIn("last_seen_at", backward,
                         "an older snapshot must not rewind the last sighting")

    def test_history_fields_are_never_rewritten_by_an_observation(self):
        changes, _ = self.plan({"first_seen_at": EARLY, "created_at": EARLY},
                               {"first_seen_at": LATER, "created_at": LATER},
                               same_source=True)
        for field in IMMUTABLE:
            self.assertNotIn(field, changes)

    def test_an_unknown_string_counts_as_blank_for_evidence(self):
        changes, _ = self.plan({"visa_status": "unknown"},
                               {"visa_status": "sponsorship_available"}, same_source=False)
        self.assertEqual("sponsorship_available", changes["visa_status"])

    def test_the_spec_fields_all_have_a_declared_policy(self):
        declared = set(AUTHORITATIVE) | set(EVIDENCE) | set(LAST_SEEN) | set(IMMUTABLE)
        for field in ("appointment_type", "last_seen_at", "contract_length",
                      "phd_required_by", "teaching_areas_json", "research_areas_json",
                      "teaching_load_raw", "visa_text", "language_requirements"):
            self.assertIn(field, declared, field)


class StubAdapter(SourceAdapter):
    name = adapter_name = "ais"
    base_url = "https://stub.example/jobs"

    def __init__(self, jobs, **kwargs):
        super().__init__(**kwargs)
        self._jobs = jobs

    def fetch(self):
        return AdapterResponse(list(self._jobs), pages_fetched=1)


class PersistenceTests(unittest.TestCase):
    """The contract the policy exists to keep, exercised end to end."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)

    def tearDown(self):
        self.dir.cleanup()

    def posting(self, captured):
        return SourceJob(
            source="ais", source_job_id="adj-1",
            source_url="https://stub.example/jobs/adj-1",
            title_raw="Adjunct Faculty, Accounting",
            institution_raw="Example University",
            location_raw="Boston, Massachusetts",
            captured_at=captured,
        )

    def run_once(self, captured):
        return update_faculty_jobs(
            self.db, source_names=["ais"],
            adapters=[StubAdapter([self.posting(captured)])], max_pages=1)

    def read(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(
                "SELECT id,appointment_type,last_seen_at,first_seen_at FROM jobs").fetchone()
        finally:
            conn.close()

    def test_appointment_type_is_written_on_the_first_observation(self):
        # It was on the table but missing from the write whitelist, so every
        # newly ingested adjunct posting stored NULL.
        self.assertIn("appointment_type", _JOB_WRITE_COLUMNS)
        self.run_once(EARLY)
        self.assertEqual("adjunct", self.read()["appointment_type"])

    def test_a_second_observation_advances_the_job_last_seen(self):
        self.run_once(EARLY)
        first = self.read()
        self.run_once(LATER)
        second = self.read()
        self.assertEqual(first["id"], second["id"], "the same posting, not a new row")
        self.assertGreater(second["last_seen_at"], first["last_seen_at"])
        self.assertEqual(first["first_seen_at"], second["first_seen_at"])

    def test_the_job_and_its_source_link_agree_on_the_last_sighting(self):
        self.run_once(EARLY)
        self.run_once(LATER)
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            job = conn.execute("SELECT last_seen_at FROM jobs").fetchone()["last_seen_at"]
            link = conn.execute("SELECT last_seen FROM job_sources").fetchone()["last_seen"]
        finally:
            conn.close()
        self.assertEqual(job[:10], link[:10],
                         "the row must not look stale while its link is current")


if __name__ == "__main__":
    unittest.main()
