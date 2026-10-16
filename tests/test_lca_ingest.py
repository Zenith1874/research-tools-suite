# -*- coding: utf-8 -*-
"""The H-1B LCA faculty slice.

Two things are being defended here.

The first is the boundary of the category. The disclosure file is ~800k rows a
year and overwhelmingly not academic, so every rule that lets a row in has to
be justified by who made the judgement: a SOC code is the publisher's
classification of the occupation, a job title is our reading of free text.
Collapsing those would let a row in on our authority while labelling it as the
publisher's -- which is exactly what happened when the SOC-title fallback
matched the word "postsecondary" and admitted 66 rows of `11-9033 Education
Administrators, Postsecondary` as publisher-classified teachers.

The second is what a row means once admitted. An LCA is filed before an H-1B
petition. Certified is not approved, approved is not hired, and one filing can
cover several positions. Anything that reduces this table to "N international
faculty hired" is wrong, so the shape that keeps those apart is asserted.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services import lca_ingest as lca
from services.academic_market_store import ensure_tables, register_release
from services.lca_ingest import (
    BUSINESS_TEACHER_SOC, EVIDENCE_BUSINESS_SOC, EVIDENCE_POSTSECONDARY_SOC,
    EVIDENCE_TITLE, LCA_RELEASES, business_faculty_summary, classify_faculty,
    institution_profile,
)


def row(**kwargs):
    base = {"SOC_CODE": "", "SOC_TITLE": "", "JOB_TITLE": "", "EMPLOYER_NAME": ""}
    base.update(kwargs)
    return base


class ClassificationTests(unittest.TestCase):
    def test_the_business_teacher_soc_is_its_own_evidence_level(self):
        # 25-1011 is the publisher's code for exactly this market. It should
        # never be diluted into the generic postsecondary bucket.
        self.assertEqual(EVIDENCE_BUSINESS_SOC, classify_faculty(row(
            SOC_CODE="25-1011.00", SOC_TITLE="Business Teachers, Postsecondary",
            JOB_TITLE="Assistant Professor in Finance")))

    def test_another_postsecondary_code_is_faculty_but_not_business(self):
        self.assertEqual(EVIDENCE_POSTSECONDARY_SOC, classify_faculty(row(
            SOC_CODE="25-1067.00", SOC_TITLE="Sociology Teachers, Postsecondary",
            JOB_TITLE="Assistant Professor")))

    def test_an_education_administrator_is_not_publisher_classified_faculty(self):
        # The real row that motivated this: the SOC title ends in
        # "Postsecondary", but the occupation is administration.
        verdict = classify_faculty(row(
            SOC_CODE="11-9033.00", SOC_TITLE="Education Administrators, Postsecondary",
            JOB_TITLE="Associate Director for Programs and Training",
            EMPLOYER_NAME="The Leland Stanford, Jr University"))
        self.assertIsNone(verdict)

    def test_a_postsecondary_teaching_assistant_is_not_faculty(self):
        self.assertIsNone(classify_faculty(row(
            SOC_CODE="25-9044.00", SOC_TITLE="Teaching Assistants, Postsecondary",
            JOB_TITLE="Graduate Teaching Assistant")))

    def test_a_mistyped_soc_code_is_rescued_by_the_publishers_own_title(self):
        # The file really does carry 24-1124 for a row whose SOC title reads
        # "Foreign Language and Literature Teachers, Postsecondary".
        self.assertEqual(EVIDENCE_POSTSECONDARY_SOC, classify_faculty(row(
            SOC_CODE="24-1124.00",
            SOC_TITLE="Foreign Language and Literature Teachers, Postsecondary",
            JOB_TITLE="Lecturer")))

    def test_a_professorship_with_an_administrative_code_is_title_evidence(self):
        # "Professor and Department Head" is a faculty appointment the employer
        # coded as administration. Admitting it is right; claiming the
        # publisher classified it as teaching would not be.
        self.assertEqual(EVIDENCE_TITLE, classify_faculty(row(
            SOC_CODE="11-9033.00", SOC_TITLE="Education Administrators, Postsecondary",
            JOB_TITLE="Professor and Department Head",
            EMPLOYER_NAME="Mississippi State University")))

    def test_an_industry_job_that_merely_says_professor_is_not_admitted(self):
        self.assertIsNone(classify_faculty(row(
            SOC_CODE="15-1211.00", SOC_TITLE="Computer Systems Analysts",
            JOB_TITLE="Project Manager - 2 - US", EMPLOYER_NAME="INFOSYS LIMITED")))

    def test_a_faculty_support_role_is_not_a_faculty_post(self):
        self.assertIsNone(classify_faculty(row(
            SOC_CODE="43-6014.00", SOC_TITLE="Secretaries and Administrative Assistants",
            JOB_TITLE="Faculty Services Coordinator")))

    def test_every_registered_release_is_a_recorded_url_not_a_template(self):
        # The audit found NCSES and DOL both move asset paths between years, so
        # a templated URL 404s silently. Each entry must be a URL that worked.
        for year, url in LCA_RELEASES.items():
            self.assertTrue(url.startswith("https://www.dol.gov/"), url)
            self.assertIn(str(year), url, "the release key should name its year")
            self.assertTrue(url.endswith(".xlsx"), url)


class ShapeTests(unittest.TestCase):
    """What the stored rows have to keep separate."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.dir.name) / "market.db"
        self.conn = sqlite3.connect(str(self.db))
        self.conn.row_factory = sqlite3.Row
        ensure_tables(self.conn)
        self.release = register_release(
            self.conn, "dol_lca", "LCA_FY2024", "https://example.test/LCA.xlsx",
            data_year=2024, status="downloaded")

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add(self, case, employer, **kwargs):
        fields = {"fiscal_year": 2024, "case_status": "Certified",
                  "prevailing_wage": 120000.0,
                  "soc_code": BUSINESS_TEACHER_SOC + ".00",
                  "job_title": "Assistant Professor of Finance",
                  "total_worker_positions": 1, "new_employment": 1,
                  "continued_employment": 0, "change_employer": 0,
                  "wage_from": 165000.0, "wage_unit": "Year",
                  "faculty_evidence": EVIDENCE_BUSINESS_SOC}
        fields.update(kwargs)
        columns = ", ".join(["case_number", "employer_name", *fields, "release_id"])
        marks = ",".join("?" * (len(fields) + 3))
        self.conn.execute(
            f"INSERT INTO lca_faculty_cases ({columns}) VALUES ({marks})",
            (case, employer, *fields.values(), self.release))

    def test_positions_are_counted_separately_from_filings(self):
        # One filing covering three positions is one filing and three
        # positions. Reporting either number as the other overstates or
        # understates by exactly the amount that matters.
        self.add("A-1", "Example University", total_worker_positions=3)
        self.add("A-2", "Example University", total_worker_positions=1)
        self.conn.commit()
        profile = institution_profile(self.conn, "Example University")
        year = profile["years"][0]
        self.assertEqual(2, year["cases"])
        self.assertEqual(4, year["positions"])

    def test_new_hiring_is_reported_apart_from_continuations(self):
        # A school with continuations and no new filings is not currently
        # going to the international market.
        self.add("B-1", "Quiet College", new_employment=0, continued_employment=1)
        self.add("B-2", "Quiet College", new_employment=0, continued_employment=1)
        self.conn.commit()
        year = institution_profile(self.conn, "Quiet College")["years"][0]
        self.assertEqual(2, year["cases"])
        self.assertEqual(0, year["new_employment"],
                         "continuations must not be counted as new hiring")
        self.assertEqual(2, year["continued"])

    def test_the_profile_says_a_filing_is_not_a_hire(self):
        self.add("C-1", "Example University")
        self.conn.commit()
        caveat = institution_profile(self.conn, "Example University")["caveat"]
        self.assertIn("not an approved H-1B", caveat)
        self.assertIn("not a hire", caveat)

    def test_a_keyed_in_extra_digit_does_not_move_the_reported_wage(self):
        # The real row: Kent State filed one assistant professorship four times
        # at $81,553 and once at $8,155,283, against a prevailing wage of
        # $52,397. The mean reported that institution at $1.24m.
        for n in range(4):
            self.add(f"E-{n}", "Kent State University", wage_from=81553.0,
                     prevailing_wage=52397.0)
        self.add("E-bad", "Kent State University", wage_from=8155283.0,
                 prevailing_wage=52397.0)
        self.conn.commit()
        wages = institution_profile(self.conn, "Kent State University")["wages"]
        self.assertEqual(81553, wages["median_annual_wage"])
        self.assertEqual(1, wages["wage_rows_excluded"])
        self.assertEqual(4, wages["wage_rows_used"])

    def test_an_excluded_row_is_named_not_silently_dropped(self):
        self.add("F-1", "Example University", wage_from=95000.0, prevailing_wage=90000.0)
        self.add("F-bad", "Example University", wage_from=9500000.0, prevailing_wage=90000.0)
        self.conn.commit()
        wages = institution_profile(self.conn, "Example University")["wages"]
        excluded = wages["excluded_examples"]
        self.assertEqual(1, len(excluded))
        self.assertEqual("F-bad", excluded[0]["case_number"])
        self.assertIn("keying errors", wages["wage_note"])

    def test_a_high_wage_that_the_form_itself_supports_is_kept(self):
        # A $273,000 finance professorship is real. The threshold is anchored
        # to the prevailing wage on the same filing, not to a guess about what
        # a professor should earn.
        self.add("G-1", "Rich Business School", wage_from=273000.0,
                 prevailing_wage=180000.0)
        self.conn.commit()
        wages = institution_profile(self.conn, "Rich Business School")["wages"]
        self.assertEqual(273000, wages["median_annual_wage"])
        self.assertEqual(0, wages["wage_rows_excluded"])

    def test_a_non_annual_filing_is_excluded_rather_than_converted(self):
        # The file carries annual amounts entered under an hourly unit, so
        # multiplying by 2080 would turn one keying error into a salary.
        self.add("H-1", "Hourly College", wage_from=80000.0, wage_unit="Hour",
                 prevailing_wage=60.0)
        self.conn.commit()
        wages = institution_profile(self.conn, "Hourly College")["wages"]
        self.assertIsNone(wages["median_annual_wage"])
        self.assertEqual(0, wages["wage_rows_used"])
        self.assertIn("not converted", wages["wage_note"])

    def test_a_withdrawn_filing_is_counted_apart_from_a_certified_one(self):
        # "Certified - Withdrawn" is the employer taking the filing back. 202
        # of 803 business-faculty rows are withdrawn, so folding them into
        # "certified" would overstate by a quarter.
        self.add("I-1", "Split University", case_status="Certified")
        self.add("I-2", "Split University", case_status="Certified - Withdrawn")
        self.add("I-3", "Split University", case_status="Withdrawn")
        self.add("I-4", "Split University", case_status="Denied")
        self.conn.commit()
        year = institution_profile(self.conn, "Split University")["years"][0]
        self.assertEqual(4, year["cases"])
        self.assertEqual(1, year["certified"], "only an un-withdrawn Certified counts")
        self.assertEqual(2, year["withdrawn"])
        self.assertEqual(1, year["denied"])

    def test_the_business_summary_counts_only_the_publishers_business_code(self):
        self.add("D-1", "Business School U")
        self.add("D-2", "Med School U", soc_code="25-1071.00",
                 job_title="Assistant Professor of Medicine",
                 faculty_evidence=EVIDENCE_POSTSECONDARY_SOC)
        self.conn.commit()
        summary = business_faculty_summary(self.conn, 2024)
        self.assertEqual(1, summary["totals"]["cases"])
        self.assertEqual(["Business School U"],
                         [row["employer_name"] for row in summary["top_employers"]])
        self.assertIn("floors", summary["caveat"],
                      "a code-restricted count is a floor, and must say so")


