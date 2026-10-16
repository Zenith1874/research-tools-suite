"""Issue-shared URLs must preserve separately identified publisher items."""

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services import abdc_astar_research_service as radar
from services.astar_history_service import init_run, digest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_nzulr_metadata.py"
SPEC = importlib.util.spec_from_file_location("nzulr_import", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NZULRImportTests(unittest.TestCase):
    def test_shared_issue_url_distinct_items_and_idempotent_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "source.db"
            journal = {"journal_title": "New Zealand Universities Law Review", "issn_print": "0549-0618",
                       "issn_online": "", "abdc_rating": "A", "abdc_version": "2025",
                       "discipline": "Law", "is_active": 1, "source_table": "fixture"}
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            radar.ensure_astar_tables(c)
            keys = list(journal)
            c.execute("INSERT INTO abdc_astar_journals(%s) VALUES(%s)" % (",".join(keys), ",".join("?" for _ in keys)), list(journal.values()))
            c.commit(); c.close()
            scope = root / "scope.json"
            scope.write_text(json.dumps([journal]), encoding="utf-8")
            run = root / "run"
            init_run(run, path, 2010, "2026-10-06", scope)
            raw = root / "issue.html.gz"
            raw.write_bytes(b"original HTML evidence")
            records = []
            for number in (1, 2):
                records.append({"status": "VERIFIED_ISSUE_HTML_METADATA", "journal_title": journal["journal_title"],
                    "source_raw_id": "nzulr_issue_item:" + str(number), "source_url": "https://nzulr.com/archives/same.htm",
                    "title": "Editorial", "authors": ["Editor Name"], "publication_year": 2017,
                    "publication_month": "2017-12", "publication_date": None, "date_precision": "month",
                    "archive_year": 2017, "year_basis": "publisher_issue_heading_year", "volume": 27,
                    "issue": "4A" if number == 1 else "4B", "record_type": "journal-metadata-item",
                    "source_html_path": str(raw), "source_html_sha256": digest(raw),
                    "source_issue_heading": "Vol 27 December 2017"})
            record_file = root / "records.json"
            record_file.write_text(json.dumps(records), encoding="utf-8")
            first = MODULE.apply_records(record_file, run, root / "first")
            self.assertEqual(first["dispositions"], [["INSERTED", 2]])
            MODULE.apply_records(record_file, run, root / "second")
            c = sqlite3.connect(path)
            self.assertEqual(2, c.execute("SELECT COUNT(*) FROM astar_articles").fetchone()[0])
            self.assertEqual(2, c.execute("SELECT COUNT(*) FROM astar_articles WHERE publication_date IS NULL AND publication_month='2017-12'").fetchone()[0])
            self.assertEqual(2, c.execute("SELECT COUNT(*) FROM astar_article_sources WHERE raw_json IS NOT NULL").fetchone()[0])
            c.close()


if __name__ == "__main__":
    unittest.main()
