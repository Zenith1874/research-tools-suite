"""Resumable, source-reconciled history ingestion for the existing journal scope.

Existing article values, classifications, and affiliation rows are preserved.
The private run directory holds the baseline, immutable API pages, checkpoints,
record dispositions, and reconciliation reports. No paid APIs are called.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from services import abdc_astar_research_service as radar

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
PIPELINE_VERSION = "astar-history-v1.2"
CROSSREF_FIELDS = (
    "DOI,title,published,published-online,published-print,author,publisher,"
    "type,container-title,ISSN,URL,abstract,subject,is-referenced-by-count"
)
OPENALEX_FIELDS = (
    "id,doi,title,display_name,publication_date,publication_year,primary_location,"
    "open_access,cited_by_count,authorships,concepts,keywords,abstract_inverted_index,type"
)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def article_db_now():
    """Match the existing article-table convention; run receipts remain UTC."""
    return datetime.now().isoformat(timespec="seconds")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_new_json(path, data):
    """Never replace an existing input, page, manifest, or report."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def connect(path, readonly=False):
    if readonly:
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro",
                               uri=True, timeout=60, check_same_thread=False)
        conn.execute("PRAGMA query_only=ON")
    else:
        conn = sqlite3.connect(path, timeout=60, check_same_thread=False)
        conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    return conn


def journal_key(journal):
    # The daily updater recreates journal rows, so its autoincrement IDs are not stable.
    issns = sorted(set(filter(None, (journal.get("issn_print"), journal.get("issn_online")))))
    return hashlib.sha256((journal["journal_title"] + "|" + "|".join(issns)).encode()).hexdigest()[:20]


def priority(journal):
    if 'collection_priority' in journal:
        value = journal['collection_priority']
        if not isinstance(value, int) or value < 0:
            raise ValueError('collection priority must be a nonnegative integer')
        return value
    title = journal["journal_title"].lower()
    if any(term in title for term in ("law review", "tax", "law quarterly", "harvard business")):
        return 0
    if any(term in title for term in ("information", "mis quarterly", "management", "organizational", "human resource")):
        return 1
    return 2


def baseline_profile(conn):
    queries = {
        "years": "SELECT publication_year AS year,COUNT(*) AS n FROM astar_articles WHERE is_duplicate=0 GROUP BY publication_year ORDER BY publication_year",
        "range": "SELECT COUNT(*) AS n,MIN(publication_year) AS min_year,MAX(publication_year) AS max_year,MAX(id) AS max_id FROM astar_articles WHERE is_duplicate=0",
        "ratings": "SELECT journal_abdc_rating AS rating,COUNT(*) AS n FROM astar_articles WHERE is_duplicate=0 GROUP BY journal_abdc_rating",
        "abstracts": "SELECT abstract_status,COUNT(*) AS n FROM astar_articles WHERE is_duplicate=0 GROUP BY abstract_status",
        "classifications": "SELECT classification_method,COUNT(*) AS n FROM astar_article_classifications GROUP BY classification_method",
    }
    return {name: [dict(row) for row in conn.execute(query)] for name, query in queries.items()}


