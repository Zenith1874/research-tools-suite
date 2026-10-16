# -*- coding: utf-8 -*-
"""Location adopted from the institution when the posting carried none.

Some boards publish no location column at all -- the POMS table is Position /
University / Date -- so 411 jobs rendered as a bare "United States". The school's
city is already observed in this database from other sources. Adopting it is
entity-level evidence, and has to stay labelled as such.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import (
    _backfill_job_location_from_entity,
    _plausible_city,
    _repair_institution_city_labels,
    ensure_faculty_jobs_tables,
)


class PlausibleCityTests(unittest.TestCase):
    def test_real_cities_pass(self):
        for value in ("New Orleans", "Dallas", "Los Angeles", "Rotterdam"):
            self.assertEqual(value, _plausible_city(value))

    def test_leaked_form_labels_are_stripped(self):
        self.assertEqual("Ontario", _plausible_city("Location Ontario"))
        self.assertEqual("Quebec", _plausible_city("Location Quebec"))

    def test_street_addresses_are_rejected(self):
        # EURAXESS cards put the campus address where the city belongs.
        for value in ("Mekelweg 5", "Princetonlaan 8a", "Drienerlolaan 5"):
            self.assertIsNone(_plausible_city(value), value)

    def test_form_fragments_are_rejected(self):
        self.assertIsNone(_plausible_city("Work Locations: Number of offers: 1"))
        self.assertIsNone(_plausible_city("Apply by deadline"))

    def test_organization_and_prose_fragments_are_rejected(self):
        for value in (
            "Haslam College of Business",
            "College of Osteopathic Medicine",
            "located within the Howard H. Baker",
        ):
            self.assertIsNone(_plausible_city(value), value)
        # This is a real Pennsylvania locality, not an organization-of phrase.
        self.assertEqual("University Park", _plausible_city("University Park"))

    def test_a_country_is_not_a_city(self):
        self.assertIsNone(_plausible_city("Location United States"))
        self.assertIsNone(_plausible_city("Canada"))

    def test_genuine_city_states_survive(self):
        # Here the name really is both, so rejecting it would lose a real city.
        self.assertEqual("Singapore", _plausible_city("Singapore"))
        self.assertEqual("Luxembourg", _plausible_city("Luxembourg"))

    def test_empty_and_none(self):
        self.assertIsNone(_plausible_city(""))
        self.assertIsNone(_plausible_city(None))


class EntityLocationTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        now = "2026-08-26T00:00:00Z"
        # Two records for one school: one located, one bare -- exactly the shape
        # that left a POMS job with no location.
        self.conn.execute(
            "INSERT INTO institutions (id,official_name,normalized_name,city,state_province,"
            "country,country_code,is_current,created_at,updated_at) VALUES "
            "(1,'Tulane University','tulane university','New Orleans','LA','United States','US',1,?,?)",
            (now, now))
        self.conn.execute(
            "INSERT INTO institutions (id,official_name,normalized_name,is_current,created_at,updated_at) "
            "VALUES (2,'Tulane University','tulane university',1,?,?)", (now, now))
        self.conn.execute(
            "INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,institution_id,status,"
            "first_seen_at,last_seen_at,created_at,updated_at) VALUES "
            "(1,'k1','Assistant Professor in IS','assistant professor in is',2,'open',?,?,?,?)",
            (now, now, now, now))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def job(self):
        return self.conn.execute(
            "SELECT city, state_province, country_code, location_evidence FROM jobs WHERE id=1"
        ).fetchone()

    def test_location_is_adopted_from_the_matching_institution_record(self):
        stats = _backfill_job_location_from_entity(self.conn)
        self.conn.commit()
        self.assertEqual(1, stats["from_institution"])
        row = self.job()
        self.assertEqual("New Orleans", row["city"])
        self.assertEqual("LA", row["state_province"])
        self.assertEqual("US", row["country_code"])

    def test_adopted_location_is_labelled_as_entity_evidence(self):
        _backfill_job_location_from_entity(self.conn)
        self.conn.commit()
        self.assertEqual("institution_entity", self.job()["location_evidence"],
                         "a derived city must not read as something the posting said")

    def test_a_posting_level_location_is_never_overwritten(self):
        self.conn.execute("UPDATE jobs SET city='Metairie', location_evidence='location_raw' WHERE id=1")
        self.conn.commit()
        stats = _backfill_job_location_from_entity(self.conn)
        self.conn.commit()
        self.assertEqual(0, stats["from_institution"])
        row = self.job()
        self.assertEqual("Metairie", row["city"])
        self.assertEqual("location_raw", row["location_evidence"])

    def test_an_implausible_institution_city_is_not_adopted(self):
        self.conn.execute("UPDATE institutions SET city='Mekelweg 5', state_province=NULL WHERE id=1")
        self.conn.commit()
        stats = _backfill_job_location_from_entity(self.conn)
        self.conn.commit()
        self.assertEqual(0, stats["from_institution"])
        self.assertIsNone(self.job()["city"])

    def test_an_organization_label_is_not_adopted_as_a_city(self):
        self.conn.execute(
            "UPDATE institutions SET city='College of Osteopathic Medicine', "
            "state_province=NULL WHERE id=1"
        )
        self.conn.commit()
        stats = _backfill_job_location_from_entity(self.conn)
        self.conn.commit()
        self.assertEqual(0, stats["from_institution"])
        self.assertIsNone(self.job()["city"])

    def test_the_aacsb_roster_is_the_fallback(self):
        self.conn.execute("DELETE FROM institutions WHERE id=1")
        self.conn.execute(
            "INSERT INTO aacsb_directory_schools (directory_result_id,directory_url,"
            "institution_name,directory_title,roster_source_url,first_seen_at,last_seen_at,"
            "city,state_province,country,active,created_at,updated_at) "
            "VALUES ('r1','http://x','Tulane University','Tulane University',"
            "'http://roster',?,?,'New Orleans','LA','United States',1,?,?)",
            ("2026-08-26T00:00:00Z",) * 4)
        self.conn.commit()
        stats = _backfill_job_location_from_entity(self.conn)
        self.conn.commit()
        self.assertEqual(1, stats["from_aacsb_roster"])
        self.assertEqual("aacsb_roster", self.job()["location_evidence"])

    def test_a_reingested_job_does_not_lose_its_adopted_location(self):
        """The one-shot migration was not enough.

        A job rewritten from source values on the next update loses the adopted
        city, so the fallback runs at the end of every update_faculty_jobs pass.
        This asserts the operation is idempotent and re-fills after a wipe.
        """
        _backfill_job_location_from_entity(self.conn)
        self.conn.commit()
        self.assertEqual("New Orleans", self.job()["city"])
        # Simulate the re-ingest that overwrote it in production.
        self.conn.execute(
            "UPDATE jobs SET city=NULL, state_province=NULL, "
            "location_evidence='institution_entity' WHERE id=1")
        self.conn.commit()
        stats = _backfill_job_location_from_entity(self.conn)
        self.conn.commit()
        self.assertEqual(1, stats["from_institution"])
        self.assertEqual("New Orleans", self.job()["city"])

    def test_running_twice_changes_nothing_the_second_time(self):
        _backfill_job_location_from_entity(self.conn)
        self.conn.commit()
        second = _backfill_job_location_from_entity(self.conn)
        self.conn.commit()
        self.assertEqual(0, second["considered"], "a filled job is no longer a candidate")

    def test_nothing_is_invented_when_no_evidence_exists(self):
        self.conn.execute("DELETE FROM institutions WHERE id=1")
        self.conn.commit()
        stats = _backfill_job_location_from_entity(self.conn)
        self.conn.commit()
        self.assertEqual(0, stats["from_institution"] + stats["from_aacsb_roster"])
        self.assertIsNone(self.job()["city"])


class InstitutionLabelRepairTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add(self, institution_id, city, country_code="CA"):
        now = "2026-08-26T00:00:00Z"
        self.conn.execute(
            "INSERT INTO institutions (id,official_name,normalized_name,city,country_code,"
            "is_current,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?)",
            (institution_id, f"School {institution_id}", f"school {institution_id}",
             city, country_code, now, now))

    def test_a_province_label_moves_to_state_province(self):
        self.add(1, "Location Ontario")
        self.conn.commit()
        stats = _repair_institution_city_labels(self.conn)
        self.conn.commit()
        self.assertEqual(1, stats["moved_to_state"])
        row = self.conn.execute("SELECT city, state_province FROM institutions WHERE id=1").fetchone()
        self.assertIsNone(row["city"], "a province is not a city")
        self.assertEqual("ON", row["state_province"])

    def test_parser_artifacts_are_dropped(self):
        self.add(2, "Work Locations: Number of offers: 1")
        self.conn.commit()
        stats = _repair_institution_city_labels(self.conn)
        self.conn.commit()
        self.assertEqual(1, stats["dropped"])
        self.assertIsNone(
            self.conn.execute("SELECT city FROM institutions WHERE id=2").fetchone()["city"])

    def test_a_clean_city_is_left_alone(self):
        self.add(3, "Toronto")
        self.conn.commit()
        stats = _repair_institution_city_labels(self.conn)
        self.conn.commit()
        self.assertEqual({"cleaned": 0, "moved_to_state": 0, "dropped": 0}, stats)
        self.assertEqual(
            "Toronto",
            self.conn.execute("SELECT city FROM institutions WHERE id=3").fetchone()["city"])


if __name__ == "__main__":
    unittest.main()
