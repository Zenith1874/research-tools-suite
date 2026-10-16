# -*- coding: utf-8 -*-
import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.carnegie_recruitment_registry import (
    DISCOVERY_RULE_VERSION,
    build_target_rows,
    export_registry_csv,
    is_teaching_oriented_classification,
    registry_connect,
    registry_summary,
    seed_registry,
)


class CarnegieRecruitmentRegistryTests(unittest.TestCase):
    def test_teaching_proxy_is_four_year_and_excludes_associate_categories(self):
        self.assertTrue(is_teaching_oriented_classification("Mixed Baccalaureate"))
        self.assertTrue(is_teaching_oriented_classification(
            "Professions-focused Undergraduate/Graduate-Master's Small"
        ))
        self.assertFalse(is_teaching_oriented_classification("Mixed Associate/Baccalaureate"))
        self.assertFalse(is_teaching_oriented_classification("Special Focus: Business"))
        self.assertFalse(is_teaching_oriented_classification(
            "Mixed Undergraduate/Graduate-Doctorate Medium"
        ))

    def test_build_target_rows_keeps_r2_and_teaching_as_separate_flags(self):
        public = [
            {
                "unitid": 1, "instnm": "R2 Master's University", "city": "Albuquerque",
                "stabbr": "New Mexico", "control": 1, "research2025": 2,
                "research2025name": "Research 2: High Spending and Doctorate Production",
                "ic2025": 9,
                "ic2025name": "Mixed Undergraduate/Graduate-Master's Large/Medium",
            },
            {
                "unitid": 2, "instnm": "Teaching Baccalaureate College", "city": "Las Cruces",
                "stabbr": "New Mexico", "control": 1, "research2025": 4,
                "research2025name": "No research designation", "ic2025": 5,
                "ic2025name": "Mixed Baccalaureate",
            },
            {
                "unitid": 3, "instnm": "Associate College", "city": "Roswell",
                "stabbr": "New Mexico", "control": 1, "research2025": 4,
                "research2025name": "No research designation", "ic2025": 6,
                "ic2025name": "Mixed Associate/Baccalaureate",
            },
            {
                "unitid": 4, "instnm": "Business Focus College", "city": "Santa Fe",
                "stabbr": "New Mexico", "control": 2, "research2025": 4,
                "research2025name": "No research designation", "ic2025": 20,
                "ic2025name": "Special Focus: Business",
            },
        ]
        ipeds = {
            1: {"unitid": 1, "state": "NM", "control": 1,
                "website": "https://r2.example.edu/", "release_id": 10},
            2: {"unitid": 2, "state": "NM", "control": 1,
                "website": "teaching.example.edu", "release_id": 10},
            3: {"unitid": 3, "state": "NM", "control": 1,
                "website": "associate.example.edu", "release_id": 10},
            4: {"unitid": 4, "state": "NM", "control": 2,
                "website": "business.example.edu", "release_id": 10},
        }
        selected, diagnostics = build_target_rows(public, [], ipeds)
        self.assertEqual({1, 2}, {row["unitid"] for row in selected})
        self.assertEqual(1, diagnostics["r2_count"])
        self.assertEqual(2, diagnostics["teaching_oriented_count"])
        self.assertEqual(1, diagnostics["business_focused_available"])
        self.assertEqual(1, diagnostics["r2_teaching_overlap"])
        self.assertEqual(2, diagnostics["target_count"])
        r2 = next(row for row in selected if row["unitid"] == 1)
        self.assertEqual(1, r2["is_r2"])
        self.assertEqual(1, r2["is_teaching_oriented"])
        self.assertEqual("r2_and_teaching_oriented", r2["target_segment"])

        selected_with_business, _ = build_target_rows(
            public, [], ipeds, include_business_focused=True
        )
        self.assertEqual({1, 2, 4}, {row["unitid"] for row in selected_with_business})

    def test_seed_and_export_fixture_without_live_release_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "academic_market.db"
            registry_path = root / "registry.db"
            public_path = root / "public.xlsx"
            rad_path = root / "rad.xlsx"

            source = sqlite3.connect(source_path)
            source.execute("""CREATE TABLE ipeds_institutions (
                data_year INTEGER, unitid INTEGER, institution_name TEXT,
                state TEXT, control INTEGER, website TEXT, release_id INTEGER
            )""")
            source.executemany("INSERT INTO ipeds_institutions VALUES (?,?,?,?,?,?,?)", [
                (2023, 1, "R2 Master's University", "NM", 1,
                 "https://r2.example.edu/", 10),
                (2023, 2, "Teaching Baccalaureate College", "NM", 1,
                 "https://teaching.example.edu/", 10),
            ])
            source.commit()
            source.close()

            import openpyxl
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "data"
            headers = [
                "unitid", "instnm", "city", "stabbr", "ic2025", "ic2025name",
                "research2025", "research2025name", "control",
            ]
            sheet.append(headers)
            sheet.append([
                1, "R2 Master's University", "Albuquerque", "New Mexico", 9,
                "Mixed Undergraduate/Graduate-Master's Large/Medium", 2,
                "Research 2: High Spending and Doctorate Production", 1,
            ])
            sheet.append([
                2, "Teaching Baccalaureate College", "Las Cruces", "New Mexico", 5,
                "Mixed Baccalaureate", 4, "No research designation", 1,
            ])
            workbook.save(public_path)
            workbook.close()

            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "Data"
            sheet.append(["UNITID", "2025 Research Activity Designation"])
            sheet.append([1, "Research 2: High Spending and Doctorate Production"])
            workbook.save(rad_path)
            workbook.close()

            result = seed_registry(
                source_db=source_path,
                registry_db=registry_path,
                public_file=public_path,
                rad_file=rad_path,
                validate_release=False,
            )
            self.assertEqual(2, result["target_count"])
            self.assertEqual(2, result["website_group_count"])
            self.assertEqual(0, result["missing_official_website"])

            summary = registry_summary(registry_path)
            self.assertEqual(2, summary["targets"])
            self.assertEqual(2, summary["website_groups"])
            self.assertEqual(DISCOVERY_RULE_VERSION, summary["rule_version"])

            conn = registry_connect(registry_path)
            self.assertEqual(2, conn.execute(
                "SELECT COUNT(*) FROM registry_sources"
            ).fetchone()[0])
            self.assertEqual(0, conn.execute(
                "SELECT COUNT(*) FROM registry_runs WHERE status!='ok'"
            ).fetchone()[0])
            conn.close()

            output = root / "registry.csv"
            export_result = export_registry_csv(registry_path, output)
            self.assertEqual(2, export_result["rows"])
            with output.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(2, len(rows))
            self.assertTrue(all(row["latest_status"] == "not_scanned" for row in rows))


if __name__ == "__main__":
    unittest.main()