if __name__ == "__main__":
    unittest.main()


class ReloadTests(unittest.TestCase):
    """Re-reading a release must not undo institution matching.

    `institution_id` is resolved after loading, by matching employer names
    against the whole faculty database -- 7,885 of 11,763 cases carry one. The
    release file knows nothing about it, so a re-load that wrote the column
    would blank every resolved case, and the damage would look like the matcher
    having regressed rather than the loader having overwritten its work.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.conn = sqlite3.connect(str(Path(self.dir.name) / "market.db"))
        self.conn.row_factory = sqlite3.Row
        ensure_tables(self.conn)
        self.release = register_release(
            self.conn, "dol_lca", "LCA_FY2024", "https://example.test/LCA.xlsx",
            data_year=2024, status="downloaded")

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def values(self, case, **over):
        row = {name: None for name in lca.UPSERT_COLUMNS}
        row.update({"fiscal_year": 2024, "case_status": "Certified",
                    "decision_date": "2024-06-01", "employer_name": "Example University",
                    "job_title": "Assistant Professor", "soc_code": "25-1011.00",
                    "faculty_evidence": lca.EVIDENCE_BUSINESS_SOC,
                    "release_id": self.release})
        row.update(over)
        return (case, *[row[name] for name in lca.UPSERT_COLUMNS])

    def test_the_release_never_supplies_the_matched_institution(self):
        self.assertNotIn("institution_id", lca.UPSERT_COLUMNS)
        self.assertNotIn("institution_id", lca.upsert_sql())
        self.assertIn("institution_id", lca.PRESERVED_ON_RELOAD)

    def test_a_later_decision_supersedes_but_keeps_the_matched_institution(self):
        self.conn.execute(lca.upsert_sql(), self.values("I-1"))
        self.conn.execute(
            "UPDATE lca_faculty_cases SET institution_id = 4242 WHERE case_number='I-1'")
        self.conn.commit()
        # The next annual file carries the same case, later, as withdrawn.
        self.conn.execute(lca.upsert_sql(), self.values(
            "I-1", decision_date="2025-02-01", case_status="Certified - Withdrawn",
            fiscal_year=2025))
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM lca_faculty_cases WHERE case_number='I-1'").fetchone()
        self.assertEqual("Certified - Withdrawn", row["case_status"],
                         "the later decision is the current state")
        self.assertEqual(4242, row["institution_id"],
                         "matching survives the re-read")

    def test_an_earlier_decision_does_not_overwrite_a_later_one(self):
        # Loading the years out of order must not resurrect a certification
        # that was later withdrawn.
        self.conn.execute(lca.upsert_sql(), self.values(
            "I-2", decision_date="2025-02-01", case_status="Certified - Withdrawn"))
        self.conn.commit()
        self.conn.execute(lca.upsert_sql(), self.values(
            "I-2", decision_date="2024-06-01", case_status="Certified"))
        self.conn.commit()
        row = self.conn.execute(
            "SELECT case_status FROM lca_faculty_cases WHERE case_number='I-2'").fetchone()
        self.assertEqual("Certified - Withdrawn", row["case_status"])

    def test_the_statement_binds_exactly_the_columns_it_names(self):
        sql = lca.upsert_sql()
        self.assertEqual(len(lca.UPSERT_COLUMNS) + 1, sql.count("?"),
                         "a placeholder count that drifts from the column list "
                         "silently shifts every value one position")
