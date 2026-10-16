# -*- coding: utf-8 -*-
"""IPEDS, SED and PERM: the loaders, and the distinctions they must preserve.

Each of these files has one shape that quietly produces wrong numbers, and
each is covered here because each was actually hit while building the loaders:

* IPEDS ships UTF-8 **with a BOM**, so the first column reads as ``﻿UNITID``
  and a loader that does not decode ``utf-8-sig`` skips every row while
  reporting success;
* SED repeats row labels inside per-sex subsections, so a key without the
  section lets the female block overwrite the national figure;
* DOL writes dates as Excel serials, so a "latest sponsorship" of ``45454``
  looks like data rather than a bug.
"""

import io
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

from services import academic_market_store as store
from services import ipeds_ingest as ipeds
from services import perm_ingest as perm
from services import sed_ingest as sed


def _completions_zip(path, *, with_bom=True):
    """A minimal Completions file, BOM included as the real one has it."""
    header = "UNITID,CIPCODE,MAJORNUM,AWLEVEL,CTOTALT,CTOTALM,CTOTALW,CNRALT"
    rows = [
        "100001,52.0201,1,17,40,20,20,12",   # business research doctorate
        "100001,52.1003,1,17,6,3,3,2",       # organizational behaviour
        "100002,52.0201,1,17,300,150,150,20",  # a large online producer
        "100001,52.0201,1,18,9,4,5,1",       # professional doctorate: excluded
        "100001,14.0101,1,17,25,12,13,8",    # engineering: excluded
    ]
    text = "\n".join([header, *rows])
    payload = ("﻿" + text if with_bom else text).encode("utf-8")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("c2023_a.csv", payload)
    return path


def _hd_zip(path):
    header = "UNITID,INSTNM,STABBR,CONTROL,C21BASIC,WEBADDR"
    rows = [
        "100001,Example Research University,NM,1,15,www.example.edu",
        "100002,Example Online University,AZ,3,17,www.online.example",
    ]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("hd2023.csv",
                         ("﻿" + "\n".join([header, *rows])).encode("utf-8"))
    return path


class _StoreFixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.dir.name)
        self.conn = store.ensure_tables(store.connect(self.root / "market.db"))

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()


