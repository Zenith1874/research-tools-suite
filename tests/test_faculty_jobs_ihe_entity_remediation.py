# -*- coding: utf-8 -*-
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.repair_ihe_historical_school_entities import (
    TargetSpec,
    apply_connection,
    inspect_connection,
)
from services.faculty_jobs_normalizer import normalize_name
from services.faculty_jobs_service import (
    _resolved_posting_school_name,
    ensure_faculty_jobs_tables,
    update_faculty_jobs,
)
from services.faculty_jobs_sources.base import AdapterResponse, SourceJob
from services.faculty_jobs_sources.insidehighered import InsideHigherEdAdapter


CAPTURED_AT = "2026-08-31T00:11:33Z"
INSTITUTION = "University of Macau"
SCHOOL = "Faculty of Business Administration"
EXCERPTS = {
    "3540010": (
        "Associate/Assistant Professor in Marketing Macau, China University of Macau "
        "The Department of Management and Marketing at the Faculty of Business "
        "Administration (FBA) invites applications for the position."
    ),
    "3540011": (
        "Associate/Assistant Professor in Finance Macau, China University of Macau "
        "The Department of Finance and Business Economics (DFBE) at the Faculty of "
        "Business Administration (FBA) invites applications."
    ),
    "3540012": (
        "Associate/Assistant Professor in Microeconometrics Macau, China University "
        "of Macau The Department of Finance and Business Economics at the Faculty "
        "of Business Administration (FBA) invites applications."
    ),
}
TITLES = {
    "3540010": "Associate/Assistant Professor in Marketing",
    "3540011": "Associate/Assistant Professor in Finance",
    "3540012": "Associate/Assistant Professor in Microeconometrics",
}


class FakeIHEAdapter:
    name = "inside_higher_ed"
    adapter_name = "inside_higher_ed"
    timeout = 5
    max_pages = 1

    def __init__(self, jobs):
        self.jobs = list(jobs)

    def fetch(self):
        return AdapterResponse(
            jobs=list(self.jobs),
            pages_fetched=1,
            listing_pages=1,
            reported_total=851,
            coverage_complete=False,
        )


def source_jobs():
    return [
        SourceJob(
            source="inside_higher_ed",
            source_job_id=source_job_id,
            source_url=(
                "https://careers.insidehighered.com/job/"
                f"{source_job_id}/fixture/"
            ),
            title_raw=TITLES[source_job_id],
            institution_raw=INSTITUTION,
            school_raw=None,
            location_raw="Macau, China",
            description_excerpt=EXCERPTS[source_job_id],
            captured_at=CAPTURED_AT,
        )
        for source_job_id in ("3540010", "3540011", "3540012")
    ]


class IHEEntityResolverTests(unittest.TestCase):
    def test_macau_excerpts_use_exact_home_unit(self):
        for source_job_id, excerpt in EXCERPTS.items():
            with self.subTest(source_job_id=source_job_id):
                self.assertEqual(SCHOOL, InsideHigherEdAdapter._detail_school(excerpt))
                job = next(
                    item for item in source_jobs()
                    if item.source_job_id == source_job_id
                )
                self.assertEqual(
                    SCHOOL,
                    _resolved_posting_school_name(job, None, INSTITUTION),
                )

    def test_ihe_collaborator_text_does_not_fall_through_to_generic_parser(self):
        excerpt = (
            "The School of Medicine invites applications for an Assistant Professor. "
            "The successful candidate may collaborate with the Rotman School of Management."
        )
        job = SourceJob(
            source="inside_higher_ed",
            source_job_id="negative",
            source_url="https://careers.insidehighered.com/job/negative/",
            title_raw="Assistant Professor of Medicine",
            institution_raw="Example University",
            description_excerpt=excerpt,
        )
        self.assertIsNone(InsideHigherEdAdapter._detail_school(excerpt))
        self.assertIsNone(
            _resolved_posting_school_name(job, None, "Example University")
        )


class IHEHistoricalEntityRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "faculty_jobs.db"
        ensure_faculty_jobs_tables(self.db)
        update_faculty_jobs(
            self.db,
            source_names=["inside_higher_ed"],
            adapters=[FakeIHEAdapter(source_jobs())],
        )

    def tearDown(self):
        self.temp.cleanup()

    def _connection(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        return conn

    def _seed_s0(self):
        conn = self._connection()
        institution_id = conn.execute(
            "SELECT id FROM institutions WHERE official_name=? AND is_current=1",
            (INSTITUTION,),
        ).fetchone()[0]
        target_school_id = conn.execute(
            "SELECT id FROM business_schools WHERE institution_id=? AND normalized_name=?",
            (institution_id, normalize_name(SCHOOL)),
        ).fetchone()[0]
        now = CAPTURED_AT
        conn.execute(
            """
            INSERT INTO school_evidence
              (school_id,evidence_type,value,source_name,source_url,
               verified_at,confidence,is_current,valid_from)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                target_school_id, "AACSB", "accredited", "AACSB",
                "https://www.aacsb.edu/accredited/u/university-of-macau",
                now, "high", 1, now,
            ),
        )
        conn.execute(
            """
            INSERT INTO aacsb_directory_schools
              (directory_result_id,directory_url,institution_name,school_name,
               directory_title,roster_source_url,first_seen_at,last_seen_at,
               linked_business_school_id,active,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "umac-fixture", "https://www.aacsb.edu/accredited/u/university-of-macau",
                INSTITUTION, SCHOOL, SCHOOL,
                "https://www.aacsb.edu/accredited/u/university-of-macau",
                now, now, target_school_id, 1, now, now,
            ),
        )
        old_specs = []
        for source_job_id, old_name in (
            ("3540011", "Economics DFBE Faculty of Business Administration"),
            ("3540012", "Economics Faculty of Business Administration"),
        ):
            old_school_id = conn.execute(
                """
                INSERT INTO business_schools
                  (institution_id,official_name,normalized_name,created_at,updated_at)
                VALUES (?,?,?,?,?)
                """,
                (institution_id, old_name, normalize_name(old_name), now, now),
            ).lastrowid
            job_id = conn.execute(
                """
                SELECT j.id
                FROM jobs j JOIN job_sources js ON js.job_id=j.id
                JOIN sources s ON s.id=js.source_id
                WHERE s.name='inside_higher_ed' AND js.source_job_id=?
                """,
                (source_job_id,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE jobs SET school_id=? WHERE id=?",
                (old_school_id, job_id),
            )
            old_specs.append(TargetSpec(source_job_id, job_id, old_school_id, old_name))
        conn.execute(
            """
            INSERT INTO user_job_state
              (job_id,state,priority,saved_at,updated_at,notes)
            VALUES (?,?,?,?,?,?)
            """,
            (old_specs[0].job_id, "Saved", 1, now, now, "preserve me"),
        )
        conn.commit()
        conn.close()
        return tuple(old_specs), institution_id, target_school_id

    def test_same_source_reobservation_never_creates_contaminated_school(self):
        update_faculty_jobs(
            self.db,
            source_names=["inside_higher_ed"],
            adapters=[FakeIHEAdapter(source_jobs())],
        )
        conn = self._connection()
        rows = conn.execute(
            """
            SELECT js.source_job_id,bs.official_name,j.business_scope
            FROM jobs j
            JOIN job_sources js ON js.job_id=j.id
            JOIN sources s ON s.id=js.source_id AND s.name='inside_higher_ed'
            LEFT JOIN business_schools bs ON bs.id=j.school_id
            WHERE js.source_job_id IN ('3540010','3540011','3540012')
            ORDER BY js.source_job_id
            """
        ).fetchall()
        self.assertEqual(
            [(source_job_id, SCHOOL, "business_discipline")
             for source_job_id in ("3540010", "3540011", "3540012")],
            [tuple(row) for row in rows],
        )
        contaminated = conn.execute(
            "SELECT COUNT(*) FROM business_schools WHERE official_name LIKE 'Economics%Faculty of Business Administration'"
        ).fetchone()[0]
        self.assertEqual(0, contaminated)
        self.assertEqual(3, conn.execute(
            "SELECT COUNT(*) FROM source_job_records WHERE source_job_id IN ('3540010','3540011','3540012')"
        ).fetchone()[0])
        conn.close()

    def test_exact_repair_is_audited_idempotent_and_preserves_private_state(self):
        targets, institution_id, target_school_id = self._seed_s0()
        conn = self._connection()
        before = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("jobs", "job_sources", "source_job_records", "user_job_state")
        }
        inspection = inspect_connection(
            conn, targets,
            target_institution_id=institution_id,
            target_school_id=target_school_id,
            target_school_name=SCHOOL,
        )
        self.assertTrue(inspection["valid"], inspection["errors"])
        self.assertEqual("s0_needs_relink_and_retire", inspection["state"])
        changes = apply_connection(
            conn, inspection, targets,
            target_school_id=target_school_id,
            target_school_name=SCHOOL,
        )
        conn.commit()
        self.assertEqual(2, changes["job_relinks"])
        self.assertEqual(2, changes["entities_retired"])
        after = inspect_connection(
            conn, targets,
            target_institution_id=institution_id,
            target_school_id=target_school_id,
            target_school_name=SCHOOL,
        )
        self.assertTrue(after["valid"], after["errors"])
        self.assertEqual("already_repaired", after["state"])
        self.assertEqual(
            [target_school_id, target_school_id],
            [item["job"]["school_id"] for item in after["targets"]],
        )
        self.assertEqual(
            [(0, target_school_id), (0, target_school_id)],
            [(item["old_entity"]["is_current"], item["old_entity"]["merged_into_id"])
             for item in after["targets"]],
        )
        aliases = json.loads(conn.execute(
            "SELECT aliases_json FROM business_schools WHERE id=?",
            (target_school_id,),
        ).fetchone()[0])
        self.assertNotIn("Economics Faculty of Business Administration", aliases)
        self.assertNotIn("Economics DFBE Faculty of Business Administration", aliases)
        self.assertEqual("preserve me", conn.execute(
            "SELECT notes FROM user_job_state WHERE job_id=?",
            (targets[0].job_id,),
        ).fetchone()[0])
        for table, count in before.items():
            self.assertEqual(count, conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0])
        self.assertEqual(2, conn.execute(
            "SELECT COUNT(*) FROM faculty_job_repair_audit "
            "WHERE action='ihe_historical_school_entity_relink'"
        ).fetchone()[0])
        self.assertEqual(2, conn.execute(
            "SELECT COUNT(*) FROM faculty_job_repair_audit "
            "WHERE action='ihe_historical_school_entity_retire'"
        ).fetchone()[0])
        second = apply_connection(
            conn, after, targets,
            target_school_id=target_school_id,
            target_school_name=SCHOOL,
        )
        self.assertEqual(0, second["job_relinks"])
        self.assertEqual(0, second["entities_retired"])
        conn.close()

    def test_unexpected_third_mismatch_aborts_candidate_gate(self):
        targets, institution_id, target_school_id = self._seed_s0()
        conn = self._connection()
        control_job = conn.execute(
            """
            SELECT j.id FROM jobs j
            JOIN job_sources js ON js.job_id=j.id
            JOIN sources s ON s.id=js.source_id AND s.name='inside_higher_ed'
            WHERE js.source_job_id='3540010'
            """
        ).fetchone()[0]
        bad_control_id = conn.execute(
            """
            INSERT INTO business_schools
              (institution_id,official_name,normalized_name,created_at,updated_at)
            VALUES (?,?,?,?,?)
            """,
            (
                institution_id, "Marketing Faculty of Business Administration",
                normalize_name("Marketing Faculty of Business Administration"),
                CAPTURED_AT, CAPTURED_AT,
            ),
        ).lastrowid
        conn.execute(
            "UPDATE jobs SET school_id=? WHERE id=?", (bad_control_id, control_job)
        )
        conn.commit()
        inspection = inspect_connection(
            conn, targets,
            target_institution_id=institution_id,
            target_school_id=target_school_id,
            target_school_name=SCHOOL,
        )
        self.assertFalse(inspection["valid"])
        self.assertEqual("invalid", inspection["state"])
        self.assertTrue(any(
            "active IHE mismatch set" in error for error in inspection["errors"]
        ))
        conn.close()


if __name__ == "__main__":
    unittest.main()
