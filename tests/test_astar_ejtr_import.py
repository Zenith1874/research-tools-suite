"""Publisher URL identity and original-data protection using isolated databases."""

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services import abdc_astar_research_service as radar
from services.astar_history_service import init_run, digest, parse_crossref

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_ejtr_metadata.py"
SPEC = importlib.util.spec_from_file_location("ejtr_import", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PublisherImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "source.db"
        journal = {"journal_title": "eJournal of Tax Research", "issn_print": "1448-2398",
                   "issn_online": "", "abdc_rating": "A", "abdc_version": "2025",
                   "discipline": "Accounting", "is_active": 1, "source_table": "fixture"}
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        radar.ensure_astar_tables(c)
        fields = list(journal)
        c.execute("INSERT INTO abdc_astar_journals(%s) VALUES(%s)" % (",".join(fields), ",".join("?" for _ in fields)), list(journal.values()))
        original = parse_crossref({"DOI": "10.test/original", "title": ["Original paper"],
                                   "published": {"date-parts": [[2020, 3, 4]]}}, journal)
        original.update(abstract="Original verified abstract.", url="https://www.unsw.edu.au/fixture/original.pdf",
                        landing_page_url="https://www.unsw.edu.au/fixture/original.pdf")
        _, self.aid = radar._upsert_article(c, original, journal)
        c.execute("UPDATE astar_article_classifications SET classification_method='llm',classification_notes='original paid decision' WHERE article_id=?", (self.aid,))
        c.commit()
        self.before = dict(c.execute("SELECT * FROM astar_articles WHERE id=?", (self.aid,)).fetchone())
        self.paid = dict(c.execute("SELECT * FROM astar_article_classifications WHERE article_id=?", (self.aid,)).fetchone())
        self.source = dict(c.execute("SELECT * FROM astar_article_sources WHERE article_id=?", (self.aid,)).fetchone())
        c.close()
        scope = self.root / "scope.json"
        scope.write_text(json.dumps([journal]), encoding="utf-8")
        self.run_dir = self.root / "run"
        init_run(self.run_dir, self.db, 2010, "2026-10-06", scope)
        raw = self.root / "original-public-pdf.pdf"
        raw.write_bytes(b"%PDF-fixture-source-retained")
        records = []
        for number, title in enumerate(["New source title for original", "Editorial", "Editorial"]):
            url = "https://www.unsw.edu.au/fixture/" + ("original.pdf" if number == 0 else str(number) + ".pdf")
            metadata = {"status": "VERIFIED_METADATA", "title": title, "source_url": url,
                        "pdf_path": str(raw), "pdf_sha256": digest(raw), "archive_year": 2020,
                        "publication_year": 2020, "publication_date": None, "authors": ["Editor Name"],
                        "abstract": "Incoming public abstract.", "volume": 18, "issue": number + 1,
                        "year_basis": "article_bibliographic_header_year", "index_evidence": []}
            path = self.root / (str(number) + ".metadata.json")
            path.write_text(json.dumps(metadata), encoding="utf-8")
            records.append({"url": url, "status": "VERIFIED_METADATA", "metadata_path": str(path), "metadata_sha256": digest(path)})
        self.report = self.root / "report.json"
        self.report.write_text(json.dumps({"states": {"VERIFIED_METADATA": 3}, "records": records,
                                         "original_metadata_hashes": {}}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_distinct_editorial_urls_do_not_merge_and_original_values_stay_fixed(self):
        result = MODULE.apply_metadata(self.report, self.run_dir, self.root / "import")
        self.assertEqual(3, result["record_count"])
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        self.assertEqual(self.before, dict(c.execute("SELECT * FROM astar_articles WHERE id=?", (self.aid,)).fetchone()))
        self.assertEqual(self.paid, dict(c.execute("SELECT * FROM astar_article_classifications WHERE article_id=?", (self.aid,)).fetchone()))
        self.assertEqual(self.source, dict(c.execute("SELECT * FROM astar_article_sources WHERE id=?", (self.source["id"],)).fetchone()))
        self.assertEqual(2, c.execute("SELECT COUNT(*) FROM astar_articles WHERE title='Editorial'").fetchone()[0])
        self.assertEqual(2, c.execute("SELECT COUNT(*) FROM astar_articles WHERE title='Editorial' AND publication_date IS NULL").fetchone()[0])
        c.close()

    def test_replaying_strong_publisher_ids_keeps_one_article_per_url(self):
        MODULE.apply_metadata(self.report, self.run_dir, self.root / "first")
        MODULE.apply_metadata(self.report, self.run_dir, self.root / "second")
        c = sqlite3.connect(self.db)
        self.assertEqual(3, c.execute("SELECT COUNT(*) FROM astar_articles").fetchone()[0])
        self.assertEqual(3, c.execute("SELECT COUNT(*) FROM astar_article_sources WHERE source_type='publisher_metadata'").fetchone()[0])
        c.close()


if __name__ == "__main__":
    unittest.main()