def init_run(run_dir, db_path=None, from_year=2010, to_date=None, journal_scope_file=None):
    """Freeze scope and save an online SQLite backup before any article writes."""
    run_dir = Path(run_dir).resolve()
    db_path = Path(db_path or ROOT / "pboc_data.db").resolve()
    end_date = date.fromisoformat(to_date or date.today().isoformat())
    if from_year < 1900 or date(from_year, 1, 1) > end_date:
        raise ValueError("invalid history date range")
    run_dir.mkdir(parents=True, exist_ok=False)
    source = connect(db_path, readonly=True)
    snapshot_path = run_dir / "baseline" / "pboc_data.before.db"
    snapshot_path.parent.mkdir()
    snapshot = sqlite3.connect(snapshot_path)
    try:
        LOG.info("Saving online database backup to %s", snapshot_path)
        source.backup(snapshot, pages=8192, sleep=0.05)
        snapshot.close()
        snapshot = None
        frozen = connect(snapshot_path, readonly=True)
        try:
            journals = [dict(row) for row in frozen.execute(
                "SELECT * FROM abdc_astar_journals WHERE is_active=1 ORDER BY journal_title")]
            profile = baseline_profile(frozen)
            quick_check = frozen.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            frozen.close()
    finally:
        source.close()
        if snapshot is not None:
            snapshot.close()
    if quick_check != "ok" or not journals:
        raise RuntimeError("baseline snapshot or journal scope failed validation")
    if journal_scope_file is not None:
        journal_scope_file = Path(journal_scope_file).resolve()
        selection = json.loads(journal_scope_file.read_text(encoding='utf-8'))
        selected = selection['journals'] if isinstance(selection, dict) else selection
        by_key = {journal_key(journal): journal for journal in journals}
        keys = [journal_key(journal) for journal in selected]
        if not keys or len(set(keys)) != len(keys) or set(keys) - by_key.keys():
            raise ValueError('selected journals must be unique active journals in the baseline')
        journals = []
        for selected_journal, key in zip(selected, keys):
            journal = by_key[key]
            for field in ('collection_priority', 'collection_group', 'priority_basis'):
                if field in selected_journal:
                    journal[field] = selected_journal[field]
            priority(journal)
            journals.append(journal)
    for journal in journals:
        journal["history_key"] = journal_key(journal)
        journal["_area"] = radar._area_from_discipline(journal.get("discipline"))
    journals.sort(key=lambda journal: (priority(journal), journal["journal_title"]))
    write_new_json(run_dir / "journals.json", journals)
    write_new_json(run_dir / "baseline" / "profile.json", profile)
    files = ("services/astar_history_service.py", "scripts/backfill_astar_history.py",
             "services/abdc_astar_research_service.py", "services/business_research_service.py",
             "data/astar_emb_meta.json")
    manifest = {
        "pipeline_version": PIPELINE_VERSION, "created_at": utc_now(),
        "db_path": str(db_path), "run_dir": str(run_dir),
        "from_date": f"{from_year}-01-01", "to_date": end_date.isoformat(),
        "journal_count": len(journals), "journal_scope": "existing active journals only",
        "snapshot_path": str(snapshot_path), "snapshot_sha256": digest(snapshot_path),
        "baseline_quick_check": quick_check, "baseline_profile": profile,
        "python_version": sys.version, "requests_version": requests.__version__,
        "source_files": {name: digest(ROOT / name) for name in files if (ROOT / name).exists()},
        "source_contract": {
            "crossref": "Union of print/online ISSN filters; all deposited work types, matching the existing Crossref feed",
            "openalex": "Primary-location source ISSN union; type:article, matching the existing OpenAlex feed",
            "date": "Provider publication-date filters; missing month/day retain source precision in record audit",
            "preservation": "Insert new records; preserve all nonempty existing article fields and all existing classifications",
            "coverage": "API cursor and advertised-count reconciliation; not proof that a provider indexes every published issue",
        },
        "documentation": [
            "https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/",
            "https://help.openalex.org/api/authentication/",
        ],
    }
    if journal_scope_file is not None:
        manifest.update({'journal_scope': 'explicit frozen selection of active journals',
                         'journal_scope_file': str(journal_scope_file),
                         'journal_scope_sha256': digest(journal_scope_file)})
    write_new_json(run_dir / "manifest.json", manifest)
    state = connect(run_dir / "checkpoint.sqlite3")
    state.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE units (
            unit_key TEXT PRIMARY KEY,journal_key TEXT NOT NULL,provider TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',cursor TEXT DEFAULT '*',
            next_page INTEGER NOT NULL DEFAULT 1,expected_count INTEGER,
            observed_count INTEGER NOT NULL DEFAULT 0,not_before REAL DEFAULT 0,
            error TEXT,updated_at TEXT,attempts INTEGER DEFAULT 0
        );
        CREATE TABLE pages (
            unit_key TEXT,page INTEGER,path TEXT,sha256 TEXT,row_count INTEGER,
            expected_count INTEGER,next_cursor TEXT,committed_at TEXT,
            PRIMARY KEY(unit_key,page)
        );
        CREATE TABLE records (
            unit_key TEXT,source_id TEXT,article_id INTEGER,disposition TEXT,
            publication_year INTEGER,record_type TEXT,date_precision TEXT,
            PRIMARY KEY(unit_key,source_id)
        );
        CREATE INDEX idx_records_article ON records(article_id);
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,created_at TEXT,event TEXT,details TEXT
        );
    """)
    for journal in journals:
        for provider in ("crossref", "openalex"):
            key = f"{provider}-{journal['history_key']}"
            state.execute("INSERT INTO units(unit_key,journal_key,provider,updated_at) VALUES (?,?,?,?)",
                          (key, journal["history_key"], provider, utc_now()))
    state.commit()
    state.close()
    return manifest


def normalize_doi(value):
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", (value or "").strip(), flags=re.I).lower() or None


def parse_crossref(item, journal):
    """Use deposited publication metadata, never created/indexed timestamps."""
    title = next(iter(item.get("title") or []), None)
    parts = None
    for field in ("published", "published-online", "published-print"):
        dates = (item.get(field) or {}).get("date-parts") or []
        if dates and dates[0] and dates[0][0] is not None:
            parts = dates[0]
            break
    pub_date = None
    pub_month = None
    if parts and len(parts) >= 2:
        try:
            if len(parts) == 2:
                pub_month = date(int(parts[0]), int(parts[1]), 1).strftime('%Y-%m')
            if len(parts) >= 3:
                pub_date = date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
        except (ValueError, TypeError):
            pass
    doi = normalize_doi(item.get("DOI"))
    abstract = radar._clean_verified_abstract(item.get("abstract")) if item.get("abstract") else None
    authors = [" ".join(filter(None, (author.get("given"), author.get("family"))))
               or author.get("name", "") for author in item.get("author") or []]
    print_parts = ((item.get('published-print') or {}).get('date-parts') or [[]])[0]
    return {
        "doi": doi, "openalex_id": None, "title": title, "abstract": abstract,
        "abstract_status": "available" if abstract else "missing",
        "publication_date": pub_date, "publication_year": int(parts[0]) if parts else None,
        "publication_month": pub_month,
        "journal_title": journal["journal_title"],
        "journal_issn": journal.get("issn_print") or journal.get("issn_online"),
        "publisher": item.get("publisher"), "authors": [author for author in authors if author],
        "concepts": [], "keywords": item.get("subject") or [],
        "url": item.get("URL"), "landing_page_url": item.get("URL"),
        "cited_by_count": item.get("is-referenced-by-count"), "open_access_status": None,
        "source_name": "Crossref", "source_type": "crossref",
        "source_url": f"https://doi.org/{doi}" if doi else item.get("URL"),
        "data_status": "api_metadata" if abstract else "title_only",
        "record_type": item.get("type"),
        "date_precision": ("year", "month", "day")[min(len(parts or []), 3) - 1] if parts else "missing",
        "_archive_issue_year": print_parts[0] if print_parts and isinstance(print_parts[0], int) else None,
        "_archive_year_evidence": {"source_print_date_parts": print_parts, "volume": item.get('volume'),
                                    "issue": item.get('issue'), "source_publication_date": pub_date},
    }


def parse_openalex(item, journal):
    article = radar._parse_openalex_work(item, journal.get("issn_print") or journal.get("issn_online"))
    article["doi"] = normalize_doi(article.get("doi"))
    article["journal_title"] = journal["journal_title"]
    article["record_type"] = item.get("type")
    article["date_precision"] = "day" if article.get("publication_date") else "missing"
    return article


def request_spec(provider, journal, manifest, cursor, page_size):
    issns = sorted(set(filter(None, (journal.get("issn_print"), journal.get("issn_online")))))
    if not issns:
        raise ValueError("journal has no ISSN")
    start, end = manifest["from_date"], manifest["to_date"]
    if provider == "crossref":
        # Repeated ISSN filters are ORed by Crossref (verified against unrelated journal counts).
        filters = [f"issn:{issn}" for issn in issns]
        filters += [f"from-pub-date:{start}", f"until-pub-date:{end}"]
        return "https://api.crossref.org/works", {
            "filter": ",".join(filters), "rows": page_size, "cursor": cursor,
            "select": CROSSREF_FIELDS,
        }
    return "https://api.openalex.org/works", {
        "filter": (f"primary_location.source.issn:{'|'.join(issns)},"
                   f"from_publication_date:{start},to_publication_date:{end},type:article"),
        "per-page": page_size, "cursor": cursor, "select": OPENALEX_FIELDS,
    }


def unpack_page(provider, data):
    if provider == "crossref":
        message = data["message"]
        return message["items"], int(message["total-results"]), message.get("next-cursor")
    return data["results"], int(data["meta"]["count"]), data["meta"].get("next_cursor")


class SourceUnavailable(RuntimeError):
    pass


class BudgetWait(RuntimeError):
    def __init__(self, seconds, reason):
        self.seconds = max(60, seconds)
        super().__init__(reason)


class HistoryRunner:
    def __init__(self, run_dir, crossref_page_size=1000, openalex_page_size=100,
                 openalex_reserve=100, request_delay=0.35, sqlite_identities=False):
        self.run_dir = Path(run_dir).resolve()
        self.manifest = json.loads((self.run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.journals = {journal["history_key"]: journal for journal in
                         json.loads((self.run_dir / "journals.json").read_text(encoding="utf-8"))}
        self.state = connect(self.run_dir / "checkpoint.sqlite3")
        self.main = connect(self.manifest["db_path"])
        baseline = connect(self.manifest["snapshot_path"], readonly=True)
        try:
            self.baseline_max_id = baseline.execute("SELECT MAX(id) FROM astar_articles").fetchone()[0] or 0
        finally:
            baseline.close()
        self.lock = threading.RLock()
        self.report_lock = threading.Lock()
        self.page_sizes = {"crossref": crossref_page_size, "openalex": openalex_page_size}
        self.openalex_reserve = openalex_reserve
        self.request_delay = request_delay
        self.stop = threading.Event()
        self.openalex_not_before = self.state.execute(
            "SELECT MAX(not_before) FROM units WHERE provider='openalex' AND status='WAITING_BUDGET'").fetchone()[0] or 0
        self.last_report_at = 0
        self.last_report = None
        self.sqlite_identities = sqlite_identities
        try:
            self.refresh_indexes()
        except BaseException:
            self.main.close()
            self.state.close()
            raise

    def refresh_indexes(self):
        self.doi_index, self.oa_index, self.title_index = {}, {}, {}
        if self.sqlite_identities:
            # Existing DOI storage must already have the canonical representation
            # used by the cached backend. Never silently change identity semantics.
            self.main.create_function('history_normalize_doi', 1, normalize_doi, deterministic=True)
            bad = self.main.execute('''SELECT id FROM astar_articles WHERE doi IS NOT NULL
                AND doi IS NOT history_normalize_doi(doi) LIMIT 1''').fetchone()
            if bad:
                raise ValueError('SQL identity lookup requires canonical stored DOI values')
            self.publisher_source_index = {}
            return
        self.publisher_source_index = {
            row["raw_id"]: row["article_id"] for row in self.main.execute(
                "SELECT raw_id,article_id FROM astar_article_sources WHERE source_type='publisher_metadata' AND raw_id IS NOT NULL")
        }
        for row in self.main.execute("SELECT id,doi,openalex_id,title_normalized,publication_year,journal_issn FROM astar_articles"):
            if row["doi"]:
                self.doi_index.setdefault(normalize_doi(row["doi"]), row["id"])
            if row["openalex_id"]:
                self.oa_index.setdefault(row["openalex_id"].replace("https://openalex.org/", ""), row["id"])
            if row["title_normalized"]:
                key = (row["title_normalized"], row["publication_year"], row["journal_issn"])
                self.title_index.setdefault(key, []).append(row["id"])

    def close(self):
        self.state.close()
        self.main.close()

    def event(self, event, details):
        with self.lock:
            self.state.execute("INSERT INTO events(created_at,event,details) VALUES (?,?,?)",
                               (utc_now(), event, json.dumps(details, ensure_ascii=False)))
            self.state.commit()

    def fetch_page(self, provider, journal, unit):
        page_size = self.page_sizes[provider]
        url, params = request_spec(provider, journal, self.manifest, unit["cursor"], page_size)
        session = requests.Session()
        session.headers["User-Agent"] = "ResearchTools-HistoryBackfill/1.0"
        key = os.environ.get("OPENALEX_API_KEY")
        if provider == "openalex" and key:
            session.headers["Authorization"] = f"Bearer {key}"
        mailto = os.environ.get("ASTAR_MAILTO")
        if mailto and not mailto.endswith("@example.com"):
            params["mailto"] = mailto
        try:
            for attempt in range(5):
                response = session.get(url, params=params, timeout=(15, 60))
                if response.status_code == 429:
                    retry = float(response.headers.get("Retry-After", "5"))
                    if provider == "openalex" and (retry > 900 or response.headers.get("X-RateLimit-Remaining") == "0"):
                        raise BudgetWait(retry, "OpenAlex daily budget exhausted")
                    if attempt == 4:
                        raise RuntimeError(f"{provider} burst limit after 5 attempts")
                    self.stop.wait(min(max(retry, 1), 60))
                    continue
                if response.status_code == 404:
                    raise SourceUnavailable(f"{provider}: ISSN filter unavailable (404)")
                if response.status_code >= 500 and attempt < 4:
                    self.stop.wait(min(2 ** attempt, 30))
                    continue
                if response.status_code != 200:
                    raise RuntimeError(f"{provider}: HTTP {response.status_code}; response body preserved in events only by status")
                data = response.json()
                unpack_page(provider, data)  # validate required keys before saving or writing
                headers = {name: value for name, value in response.headers.items()
                           if name.lower().startswith("x-ratelimit") or name.lower() == "retry-after"}
                return {"requested_at": utc_now(), "provider": provider, "url": url,
                        "params": {k: v for k, v in params.items() if k != "mailto"},
                        "status_code": response.status_code, "rate_headers": headers, "data": data}
            raise RuntimeError("request retry loop exhausted")
        finally:
            session.close()

    def existing_id(self, article, journal):
        if self.sqlite_identities:
            if article.get('source_type') == 'publisher_metadata' and article.get('source_raw_id'):
                row = self.main.execute('''SELECT article_id FROM astar_article_sources
                    WHERE source_type='publisher_metadata' AND raw_id=? ORDER BY id LIMIT 1''',
                    (article['source_raw_id'],)).fetchone()
                if row:
                    return row[0]
            if article.get('doi'):
                row = self.main.execute('SELECT id FROM astar_articles WHERE doi=? ORDER BY id LIMIT 1',
                                        (article['doi'],)).fetchone()
                if row:
                    return row[0]
            if article.get('openalex_id'):
                identifier = article['openalex_id']
                row = self.main.execute('''SELECT id FROM astar_articles WHERE openalex_id IN (?,?)
                    ORDER BY id LIMIT 1''', (identifier, 'https://openalex.org/' + identifier)).fetchone()
                if row:
                    return row[0]
        if article.get("source_type") == "publisher_metadata" and article.get("source_raw_id") in self.publisher_source_index:
            return self.publisher_source_index[article["source_raw_id"]]
        if article.get("doi") in self.doi_index:
            return self.doi_index[article["doi"]]
        if article.get("openalex_id") in self.oa_index:
            return self.oa_index[article["openalex_id"]]
        # Another process can add a DOI after the initial in-memory index load.
        if article.get("doi"):
            row = self.main.execute("SELECT id FROM astar_articles WHERE doi=?", (article["doi"],)).fetchone()
            if row:
                return row["id"]
        candidates = set()
        for issn in (journal.get("issn_print"), journal.get("issn_online")):
            key = (radar.normalize_title(article.get("title")), article.get("publication_year"), issn)
            if self.sqlite_identities:
                candidates.update(row[0] for row in self.main.execute('''SELECT id FROM astar_articles
                    WHERE title_normalized=? AND publication_year IS ? AND journal_issn IS ?''', key))
            else:
                candidates.update(self.title_index.get(key, []))
        matches = []
        for aid in candidates:
            row = self.main.execute("SELECT doi,openalex_id,publication_date,authors_json FROM astar_articles WHERE id=?", (aid,)).fetchone()
            if not row:
                continue
            if row["doi"] and article.get("doi") and normalize_doi(row["doi"]) != article["doi"]:
                continue
            if row["openalex_id"] and article.get("openalex_id") and row["openalex_id"].replace("https://openalex.org/", "") != article["openalex_id"]:
                continue
            try:
                authors = json.loads(row["authors_json"] or "[]")
            except (ValueError, TypeError):
                authors = []
            incoming_authors = article.get("authors") or []
            if (row["publication_date"] == article.get("publication_date") and
                authors and incoming_authors and authors[0].casefold() == incoming_authors[0].casefold()):
                matches.append(aid)
        if len(matches) == 1:
            return matches[0]
        return None

    def ingest_article(self, article, journal):
        if not article.get("title"):
            return None, "EXCLUDED_MISSING_TITLE"
        pub_date = article.get("publication_date")
        year_only = (not pub_date and article.get("date_precision") == "year" and
                     isinstance(article.get("publication_year"), int) and
                     int(self.manifest["from_date"][:4]) <= article["publication_year"] <= int(self.manifest["to_date"][:4]))
        archive_year = article.get('_archive_issue_year')
        archive_scope = (article.get('_archive_scope_admission') is True and
                         article.get('source_type') == 'crossref' and
                         isinstance(archive_year, int) and
                         ((pub_date and pub_date <= self.manifest['to_date']) or
                          (not pub_date and isinstance(article.get('publication_year'), int) and
                           article['publication_year'] < int(self.manifest['to_date'][:4]))) and
                         int(self.manifest['from_date'][:4]) <= archive_year <= int(self.manifest['to_date'][:4]))
        pub_month = article.get("publication_month")
        month_only = False
        if not pub_date and article.get("date_precision") == "month" and isinstance(pub_month, str):
            try:
                parsed_month = datetime.strptime(pub_month, "%Y-%m")
                month_only = (parsed_month.strftime("%Y-%m") == pub_month and
                              parsed_month.year == article.get("publication_year") and
                              self.manifest["from_date"][:7] <= pub_month <= self.manifest["to_date"][:7])
            except ValueError:
                pass
        if not (year_only or month_only or archive_scope) and (not pub_date or not self.manifest["from_date"] <= pub_date <= self.manifest["to_date"]):
            return None, "EXCLUDED_CANONICAL_PUBLICATION_DATE"
        required = radar.JOURNAL_DOI_FILTER.get(article.get("journal_issn"))
        if required and required not in (article.get("doi") or ""):
            return None, "EXCLUDED_EXISTING_JOURNAL_DOI_RULE"
        existing = self.existing_id(article, journal)
        now = article_db_now()
        if existing:
            # The ingestion is additive. Existing text, dates, source choices,
            # paid classifications, and affiliations are never overwritten.
            updates = {key: article[key] for key in ("doi", "openalex_id", "abstract") if article.get(key)}
            enriched = False
            abstract_added = False
            for key, value in updates.items():
                changed = self.main.execute(f"UPDATE astar_articles SET {key}=? WHERE id=? AND ({key} IS NULL OR {key}='')",
                                            (value, existing)).rowcount
                enriched = enriched or bool(changed)
                abstract_added = abstract_added or (key == "abstract" and bool(changed))
            if abstract_added:
                self.main.execute("UPDATE astar_articles SET abstract_status=? WHERE id=? AND abstract_status='missing' AND abstract=?",
                                  (article["abstract_status"], existing, article["abstract"]))
            if enriched:
                self.main.execute("UPDATE astar_articles SET updated_at=? WHERE id=?", (now, existing))
            if existing > self.baseline_max_id:
                # Complete the newly ingested records as their second source
                # arrives. Original article content and decisions remain fixed.
                for field, value in (("authors_json", article.get("authors")),
                                     ("concepts_json", article.get("concepts")),
                                     ("keywords_json", article.get("keywords"))):
                    if value:
                        changed = self.main.execute(
                            f"UPDATE astar_articles SET {field}=? WHERE id=? AND ({field} IS NULL OR {field}='' OR {field}='[]')",
                            (json.dumps(value, ensure_ascii=False), existing)).rowcount
                        enriched = enriched or bool(changed)
                        if changed and field == "authors_json":
                            self.main.execute("UPDATE astar_articles SET author_count=? WHERE id=?", (len(value), existing))
                if article.get("source_type") == "openalex":
                    from services.astar_affiliation_service import ensure_affiliation_tables
                    ensure_affiliation_tables(self.main)
                    has_affiliations = self.main.execute("SELECT 1 FROM astar_article_affiliations WHERE article_id=? LIMIT 1", (existing,)).fetchone()
                    if not has_affiliations:
                        radar._record_affiliations_if_available(self.main, existing, article)
                if enriched:
                    stored = self.main.execute("SELECT title,abstract,concepts_json,keywords_json FROM astar_articles WHERE id=?", (existing,)).fetchone()
                    classification_article = dict(article)
                    classification_article.update({
                        "title": stored["title"], "abstract": stored["abstract"],
                        "concepts": json.loads(stored["concepts_json"] or "[]"),
                        "keywords": json.loads(stored["keywords_json"] or "[]"),
                        "_journal_discipline_area": journal.get("_area"),
                    })
                    radar._persist_classification(self.main, existing, classification_article)
                    self.main.execute("UPDATE astar_articles SET updated_at=? WHERE id=?", (now, existing))
            aid, disposition = existing, "EXISTING_ENRICHED" if enriched else "EXISTING_PRESERVED"
        else:
            fields = {key: article.get(key) for key in (
                "doi", "openalex_id", "title", "abstract", "abstract_status", "publication_date",
                "publication_year", "journal_title", "journal_issn", "publisher", "url",
                "landing_page_url", "open_access_status", "cited_by_count", "source_name",
                "source_type", "source_url", "data_status")}
            fields.update({
                "title_normalized": radar.normalize_title(article["title"]),
                "publication_month": pub_date[:7] if pub_date else pub_month if month_only else None,
                "journal_abdc_rating": journal["abdc_rating"],
                "journal_abdc_version": journal["abdc_version"],
                "authors_json": json.dumps(article.get("authors") or [], ensure_ascii=False),
                "author_count": len(article.get("authors") or []),
                "concepts_json": json.dumps(article.get("concepts") or [], ensure_ascii=False),
                "keywords_json": json.dumps(article.get("keywords") or [], ensure_ascii=False),
                "is_duplicate": 0, "created_at": now, "updated_at": now,
            })
            if article.get('publication_month'):
                fields['publication_month'] = article['publication_month']
            columns = list(fields)
            result = self.main.execute(
                f"INSERT INTO astar_articles ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                [fields[column] for column in columns])
            aid, disposition = result.lastrowid, "INSERTED"
            article["_journal_discipline_area"] = journal.get("_area")
            radar._persist_classification(self.main, aid, article)
            radar._record_affiliations_if_available(self.main, aid, article)
            self.title_index.setdefault((fields["title_normalized"], fields["publication_year"], fields["journal_issn"]), []).append(aid)
        if article.get("doi"):
            self.doi_index[article["doi"]] = aid
        if article.get("openalex_id"):
            self.oa_index[article["openalex_id"]] = aid
        if article.get("source_raw_id"):
            self.main.execute("""INSERT INTO astar_article_sources
                (article_id,source_name,source_type,source_url,raw_id,raw_json,fetched_at,parser_notes)
                SELECT ?,?,?,?,?,?,?,? WHERE NOT EXISTS (
                    SELECT 1 FROM astar_article_sources WHERE article_id=? AND source_type=? AND raw_id=?
                )""",
                (aid, article.get("source_name"), article.get("source_type"),
                 article.get("source_url"), article["source_raw_id"], None, now,
                 "public bibliographic metadata; full_text_fetched=false; publication_date_precision=" +
                 str(article.get("date_precision") or "day"),
                 aid, article.get("source_type"), article["source_raw_id"]))
            if article.get("source_type") == "publisher_metadata":
                self.publisher_source_index[article["source_raw_id"]] = aid
        else:
            radar._record_source(self.main, aid, article)
        return aid, disposition

    def commit_page(self, unit, journal, envelope, path):
        items, expected, next_cursor = unpack_page(unit["provider"], envelope["data"])
        with self.lock:
            previous_count = unit["expected_count"]
            if previous_count is not None and previous_count != expected:
                raise RuntimeError(f"source count changed during pagination: {previous_count} -> {expected}")
            audits = []
            try:
                self.main.execute("BEGIN IMMEDIATE")
                for item in items:
                    source_id = normalize_doi(item.get("DOI")) if unit["provider"] == "crossref" else item.get("id")
                    source_id = source_id or hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
                    known = self.state.execute("SELECT article_id,disposition FROM records WHERE unit_key=? AND source_id=?",
                                               (unit["unit_key"], source_id)).fetchone()
                    if known:
                        continue
                    article = (parse_crossref(item, journal) if unit["provider"] == "crossref" else parse_openalex(item, journal))
                    aid, disposition = self.ingest_article(article, journal)
                    audits.append((unit["unit_key"], source_id, aid, disposition,
                                   article.get("publication_year"), article.get("record_type"), article.get("date_precision")))
                self.main.commit()
            except BaseException:
                self.main.rollback()
                self.refresh_indexes()
                raise
            # Commit the cursor only after the production database transaction.
            # A crash in between replays the immutable page idempotently.
            self.state.executemany("INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?,?)", audits)
            observed = unit["observed_count"] + len(items)
            unique_count = self.state.execute("SELECT COUNT(*) FROM records WHERE unit_key=?", (unit["unit_key"],)).fetchone()[0]
            terminal = (not items or not next_cursor or
                        (unit["provider"] == "crossref" and len(items) < self.page_sizes["crossref"]))
            if terminal:
                status = "COMPLETE" if unique_count == expected else "COUNT_MISMATCH"
            else:
                status = "RUNNING"
                if next_cursor == unit["cursor"]:
                    status = "CURSOR_STALLED"
            self.state.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?)",
                               (unit["unit_key"], unit["next_page"], str(path.relative_to(self.run_dir)),
                                digest(path), len(items), expected, next_cursor, utc_now()))
            self.state.execute("UPDATE units SET status=?,cursor=?,next_page=next_page+1,expected_count=?,observed_count=?,error=?,updated_at=?,not_before=0 WHERE unit_key=?",
                               (status, next_cursor, expected, observed,
                                None if status in ("COMPLETE", "RUNNING") else f"expected={expected}; unique={unique_count}",
                                utc_now(), unit["unit_key"]))
            self.state.commit()
            if self.sqlite_identities:
                # Keep only the current page's small transaction-local additions.
                self.doi_index.clear()
                self.oa_index.clear()
                self.title_index.clear()
                self.publisher_source_index.clear()
        return status, Counter(audit[3] for audit in audits)

    def run_unit(self, unit_key):
        with self.lock:
            unit = dict(self.state.execute("SELECT * FROM units WHERE unit_key=?", (unit_key,)).fetchone())
        journal = self.journals[unit["journal_key"]]
        while not self.stop.is_set():
            if unit["status"] == "COMPLETE":
                return
            path = self.run_dir / "raw" / unit_key / f"page_{unit['next_page']:06d}.json.gz"
            try:
                if path.exists():
                    with gzip.open(path, "rt", encoding="utf-8") as stream:
                        envelope = json.load(stream)
                    expected_url, expected_params = request_spec(unit["provider"], journal, self.manifest,
                                                                 unit["cursor"], self.page_sizes[unit["provider"]])
                    if envelope["url"] != expected_url or envelope["params"] != expected_params:
                        raise RuntimeError("cached page parameters do not match the checkpoint")
                else:
                    envelope = self.fetch_page(unit["provider"], journal, unit)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    # Exclusive creation preserves raw responses from earlier attempts.
                    temporary = path.with_name(path.name + f".partial.{threading.get_ident()}")
                    with temporary.open("xb") as binary:
                        with gzip.GzipFile(fileobj=binary, mode="wb") as compressed:
                            compressed.write(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
                    temporary.rename(path)
                status, changes = self.commit_page(unit, journal, envelope, path)
                LOG.info("%s | %s | page=%s | %s | %s", unit["provider"], journal["journal_title"],
                         unit["next_page"], status, dict(changes))
                if unit["provider"] == "openalex":
                    remaining = envelope["rate_headers"].get("X-RateLimit-Remaining")
                    reset = envelope["rate_headers"].get("X-RateLimit-Reset", "3600")
                    if remaining is not None and float(remaining) <= self.openalex_reserve and status != "COMPLETE":
                        raise BudgetWait(float(reset) + 30, f"OpenAlex reserve reached ({remaining} remaining)")
                    if remaining is not None and float(remaining) <= self.openalex_reserve:
                        self.openalex_not_before = time.time() + float(reset) + 30
                if status != "RUNNING":
                    return
                self.stop.wait(self.request_delay)
                with self.lock:
                    unit = dict(self.state.execute("SELECT * FROM units WHERE unit_key=?", (unit_key,)).fetchone())
            except BudgetWait as exc:
                self.openalex_not_before = time.time() + exc.seconds
                with self.lock:
                    self.state.execute("UPDATE units SET status='WAITING_BUDGET',not_before=?,error=?,updated_at=? WHERE unit_key=? AND status!='COMPLETE'",
                                       (self.openalex_not_before, str(exc), utc_now(), unit_key))
                    self.state.commit()
                self.event("budget_wait", {"unit_key": unit_key, "seconds": exc.seconds, "reason": str(exc)})
                LOG.warning("%s; waiting until %s", exc, datetime.fromtimestamp(self.openalex_not_before, timezone.utc).isoformat())
                return
            except SourceUnavailable as exc:
                self.finish_error(unit_key, "SOURCE_UNAVAILABLE", str(exc))
                return
            except Exception as exc:
                self.finish_error(unit_key, "ERROR", f"{type(exc).__name__}: {str(exc)[:300]}")
                return

    def finish_error(self, unit_key, status, error):
        with self.lock:
            self.state.execute("UPDATE units SET status=?,error=?,attempts=attempts+1,updated_at=? WHERE unit_key=?",
                               (status, error, utc_now(), unit_key))
            self.state.commit()
        LOG.error("%s | %s | %s", unit_key, status, error)

    def worker(self, provider):
        while not self.stop.is_set():
            with self.lock:
                remaining_units = self.state.execute("SELECT COUNT(*) FROM units WHERE provider=? AND (status IN ('PENDING','WAITING_BUDGET') OR (status='ERROR' AND attempts<3))", (provider,)).fetchone()[0]
            if not remaining_units:
                return
            if provider == "openalex" and time.time() < self.openalex_not_before:
                self.stop.wait(min(45, self.openalex_not_before - time.time()))
                continue
            with self.lock:
                ordered_keys = [f"{provider}-{key}" for key in self.journals]
                unit_key = None
                for key in ordered_keys:
                    unit = self.state.execute("SELECT status,attempts,not_before FROM units WHERE unit_key=?", (key,)).fetchone()
                    if (unit["status"] in ("PENDING", "WAITING_BUDGET") or
                        (unit["status"] == "ERROR" and unit["attempts"] < 3)) and unit["not_before"] <= time.time():
                        unit_key = key
                        self.state.execute("UPDATE units SET status='CLAIMED',updated_at=? WHERE unit_key=?", (utc_now(), key))
                        self.state.commit()
                        break
                if unit_key is None:
                    waiting = self.state.execute("SELECT MIN(not_before) FROM units WHERE provider=? AND status='WAITING_BUDGET'", (provider,)).fetchone()[0]
                    if waiting and waiting > time.time():
                        self.openalex_not_before = waiting
                    else:
                        return
            if unit_key:
                self.run_unit(unit_key)
                self.report()

    def report(self, force=False):
        with self.report_lock, self.lock:
            if not force and self.last_report is not None and time.time() - self.last_report_at < 30:
                return self.last_report
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            folder = self.run_dir / "reports" / stamp
            folder.mkdir(parents=True)
            units = [dict(row) for row in self.state.execute("SELECT * FROM units ORDER BY provider,journal_key")]
            record_counts = {row["unit_key"]: row["n"] for row in self.state.execute("SELECT unit_key,COUNT(*) AS n FROM records GROUP BY unit_key")}
            for unit in units:
                unit["journal_title"] = self.journals[unit["journal_key"]]["journal_title"]
                unit["unique_source_records"] = record_counts.get(unit["unit_key"], 0)
            with (folder / "source_coverage.csv").open("x", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(units[0]))
                writer.writeheader()
                writer.writerows(units)
            years = [dict(row) for row in self.main.execute("SELECT publication_year AS year,COUNT(*) AS n FROM astar_articles WHERE is_duplicate=0 GROUP BY publication_year ORDER BY publication_year")]
            imported = [dict(row) for row in self.state.execute("SELECT disposition,COUNT(*) AS n FROM records GROUP BY disposition")]
            summary = {"created_at": utc_now(), "pipeline_version": PIPELINE_VERSION,
                       "unit_states": dict(Counter(unit["status"] for unit in units)),
                       "by_provider": {provider: dict(Counter(unit["status"] for unit in units if unit["provider"] == provider)) for provider in ("crossref", "openalex")},
                       "record_dispositions": imported, "database_years": years,
                       "database_total": sum(row["n"] for row in years),
                       "all_source_units_complete": all(unit["status"] == "COMPLETE" for unit in units),
                       "openalex_not_before": self.openalex_not_before,
                       "report_directory": str(folder)}
            write_new_json(folder / "summary.json", summary)
            self.last_report_at = time.time()
            self.last_report = summary
            return summary

    def run(self, sources=("crossref", "openalex"), crossref_workers=2):
        with self.lock:
            # Only the confirmed single process owns this run. Resume committed
            # cursors rather than restarting unfinished source units.
            self.state.execute("UPDATE units SET status='PENDING' WHERE status IN ('CLAIMED','RUNNING')")
            self.state.commit()
        self.event("run_started", {"pid": os.getpid(), "sources": list(sources),
                                   "crossref_workers": crossref_workers, "page_sizes": self.page_sizes,
                                   "openalex_reserve": self.openalex_reserve,
                                   "identity_backend": "indexed_sqlite" if self.sqlite_identities else "cached",
                                   "pipeline_version": PIPELINE_VERSION,
                                   "engine_sha256": digest(__file__)})
        try:
            workers = (["crossref"] * crossref_workers if "crossref" in sources else [])
            if "openalex" in sources:
                workers.append("openalex")
            with ThreadPoolExecutor(max_workers=len(workers), thread_name_prefix="history") as pool:
                futures = [pool.submit(self.worker, provider) for provider in workers]
                try:
                    while not all(future.done() for future in futures):
                        self.stop.wait(45)
                    for future in futures:
                        future.result()
                except BaseException:
                    self.stop.set()
                    raise
            result = self.report(force=True)
            self.event("run_finished", result)
            return result
        except KeyboardInterrupt:
            self.stop.set()
            self.event("run_interrupted", {"pid": os.getpid()})
            raise

    def replay_new_metadata(self):
        """Enrich new IDs from saved pages, without fetching or restarting units."""
        pages = self.state.execute("SELECT p.* FROM pages p JOIN units u ON u.unit_key=p.unit_key WHERE u.provider='openalex' ORDER BY p.unit_key,p.page").fetchall()
        changed_records = 0
        for page in pages:
            path = self.run_dir / page["path"]
            if digest(path) != page["sha256"]:
                raise RuntimeError("raw page hash differs from committed checkpoint")
            unit = self.state.execute("SELECT * FROM units WHERE unit_key=?", (page["unit_key"],)).fetchone()
            journal = self.journals[unit["journal_key"]]
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                envelope = json.load(stream)
            items, _, _ = unpack_page("openalex", envelope["data"])
            try:
                self.main.execute("BEGIN IMMEDIATE")
                for item in items:
                    known = self.state.execute("SELECT article_id FROM records WHERE unit_key=? AND source_id=?", (unit["unit_key"], item.get("id"))).fetchone()
                    if not known or not known["article_id"] or known["article_id"] <= self.baseline_max_id:
                        continue
                    article = parse_openalex(item, journal)
                    _, disposition = self.ingest_article(article, journal)
                    changed_records += disposition == "EXISTING_ENRICHED"
                self.main.commit()
            except BaseException:
                self.main.rollback()
                self.refresh_indexes()
                raise
        result = {"pipeline_version": PIPELINE_VERSION, "pages_reused": len(pages),
                  "new_records_enriched": changed_records, "external_requests": 0,
                  "baseline_max_id": self.baseline_max_id,
                  "engine_sha256": digest(__file__)}
        self.event("new_metadata_replayed", result)
        return result


def status_run(run_dir):
    """A status read never replays requests, writes articles, or changes checkpoints."""
    run_dir = Path(run_dir).resolve()
    state = connect(run_dir / "checkpoint.sqlite3", readonly=True)
    try:
        summary = {"run_dir": str(run_dir), "unit_states": [dict(row) for row in state.execute(
            "SELECT provider,status,COUNT(*) AS n FROM units GROUP BY provider,status")],
            "record_dispositions": [dict(row) for row in state.execute("SELECT disposition,COUNT(*) AS n FROM records GROUP BY disposition")],
            "latest_events": [dict(row) for row in state.execute("SELECT * FROM events ORDER BY id DESC LIMIT 3")],
            "pages": state.execute("SELECT COUNT(*) FROM pages").fetchone()[0]}
        return summary
    finally:
        state.close()
