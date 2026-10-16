import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.apply_abdc_abstract_candidates import (
    apply_article_batch,
    read_jsonl,
    stratified_order,
)


class AbstractCandidateApplyTests(unittest.TestCase):
    def test_read_jsonl_requires_matching_abstract_hash_and_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidates.jsonl"
            abstract = "Publisher/API supplied abstract."
            record = {
                "status": "abstract_candidate", "article_id": 1,
                "doi": "10.1234/example", "returned_doi": "10.1234/example",
                "title": "A Research Title", "returned_title": "A Research Title",
                "abstract": abstract,
                "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest(),
            }
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            self.assertEqual(1, len(read_jsonl(path)))
            record["abstract_sha256"] = "0" * 64
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                read_jsonl(path)

    def test_read_jsonl_allows_no_doi_only_with_matching_openalex_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidates.jsonl"
            abstract = "A public abstract for a work without a local DOI."
            record = {
                "status": "abstract_candidate", "article_id": 1,
                "doi": None, "returned_doi": None,
                "title": "A Research Title", "returned_title": "A Research Title",
                "source": "OpenAlex", "source_type": "openalex_abstract",
                "openalex_id": "https://openalex.org/W123", "returned_openalex_id": "W123",
                "identity_method": "openalex_id",
                "abstract": abstract,
                "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest(),
            }
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            self.assertEqual(1, len(read_jsonl(path)))
            record["returned_openalex_id"] = "W456"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "OpenAlex ID"):
                read_jsonl(path)

    def test_read_jsonl_rejects_known_source_placeholder(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidates.jsonl"
            placeholder = "No description provided"
            row = {
                "status": "abstract_candidate", "article_id": 4,
                "doi": "10.1234/placeholder", "returned_doi": "10.1234/placeholder",
                "title": "A Research Title", "returned_title": "A Research Title",
                "source": "OpenAlex", "source_type": "openalex_abstract",
                "openalex_id": "W123", "returned_openalex_id": "W123",
                "abstract": placeholder,
                "abstract_sha256": hashlib.sha256(placeholder.encode()).hexdigest(),
            }
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "placeholder"):
                read_jsonl(path)

    def test_read_jsonl_accepts_verified_institutional_repository_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidates.jsonl"
            abstract = "A public institutional-repository abstract."
            row = {
                "status": "abstract_candidate", "article_id": 10,
                "doi": None, "returned_doi": None,
                "title": "Making the Minimum Wage Work: An Examination of the Economic Impact",
                "returned_title": "Making the Minimum Wage Work: An Examination of the Economic Impact",
                "journal_title": "Stanford Journal of Law, Business and Finance",
                "returned_journal_title": "Stanford Journal of Law, Business & Finance",
                "publication_year": 2017, "returned_publication_year": 2017,
                "source": "University of Washington School of Law repository",
                "source_type": "institutional_repository_abstract",
                "source_record_id": "faculty-articles/124",
                "source_url": "https://digitalcommons.law.uw.edu/faculty-articles/124/",
                "identity_method": "title_journal_year", "abstract": abstract,
                "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest(),
            }
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertEqual(1, len(read_jsonl(path)))

    def test_read_jsonl_accepts_public_uts_ssrn_and_stanford_title_year_sources(self):
        cases = [
            (11, "University of Technology Sydney Open Publications", "institutional_repository_abstract",
             "10453/16002", "https://opus.lib.uts.edu.au/handle/10453/16002",
             "The Hardship Discretion – Building Bridges with the Community", "eJournal of Tax Research", 2010,
             "https://opus.lib.uts.edu.au/handle/10453/16002"),
            (12, "SSRN author repository", "author_manuscript_abstract", "SSRN:2704662",
             "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2704662",
             "100 Years of the Minimum Wage and the Australian Tax and Transfer System",
             "Australian Tax Forum", 2015, "10.2139/ssrn.2704662"),
            (13, "Stanford Law School publisher version", "publisher_abstract_document",
             "SJLBF-2023-28-2-p307", "https://law.stanford.edu/wp-content/uploads/2023/08/Bebchuk_Final.pdf#page=1",
             "How Twitter Pushed Stakeholders under the Bus", "Stanford Journal of Law, Business and Finance", 2023,
             "https://law.stanford.edu/wp-content/uploads/2023/08/Bebchuk_Final.pdf#page=1"),
            (14, "Private Law Theory abstract index", "secondary_abstract_index",
             "PLT:2025-08-14-michael-ilg-rage-against-the-machine",
             "https://www.private-law-theory.org/2025/08/14/michael-ilg-rage-against-the-machine-artificial-intelligence-and-mistaken-contracts/",
             "Rage Against the Machine: Artificial Intelligence and Mistaken Contracts",
             "Canadian Business Law Journal", 2025,
             "https://www.private-law-theory.org/2025/08/14/michael-ilg-rage-against-the-machine-artificial-intelligence-and-mistaken-contracts/"),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidates.jsonl"
            rows = []
            for article_id, source, source_type, raw_id, source_url, title, journal, year, returned_doi in cases:
                abstract = f"Publisher source abstract {article_id}."
                rows.append({
                    "status": "abstract_candidate", "article_id": article_id, "doi": None,
                    "returned_doi": returned_doi, "title": title, "returned_title": title,
                    "journal_title": journal, "returned_journal_title": journal,
                    "publication_year": year, "returned_publication_year": year,
                    "source": source, "source_type": source_type, "source_record_id": raw_id,
                    "source_url": source_url, "identity_method": "title_journal_year",
                    "abstract": abstract,
                    "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest(),
                })
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            self.assertEqual(4, len(read_jsonl(path)))

    def test_stratified_order_starts_with_requested_fields(self):
        rows = [
            {"article_id": 8, "broad_area": "OB / HR"},
            {"article_id": 7, "broad_area": "Management / Strategy"},
            {"article_id": 9, "broad_area": "Economics"},
            {"article_id": 6, "broad_area": "Marketing"},
            {"article_id": 5, "broad_area": "Information Systems"},
        ]
        ordered = stratified_order(rows)
        self.assertEqual([
            "Management / Strategy", "Marketing", "Information Systems", "OB / HR", "Economics"
        ], [row["broad_area"] for row in ordered])

    def test_apply_updates_only_empty_abstract_and_adds_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            article_db = root / "articles.db"
            state_db = root / "state.db"
            before_path = root / "before_images.jsonl"
            abstract = "A source-provided abstract for the verified DOI."
            digest = hashlib.sha256(abstract.encode("utf-8")).hexdigest()
            candidate = {
                "article_id": 1, "doi": "10.1234/example", "title": "A Research Title",
                "returned_doi": "10.1234/example", "returned_title": "A Research Title",
                "abstract": abstract, "abstract_sha256": digest, "paper_id": "paper-1",
                "source_url": "https://www.semanticscholar.org/paper/paper-1",
                "checked_at_utc": "2026-10-16T00:00:00+00:00",
            }
            with closing(sqlite3.connect(article_db)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE astar_articles (
                        id INTEGER PRIMARY KEY, doi TEXT, openalex_id TEXT, semantic_scholar_id TEXT,
                        title TEXT, journal_title TEXT, publication_year INTEGER, abstract TEXT,
                        abstract_status TEXT, data_status TEXT, updated_at TEXT,
                        is_duplicate INTEGER DEFAULT 0);
                    CREATE TABLE astar_article_sources (
                        article_id INTEGER, source_name TEXT, source_type TEXT,
                        source_url TEXT, raw_id TEXT, raw_json TEXT, fetched_at TEXT,
                        parser_notes TEXT);
                    CREATE TABLE astar_article_classifications (
                        article_id INTEGER PRIMARY KEY, relevance_score REAL,
                        is_related_to_my_research INTEGER);
                    INSERT INTO astar_articles VALUES
                        (1,'10.1234/example',NULL,NULL,'A Research Title','Example Journal',2025,NULL,'missing','title_only','old',0);
                    INSERT INTO astar_article_classifications VALUES (1,54,0);
                """)
            with closing(sqlite3.connect(state_db)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE research_entity_assertions (
                        paper_id INTEGER, verification_status TEXT, reviewed_at TEXT);
                """)

            changed = apply_article_batch(article_db, state_db, [candidate], before_path, "candidate-sha")
            self.assertEqual([1], changed)
            with closing(sqlite3.connect(article_db)) as conn, conn:
                self.assertEqual((abstract, "available", "api_metadata"), conn.execute(
                    "SELECT abstract,abstract_status,data_status FROM astar_articles WHERE id=1"
                ).fetchone())
                source = conn.execute(
                    "SELECT source_name,source_type,raw_id FROM astar_article_sources WHERE article_id=1"
                ).fetchone()
                self.assertEqual(("Semantic Scholar", "semantic_scholar", "paper-1"), source)
                self.assertEqual((54.0, 0), conn.execute(
                    "SELECT relevance_score,is_related_to_my_research "
                    "FROM astar_article_classifications WHERE article_id=1"
                ).fetchone())
            before = json.loads(before_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("title_only", before["data_status"])
            self.assertEqual("missing", before["abstract_status"])

    def test_apply_accepts_openalex_abstract_with_distinct_source_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            article_db = root / "articles.db"
            state_db = root / "state.db"
            before_path = root / "before_images.jsonl"
            abstract = "A public OpenAlex metadata abstract."
            candidate = {
                "article_id": 1, "doi": "10.1234/example", "title": "A Research Title",
                "returned_doi": "https://doi.org/10.1234/example", "returned_title": "A Research Title",
                "abstract": abstract, "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest(),
                "source": "OpenAlex", "source_type": "openalex_abstract", "openalex_id": "W123",
                "source_url": "https://openalex.org/W123", "checked_at_utc": "2026-10-16T00:00:00+00:00",
            }
            with closing(sqlite3.connect(article_db)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE astar_articles (
                        id INTEGER PRIMARY KEY, doi TEXT, openalex_id TEXT, semantic_scholar_id TEXT,
                        title TEXT, journal_title TEXT, publication_year INTEGER, abstract TEXT,
                        abstract_status TEXT, data_status TEXT, updated_at TEXT,
                        is_duplicate INTEGER DEFAULT 0);
                    CREATE TABLE astar_article_sources (
                        article_id INTEGER, source_name TEXT, source_type TEXT,
                        source_url TEXT, raw_id TEXT, raw_json TEXT, fetched_at TEXT,
                        parser_notes TEXT);
                    CREATE TABLE astar_article_classifications (
                        article_id INTEGER PRIMARY KEY, relevance_score REAL,
                        is_related_to_my_research INTEGER);
                    INSERT INTO astar_articles VALUES
                        (1,'10.1234/example','W123',NULL,'A Research Title','Example Journal',2025,NULL,'missing','title_only','old',0);
                    INSERT INTO astar_article_classifications VALUES (1,54,0);
                """)
            with closing(sqlite3.connect(state_db)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE research_entity_assertions (
                        paper_id INTEGER, verification_status TEXT, reviewed_at TEXT);
                """)

            changed = apply_article_batch(article_db, state_db, [candidate], before_path, "openalex-sha")
            self.assertEqual([1], changed)
            with closing(sqlite3.connect(article_db)) as conn, conn:
                self.assertEqual(("OpenAlex", "openalex_abstract", "W123"), conn.execute(
                    "SELECT source_name,source_type,raw_id FROM astar_article_sources WHERE article_id=1"
                ).fetchone())
                self.assertEqual((54.0, 0), conn.execute(
                    "SELECT relevance_score,is_related_to_my_research "
                    "FROM astar_article_classifications WHERE article_id=1"
                ).fetchone())

    def test_apply_fills_no_doi_row_only_when_openalex_id_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            article_db = root / "articles.db"
            state_db = root / "state.db"
            before_path = root / "before_images.jsonl"
            abstract = "A source-provided abstract for an OpenAlex-ID matched work."
            candidate = {
                "article_id": 1, "doi": None, "title": "A Research Title",
                "returned_doi": "10.1234/source-doi", "returned_title": "A Research Title",
                "abstract": abstract, "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest(),
                "source": "OpenAlex", "source_type": "openalex_abstract",
                "openalex_id": "W123", "returned_openalex_id": "https://openalex.org/W123",
                "identity_method": "openalex_id", "source_url": "https://openalex.org/W123",
                "checked_at_utc": "2026-10-16T00:00:00+00:00",
            }
            with closing(sqlite3.connect(article_db)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE astar_articles (
                        id INTEGER PRIMARY KEY, doi TEXT, openalex_id TEXT, semantic_scholar_id TEXT,
                        title TEXT, journal_title TEXT, publication_year INTEGER, abstract TEXT,
                        abstract_status TEXT, data_status TEXT, updated_at TEXT,
                        is_duplicate INTEGER DEFAULT 0);
                    CREATE TABLE astar_article_sources (
                        article_id INTEGER, source_name TEXT, source_type TEXT,
                        source_url TEXT, raw_id TEXT, raw_json TEXT, fetched_at TEXT,
                        parser_notes TEXT);
                    CREATE TABLE astar_article_classifications (
                        article_id INTEGER PRIMARY KEY, relevance_score REAL,
                        is_related_to_my_research INTEGER);
                    INSERT INTO astar_articles VALUES
                        (1,NULL,'W123',NULL,'A Research Title','Example Journal',2025,NULL,'missing','title_only','old',0);
                    INSERT INTO astar_article_classifications VALUES (1,54,0);
                """)
            with closing(sqlite3.connect(state_db)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE research_entity_assertions (
                        paper_id INTEGER, verification_status TEXT, reviewed_at TEXT);
                """)

            changed = apply_article_batch(article_db, state_db, [candidate], before_path, "no-doi-id-sha")
            self.assertEqual([1], changed)
            with closing(sqlite3.connect(article_db)) as conn, conn:
                article = conn.execute(
                    "SELECT doi,openalex_id,abstract,abstract_status FROM astar_articles WHERE id=1"
                ).fetchone()
                self.assertEqual((None, "W123", abstract, "available"), article)
                source = conn.execute(
                    "SELECT source_name,source_type,raw_id FROM astar_article_sources WHERE article_id=1"
                ).fetchone()
                self.assertEqual(("OpenAlex", "openalex_abstract", "W123"), source)
                self.assertEqual((54.0, 0), conn.execute(
                    "SELECT relevance_score,is_related_to_my_research "
                    "FROM astar_article_classifications WHERE article_id=1"
                ).fetchone())

    def test_apply_supports_publisher_abstract_with_exact_title_journal_year_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            article_db = root / "articles.db"
            state_db = root / "state.db"
            before_path = root / "before_images.jsonl"
            abstract = "A publisher-provided abstract for an article without a DOI."
            source_url = "https://journalofaustraliantax.com.au/Articles_Free/JAT%20Volume%2027%20Issue%201.pdf#page=85"
            candidate = {
                "article_id": 1, "doi": None, "title": "Readability Tests on the South African VAT Act",
                "returned_doi": None, "returned_title": "Readability Tests on the South African VAT Act",
                "journal_title": "Journal of Australian Taxation", "returned_journal_title": "Journal of Australian Taxation",
                "publication_year": 2025, "returned_publication_year": 2025,
                "abstract": abstract, "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest(),
                "source": "Journal of Australian Taxation", "source_type": "publisher_abstract_document",
                "source_record_id": "JAT-2025-27-1-85-112", "source_url": source_url,
                "identity_method": "title_journal_year", "checked_at_utc": "2026-10-16T00:00:00+00:00",
            }
            with closing(sqlite3.connect(article_db)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE astar_articles (
                        id INTEGER PRIMARY KEY, doi TEXT, openalex_id TEXT, semantic_scholar_id TEXT,
                        title TEXT, journal_title TEXT, publication_year INTEGER, abstract TEXT,
                        abstract_status TEXT, data_status TEXT, updated_at TEXT, is_duplicate INTEGER DEFAULT 0);
                    CREATE TABLE astar_article_sources (
                        article_id INTEGER, source_name TEXT, source_type TEXT,
                        source_url TEXT, raw_id TEXT, raw_json TEXT, fetched_at TEXT, parser_notes TEXT);
                    CREATE TABLE astar_article_classifications (
                        article_id INTEGER PRIMARY KEY, relevance_score REAL, is_related_to_my_research INTEGER);
                    INSERT INTO astar_articles VALUES
                        (1,NULL,NULL,NULL,'Readability Tests on the South African VAT Act',
                         'Journal of Australian Taxation',2025,NULL,'missing','title_only','old',0);
                    INSERT INTO astar_article_classifications VALUES (1,54,0);
                """)
            with closing(sqlite3.connect(state_db)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE research_entity_assertions (
                        paper_id INTEGER, verification_status TEXT, reviewed_at TEXT);
                """)

            changed = apply_article_batch(article_db, state_db, [candidate], before_path, "publisher-abstract-sha")
            self.assertEqual([1], changed)
            with closing(sqlite3.connect(article_db)) as conn, conn:
                self.assertEqual((None, abstract, "available"), conn.execute(
                    "SELECT doi,abstract,abstract_status FROM astar_articles WHERE id=1"
                ).fetchone())
                source = conn.execute(
                    "SELECT source_name,source_type,raw_id,source_url FROM astar_article_sources WHERE article_id=1"
                ).fetchone()
                self.assertEqual(("Journal of Australian Taxation", "publisher_abstract_document",
                                  "JAT-2025-27-1-85-112", source_url), source)


if __name__ == "__main__":
    unittest.main()
