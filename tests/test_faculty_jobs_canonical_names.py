# -*- coding: utf-8 -*-
"""Canonical school-name selection, and idempotency of the entity resolvers.

Every name in this file was observed in the production database on 2026-08-26.
That matters: the first canonical rule was "longest name", which passes any
invented fixture and fails on real data, because the extra length is usually a
listing prefix that leaked into the school label. These tests exist so that
class of mistake cannot pass again.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import (
    _canonical_variant_school,
    _current_entity_id,
    _institution,
    _link_jobs_to_unique_school,
    _merge_duplicate_institutions,
    _merge_variant_school_entities,
    _repair_country_slash_locations,
    _repair_current_schools_on_retired_institutions,
    _recanonicalize_merged_schools,
    _school,
    _school_name_quality,
    _strip_school_name_noise,
    ensure_faculty_jobs_tables,
)
from services.faculty_jobs_sources.base import SourceJob

NOW = "2026-08-26T00:00:00Z"

# (institution, [observed school labels], expected canonical)
OBSERVED_GROUPS = [
    ("Miami University",
     ["Farmer School of Business",
      "Full-time Fully On-Campus Farmer School of Business",
      "Part-time Fully On-Campus Farmer School of Business"],
     "Farmer School of Business"),
    ("Tulane University",
     ["Freeman School of Business", "A. B. Freeman School of Business"],
     "A. B. Freeman School of Business"),
    ("Lingnan University",
     ["Faculty of Business", "Office Faculty of Business",
      "Teaching Office Faculty of Business",
      "University The Department Faculty of Business"],
     "Faculty of Business"),
    ("Singapore Management University",
     ["Lee Kong Chian School of Business", "AREA LEE KONG CHIAN SCHOOL OF BUSINESS"],
     "Lee Kong Chian School of Business"),
    ("University of Tennessee, Knoxville",
     ["Haslam College of Business",
      "University Tennessee Knoxville Haslam College of Business"],
     "Haslam College of Business"),
    ("Stockholm School of Economics",
     ["Stockholm School of Economics",
      "House Innovation. University Stockholm School of Economics",
      "Chain Transformation. University Stockholm School of Economics"],
     "Stockholm School of Economics"),
    ("University of Kansas",
     ["School of Business", "Kansas School of Business"],
     "Kansas School of Business"),
    ("Ohio State University",
     ["Fisher College of Business", "Max M. Fisher College of Business"],
     "Max M. Fisher College of Business"),
    ("George Mason University",
     ["Costello College of Business", "Donald G. Costello College of Business"],
     "Donald G. Costello College of Business"),
    ("University of Florida",
     ["Florida Warrington College of Business", "Warrington College of Business"],
     "Florida Warrington College of Business"),
]


class NameQualityTests(unittest.TestCase):
    def test_every_observed_group_picks_the_school_s_own_name(self):
        for institution, names, expected in OBSERVED_GROUPS:
            best = min(names, key=lambda name: _school_name_quality(name, institution))
            self.assertEqual(expected, best, institution)

    def test_a_longer_name_wins_only_when_it_is_not_a_leaked_prefix(self):
        # Both of these are longer than their sibling; only one is more official.
        self.assertEqual("A. B. Freeman School of Business", min(
            ["Freeman School of Business", "A. B. Freeman School of Business"],
            key=lambda name: _school_name_quality(name, "Tulane University")))
        self.assertEqual("Farmer School of Business", min(
            ["Farmer School of Business", "Full-time Fully On-Campus Farmer School of Business"],
            key=lambda name: _school_name_quality(name, "Miami University")))

    def test_a_single_shared_word_is_not_an_institution_prefix(self):
        # "Stockholm School of Economics" at Stockholm School of Economics must
        # not be shortened to "School of Economics".
        cleaned, removed = _strip_school_name_noise(
            "Stockholm School of Economics", "Stockholm School of Economics")
        self.assertEqual("Stockholm School of Economics", cleaned)
        self.assertFalse(removed)

    def test_a_repeated_institution_name_is_stripped(self):
        cleaned, removed = _strip_school_name_noise(
            "University Tennessee Knoxville Haslam College of Business",
            "University of Tennessee, Knoxville")
        self.assertEqual("Haslam College of Business", cleaned)
        self.assertTrue(removed)

    def test_shouting_loses_to_normal_case(self):
        self.assertEqual("Lee Kong Chian School of Business", min(
            ["AREA LEE KONG CHIAN SCHOOL OF BUSINESS", "Lee Kong Chian School of Business"],
            key=lambda name: _school_name_quality(name, "Singapore Management University")))


class ResolverBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def institution(self, institution_id, name, normalized=None):
        self.conn.execute(
            "INSERT INTO institutions (id,official_name,normalized_name,is_current,created_at,"
            "updated_at) VALUES (?,?,?,1,?,?)",
            (institution_id, name, normalized or name.casefold(), NOW, NOW))

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
            "created_at,updated_at) VALUES (?,?,?,?,?,?, 'business_discipline','accepted','open',"
            "?,?,?,?)",
            (job_id, f"k{job_id}", "Assistant Professor", "assistant professor",
             institution_id, school_id, NOW, NOW, NOW, NOW))

    def current_school_names(self, institution_id):
        return sorted(row["official_name"] for row in self.conn.execute(
            "SELECT official_name FROM business_schools WHERE institution_id=? AND is_current=1",
            (institution_id,)))

    def counts(self):
        return tuple(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("jobs", "source_job_records", "job_sources"))

    def orphaned_jobs(self):
        return self.conn.execute("""
            SELECT COUNT(*) FROM jobs j
            LEFT JOIN business_schools bs ON bs.id=j.school_id
            LEFT JOIN institutions i ON i.id=j.institution_id
            WHERE (j.school_id IS NOT NULL AND bs.is_current=0)
               OR (j.institution_id IS NOT NULL AND i.is_current=0)
        """).fetchone()[0]


class ObservedGroupMergeTests(ResolverBase):
    def test_each_observed_group_merges_onto_the_right_survivor(self):
        for index, (institution, names, expected) in enumerate(OBSERVED_GROUPS, start=1):
            institution_id = index * 100
            self.institution(institution_id, institution,
                             normalized=f"institution-{institution_id}")
            for offset, name in enumerate(names):
                self.school(institution_id + offset + 1, institution_id, name)
            self.job(institution_id + 90, institution_id)
        self.conn.commit()
        _merge_variant_school_entities(self.conn)
        self.conn.commit()
        for index, (institution, _names, expected) in enumerate(OBSERVED_GROUPS, start=1):
            self.assertEqual([expected], self.current_school_names(index * 100), institution)


class IdempotencyTests(ResolverBase):
    """Running a resolver twice must change nothing the second time."""

    def build(self):
        self.institution(1, "Miami University")
        self.school(10, 1, "Farmer School of Business")
        self.school(11, 1, "Full-time Fully On-Campus Farmer School of Business")
        self.institution(2, "Duplicate Row", normalized="same key")
        self.institution(3, "Duplicate Row Again", normalized="same key")
        self.job(100, 1)
        self.job(101, 2)
        self.job(102, 3)
        self.conn.commit()

    def snapshot(self):
        return {
            "schools": sorted(tuple(row) for row in self.conn.execute(
                "SELECT id, institution_id, is_current FROM business_schools")),
            "institutions": sorted(tuple(row) for row in self.conn.execute(
                "SELECT id, is_current FROM institutions")),
            "jobs": sorted(tuple(row) for row in self.conn.execute(
                "SELECT id, institution_id, school_id FROM jobs")),
        }

    def test_school_variant_merge_is_idempotent(self):
        self.build()
        _merge_variant_school_entities(self.conn)
        self.conn.commit()
        first = self.snapshot()
        second_stats = _merge_variant_school_entities(self.conn)
        self.conn.commit()
        self.assertEqual(0, second_stats["merged"])
        self.assertEqual(first, self.snapshot())

    def test_institution_merge_is_idempotent(self):
        self.build()
        _merge_duplicate_institutions(self.conn)
        self.conn.commit()
        first = self.snapshot()
        second_stats = _merge_duplicate_institutions(self.conn)
        self.conn.commit()
        self.assertEqual(0, second_stats["merged"])
        self.assertEqual(first, self.snapshot())

    def test_the_school_linker_is_idempotent(self):
        self.build()
        _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        first = self.snapshot()
        _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        self.assertEqual(first, self.snapshot())

    def test_the_full_resolver_sequence_settles_after_one_pass(self):
        self.build()
        for _ in range(2):
            _merge_duplicate_institutions(self.conn)
            _merge_variant_school_entities(self.conn)
            _link_jobs_to_unique_school(self.conn)
            self.conn.commit()
        first = self.snapshot()
        _merge_duplicate_institutions(self.conn)
        _merge_variant_school_entities(self.conn)
        _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        self.assertEqual(first, self.snapshot(), "the resolvers must reach a fixed point")


class MergeInvariantTests(ResolverBase):
    """Guards that used to be checked by hand after every merge."""

    def test_no_source_row_is_lost_and_no_job_is_orphaned(self):
        self.institution(1, "Miami University")
        self.school(10, 1, "Farmer School of Business")
        self.school(11, 1, "Full-time Fully On-Campus Farmer School of Business")
        self.institution(2, "Dup", normalized="same key")
        self.institution(3, "Dup Again", normalized="same key")
        self.job(100, 1, school_id=11)
        self.job(101, 2)
        self.job(102, 3)
        self.conn.commit()
        before = self.counts()
        _merge_duplicate_institutions(self.conn)
        _merge_variant_school_entities(self.conn)
        _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        self.assertEqual(before, self.counts(), "merges must not drop jobs or source rows")
        self.assertEqual(0, self.orphaned_jobs(),
                         "no job may point at a retired school or institution")


class RecanonicalizeTests(ResolverBase):
    def test_a_wrongly_chosen_survivor_is_revived_and_the_group_re_merged(self):
        """Reproduces what the old longest-name rule did to Miami."""
        self.institution(1, "Miami University")
        self.school(10, 1, "Farmer School of Business")
        self.school(11, 1, "Full-time Fully On-Campus Farmer School of Business")
        self.job(100, 1, school_id=11)
        # Simulate the old outcome: the leaked-prefix row survived.
        self.conn.execute("UPDATE business_schools SET is_current=0 WHERE id=10")
        self.conn.execute("""
            INSERT INTO faculty_job_repair_audit (observed_at,action,job_id,old_value,new_value,reason)
            VALUES (?,'merge_variant_school_entity',NULL,'10','11','longest name rule')
        """, (NOW,))
        self.conn.commit()

        stats = _recanonicalize_merged_schools(self.conn)
        self.conn.commit()
        self.assertEqual(1, stats["recanonicalized"])
        self.assertEqual(["Farmer School of Business"], self.current_school_names(1))
        self.assertEqual(10, self.conn.execute(
            "SELECT school_id FROM jobs WHERE id=100").fetchone()["school_id"],
            "the job must follow the revived canonical row")

    def test_recanonicalization_is_idempotent(self):
        self.institution(1, "Miami University")
        self.school(10, 1, "Farmer School of Business")
        self.school(11, 1, "Full-time Fully On-Campus Farmer School of Business")
        self.conn.execute("UPDATE business_schools SET is_current=0 WHERE id=10")
        self.conn.execute("""
            INSERT INTO faculty_job_repair_audit (observed_at,action,job_id,old_value,new_value,reason)
            VALUES (?,'merge_variant_school_entity',NULL,'10','11','longest name rule')
        """, (NOW,))
        self.conn.commit()
        _recanonicalize_merged_schools(self.conn)
        self.conn.commit()
        first = self.snapshot_schools()
        _recanonicalize_merged_schools(self.conn)
        self.conn.commit()
        self.assertEqual(first, self.snapshot_schools())

    def snapshot_schools(self):
        return sorted(tuple(row) for row in self.conn.execute(
            "SELECT id, is_current FROM business_schools"))

    def test_a_group_that_became_genuinely_distinct_is_left_alone(self):
        # If a later import added a real second school, do not revive and merge.
        self.institution(1, "University of Virginia")
        self.school(10, 1, "Darden School of Business")
        self.school(11, 1, "McIntire School of Commerce")
        self.conn.execute("UPDATE business_schools SET is_current=0 WHERE id=10")
        self.conn.execute("""
            INSERT INTO faculty_job_repair_audit (observed_at,action,job_id,old_value,new_value,reason)
            VALUES (?,'merge_variant_school_entity',NULL,'10','11','earlier merge')
        """, (NOW,))
        self.conn.commit()
        stats = _recanonicalize_merged_schools(self.conn)
        self.conn.commit()
        self.assertEqual(0, stats["recanonicalized"])
        self.assertEqual(0, stats["merged"])


class DistinctSchoolTests(ResolverBase):
    def test_darden_and_mcintire_are_never_collapsed(self):
        self.institution(1, "University of Virginia")
        self.school(10, 1, "Darden School of Business")
        self.school(11, 1, "McIntire School of Commerce")
        self.conn.commit()
        self.assertIsNone(_canonical_variant_school(self.conn, 1))
        stats = _merge_variant_school_entities(self.conn)
        self.conn.commit()
        self.assertEqual(0, stats["merged"])
        self.assertEqual(2, len(self.current_school_names(1)))

    def test_three_or_more_school_families_do_not_use_generic_label_as_a_bridge(self):
        self.institution(1, "University of Virginia")
        self.school(10, 1, "Darden School of Business")
        self.school(11, 1, "Darden School of Business Administration")
        self.school(12, 1, "McIntire School of Commerce")
        self.school(13, 1, "School of Business")
        self.conn.commit()

        self.assertIsNone(_canonical_variant_school(self.conn, 1))
        stats = _merge_variant_school_entities(self.conn)
        self.conn.commit()

        self.assertEqual(1, stats["merged"])
        current = set(self.current_school_names(1))
        self.assertEqual(3, len(current))
        self.assertEqual(1, len([name for name in current if name.startswith("Darden School of Business")]))
        self.assertIn("McIntire School of Commerce", current)
        self.assertIn("School of Business", current)


class ResolverSafetyTests(ResolverBase):
    def source_job(self):
        return SourceJob(
            source="fixture", source_job_id="resolver-1", source_url="https://example.edu/job/1",
            official_url="https://example.edu/job/1", title_raw="Assistant Professor of Finance",
            institution_raw="Example University", school_raw="Former School of Business",
            captured_at=NOW, extra={},
        )

    def test_null_country_institution_resolution_is_idempotent(self):
        normalized = {
            "institution_raw": "Example University",
            "institution_entity_raw": "Example University",
            "country_code": None,
            "country": None,
            "region_group": None,
            "state_province": None,
            "city": None,
        }
        first = _institution(self.conn, dict(normalized), self.source_job())
        second = _institution(self.conn, dict(normalized), self.source_job())
        self.conn.commit()
        self.assertEqual(first, second)
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM institutions WHERE normalized_name=? AND is_current=1",
            ("example university",),
        ).fetchone()[0])

    def test_retired_school_key_is_not_reactivated_or_overwritten(self):
        self.institution(1, "Example University")
        self.school(10, 1, "Former School of Business")
        self.conn.execute(
            "UPDATE business_schools SET is_current=0,merged_into_id=NULL WHERE id=10"
        )
        self.conn.commit()

        result = _school(self.conn, 1, "Former School of Business", self.source_job())
        self.conn.commit()

        self.assertIsNone(result)
        self.assertEqual((0, None), tuple(self.conn.execute(
            "SELECT is_current,merged_into_id FROM business_schools WHERE id=10"
        ).fetchone()))
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM entity_resolution_queue WHERE entity_type='business_school' AND entity_id=10"
        ).fetchone()[0])

    def test_school_resolver_refuses_a_retired_parent_without_survivor(self):
        self.institution(1, "Retired Parent University")
        self.conn.execute(
            "UPDATE institutions SET is_current=0,merged_into_id=NULL WHERE id=1"
        )
        result = _school(self.conn, 1, "School of Business", self.source_job())
        self.conn.commit()
        self.assertIsNone(result)
        self.assertEqual(0, self.conn.execute(
            "SELECT COUNT(*) FROM business_schools WHERE institution_id=1 AND is_current=1"
        ).fetchone()[0])
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM entity_resolution_queue "
            "WHERE entity_type='institution' AND entity_id=1"
        ).fetchone()[0])

    def test_school_resolver_follows_an_explicit_current_parent_redirect(self):
        self.institution(1, "Current Parent University")
        self.institution(2, "Former Parent University")
        self.conn.execute(
            "UPDATE institutions SET is_current=0,merged_into_id=1 WHERE id=2"
        )
        school_id = _school(self.conn, 2, "School of Business", self.source_job())
        self.conn.commit()
        self.assertEqual(1, self.conn.execute(
            "SELECT institution_id FROM business_schools WHERE id=?", (school_id,)
        ).fetchone()[0])

    def test_unused_current_school_under_retired_parent_is_retired_not_deleted(self):
        self.institution(1, "Retired Parent University")
        self.school(10, 1, "Orphan School of Business")
        self.conn.execute(
            "UPDATE institutions SET is_current=0,merged_into_id=NULL WHERE id=1"
        )
        stats = _repair_current_schools_on_retired_institutions(self.conn)
        self.conn.commit()
        self.assertEqual(1, stats["retired"])
        self.assertEqual((0, None), tuple(self.conn.execute(
            "SELECT is_current,merged_into_id FROM business_schools WHERE id=10"
        ).fetchone()))

    def test_country_slash_repair_does_not_force_an_institution_identity_collision(self):
        self.institution(1, "VinUniversity", normalized="vinuniversity")
        self.conn.execute(
            "UPDATE institutions SET country='Vietnam',country_code='VN',is_current=0 WHERE id=1"
        )
        self.institution(2, "VinUniversity", normalized="vinuniversity")
        self.conn.execute(
            "UPDATE institutions SET city='Viet Nam / Hanoi' WHERE id=2"
        )
        stats = _repair_country_slash_locations(self.conn)
        self.conn.commit()
        self.assertEqual(1, stats["identity_conflicts_queued"])
        self.assertEqual((None, "Hanoi"), tuple(self.conn.execute(
            "SELECT country_code,city FROM institutions WHERE id=2"
        ).fetchone()))
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM entity_resolution_queue "
            "WHERE entity_id=2 AND match_basis='country_slash_identity_collision'"
        ).fetchone()[0])

    def test_retired_institution_key_is_released_without_reactivating_history(self):
        self.institution(20, "Retired University", normalized="retired university")
        self.conn.execute(
            "UPDATE institutions SET is_current=0,merged_into_id=NULL WHERE id=20"
        )
        self.conn.commit()
        normalized = {
            "institution_raw": "Retired University",
            "institution_entity_raw": "Retired University",
            "country_code": None,
            "country": None,
            "region_group": None,
            "state_province": None,
            "city": None,
        }

        current_id = _institution(self.conn, normalized, self.source_job())
        self.conn.commit()

        self.assertNotEqual(20, current_id)
        self.assertEqual((0, "retired university__retired_20"), tuple(self.conn.execute(
            "SELECT is_current,normalized_name FROM institutions WHERE id=20"
        ).fetchone()))
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM institutions WHERE id=? AND is_current=1", (current_id,)
        ).fetchone()[0])

    def test_redirect_cycle_is_treated_as_unresolved(self):
        self.institution(1, "Cycle A")
        self.institution(2, "Cycle B")
        self.conn.execute("UPDATE institutions SET is_current=0,merged_into_id=2 WHERE id=1")
        self.conn.execute("UPDATE institutions SET is_current=0,merged_into_id=1 WHERE id=2")
        self.conn.commit()
        self.assertIsNone(_current_entity_id(self.conn, "institutions", 1))
        self.assertIsNone(_current_entity_id(self.conn, "institutions", 2))


if __name__ == "__main__":
    unittest.main()
