"""Auditable OpenAlex supplements outside primary-location article queries.

Collection writes only a separate checkpoint and immutable raw responses.
Import requires reconciled collection and a published, matching journal location.
Neither operation changes the original run's units or source pages.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from services.astar_history_service import (
    BudgetWait, HistoryRunner, OPENALEX_FIELDS, connect, digest,
    normalize_doi, parse_openalex, priority, utc_now, write_new_json,
)
from services.openalex_budget import openalex_headers

LOG = logging.getLogger(__name__)
KINDS = ("secondary_location", "primary_nonarticle")
JOURNAL_CONTENT_TYPES = {
    "article", "review", "letter", "editorial", "erratum", "other", "paratext", "peer-review",
    "book-review", "data-paper", "software-paper", "retraction", "conference-paper",
    "conference-abstract", "preprint",
}
NON_JOURNAL_TYPES = {"book", "book-chapter", "dataset", "dissertation", "grant", "standard"}
SELECT_FIELDS = ",".join(dict.fromkeys((OPENALEX_FIELDS + ",locations,biblio").split(",")))


def journal_issns(journal):
    return sorted({str(journal.get(key) or "").upper() for key in ("issn_print", "issn_online")}
                  - {""})


def source_issns(location):
    source = (location or {}).get("source") or {}
    return {str(value).upper() for value in (source.get("issn") or []) if value}


def published_location_doi(location):
    """Use the DOI explicitly carried by the matched publisher location, if present."""
    identifier = str((location or {}).get("id") or "")
    if identifier.startswith("doi:"):
        return normalize_doi(identifier[4:])
    landing = str((location or {}).get("landing_page_url") or "")
    if landing.lower().startswith(("https://doi.org/", "http://doi.org/")):
        return normalize_doi(landing)
    return None


def supplement_spec(kind, journal, manifest, cursor):
    """Keep the two delta sets disjoint, including journals with two ISSNs."""
    issns = journal_issns(journal)
    if not issns:
        raise ValueError("The frozen journal has no ISSN")
    if kind == "secondary_location":
        filters = ["locations.source.issn:" + "|".join(issns)]
        # Repeated negations are an AND. A negated OR is ambiguous and is avoided.
        filters += ["primary_location.source.issn:!" + value for value in issns]
    elif kind == "primary_nonarticle":
        filters = ["primary_location.source.issn:" + "|".join(issns), "type:!article"]
    else:
        raise ValueError("Unknown supplemental query kind")
    filters += ["from_publication_date:" + manifest["from_date"],
                "to_publication_date:" + manifest["to_date"]]
    return "https://api.openalex.org/works", {
        "filter": ",".join(filters), "cursor": cursor,
        "per-page": manifest["page_size"], "select": manifest["select_fields"],
    }


def assess_work(item, journal, kind):
    """Preserve uncertain records for review instead of inventing publication evidence."""
    if kind not in KINDS:
        raise ValueError("Unknown supplemental query kind")
    wanted = set(journal_issns(journal))
    primary = item.get("primary_location") or {}
    primary_matches = bool(source_issns(primary) & wanted)
    if ((kind == "secondary_location" and primary_matches) or
            (kind == "primary_nonarticle" and
             (not primary_matches or item.get("type") == "article"))):
        return "REVIEW_QUERY_SCOPE_MISMATCH", [], None
    return assess_published_work(item, journal)


def assess_published_work(item, journal):
    """Assess a matching published journal copy, without imposing a delta query."""
    wanted = set(journal_issns(journal))
    primary = item.get("primary_location") or {}
    locations = list(item.get("locations") or [])
    if primary:
        locations.append(primary)
    evidence, published = [], []
    for location in locations:
        if not source_issns(location) & wanted:
            continue
        source = location.get("source") or {}
        fact = {"source_id": source.get("id"), "location_id": location.get("id"),
                "issns": sorted(source_issns(location)),
                "source_type": source.get("type"), "version": location.get("version"),
                "is_published": location.get("is_published"),
                "landing_page_url": location.get("landing_page_url"),
                "work_doi": item.get("doi"), "publisher_location_doi": published_location_doi(location),
                "biblio": item.get("biblio") or {}}
        if fact not in evidence:
            evidence.append(fact)
        if (source.get("type") == "journal" and
                (location.get("is_published") is True or location.get("version") == "publishedVersion")):
            published.append(location)
    if not evidence:
        return "REVIEW_NO_MATCHING_LOCATION", [], None
    if item.get("type") in NON_JOURNAL_TYPES:
        return "EXCLUDED_NON_JOURNAL_WORK_TYPE", evidence, None
    if item.get("type") not in JOURNAL_CONTENT_TYPES:
        return "REVIEW_UNSUPPORTED_WORK_TYPE", evidence, None
    if not published:
        return "REVIEW_PUBLICATION_STATUS_UNCONFIRMED", evidence, None
    return "ELIGIBLE_PENDING_IMPORT", evidence, published[0]


def initialize(output_dir, primary_dirs, expected_journals=None, page_size=100):
    output_dir = Path(output_dir).resolve()
    primary_dirs = [Path(value).resolve() for value in primary_dirs]
    if not primary_dirs or not 1 <= page_size <= 200:
        raise ValueError("Supply primary runs and a page size from 1 to 200")
    inputs, selected, shared = [], {}, None
    for directory in primary_dirs:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        identity = (str(Path(manifest["db_path"]).resolve()), manifest["from_date"], manifest["to_date"])
        if shared is not None and shared != identity:
            raise ValueError("Primary runs have different databases or date scopes")
        shared = identity
        for journal in json.loads((directory / "journals.json").read_text(encoding="utf-8")):
            if journal["abdc_rating"] != "A":
                continue
            key = journal["history_key"]
            if key in selected and (journal_issns(selected[key]) != journal_issns(journal) or
                                    selected[key]["journal_title"] != journal["journal_title"]):
                raise ValueError("Conflicting frozen journal identities")
            selected.setdefault(key, journal)
        inputs.append({"run_dir": str(directory), "manifest_sha256": digest(directory / "manifest.json"),
                       "journals_sha256": digest(directory / "journals.json")})
    if not selected or (expected_journals is not None and len(selected) != expected_journals):
        raise ValueError(f"Frozen A-rated union has {len(selected)} journals, not {expected_journals}")
    existing = output_dir / "manifest.json"
    if existing.exists():
        saved = json.loads(existing.read_text(encoding="utf-8"))
        if saved["inputs"] != inputs or saved["page_size"] != page_size:
            raise ValueError("Resume arguments differ from the saved supplement")
        if digest(output_dir / "journals.json") != saved["journals_sha256"]:
            raise ValueError("The saved supplemental journal scope changed")
        return saved
    output_dir.mkdir(parents=True, exist_ok=True)
    if (output_dir / "checkpoint.sqlite3").exists():
        raise ValueError("A checkpoint without its manifest must be inspected before reuse")
    journals = sorted(selected.values(), key=lambda row: (priority(row), row["history_key"]))
    write_new_json(output_dir / "journals.json", journals)
    state = connect(output_dir / "checkpoint.sqlite3")
    state.executescript("""
        CREATE TABLE units(unit_key TEXT PRIMARY KEY,journal_key TEXT,kind TEXT,status TEXT,
            cursor TEXT,next_page INTEGER,expected_count INTEGER,observed_count INTEGER,
            not_before REAL,attempts INTEGER,error TEXT,updated_at TEXT);
        CREATE TABLE pages(unit_key TEXT,page INTEGER,path TEXT,sha256 TEXT,row_count INTEGER,
            expected_count INTEGER,cursor_before TEXT,next_cursor TEXT,committed_at TEXT,
            PRIMARY KEY(unit_key,page));
        CREATE TABLE records(unit_key TEXT,source_id TEXT,record_type TEXT,source_year INTEGER,
            disposition TEXT,evidence_json TEXT,article_id INTEGER,imported_at TEXT,page INTEGER,
            PRIMARY KEY(unit_key,source_id));
        CREATE TABLE events(created_at TEXT,event TEXT,details TEXT);
    """)
    for journal in journals:
        for kind in KINDS:
            key = kind + "-" + journal["history_key"]
            state.execute("INSERT INTO units VALUES(?,?,?,'PENDING','*',1,NULL,0,0,0,NULL,?)",
                          (key, journal["history_key"], kind, utc_now()))
    state.commit()
    state.close()
    result = {"created_at": utc_now(), "db_path": shared[0], "from_date": shared[1], "to_date": shared[2],
              "journal_count": len(journals), "rating_scope": "A", "inputs": inputs,
              "journals_sha256": digest(output_dir / "journals.json"), "page_size": page_size,
              "select_fields": SELECT_FIELDS, "query_kinds": list(KINDS),
              "collection_writes_main_database": False,
              "import_requires_published_matching_journal_location": True,
              "full_text_fetched": False, "script_sha256": digest(__file__),
              "filter_documentation": "https://help.openalex.org/api/filtering/"}
    write_new_json(existing, result)
    return result


def reset_seconds():
    now = datetime.now(timezone.utc)
    reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=30, microsecond=0)
    return max(1, (reset - now).total_seconds())


class SupplementCollector:
    def __init__(self, directory, reserve=1500):
        self.directory = Path(directory).resolve()
        self.manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
        if digest(self.directory / "journals.json") != self.manifest["journals_sha256"]:
            raise ValueError("Supplemental journal scope changed")
        self.journals = {row["history_key"]: row for row in
                         json.loads((self.directory / "journals.json").read_text(encoding="utf-8"))}
        self.state = connect(self.directory / "checkpoint.sqlite3")
        if reserve < 0:
            self.state.close()
            raise ValueError("The OpenAlex reserve must be nonnegative")
        self.reserve = reserve

    def close(self):
        self.state.close()

    def status(self):
        states = dict(self.state.execute("SELECT status,COUNT(*) FROM units GROUP BY status"))
        dispositions = dict(self.state.execute("SELECT disposition,COUNT(*) FROM records GROUP BY disposition"))
        return {"created_at": utc_now(), "journal_count": len(self.journals), "unit_states": states,
                "record_dispositions": dispositions, "source_records": sum(dispositions.values()),
                "all_queries_reconciled": states == {"COMPLETE": len(self.journals) * len(KINDS)}}

    def primaries_complete(self):
        for source in self.manifest["inputs"]:
            conn = connect(Path(source["run_dir"]) / "checkpoint.sqlite3", readonly=True)
            try:
                row = conn.execute("SELECT COUNT(*),SUM(status!='COMPLETE') FROM units").fetchone()
                if not row[0] or row[1]:
                    return False
            finally:
                conn.close()
        return True

    def fetch_page(self, unit):
        journal = self.journals[unit["journal_key"]]
        url, params = supplement_spec(unit["kind"], journal, self.manifest, unit["cursor"])
        headers = openalex_headers(url, {"User-Agent": "ResearchTools-JournalScopeSupplement/1.0"})
        for attempt in range(5):
            response = requests.get(url, params=params, headers=headers, timeout=(15, 60))
            if response.status_code == 429:
                delay = float(response.headers.get("Retry-After") or 5)
                if delay > 900 or response.headers.get("x-ratelimit-remaining") == "0":
                    raise BudgetWait(max(delay, reset_seconds()), "OpenAlex daily budget wait")
                time.sleep(min(60, max(1, delay)))
                continue
            if response.status_code >= 500 and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            if response.status_code != 200:
                raise RuntimeError(f"OpenAlex supplement HTTP {response.status_code}")
            data = response.json()
            if not isinstance(data.get("results"), list) or not isinstance(data.get("meta", {}).get("count"), int):
                raise ValueError("Invalid OpenAlex page shape")
            safe_headers = {key: value for key, value in response.headers.items()
                            if key.lower().startswith("x-ratelimit") or key.lower() == "retry-after"}
            return {"requested_at": utc_now(), "provider": "openalex_scope_supplement", "kind": unit["kind"],
                    "url": url, "params": params, "status_code": 200,
                    "rate_headers": safe_headers, "data": data}
        raise RuntimeError("OpenAlex supplement burst retry budget exhausted")

    def commit_page(self, unit, envelope, path):
        journal = self.journals[unit["journal_key"]]
        url, params = supplement_spec(unit["kind"], journal, self.manifest, unit["cursor"])
        if envelope["url"] != url or envelope["params"] != params:
            raise ValueError("Saved page does not match its frozen query/cursor")
        items, meta = envelope["data"]["results"], envelope["data"]["meta"]
        expected, next_cursor = int(meta["count"]), meta.get("next_cursor")
        if unit["expected_count"] is not None and unit["expected_count"] != expected:
            raise ValueError("Source count changed; retain the page for reconciliation")
        self.state.execute("BEGIN IMMEDIATE")
        try:
            for item in items:
                source_id = item.get("id") or hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
                disposition, evidence, _ = assess_work(item, journal, unit["kind"])
                self.state.execute("INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?,NULL,NULL,?)",
                                   (unit["unit_key"], source_id, item.get("type"), item.get("publication_year"),
                                    disposition, json.dumps(evidence, ensure_ascii=False), unit["next_page"]))
            observed = unit["observed_count"] + len(items)
            unique = self.state.execute("SELECT COUNT(*) FROM records WHERE unit_key=?", (unit["unit_key"],)).fetchone()[0]
            if items and next_cursor == unit["cursor"]:
                status = "CURSOR_STALLED"
            elif not items or not next_cursor or observed >= expected:
                status = "COMPLETE" if unique == expected and observed == expected else "COUNT_MISMATCH"
            else:
                status = "RUNNING"
            self.state.execute("INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,?)",
                               (unit["unit_key"], unit["next_page"], str(path.relative_to(self.directory)),
                                digest(path), len(items), expected, unit["cursor"], next_cursor, utc_now()))
            self.state.execute("UPDATE units SET status=?,cursor=?,next_page=next_page+1,expected_count=?,observed_count=?,error=?,updated_at=? WHERE unit_key=?",
                               (status, next_cursor, expected, observed,
                                None if status in ("COMPLETE", "RUNNING") else f"expected={expected}; observed={observed}; unique={unique}",
                                utc_now(), unit["unit_key"]))
            self.state.commit()
            return status
        except BaseException:
            self.state.rollback()
            raise

    def collect(self, wait_for_primary=True):
        if wait_for_primary:
            if not self.primaries_complete():
                LOG.info("Waiting for the confirmed primary acquisitions before supplemental API requests")
            while not self.primaries_complete():
                time.sleep(30)
        self.state.execute("UPDATE units SET status='PENDING' WHERE status='RUNNING'")
        self.state.commit()
        keys = [kind + "-" + key for key in self.journals for kind in KINDS]
        while True:
            candidates = [dict(self.state.execute("SELECT * FROM units WHERE unit_key=?", (key,)).fetchone())
                          for key in keys]
            candidates = [row for row in candidates if row["status"] in ("PENDING", "RUNNING", "WAITING_BUDGET")
                          or (row["status"] == "ERROR" and row["attempts"] < 3)]
            if not candidates:
                break
            global_wait = max([row["not_before"] or 0 for row in candidates] + [0])
            if global_wait > time.time():
                time.sleep(min(30, global_wait - time.time()))
                continue
            unit = candidates[0]
            path = self.directory / "raw" / unit["unit_key"] / ("page_%06d.json.gz" % unit["next_page"])
            try:
                if path.exists():
                    with gzip.open(path, "rt", encoding="utf-8") as stream:
                        envelope = json.load(stream)
                else:
                    envelope = self.fetch_page(unit)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as handle:
                        with gzip.GzipFile(fileobj=handle, mode="wb") as stream:
                            stream.write(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
                    time.sleep(0.35)
                status = self.commit_page(unit, envelope, path)
                LOG.info("%s | %s | page=%s | %s", unit["kind"], self.journals[unit["journal_key"]]["journal_title"], unit["next_page"], status)
                remaining = next((value for name, value in envelope.get("rate_headers", {}).items()
                                  if name.lower() == "x-ratelimit-remaining"), None)
                # Old cached responses are not evidence of today's budget.
                requested_day = str(envelope.get("requested_at") or "")[:10]
                if remaining is not None and requested_day == utc_now()[:10] and int(remaining) <= self.reserve:
                    raise BudgetWait(reset_seconds(), "OpenAlex routine-update reserve reached")
            except BudgetWait as exc:
                not_before = time.time() + exc.seconds
                self.state.execute("UPDATE units SET status=CASE WHEN status IN ('PENDING','RUNNING','WAITING_BUDGET') THEN 'WAITING_BUDGET' ELSE status END,not_before=?,updated_at=? WHERE unit_key=?",
                                   (not_before, utc_now(), unit["unit_key"]))
                # The reserve applies to the whole collector, including a completed unit's last response.
                self.state.execute("UPDATE units SET not_before=? WHERE status!='COMPLETE'", (not_before,))
                self.state.commit()
                LOG.info("Supplement respects the shared reserve until %s", datetime.fromtimestamp(not_before, timezone.utc).isoformat())
            except Exception as exc:
                self.state.execute("UPDATE units SET status='ERROR',attempts=attempts+1,error=?,updated_at=? WHERE unit_key=?",
                                   (f"{type(exc).__name__}: {str(exc)[:250]}", utc_now(), unit["unit_key"]))
                self.state.commit()
                LOG.error("Supplemental unit %s requires attention: %s", unit["unit_key"], type(exc).__name__)
                time.sleep(2)
        result = self.status()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        write_new_json(self.directory / ("collection_report_" + stamp + ".json"), result)
        return result


def import_collected(directory, import_run, sqlite_identities=False):
    collector = SupplementCollector(directory)
    runner = None
    try:
        if not collector.status()["all_queries_reconciled"]:
            raise ValueError("All supplemental source queries must reconcile before import")
        runner = HistoryRunner(import_run, sqlite_identities=sqlite_identities)
        if str(Path(runner.manifest["db_path"]).resolve()) != collector.manifest["db_path"]:
            raise ValueError("Import target differs from the frozen source database")
        if any(runner.manifest[key] != collector.manifest[key] for key in ("from_date", "to_date")):
            raise ValueError("Import target has a different date scope")
        pages_verified, imported = 0, Counter()
        for page in collector.state.execute("SELECT * FROM pages ORDER BY unit_key,page").fetchall():
            path = collector.directory / page["path"]
            if digest(path) != page["sha256"]:
                raise ValueError("An immutable supplemental page hash changed")
            pages_verified += 1
            unit = dict(collector.state.execute("SELECT * FROM units WHERE unit_key=?", (page["unit_key"],)).fetchone())
            journal = collector.journals[unit["journal_key"]]
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                envelope = json.load(stream)
            expected_url, expected_params = supplement_spec(unit["kind"], journal, collector.manifest, page["cursor_before"])
            if envelope["url"] != expected_url or envelope["params"] != expected_params:
                raise ValueError("Supplemental page parameters changed")
            updates = []
            try:
                runner.main.execute("BEGIN IMMEDIATE")
                for item in envelope["data"]["results"]:
                    source_id = item.get("id") or hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
                    record = collector.state.execute("SELECT * FROM records WHERE unit_key=? AND source_id=?", (unit["unit_key"], source_id)).fetchone()
                    if record is None or record["disposition"] != "ELIGIBLE_PENDING_IMPORT":
                        continue
                    disposition, _, location = assess_work(item, journal, unit["kind"])
                    if disposition != "ELIGIBLE_PENDING_IMPORT":
                        raise ValueError("Saved publication evidence no longer matches the assessment")
                    for_parsing = dict(item, primary_location=location)
                    location_doi = published_location_doi(location)
                    if location_doi:
                        for_parsing["doi"] = "https://doi.org/" + location_doi
                    article = parse_openalex(for_parsing, journal)
                    # A supplemental location must not merge conflicting persistent identifiers.
                    conflict = runner.main.execute("SELECT doi FROM astar_articles WHERE openalex_id IN (?,?) AND doi IS NOT NULL",
                                                   (article.get("openalex_id"), "https://openalex.org/" + str(article.get("openalex_id")))).fetchall()
                    if article.get("doi") and any(normalize_doi(row[0]) != article["doi"] for row in conflict):
                        aid, outcome = None, "REVIEW_CONFLICTING_IDENTIFIER"
                    else:
                        aid, outcome = runner.ingest_article(article, journal)
                    updates.append((outcome, aid, utc_now(), unit["unit_key"], source_id))
                    imported[outcome] += 1
                runner.main.commit()
            except BaseException:
                runner.main.rollback()
                runner.refresh_indexes()
                raise
            # Commit import dispositions after the production commit. A crash safely replays by ID.
            collector.state.executemany("UPDATE records SET disposition=?,article_id=?,imported_at=? WHERE unit_key=? AND source_id=?", updates)
            collector.state.commit()
            if runner.sqlite_identities:
                # Release transaction-local additions only after both commits.
                runner.doi_index.clear()
                runner.oa_index.clear()
                runner.title_index.clear()
                runner.publisher_source_index.clear()
        result = dict(collector.status(), pages_hash_verified=pages_verified,
                      imported_this_pass=dict(imported), baseline_verification_required=True,
                      identity_backend="indexed_sqlite" if sqlite_identities else "cached",
                      preservation_policy="preserve_nonempty_baseline_fields_and_paid_classifications",
                      full_text_fetched=False)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        write_new_json(collector.directory / ("import_report_" + stamp + ".json"), result)
        return result
    finally:
        if runner is not None:
            runner.close()
        collector.close()
