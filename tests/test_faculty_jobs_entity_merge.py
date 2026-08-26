# -*- coding: utf-8 -*-
"""Merging duplicate school and institution entities.

Duplicates accumulated because sources spell the same unit differently and,
in some cases, a posting's programme text landed in the school name. Merging is
the destructive-looking operation in this domain, so every test here is about
what must survive it: job links, evidence, aliases, and any genuinely separate
school that must never be collapsed.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import (
    _merge_duplicate_institutions,
    _merge_school_entity,
    _merge_variant_school_entities,
    ensure_faculty_jobs_tables,
)

NOW = "2026-08-26T00:00:00Z"


class MergeTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def institution(self, institution_id, name, normalized=None, **fields):
        columns = "id,official_name,normalized_name,is_current,created_at,updated_at"
        values = [institution_id, name, normalized or name.casefold(), 1, NOW, NOW]
        for key, value in fields.items():
            columns += f",{key}"
            values.append(value)
        self.conn.execute(
            f"INSERT INTO institutions ({columns}) VALUES ({','.join('?' * len(values))})", values)

    def school(self, school_id, institution_id, name):
        self.conn.execute(
            "INSERT INTO business_schools (id,institution_id,official_name,normalized_name,"
            "business_research_tier,is_current,created_at,updated_at) "
            "VALUES (?,?,?,?, 'Unclassified',1,?,?)",
            (school_id, institution_id, name, name.casefold(), NOW, NOW))

    def job(self, job_id, institution_id, school_id=None):
        self.conn.execute(
            "INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,institution_id,"
            "school_id,business_scope,derived_quality,status,first_seen_at,last_seen_at,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,'business_discipline','accepted','open',"
            "?,?,?,?)",
            (job_id, f"k{job_id}", "Assistant Professor", "assistant professor",
             institution_id, school_id, NOW, NOW, NOW, NOW))

    def evidence(self, school_id, kind, value):
        self.conn.execute(
            "INSERT INTO school_evidence (school_id,evidence_type,value,source_name,source_url,"
            "verified_at,confidence) VALUES (?,?,?,'src','https://example.edu',?,'High')",
            (school_id, kind, value, NOW))


class SchoolMergeTests(MergeTestBase):
    def test_job_links_and_evidence_move_to_the_survivor(self):
        self.institution(1, "Tulane University")
        self.school(10, 1, "Freeman School of Business")
        self.school(11, 1, "A. B. Freeman School of Business")
        self.job(100, 1, school_id=10)
        self.evidence(10, "AACSB", "accredited")
        self.conn.commit()
        _merge_school_entity(self.conn, 10, 11, "variant")
        self.conn.commit()
        self.assertEqual(11, self.conn.execute(
            "SELECT school_id FROM jobs WHERE id=100").fetchone()["school_id"])
        self.assertEqual(11, self.conn.execute(
            "SELECT school_id FROM school_evidence LIMIT 1").fetchone()["school_id"])

    def test_the_merged_row_is_retired_not_deleted(self):
        self.institution(1, "Tulane University")
        self.school(10, 1, "Freeman School of Business")
        self.school(11, 1, "A. B. Freeman School of Business")
        self.conn.commit()
        _merge_school_entity(self.conn, 10, 11, "variant")
        self.conn.commit()
        row = self.conn.execute("SELECT is_current, official_name FROM business_schools "
                                "WHERE id=10").fetchone()
        self.assertEqual(0, row["is_current"])
        self.assertEqual("Freeman School of Business", row["official_name"],
                         "the old label stays readable for audit")

    def test_duplicate_evidence_is_collapsed_not_doubled(self):
        self.institution(1, "Tulane University")
        self.school(10, 1, "Freeman School of Business")
        self.school(11, 1, "A. B. Freeman School of Business")
        self.evidence(10, "AACSB", "accredited")
        self.evidence(11, "AACSB", "accredited")
        self.conn.commit()
        _merge_school_entity(self.conn, 10, 11, "variant")
        self.conn.commit()
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM school_evidence WHERE school_id=11").fetchone()[0])

    def test_the_merge_is_recorded_in_the_repair_audit(self):
        self.institution(1, "Tulane University")
        self.school(10, 1, "Freeman School of Business")
        self.school(11, 1, "A. B. Freeman School of Business")
        self.conn.commit()
        _merge_school_entity(self.conn, 10, 11, "name variant of the same school")
        self.conn.commit()
        row = self.conn.execute(
            "SELECT action, old_value, new_value, reason FROM faculty_job_repair_audit"
        ).fetchone()
        self.assertEqual("merge_variant_school_entity", row["action"])
        self.assertEqual(("10", "11"), (row["old_value"], row["new_value"]))
        self.assertIn("variant", row["reason"])

    def test_genuinely_separate_schools_survive_the_variant_pass(self):
        self.institution(2, "University of Virginia")
        self.school(20, 2, "Darden School of Business")
        self.school(21, 2, "McIntire School of Commerce")
        self.conn.commit()
        stats = _merge_variant_school_entities(self.conn)
        self.conn.commit()
        self.assertEqual(0, stats["merged"])
        self.assertEqual(1, stats["groups_skipped_as_distinct"])
        self.assertEqual(2, self.conn.execute(
            "SELECT COUNT(*) FROM business_schools WHERE institution_id=2 AND is_current=1"
        ).fetchone()[0])


class InstitutionMergeTests(MergeTestBase):
    def test_jobs_move_and_the_old_name_becomes_an_alias(self):
        self.institution(1, "Tulane University", city="New Orleans")
        self.institution(2, "Tulane Univ", normalized="tulane university")
        self.job(100, 1)
        self.job(101, 2)
        self.conn.commit()
        stats = _merge_duplicate_institutions(self.conn)
        self.conn.commit()
        self.assertEqual(1, stats["merged"])
        survivors = {row["institution_id"] for row in self.conn.execute(
            "SELECT institution_id FROM jobs")}
        self.assertEqual(1, len(survivors), "both jobs must end on one institution")
        aliases = self.conn.execute(
            "SELECT aliases_json FROM institutions WHERE id=?", (survivors.pop(),)).fetchone()[0]
        self.assertIn("Tulane Univ", aliases)

    def test_the_row_with_the_most_jobs_survives(self):
        self.institution(1, "Small Row", normalized="same name")
        self.institution(2, "Big Row", normalized="same name")
        self.job(100, 2)
        self.job(101, 2)
        self.job(102, 1)
        self.conn.commit()
        _merge_duplicate_institutions(self.conn)
        self.conn.commit()
        self.assertEqual(1, self.conn.execute(
            "SELECT is_current FROM institutions WHERE id=2").fetchone()["is_current"])
        self.assertEqual(0, self.conn.execute(
            "SELECT is_current FROM institutions WHERE id=1").fetchone()["is_current"])

    def test_a_missing_field_is_filled_but_never_overwritten(self):
        self.institution(1, "Keeper", normalized="same name", city="New Orleans")
        self.institution(2, "Absorbed", normalized="same name", city="Metairie",
                         state_province="LA")
        self.job(100, 1)
        self.conn.commit()
        _merge_duplicate_institutions(self.conn)
        self.conn.commit()
        row = self.conn.execute(
            "SELECT city, state_province FROM institutions WHERE id=1").fetchone()
        self.assertEqual("New Orleans", row["city"], "an existing value is never replaced")
        self.assertEqual("LA", row["state_province"], "a missing value is filled")

    def test_differently_named_institutions_are_not_merged(self):
        self.institution(1, "University of Virginia", normalized="university of virginia")
        self.institution(2, "University of Virginia Darden",
                         normalized="university of virginia-darden")
        self.conn.commit()
        stats = _merge_duplicate_institutions(self.conn)
        self.conn.commit()
        self.assertEqual(0, stats["merged"])
        self.assertEqual(2, self.conn.execute(
            "SELECT COUNT(*) FROM institutions WHERE is_current=1").fetchone()[0])

    def test_no_job_is_orphaned_onto_a_retired_institution(self):
        self.institution(1, "A", normalized="same name")
        self.institution(2, "B", normalized="same name")
        self.institution(3, "C", normalized="same name")
        self.job(100, 1)
        self.job(101, 2)
        self.job(102, 3)
        self.conn.commit()
        _merge_duplicate_institutions(self.conn)
        self.conn.commit()
        orphans = self.conn.execute("""
            SELECT COUNT(*) FROM jobs j JOIN institutions i ON i.id=j.institution_id
            WHERE i.is_current=0
        """).fetchone()[0]
        self.assertEqual(0, orphans)


if __name__ == "__main__":
    unittest.main()