class IpedsTests(_StoreFixture):
    def load(self):
        releases = self.root / "releases" / "ipeds"
        releases.mkdir(parents=True, exist_ok=True)
        _completions_zip(releases / "C2023_A.zip")
        _hd_zip(releases / "HD2023.zip")
        original = ipeds.download
        ipeds.download = lambda url, destination: (Path(destination), 200)
        try:
            ipeds.load_crosswalk(self.conn)
            completions = ipeds.load_completions(
                self.conn, 2023, download_root=self.root / "releases")
            ipeds.load_institutions(self.conn, 2023,
                                    download_root=self.root / "releases")
        finally:
            ipeds.download = original
        return completions

    def test_a_bom_does_not_silently_drop_every_row(self):
        # The failure mode: every column reads fine except the first, so the
        # loader reports success and writes nothing.
        result = self.load()
        self.assertEqual(3, result["rows_written"],
                         "three CIP-52 research doctorate rows were in the file")

    def test_only_research_doctorates_in_the_business_series_are_kept(self):
        self.load()
        levels = {row[0] for row in self.conn.execute(
            "SELECT DISTINCT awlevel FROM ipeds_completions")}
        self.assertEqual({17}, levels, "AWLEVEL 18 is a professional doctorate")
        series = {row[0][:2] for row in self.conn.execute(
            "SELECT DISTINCT cipcode FROM ipeds_completions")}
        self.assertEqual({"52"}, series)

    def test_reloading_the_same_year_updates_rather_than_duplicates(self):
        self.load()
        first = self.conn.execute("SELECT COUNT(*) FROM ipeds_completions").fetchone()[0]
        self.load()
        self.assertEqual(first, self.conn.execute(
            "SELECT COUNT(*) FROM ipeds_completions").fetchone()[0])

    def test_broad_production_and_the_r1_proxy_are_named_differently(self):
        # The distinction the audit turned on: 4,201 nationally against 1,460
        # at R1, and neither is a candidate pool.
        self.load()
        broad = ipeds.doctoral_production(self.conn, 2023)
        proxy = ipeds.doctoral_production(self.conn, 2023, carnegie=(ipeds.CARNEGIE_R1,))
        self.assertEqual("broad_doctoral_production", broad["measure"])
        self.assertEqual("research_academic_proxy", proxy["measure"])
        self.assertEqual(346, broad["total_doctorates"])
        self.assertEqual(46, proxy["total_doctorates"],
                         "only the R1 institution's rows")
        self.assertIn("not a job-market candidate pool", broad["caveat"])

    def test_the_general_bucket_is_marked_as_unsplittable(self):
        ipeds.load_crosswalk(self.conn)
        row = self.conn.execute(
            "SELECT narrow_field, notes FROM business_cip_crosswalk WHERE cip_code='52.0201'"
        ).fetchone()
        self.assertIsNone(row["narrow_field"])
        self.assertIn("never be attributed", row["notes"])

    def test_a_failed_load_is_recorded_rather_than_returning_zero(self):
        original = ipeds.download

        def failing(url, destination):
            raise IOError("404 from the data centre")

        ipeds.download = failing
        try:
            with self.assertRaises(IOError):
                ipeds.load_completions(self.conn, 1999,
                                       download_root=self.root / "releases")
        finally:
            ipeds.download = original
        row = self.conn.execute(
            "SELECT status, error FROM ingest_events ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual("failed", row["status"])
        self.assertIn("404", row["error"])


class SedTests(_StoreFixture):
    def test_a_repeated_label_in_a_sex_subsection_does_not_overwrite_the_national_figure(self):
        # Table 8-16 lists "Temporary visa holder" three times: overall, male,
        # female. Without the section in the key the last one wins and the
        # national share silently becomes the female share.
        rows = [
            ["Table 8-16"],
            ["Business research doctorate recipients"],
            ["(Number and percent)"],
            ["Characteristic", "All business fields"],
            ["All doctorate recipients (number)", "1510"],
            ["Temporary visa holder", "49.1"],
            ["Male doctorate recipients (number)", "822"],
            ["Temporary visa holder", "49.5"],
            ["Female doctorate recipients (number)", "688"],
            ["Temporary visa holder", "48.7"],
        ]
        self._load_rows(rows, "8-16")
        values = {row["section"]: row["value"] for row in self.conn.execute(
            "SELECT section, value FROM sed_observations "
            "WHERE characteristic='Temporary visa holder'")}
        self.assertEqual({"all": 49.1, "male": 49.5, "female": 48.7}, values)

    def test_the_sex_breakdown_rows_are_not_mistaken_for_section_headers(self):
        # "Male" and "Female" also appear as values under a "Sex (%)" heading.
        # Treating those as openers moves the national figures into a per-sex
        # section, where a national lookup finds nothing.
        rows = [
            ["Table 8-16"], ["Business"], ["(percent)"],
            ["Characteristic", "All business fields"],
            ["Sex (%)"],
            ["Male", "54.4"],
            ["Female", "45.6"],
            ["Temporary visa holder", "49.1"],
        ]
        self._load_rows(rows, "8-16")
        row = self.conn.execute(
            "SELECT section FROM sed_observations "
            "WHERE characteristic='Temporary visa holder'").fetchone()
        self.assertEqual("all", row["section"])

    def test_a_suppressed_cell_is_not_stored_as_zero(self):
        rows = [
            ["Table 9-16"], ["Business"], ["(percent)"],
            ["Characteristic", "All business fields"],
            ["Government", "D"],
            ["Industry", "14.2"],
        ]
        self._load_rows(rows, "9-16")
        stored = {row["characteristic"]: (row["value"], row["value_kind"])
                  for row in self.conn.execute(
                      "SELECT characteristic, value, value_kind FROM sed_observations")}
        self.assertEqual((None, "suppressed"), stored["Government"])
        self.assertEqual(14.2, stored["Industry"][0])

    def _load_rows(self, rows, table_number):
        """Write rows into the store the way load_year would."""
        release_id = store.register_release(
            self.conn, store.DATASET_SED_TABLES, f"test-{table_number}",
            "https://example.test/tables.zip", data_year=2023)
        section = "all"
        columns = rows[3][1:]
        for row in rows[4:]:
            characteristic = row[0]
            opener = sed._SECTION_RE.match(characteristic)
            if opener:
                section = opener.group(1).strip().casefold()
            for offset, column in enumerate(columns, start=1):
                if offset >= len(row):
                    continue
                value, kind = sed._numeric(row[offset])
                if kind in {"text", "missing"}:
                    continue
                self.conn.execute("""
                    INSERT INTO sed_observations
                      (data_year, table_number, table_title, section, characteristic,
                       column_label, value, value_kind, release_id)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (2023, table_number, rows[0][0], section, characteristic,
                      column, value, kind, release_id))
        self.conn.commit()

    def test_the_outcome_estimate_refuses_to_be_called_a_supply(self):
        benchmark_keys = sed.business_benchmark(self.conn, 2023)
        self.assertIn("realized_tt_outcomes_est", benchmark_keys)
        self.assertNotIn("candidate_supply", benchmark_keys)
        self.assertIn("never be presented as candidate supply",
                      benchmark_keys["not_a_candidate_supply"])


class PermTests(_StoreFixture):
    def test_the_forms_own_flag_beats_a_title_guess(self):
        row = {"APP_FOR_COLLEGE_U_TEACHER": "Y", "JOB_TITLE": "Research Scientist",
               "PW_SOC_TITLE": "Physicists"}
        self.assertEqual((True, perm.EVIDENCE_FORM_FLAG), perm.classify_faculty(row))

    def test_a_title_match_is_recorded_as_the_weaker_evidence(self):
        row = {"APP_FOR_COLLEGE_U_TEACHER": "N", "JOB_TITLE": "Assistant Professor",
               "PW_SOC_TITLE": "Managers, All Other"}
        self.assertEqual((True, perm.EVIDENCE_TITLE), perm.classify_faculty(row))

    def test_a_non_academic_case_is_not_faculty(self):
        row = {"APP_FOR_COLLEGE_U_TEACHER": "N", "JOB_TITLE": "Software Engineer",
               "PW_SOC_TITLE": "Software Developers"}
        self.assertEqual((False, None), perm.classify_faculty(row))

    def test_fields_are_multi_label(self):
        fields = perm.classify_business_fields(
            {"JOB_TITLE": "Assistant Professor of Information Systems and Operations "
                          "Management"})
        self.assertIn("Information Systems", fields)
        self.assertIn("Operations", fields)

    def test_a_specific_field_displaces_the_general_bucket(self):
        fields = perm.classify_business_fields(
            {"JOB_TITLE": "Assistant Professor of Business Analytics"})
        self.assertIn("Business Analytics", fields)
        self.assertNotIn("General Business", fields)

    def test_a_non_business_faculty_case_gets_no_business_field(self):
        self.assertEqual([], perm.classify_business_fields(
            {"JOB_TITLE": "Assistant Professor of Medieval History"}))

    def test_excel_serial_dates_become_real_dates(self):
        # "latest sponsorship: 45454" is a bug that looks like data.
        self.assertEqual("2024-06-11", perm._excel_date("45454"))
        self.assertEqual("2024-06-12", perm._excel_date("2024-06-12"))
        self.assertIsNone(perm._excel_date(""))
        self.assertIsNone(perm._excel_date("0"))

    def test_an_institution_with_no_cases_is_not_reported_as_not_sponsoring(self):
        profile = perm.institution_profile(self.conn, "%NOWHERE STATE%")
        self.assertEqual(0, profile["faculty_perm_cases"])
        self.assertIn("not evidence the employer does not sponsor", profile["caveat"])

    def test_the_profile_says_it_is_history_not_a_job_level_claim(self):
        release_id = store.register_release(
            self.conn, store.DATASET_PERM, "test", "https://example.test/perm.xlsx",
            data_year=2024)
        self.conn.execute("""
            INSERT INTO perm_faculty_cases
              (case_number, fiscal_year, decision_date, case_status, employer_name,
               job_title, college_teacher_flag, faculty_evidence, release_id)
            VALUES ('A-1',2024,'2024-06-11','Certified','EXAMPLE UNIVERSITY',
                    'Assistant Professor of Finance','Y',?,?)
        """, (perm.EVIDENCE_FORM_FLAG, release_id))
        self.conn.commit()
        profile = perm.institution_profile(self.conn, "%EXAMPLE UNIVERSITY%")
        self.assertEqual(1, profile["faculty_perm_cases"])
        self.assertEqual("historical institutional sponsorship evidence", profile["claim"])
        self.assertIn("not a statement about any particular job", profile["caveat"])

    def test_mobility_flows_declare_their_bias(self):
        flows = perm.mobility_flows(self.conn)
        self.assertEqual("PERM applicants only", flows["population"])
        self.assertIn("EB-1B", flows["caveat"])


class RegistryTests(_StoreFixture):
    def test_a_release_records_the_url_and_the_hash_of_what_arrived(self):
        path = self.root / "file.zip"
        path.write_bytes(b"payload")
        release_id = store.register_release(
            self.conn, "ipeds_completions", "C2023_A",
            "https://example.test/C2023_A.zip", data_year=2023, local_path=path)
        row = self.conn.execute(
            "SELECT source_url, sha256, byte_size FROM source_releases WHERE id=?",
            (release_id,)).fetchone()
        self.assertEqual("https://example.test/C2023_A.zip", row["source_url"])
        self.assertEqual(7, row["byte_size"])
        self.assertEqual(64, len(row["sha256"]))

    def test_re_registering_updates_in_place(self):
        for _ in range(2):
            store.register_release(self.conn, "ipeds_hd", "HD2023",
                                   "https://example.test/HD2023.zip", data_year=2023)
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM source_releases WHERE release_key='HD2023'").fetchone()[0])


if __name__ == "__main__":
    unittest.main()


class PermColumnContractTests(unittest.TestCase):
    """A release that renames its columns must fail, not load blanks.

    DOL renamed 150 of 155 PERM columns for FY2025 -- EMPLOYER_NAME became
    EMP_BUSINESS_NAME. The loader read by literal name, found nothing, and
    wrote 2,458 faculty cases with an empty employer: one distinct employer for
    the entire year. Every row was present, every row was worthless, and
    nothing anywhere said so.
    """

    FY2024 = ["CASE_NUMBER", "CASE_STATUS", "DECISION_DATE", "EMPLOYER_NAME",
              "EMPLOYER_STATE_PROVINCE", "JOB_TITLE", "PW_SOC_CODE", "PW_SOC_TITLE",
              "APP_FOR_COLLEGE_U_TEACHER", "COMPETITIVE_PROCESS", "PW_WAGE",
              "PW_UNIT_OF_PAY", "COUNTRY_OF_CITIZENSHIP", "CLASS_OF_ADMISSION",
              "FOREIGN_WORKER_INST_OF_ED", "FOREIGN_WORKER_INFO_MAJOR"]
    FY2025 = ["CASE_NUMBER", "CASE_STATUS", "DECISION_DATE", "EMP_BUSINESS_NAME",
              "EMP_STATE", "JOB_TITLE", "PWD_SOC_CODE", "PWD_SOC_TITLE",
              "JOB_OPP_WAGE_FROM", "JOB_OPP_WAGE_PER", "OCCUPATION_TYPE"]

    def test_the_old_layout_resolves_completely(self):
        resolved, missing = perm.resolve_columns(self.FY2024)
        self.assertEqual([], missing)
        self.assertEqual("EMPLOYER_NAME", resolved["employer_name"])

    def test_the_renamed_layout_resolves_to_the_new_names(self):
        resolved, _missing = perm.resolve_columns(self.FY2025)
        self.assertEqual("EMP_BUSINESS_NAME", resolved["employer_name"])
        self.assertEqual("PWD_SOC_CODE", resolved["soc_code"])
        self.assertEqual("EMP_STATE", resolved["employer_state"])

    def test_a_release_missing_the_employer_is_refused(self):
        # The actual failure: without this the loader wrote 2,458 blank rows.
        header = [c for c in self.FY2025 if c != "EMP_BUSINESS_NAME"]
        with self.assertRaises(perm.PermSchemaChanged) as caught:
            perm.check_contract(header, 2025)
        message = str(caught.exception)
        self.assertIn("employer_name", message)
        self.assertIn("EMP_BUSINESS_NAME", message,
                      "the error should name the rename that has happened before")

    def test_a_withdrawn_optional_field_is_reported_not_fatal(self):
        # FY2025 genuinely stopped publishing the teacher flag and the foreign
        # worker's education. That is a change in disclosure, not a parse
        # failure -- but it has to be said out loud.
        resolved, withdrawn = perm.check_contract(self.FY2025, 2025)
        self.assertIn("employer_name", resolved)
        self.assertIn("college_teacher_flag", withdrawn)
        self.assertIn("phd_institution", withdrawn)

    def test_faculty_classification_follows_the_resolved_columns(self):
        resolved, _ = perm.check_contract(self.FY2025, 2025)
        row = {"CASE_NUMBER": "G-1", "JOB_TITLE": "Assistant Professor of Finance",
               "PWD_SOC_TITLE": "Business Teachers, Postsecondary",
               "EMP_BUSINESS_NAME": "Example University"}
        is_faculty, evidence = perm.classify_faculty(row, resolved)
        self.assertTrue(is_faculty)
        self.assertEqual(perm.EVIDENCE_SOC, evidence)

    def test_business_fields_read_whichever_soc_title_the_release_carries(self):
        # The same helper serves PERM (PW_/PWD_SOC_TITLE) and LCA (SOC_TITLE).
        for key in ("PW_SOC_TITLE", "PWD_SOC_TITLE", "SOC_TITLE"):
            with self.subTest(column=key):
                fields = perm.classify_business_fields(
                    {"JOB_TITLE": "Assistant Professor", key: "Accounting"})
                self.assertIn("Accounting", fields)
