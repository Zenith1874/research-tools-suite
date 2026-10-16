# -*- coding: utf-8 -*-
"""Two filters that answer two different questions.

``source`` is provenance: which board carried this posting. ``appointment_type``
is what the job is: an adjunct opening and a tenure-track opening are not
competing for the same candidate. They correlate in the current snapshot -- one
aggregator supplies most of the adjunct rows -- which is exactly why they must
stay separate controls. Excluding the board to escape the adjunct roles would
also discard the tenure-track postings only that board carries.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_normalizer import APPOINTMENT_TYPES, infer_appointment
from services.faculty_jobs_service import (
    build_faculty_job_filters, build_faculty_jobs_payload, ensure_faculty_jobs_tables,
)

NOW = "2026-08-29T00:00:00Z"


class AppointmentInferenceTests(unittest.TestCase):
    def test_explicit_contingent_wording_is_read(self):
        for title in ("Adjunct Faculty, Accounting", "Part-Time Instructor of Finance",
                      "Sessional Lecturer, Marketing", "Per-Course Faculty in Management"):
            self.assertEqual("adjunct", infer_appointment(title), title)

    def test_contingent_wording_wins_over_full_time(self):
        # "Full-Time Adjunct Pool" carries both phrases. The contingent half is
        # the one that decides whether the role belongs in a tenure-track
        # search, so checking full_time first would file it as continuing.
        self.assertEqual("adjunct", infer_appointment("Full-Time Adjunct Pool, Business"))

    def test_visiting_and_postdoc_are_separated(self):
        self.assertEqual("visiting", infer_appointment("Visiting Assistant Professor"))
        self.assertEqual("postdoc", infer_appointment("Postdoctoral Fellow in Marketing"))

    def test_silence_is_not_read_as_a_continuing_appointment(self):
        # Absence of "part-time" is not evidence of a full-time role.
        self.assertEqual("unknown", infer_appointment("Assistant Professor of Marketing"))
        self.assertEqual("unknown", infer_appointment(""))
        self.assertEqual("unknown", infer_appointment(None))

    def test_every_value_is_declared(self):
        for title in ("Adjunct", "Visiting Professor", "Postdoc", "Full-Time Lecturer", "Dean"):
            self.assertIn(infer_appointment(title), APPOINTMENT_TYPES)


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.seed()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def source_id(self, name):
        return self.conn.execute("SELECT id FROM sources WHERE name=?", (name,)).fetchone()["id"]

    def add(self, job_id, title, appointment, sources, track="unknown"):
        self.conn.execute("""
            INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,appointment_type,
                              track_type,status,business_scope,derived_quality,
                              faculty_market_eligible,
                              first_seen_at,last_seen_at,created_at,updated_at)
            VALUES (?,?,?,?,?,?,'open','business_school','accepted',1,?,?,?,?)
        """, (job_id, f"job-{job_id}", title, title.casefold(), appointment, track,
              NOW, NOW, NOW, NOW))
        for name in sources:
            self.conn.execute("""
                INSERT INTO job_sources (job_id,source_id,source_job_id,source_url,active,
                                         first_seen,last_seen)
                VALUES (?,?,?,?,1,?,?)
            """, (job_id, self.source_id(name), f"{name}-{job_id}",
                  f"https://example.test/{job_id}", NOW, NOW))

    def seed(self):
        self.add(1, "Adjunct Faculty, Accounting", "adjunct", ["higheredjobs"])
        self.add(2, "Adjunct Instructor, Finance", "adjunct", ["higheredjobs"])
        self.add(3, "Assistant Professor of Marketing", "unknown", ["higheredjobs"],
                 track="tenure_track")
        self.add(4, "Assistant Professor of Management", "unknown", ["poms"],
                 track="tenure_track")
        # Cross-posted: carried by two boards at once.
        self.add(5, "Associate Professor of Strategy", "unknown", ["poms", "chronicle_business"])
        self.conn.commit()

    def total(self, **query):
        return build_faculty_jobs_payload(self.db, query=query)["pagination"]["total"]

    def test_source_filter_selects_one_board(self):
        self.assertEqual(3, self.total(source="higheredjobs"))
        self.assertEqual(2, self.total(source="poms"))

    def test_exclude_source_is_the_complement(self):
        self.assertEqual(5, self.total())
        self.assertEqual(2, self.total(exclude_source="higheredjobs"))

    def test_a_cross_posted_job_matches_either_of_its_boards(self):
        # Job 5 is on both boards. A column-based filter would have made it
        # match only whichever name happened to be stored.
        self.assertIn(5, [job["id"] for job in
                          build_faculty_jobs_payload(self.db, query={"source": "poms"})["jobs"]])
        self.assertIn(5, [job["id"] for job in build_faculty_jobs_payload(
            self.db, query={"source": "chronicle_business"})["jobs"]])

    def test_excluding_one_board_still_hides_a_job_carried_by_another(self):
        # Job 5 is on poms *and* chronicle_business, so excluding chronicle
        # must drop it even though poms also carries it: "not from that board"
        # is a claim about the job, not about one of its links.
        self.assertNotIn(5, [job["id"] for job in build_faculty_jobs_payload(
            self.db, query={"exclude_source": "chronicle_business"})["jobs"]])

    def test_several_sources_may_be_given_at_once(self):
        self.assertEqual(5, self.total(source="higheredjobs,poms,chronicle_business"))

    def test_appointment_filter_is_independent_of_source(self):
        self.assertEqual(2, self.total(appointment_type="adjunct"))
        self.assertEqual(3, self.total(appointment_type="unknown"))

    def test_the_two_filters_are_not_substitutes_for_each_other(self):
        # Dropping the aggregator to escape its adjunct rows also drops the
        # tenure-track posting only that board carries.
        by_appointment = self.total(appointment_type="unknown")
        by_source = self.total(exclude_source="higheredjobs")
        self.assertEqual(3, by_appointment)
        self.assertEqual(2, by_source)
        self.assertNotEqual(by_appointment, by_source)
        self.assertEqual(1, self.total(source="higheredjobs", track="tenure_track"),
                         "the aggregator carries tenure-track rows worth keeping")

    def test_an_unknown_source_name_matches_nothing_rather_than_everything(self):
        self.assertEqual(0, self.total(source="not_a_board"))

    def test_filters_payload_offers_both_controls_with_source_counts(self):
        filters = build_faculty_job_filters(self.db)["filters"]
        self.assertEqual(list(APPOINTMENT_TYPES), filters["appointment_types"])
        counts = {row["name"]: row["jobs"] for row in filters["sources"]}
        self.assertEqual(3, counts["higheredjobs"])
        self.assertEqual(2, counts["poms"])
        self.assertEqual([row["name"] for row in filters["sources"]][0], "higheredjobs",
                         "the largest contributor should be visible first")


if __name__ == "__main__":
    unittest.main()
