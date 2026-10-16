import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.revert_openalex_placeholder_abstracts import restore_rows, verify_restored


class OpenAlexPlaceholderRepairTests(unittest.TestCase):
    def create_db(self, path: Path, article_id: int = 1, source_id: int = 1):
        abstract = "No description provided"
        digest = hashlib.sha256(abstract.encode()).hexdigest()
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.executescript("""
                CREATE TABLE astar_articles (
                    id INTEGER PRIMARY KEY, doi TEXT, openalex_id TEXT, title TEXT, abstract TEXT,
                    abstract_status TEXT, data_status TEXT, updated_at TEXT, is_duplicate INTEGER);
                CREATE TABLE astar_article_sources (
                    id INTEGER PRIMARY KEY, article_id INTEGER, source_name TEXT, source_type TEXT,
                    raw_id TEXT, parser_notes TEXT);
            """)
            conn.execute("INSERT INTO astar_articles VALUES (?,?,?,?,?,?,?,?,?)", (
                article_id, "10.1234/example", "W123", "A Research Title", abstract,
                "available", "api_metadata", "2026-10-16T11:23:18+00:00", 0,
            ))
            note = "abstract=filled; DOI/title verified; source=OpenAlex; sha256=" + digest
            conn.execute("INSERT INTO astar_article_sources VALUES (?,?,?,?,?,?)", (
                source_id, article_id, "OpenAlex", "openalex_abstract", "W123", note,
            ))
        return digest, note

    def entry(self, digest: str, note: str, source_id: int = 1):
        return {
            "article_id": 1,
            "doi": "10.1234/example",
            "title": "A Research Title",
            "openalex_id": "W123",
            "placeholder_abstract_sha256": digest,
            "source_row": {
                "id": source_id, "article_id": 1, "source_name": "OpenAlex",
                "source_type": "openalex_abstract", "raw_id": "W123", "parser_notes": note,
            },
            "restore_to": {
                "abstract": None, "abstract_status": "missing", "data_status": "title_only",
                "updated_at": "2026-10-06T12:00:00",
            },
            "current": {
                "abstract": "No description provided", "abstract_status": "available",
                "data_status": "api_metadata", "updated_at": "2026-10-16T11:23:18+00:00",
            },
        }

    def test_restores_only_placeholder_row_and_removes_exact_enrichment_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "articles.db"
            before = root / "repair_before_images.jsonl"
            digest, note = self.create_db(db)
            plan = {"candidate_file_sha256": "c" * 64, "entries": [self.entry(digest, note)]}

            restored = restore_rows(db, plan, before)

            self.assertEqual([1], restored)
            self.assertTrue(verify_restored(db, plan))
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual((None, "missing", "title_only", "2026-10-06T12:00:00"), conn.execute(
                    "SELECT abstract,abstract_status,data_status,updated_at FROM astar_articles WHERE id=1"
                ).fetchone())
                self.assertEqual(0, conn.execute(
                    "SELECT count(*) FROM astar_article_sources WHERE id=1"
                ).fetchone()[0])
            self.assertTrue(before.exists())

    def test_source_mismatch_rolls_back_all_article_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "articles.db"
            before = root / "repair_before_images.jsonl"
            digest, note = self.create_db(db)
            row = self.entry(digest, note, source_id=999)
            plan = {"candidate_file_sha256": "d" * 64, "entries": [row]}

            with self.assertRaisesRegex(RuntimeError, "provenance changed"):
                restore_rows(db, plan, before)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(("No description provided", "available", "api_metadata"), conn.execute(
                    "SELECT abstract,abstract_status,data_status FROM astar_articles WHERE id=1"
                ).fetchone())
                self.assertEqual(1, conn.execute(
                    "SELECT count(*) FROM astar_article_sources WHERE id=1"
                ).fetchone()[0])

    def test_restoration_handles_semantic_scholar_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "articles.db"
            before = root / "repair_before_images.jsonl"
            abstract = "N A"
            digest = hashlib.sha256(abstract.encode()).hexdigest()
            note = "abstract=filled; source=Semantic Scholar; sha256=" + digest
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE astar_articles (
                        id INTEGER PRIMARY KEY, doi TEXT, openalex_id TEXT, title TEXT, abstract TEXT,
                        abstract_status TEXT, data_status TEXT, updated_at TEXT, is_duplicate INTEGER);
                    CREATE TABLE astar_article_sources (
                        id INTEGER PRIMARY KEY, article_id INTEGER, source_name TEXT, source_type TEXT,
                        raw_id TEXT, parser_notes TEXT);
                    INSERT INTO astar_articles VALUES
                        (1,'10.1234/example',NULL,'A Research Title','N A','available','api_metadata','new',0);
                """)
                conn.execute("INSERT INTO astar_article_sources VALUES (?,?,?,?,?,?)",
                             (1,1,"Semantic Scholar","semantic_scholar","s2-paper",note))
            entry = {
                "article_id": 1, "doi": "10.1234/example", "title": "A Research Title",
                "openalex_id": None, "placeholder_abstract_sha256": digest,
                "source_row": {"id": 1, "article_id": 1, "source_name": "Semantic Scholar",
                               "source_type": "semantic_scholar", "raw_id": "s2-paper",
                               "parser_notes": note},
                "restore_to": {"abstract": None, "abstract_status": "missing",
                               "data_status": "title_only", "updated_at": "old"},
                "current": {"abstract": abstract, "abstract_status": "available",
                            "data_status": "api_metadata", "updated_at": "new"},
            }
            plan = {"candidate_file_sha256": "e" * 64, "entries": [entry]}

            self.assertEqual([1], restore_rows(db, plan, before))
            self.assertTrue(verify_restored(db, plan))


if __name__ == "__main__":
    unittest.main()
