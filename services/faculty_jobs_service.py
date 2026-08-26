# -*- coding: utf-8 -*-
"""Academic Career / Faculty Job Market domain service.

This module owns the private ``data/faculty_jobs.db`` store, source ingestion,
normalization, provenance, lifecycle rules and read APIs.  It intentionally
uses the repository's existing standard-library HTTPServer + SQLite approach.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import csv
import difflib
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading
from urllib.parse import urlparse

from services.faculty_job_fit_service import PROFILE_PATH, load_profile, save_profile, score_job
from services.faculty_jobs_normalizer import (
    COUNTRY_OPTIONS, DISCIPLINES, REGION_GROUPS, canonical_key, classify_business_scope,
    classify_faculty_market_role,
    country_code_for, country_display, hiring_cycle, hiring_cycle_reason,
    fingerprint_fields, infer_visa, is_mergeable_official_url,
    normalize_name, normalize_source_job, normalize_url, parse_deadline, parse_location,
)
from services.faculty_jobs_school_service import (
    add_evidence, compare_schools, list_schools, refresh_school_classification,
    list_institution_aliases, save_override, save_institution_alias, school_detail,
)
from services.faculty_jobs_sources import AdapterError, SourceJob, adapter_catalog
from services.faculty_jobs_sources.insidehighered import (
    IHE_SCHOOL_EVIDENCE_RULE_VERSION, InsideHigherEdAdapter,
)


ROOT = Path(__file__).resolve().parents[1]
FACULTY_DB_PATH = ROOT / "data" / "faculty_jobs.db"
FACULTY_CACHE_DIR = ROOT / "data" / "faculty_jobs_cache"
LOG = logging.getLogger(__name__)
_FACULTY_UPDATE_LOCK = threading.Lock()

ACTIVE_STATUSES = ("open", "likely_open", "closing_soon")
APPLICATION_STATES = (
    "Saved", "Interested", "Preparing", "Applied", "Screening Interview",
    "Campus Interview", "Offer", "Rejected", "Withdrawn", "Closed",
)


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _connect(db_path=None):
    if db_path is not None and not isinstance(db_path, (str, os.PathLike)):
        # Every public builder takes ``db_path`` first and ``query`` second.
        # Passing a filter dict positionally used to stringify into a filename
        # and quietly create an empty database, so the caller got a schema-
        # correct empty result instead of an error.  Refuse it outright.
        raise TypeError(
            "db_path must be a filesystem path, got "
            f"{type(db_path).__name__}; pass filters as query=... by keyword")
    path = str(db_path or FACULTY_DB_PATH)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _table_columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn, table, name, definition):
    if name not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _migrate_job_sources_primary_key(conn):
    """Preserve early databases while allowing one source to map to merged jobs.

    The first schema draft used ``(job_id, source_id)`` as the primary key.
    That is too restrictive when two source records from the same board are
    conservatively merged into one canonical job.  SQLite cannot alter a
    composite primary key in place, so rebuild this small private table and
    copy its rows forward.
    """
    info = conn.execute("PRAGMA table_info(job_sources)").fetchall()
    if not info:
        return
    primary_key = [row["name"] for row in sorted(info, key=lambda item: item["pk"]) if row["pk"]]
    desired = ["job_id", "source_id", "source_job_id"]
    if primary_key == desired:
        return
    columns = {row["name"] for row in info}
    missing_runs = "consecutive_missing_runs" if "consecutive_missing_runs" in columns else "0"
    conn.execute("DROP TABLE IF EXISTS job_sources_migrated")
    conn.execute("""
        CREATE TABLE job_sources_migrated (
            job_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            source_job_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            official_url TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            consecutive_missing_runs INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(job_id, source_id, source_job_id),
            UNIQUE(source_id, source_job_id),
            FOREIGN KEY(job_id) REFERENCES jobs(id),
            FOREIGN KEY(source_id) REFERENCES sources(id)
        )
    """)
    conn.execute(f"""
        INSERT OR IGNORE INTO job_sources_migrated
          (job_id,source_id,source_job_id,source_url,official_url,first_seen,last_seen,active,consecutive_missing_runs)
        SELECT job_id,source_id,source_job_id,source_url,official_url,first_seen,last_seen,active,{missing_runs}
        FROM job_sources
    """)
    conn.execute("DROP TABLE job_sources")
    conn.execute("ALTER TABLE job_sources_migrated RENAME TO job_sources")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_faculty_job_sources_source ON job_sources(source_id, active)")


def _ensure_aacsb_tables(conn):
    """Create the opt-in AACSB school roster and official-site scan ledger."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS aacsb_directory_schools (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        directory_result_id TEXT NOT NULL UNIQUE,
        directory_url TEXT NOT NULL UNIQUE,
        institution_name TEXT NOT NULL,
        school_name TEXT,
        directory_title TEXT NOT NULL,
        location_raw TEXT,
        city TEXT,
        state_province TEXT,
        country TEXT,
        country_code TEXT,
        region_group TEXT,
        official_website TEXT,
        accreditation_scope TEXT,
        roster_source_url TEXT NOT NULL,
        record_excerpt TEXT,
        source_hash TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        detail_status TEXT NOT NULL DEFAULT 'not_checked',
        detail_checked_at TEXT,
        website_status TEXT NOT NULL DEFAULT 'not_checked',
        website_checked_at TEXT,
        career_page_url TEXT,
        career_page_status TEXT NOT NULL DEFAULT 'not_checked',
        job_scan_status TEXT NOT NULL DEFAULT 'not_checked',
        jobs_found INTEGER NOT NULL DEFAULT 0,
        candidates_seen INTEGER NOT NULL DEFAULT 0,
        candidates_rejected INTEGER NOT NULL DEFAULT 0,
        scan_rule_version TEXT,
        last_job_scan_at TEXT,
        job_scan_reason TEXT,
        linked_business_school_id INTEGER,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(linked_business_school_id) REFERENCES business_schools(id)
    );
    CREATE TABLE IF NOT EXISTS aacsb_scan_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        directory_school_id INTEGER NOT NULL,
        checked_at TEXT NOT NULL,
        official_website TEXT,
        career_page_url TEXT,
        website_status TEXT NOT NULL,
        career_page_status TEXT NOT NULL,
        job_scan_status TEXT NOT NULL,
        jobs_found INTEGER NOT NULL DEFAULT 0,
        candidates_seen INTEGER NOT NULL DEFAULT 0,
        candidates_rejected INTEGER NOT NULL DEFAULT 0,
        scan_rule_version TEXT,
        response_status INTEGER,
        reason TEXT,
        FOREIGN KEY(directory_school_id) REFERENCES aacsb_directory_schools(id)
    );
    CREATE TABLE IF NOT EXISTS aacsb_scan_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        pages_fetched INTEGER NOT NULL DEFAULT 0,
        records_seen INTEGER NOT NULL DEFAULT 0,
        records_upserted INTEGER NOT NULL DEFAULT 0,
        details_fetched INTEGER NOT NULL DEFAULT 0,
        websites_checked INTEGER NOT NULL DEFAULT 0,
        jobs_found INTEGER NOT NULL DEFAULT 0,
        candidates_seen INTEGER NOT NULL DEFAULT 0,
        candidates_rejected INTEGER NOT NULL DEFAULT 0,
        scan_rule_version TEXT,
        directory_results_reported INTEGER,
        directory_results_observed INTEGER,
        non_accredited_results_excluded INTEGER,
        directory_observation_complete INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0,
        max_pages INTEGER,
        max_schools INTEGER,
        scan_websites INTEGER NOT NULL DEFAULT 0,
        error_summary TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_aacsb_directory_country ON aacsb_directory_schools(country_code, active);
    CREATE INDEX IF NOT EXISTS idx_aacsb_directory_jobs ON aacsb_directory_schools(job_scan_status, active);
    CREATE INDEX IF NOT EXISTS idx_aacsb_directory_school ON aacsb_directory_schools(linked_business_school_id);
    CREATE INDEX IF NOT EXISTS idx_aacsb_scan_history_school ON aacsb_scan_history(directory_school_id, checked_at);
    """)
    _ensure_column(conn, "aacsb_directory_schools", "candidates_seen", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "aacsb_directory_schools", "candidates_rejected", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "aacsb_directory_schools", "scan_rule_version", "TEXT")
    _ensure_column(conn, "aacsb_scan_history", "candidates_seen", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "aacsb_scan_history", "candidates_rejected", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "aacsb_scan_history", "scan_rule_version", "TEXT")
    _ensure_column(conn, "aacsb_scan_runs", "candidates_seen", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "aacsb_scan_runs", "candidates_rejected", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "aacsb_scan_runs", "scan_rule_version", "TEXT")
    _ensure_column(conn, "aacsb_scan_runs", "directory_results_reported", "INTEGER")
    _ensure_column(conn, "aacsb_scan_runs", "directory_results_observed", "INTEGER")
    _ensure_column(conn, "aacsb_scan_runs", "non_accredited_results_excluded", "INTEGER")
    _ensure_column(conn, "aacsb_scan_runs", "directory_observation_complete", "INTEGER NOT NULL DEFAULT 0")
    # This source is deliberately opt-in: the regular daily job-board refresh
    # must not launch a thousand-school website reconnaissance run.
    timestamp = now_utc()
    conn.execute("""
        INSERT INTO sources
          (name,region,base_url,enabled,adapter_name,priority,method,support_status,support_reason,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(name) DO UPDATE SET
          region=excluded.region,base_url=excluded.base_url,adapter_name=excluded.adapter_name,
          priority=excluded.priority,method=excluded.method,support_status=excluded.support_status,
          support_reason=excluded.support_reason,updated_at=excluded.updated_at
    """, (
        "aacsb_official", "Global", "https://www.aacsb.edu/accredited", 0,
        "aacsb_official", 30, "aacsb_roster_plus_official_site",
        "opt_in", "Opt-in bounded scan; not part of the default daily update because it visits public school websites.",
        timestamp, timestamp,
    ))


def ensure_faculty_jobs_tables(db_path=None):
    """Create/migrate the domain database idempotently and quickly."""
    conn = _connect(db_path)
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            region TEXT NOT NULL,
            base_url TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            adapter_name TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 50,
            method TEXT NOT NULL DEFAULT 'public_html',
            support_status TEXT NOT NULL DEFAULT 'enabled',
            support_reason TEXT,
            last_success_at TEXT,
            last_attempt_at TEXT,
            last_status TEXT NOT NULL DEFAULT 'never',
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ingestion_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            pages_fetched INTEGER NOT NULL DEFAULT 0,
            items_seen INTEGER NOT NULL DEFAULT 0,
            items_inserted INTEGER NOT NULL DEFAULT 0,
            items_updated INTEGER NOT NULL DEFAULT 0,
            items_merged INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT,
            FOREIGN KEY(source_id) REFERENCES sources(id)
        );
        CREATE TABLE IF NOT EXISTS institutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            official_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            country TEXT,
            country_code TEXT,
            region_group TEXT,
            state_province TEXT,
            city TEXT,
            institution_url TEXT,
            university_research_level TEXT NOT NULL DEFAULT 'Unknown',
            university_research_level_system TEXT,
            research_memberships_json TEXT NOT NULL DEFAULT '[]',
            carnegie_class TEXT,
            u15_member INTEGER,
            is_current INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(normalized_name, country_code)
        );
        CREATE TABLE IF NOT EXISTS business_schools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institution_id INTEGER NOT NULL,
            official_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            website TEXT,
            aacsb INTEGER,
            equis INTEGER,
            amba INTEGER,
            doctoral_business_program INTEGER,
            business_research_tier TEXT NOT NULL DEFAULT 'Unclassified',
            business_research_tier_score REAL,
            business_research_tier_confidence TEXT NOT NULL DEFAULT 'Low',
            management_strength TEXT,
            is_strength TEXT,
            marketing_strength TEXT,
            finance_strength TEXT,
            accounting_strength TEXT,
            operations_strength TEXT,
            last_verified_at TEXT,
            is_current INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(institution_id, normalized_name),
            FOREIGN KEY(institution_id) REFERENCES institutions(id)
        );
        CREATE TABLE IF NOT EXISTS school_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER NOT NULL,
            evidence_type TEXT NOT NULL,
            value TEXT NOT NULL,
            source_name TEXT,
            source_url TEXT NOT NULL,
            source_date TEXT,
            verified_at TEXT NOT NULL,
            confidence TEXT NOT NULL DEFAULT 'medium',
            notes TEXT,
            FOREIGN KEY(school_id) REFERENCES business_schools(id)
        );
        CREATE TABLE IF NOT EXISTS school_tier_overrides (
            school_id INTEGER PRIMARY KEY,
            tier TEXT NOT NULL,
            reason TEXT NOT NULL,
            source_url TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(school_id) REFERENCES business_schools(id)
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_key TEXT NOT NULL UNIQUE,
            title_raw TEXT NOT NULL,
            title_normalized TEXT NOT NULL,
            institution_id INTEGER,
            school_id INTEGER,
            department TEXT,
            description_excerpt TEXT,
            discipline_primary TEXT NOT NULL DEFAULT 'Other',
            discipline_secondary_json TEXT NOT NULL DEFAULT '[]',
            classification_reason TEXT,
            business_scope TEXT NOT NULL DEFAULT 'unknown',
            business_scope_confidence TEXT NOT NULL DEFAULT 'low',
            business_scope_reason TEXT,
            faculty_market_role TEXT NOT NULL DEFAULT 'unknown',
            faculty_market_eligible INTEGER NOT NULL DEFAULT 0,
            faculty_market_reason TEXT,
            school_evidence_context TEXT NOT NULL DEFAULT 'unknown',
            keywords_json TEXT NOT NULL DEFAULT '[]',
            rank_raw TEXT,
            rank_normalized TEXT,
            career_stage TEXT NOT NULL DEFAULT 'unknown',
            rank_mapping_confidence REAL,
            rank_mapping_explanation TEXT,
            track_type TEXT NOT NULL DEFAULT 'unknown',
            contract_type TEXT,
            employment_type TEXT,
            contract_length TEXT,
            country TEXT,
            country_code TEXT,
            region_group TEXT,
            state_province TEXT,
            city TEXT,
            location_evidence TEXT,
            remote_type TEXT,
            posted_date TEXT,
            deadline_date TEXT,
            deadline_mode TEXT NOT NULL DEFAULT 'unknown',
            deadline_evidence TEXT,
            deadline_parse_reason TEXT,
            start_term TEXT,
            start_year INTEGER,
            hiring_cycle TEXT,
            salary_raw TEXT,
            salary_min REAL,
            salary_max REAL,
            salary_currency TEXT,
            salary_period TEXT,
            phd_required INTEGER,
            phd_required_by TEXT,
            teaching_areas_json TEXT NOT NULL DEFAULT '[]',
            research_areas_json TEXT NOT NULL DEFAULT '[]',
            teaching_load_raw TEXT,
            visa_text TEXT,
            visa_status TEXT NOT NULL DEFAULT 'unknown',
            language_requirements TEXT,
            official_url TEXT,
            original_title TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'unknown',
            closed_at TEXT,
            verification_note TEXT,
            hiring_cycle_reason TEXT,
            derived_quality TEXT NOT NULL DEFAULT 'accepted',
            fingerprint TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(institution_id) REFERENCES institutions(id),
            FOREIGN KEY(school_id) REFERENCES business_schools(id)
        );
        CREATE TABLE IF NOT EXISTS job_sources (
            job_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            source_job_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            official_url TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            consecutive_missing_runs INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(job_id, source_id, source_job_id),
            UNIQUE(source_id, source_job_id),
            FOREIGN KEY(job_id) REFERENCES jobs(id),
            FOREIGN KEY(source_id) REFERENCES sources(id)
        );
        CREATE TABLE IF NOT EXISTS source_job_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            source_job_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            official_url TEXT,
            content_hash TEXT NOT NULL,
            short_excerpt TEXT,
            structured_extraction TEXT NOT NULL DEFAULT '{}',
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            UNIQUE(source_id, source_job_id),
            FOREIGN KEY(source_id) REFERENCES sources(id)
        );
        CREATE TABLE IF NOT EXISTS job_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            observed_at TEXT NOT NULL,
            status TEXT NOT NULL,
            deadline TEXT,
            salary_raw TEXT,
            title_raw TEXT,
            source_count INTEGER NOT NULL DEFAULT 0,
            change_reason TEXT,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        );
        CREATE TABLE IF NOT EXISTS job_field_provenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            source_id INTEGER,
            source_job_id TEXT,
            source_url TEXT,
            value_text TEXT,
            evidence_text TEXT,
            captured_at TEXT NOT NULL,
            is_current INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(job_id) REFERENCES jobs(id),
            FOREIGN KEY(source_id) REFERENCES sources(id)
        );
        CREATE TABLE IF NOT EXISTS possible_duplicates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            possible_job_id INTEGER NOT NULL,
            confidence REAL NOT NULL,
            match_basis TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            resolution TEXT,
            resolved_at TEXT,
            resolution_reason TEXT,
            merged_into_job_id INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(job_id, possible_job_id)
        );
        CREATE TABLE IF NOT EXISTS user_job_state (
            job_id INTEGER PRIMARY KEY,
            state TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            saved_at TEXT NOT NULL,
            applied_at TEXT,
            updated_at TEXT NOT NULL,
            notes TEXT,
            cv_version TEXT,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        );
        CREATE TABLE IF NOT EXISTS application_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_date TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        );
        CREATE TABLE IF NOT EXISTS source_coverage_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at TEXT NOT NULL,
            enabled_sources_json TEXT NOT NULL DEFAULT '[]',
            successful_sources_json TEXT NOT NULL DEFAULT '[]',
            scope TEXT NOT NULL DEFAULT 'business',
            jobs_observed INTEGER NOT NULL DEFAULT 0,
            business_jobs_observed INTEGER NOT NULL DEFAULT 0,
            explicit_school_jobs INTEGER NOT NULL DEFAULT 0,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS institution_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias_normalized TEXT NOT NULL UNIQUE,
            canonical_name TEXT NOT NULL,
            reason TEXT NOT NULL,
            source_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS faculty_job_repair_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at TEXT NOT NULL,
            action TEXT NOT NULL,
            job_id INTEGER,
            source_id INTEGER,
            source_job_id TEXT,
            old_value TEXT,
            new_value TEXT,
            reason TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(id),
            FOREIGN KEY(source_id) REFERENCES sources(id)
        );
        CREATE TABLE IF NOT EXISTS faculty_job_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS job_scope_overrides (
            job_id INTEGER PRIMARY KEY,
            action TEXT NOT NULL CHECK(action IN ('include','exclude')),
            reason TEXT NOT NULL,
            source_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        );
        CREATE TABLE IF NOT EXISTS saved_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            query_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_checked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS saved_search_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            matched_at TEXT NOT NULL,
            seen_at TEXT,
            FOREIGN KEY(search_id) REFERENCES saved_searches(id) ON DELETE CASCADE,
            FOREIGN KEY(job_id) REFERENCES jobs(id),
            UNIQUE(search_id, job_id)
        );
        CREATE INDEX IF NOT EXISTS idx_faculty_saved_search_alerts_search ON saved_search_alerts(search_id, seen_at);
        CREATE INDEX IF NOT EXISTS idx_faculty_saved_search_alerts_job ON saved_search_alerts(job_id);
        CREATE INDEX IF NOT EXISTS idx_faculty_duplicates_unresolved ON possible_duplicates(resolved, confidence);
        CREATE INDEX IF NOT EXISTS idx_faculty_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_faculty_jobs_country ON jobs(country_code);
        CREATE INDEX IF NOT EXISTS idx_faculty_jobs_region ON jobs(region_group);
        CREATE INDEX IF NOT EXISTS idx_faculty_jobs_discipline ON jobs(discipline_primary);
        CREATE INDEX IF NOT EXISTS idx_faculty_jobs_rank ON jobs(rank_normalized);
        CREATE INDEX IF NOT EXISTS idx_faculty_jobs_stage ON jobs(career_stage);
        CREATE INDEX IF NOT EXISTS idx_faculty_jobs_track ON jobs(track_type);
        CREATE INDEX IF NOT EXISTS idx_faculty_jobs_posted ON jobs(posted_date);
        CREATE INDEX IF NOT EXISTS idx_faculty_jobs_deadline ON jobs(deadline_date);
        CREATE INDEX IF NOT EXISTS idx_faculty_jobs_first_seen ON jobs(first_seen_at);
        CREATE INDEX IF NOT EXISTS idx_faculty_jobs_institution ON jobs(institution_id);
        CREATE INDEX IF NOT EXISTS idx_faculty_jobs_school ON jobs(school_id);
        CREATE INDEX IF NOT EXISTS idx_faculty_job_sources_source ON job_sources(source_id, active);
        CREATE INDEX IF NOT EXISTS idx_faculty_provenance_job ON job_field_provenance(job_id, field_name);
        CREATE INDEX IF NOT EXISTS idx_faculty_history_observed ON job_status_history(observed_at);
        """)
        _ensure_aacsb_tables(conn)
        _migrate_job_sources_primary_key(conn)
        # A small compatibility migration hook keeps a manually created early
        # database usable if a field is added later.
        _ensure_column(conn, "jobs", "verification_note", "TEXT")
        _ensure_column(conn, "jobs", "description_excerpt", "TEXT")
        _ensure_column(conn, "jobs", "business_scope", "TEXT NOT NULL DEFAULT 'unknown'")
        _ensure_column(conn, "jobs", "business_scope_confidence", "TEXT NOT NULL DEFAULT 'low'")
        _ensure_column(conn, "jobs", "business_scope_reason", "TEXT")
        _ensure_column(conn, "jobs", "faculty_market_role", "TEXT NOT NULL DEFAULT 'unknown'")
        _ensure_column(conn, "jobs", "faculty_market_eligible", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "jobs", "faculty_market_reason", "TEXT")
        _ensure_column(conn, "jobs", "school_evidence_context", "TEXT NOT NULL DEFAULT 'unknown'")
        _ensure_column(conn, "jobs", "deadline_evidence", "TEXT")
        _ensure_column(conn, "jobs", "deadline_parse_reason", "TEXT")
        _ensure_column(conn, "jobs", "location_evidence", "TEXT")
        _ensure_column(conn, "jobs", "original_title", "TEXT")
        _ensure_column(conn, "jobs", "hiring_cycle_reason", "TEXT")
        _ensure_column(conn, "jobs", "derived_quality", "TEXT NOT NULL DEFAULT 'accepted'")
        _ensure_column(conn, "institutions", "is_current", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "business_schools", "is_current", "INTEGER NOT NULL DEFAULT 1")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_faculty_jobs_business_scope ON jobs(business_scope)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_faculty_jobs_market_eligible ON jobs(faculty_market_eligible)")
        _ensure_column(conn, "job_sources", "consecutive_missing_runs", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "job_field_provenance", "is_current", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "possible_duplicates", "resolution", "TEXT")
        _ensure_column(conn, "possible_duplicates", "resolved_at", "TEXT")
        _ensure_column(conn, "possible_duplicates", "resolution_reason", "TEXT")
        _ensure_column(conn, "possible_duplicates", "merged_into_job_id", "INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_faculty_provenance_current ON job_field_provenance(job_id,field_name,is_current)")
        _sync_source_catalog(conn)
        _run_faculty_jobs_repair_if_needed(conn)
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=3").fetchone():
            _repair_duplicate_review_metadata(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (3, now_utc(), "Legacy fuzzy duplicate labels converted to review-only metadata; same-source fingerprint collisions retained for manual review."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=4").fetchone():
            _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (4, now_utc(), "Legacy orphan institution and school rows retained for audit but deactivated from active explorer views."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=5").fetchone():
            _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (5, now_utc(), "Bounded salary evidence replay from preserved source excerpts."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=6").fetchone():
            _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (6, now_utc(), "Generic recruitment portals removed from derived official application URLs; preserved source-record values remain available for audit."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=7").fetchone():
            _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (7, now_utc(), "Country evidence precedence replay: uppercase ISO codes only, institution hints for KAUST, and non-city location labels/street addresses removed."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=8").fetchone():
            _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (8, now_utc(), "Avoided interpreting regional phrases such as North America as United States; replayed institution-country evidence."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=9").fetchone():
            _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (9, now_utc(), "Split explicit business-school employer labels from university entities; added conservative WPI and school-name parsing."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=10").fetchone():
            _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (10, now_utc(), "Removed discipline/title prefixes from Business School entity extraction while preserving explicit school names."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=11").fetchone():
            _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (11, now_utc(), "Removed parenthetical work-mode descriptors from normalized city values."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=12").fetchone():
            _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (12, now_utc(), "Linked the guarded DMSB abbreviation to the University of South Carolina's Darla Moore School of Business."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=13").fetchone():
            row = conn.execute("""
                SELECT bs.id, bs.official_name
                FROM business_schools bs JOIN institutions i ON i.id=bs.institution_id
                WHERE i.official_name=? AND bs.official_name=?
            """, ("University of Leeds", "Faculty of Business")).fetchone()
            if row:
                target = conn.execute("""
                    SELECT bs.id
                    FROM business_schools bs JOIN institutions i ON i.id=bs.institution_id
                    WHERE i.official_name=? AND bs.normalized_name=?
                """, ("University of Leeds", normalize_name("Leeds University Business School"))).fetchone()
                if target and int(target["id"]) != int(row["id"]):
                    # A legacy replay may have created the official target
                    # entity before this rename migration runs. Re-point
                    # derived job links and retain the old row as an
                    # inactive audit record instead of violating the unique
                    # institution/name constraint.
                    conn.execute("UPDATE jobs SET school_id=? WHERE school_id=?", (target["id"], row["id"]))
                    conn.execute("UPDATE business_schools SET is_current=0, updated_at=? WHERE id=?", (now_utc(), row["id"]))
                    new_value = "Leeds University Business School (merged into existing target)"
                else:
                    conn.execute("""
                        UPDATE business_schools
                        SET official_name=?, normalized_name=?, updated_at=?
                        WHERE id=?
                    """, ("Leeds University Business School", normalize_name("Leeds University Business School"), now_utc(), row["id"]))
                    new_value = "Leeds University Business School"
                conn.execute("""
                    INSERT INTO faculty_job_repair_audit
                      (observed_at,action,source_id,old_value,new_value,reason)
                    VALUES (?,?,?,?,?,?)
                """, (now_utc(), "school_entity_alias_repair", None, row["official_name"], new_value, "Official University of Leeds business-school page provides the stable derived entity name; source listing wording remains in provenance."))
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (13, now_utc(), "Normalized the University of Leeds Faculty of Business listing label to the official Leeds University Business School entity."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=14").fetchone():
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (14, now_utc(), "Added private saved-search alerts, auditable duplicate-review resolution fields, and local institution-alias management metadata."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=15").fetchone():
            _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (15, now_utc(), "Cleared Inside Higher Ed cards that expose a business-school/department label as location; retained country evidence and source excerpts."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=16").fetchone():
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (16, now_utc(), "Added opt-in AACSB accredited-school roster, official-website scan ledger, and bounded no-job/blocked status history."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=17").fetchone():
            quarantined = conn.execute("""
                SELECT DISTINCT j.id,j.business_scope,j.business_scope_confidence,j.status
                FROM jobs j JOIN job_sources js ON js.job_id=j.id
                JOIN sources s ON s.id=js.source_id
                WHERE s.name='aacsb_official'
            """).fetchall()
            quarantine_reason = "Quarantined pending AACSB official-site parser evidence; a roster link alone is not a job posting. Source record, provenance, and history are retained."
            for row in quarantined:
                conn.execute("""
                    UPDATE jobs SET derived_quality='quarantined',business_scope='unknown',
                      business_scope_confidence='low',business_scope_reason=?,status='unknown',updated_at=? WHERE id=?
                """, (quarantine_reason, now_utc(), row["id"]))
                conn.execute("""
                    INSERT INTO faculty_job_repair_audit
                      (observed_at,action,job_id,old_value,new_value,reason)
                    VALUES (?,?,?,?,?,?)
                """, (now_utc(), "aacsb_job_link_quarantine",
                       row["id"], json.dumps({"business_scope": row["business_scope"], "status": row["status"]}, ensure_ascii=False),
                       json.dumps({"derived_quality": "quarantined", "business_scope": "unknown", "status": "unknown"}, ensure_ascii=False),
                       quarantine_reason))
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (17, now_utc(), "Quarantined prior AACSB broad-link derived rows; only explicit business academic posting evidence can restore an accepted derived job."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=18").fetchone():
            _repair_aacsb_directory_location_evidence(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (18, now_utc(), "Replayed AACSB directory location evidence with the centralized country aliases and corrected derived job/institution geography without changing source records."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=19").fetchone():
            _quarantine_aacsb_explicit_nonbusiness_jobs(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (19, now_utc(), "Quarantined explicit non-business academic fields discovered on mixed official school pages; source records and provenance remain available for audit."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=20").fetchone():
            _repair_inside_higher_ed_location_labels(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (20, now_utc(), "Cleared an Inside Higher Ed business-school label that had survived as a city; country evidence and the original source excerpt remain preserved."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=21").fetchone():
            _repair_inside_higher_ed_institutions_from_excerpts(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (21, now_utc(), "Replayed the stricter Inside Higher Ed employer parser over preserved listing excerpts; detail-page enrichment remains explicitly budgeted."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=22").fetchone():
            _repair_inside_higher_ed_institution_names(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (22, now_utc(), "Trimmed concatenated Inside Higher Ed location/department/UI text from explicit employer values without changing source records."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=23").fetchone():
            _repair_inside_higher_ed_valid_through_deadlines(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (23, now_utc(), "Removed IHE JobPosting validThrough board-expiry dates unless bounded detail text supplied explicit application-deadline or rolling evidence."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=24").fetchone():
            _repair_academic_entity_labels_and_country_aliases(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (24, now_utc(), "Merged known institution-country aliases, corrected ambiguous Canadian location codes, and removed portal labels from active business-school entities without deleting source records."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=25").fetchone():
            stats = _repair_faculty_market_boundary(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (25, now_utc(), (
                    "Added an explicit individual faculty-role gate, removed roster-only school associations "
                    f"from job evidence, and quarantined {stats['aacsb_quarantined']} ineligible AACSB-derived records "
                    "without deleting source records."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=26").fetchone():
            _repair_inside_higher_ed_iso_only_locations(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (26, now_utc(), "Reclassified bare Inside Higher Ed ISO country tokens as country evidence rather than city values, preserving source records and repair provenance."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=27").fetchone():
            _repair_inside_higher_ed_school_links_from_records(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (27, now_utc(), "Restored explicit Inside Higher Ed business-school links from preserved structured source fields without inferring schools from locations."),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=28").fetchone():
            boundary_stats = _repair_faculty_market_boundary(conn)
            location_stats = _repair_source_location_country_mismatches(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (28, now_utc(), (
                    "Replayed the stricter individual-vacancy/business-unit boundary after IHE school-link repair; "
                    f"changed {boundary_stats['changed']} jobs, cleared {boundary_stats['school_links_cleared']} unsupported school links, "
                    f"and repaired {location_stats['changed_jobs']} high-confidence source-location country mismatches without changing source records."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=29").fetchone():
            school_stats = _repair_inside_higher_ed_school_links_from_records(conn)
            boundary_stats = _repair_faculty_market_boundary(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (29, now_utc(), (
                    "Replayed explicit IHE structured school evidence after the faculty-market boundary repair; "
                    f"restored {school_stats['changed_jobs']} posting-level school links and reclassified "
                    f"{boundary_stats['changed']} derived rows without changing source records."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=30").fetchone():
            replay_stats = _repair_overbroad_location_replay(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (30, now_utc(), (
                    "Forward-corrected an early v28 evidence-only replay by restoring "
                    f"{replay_stats['restored_jobs']} unchanged jobs' prior location-evidence labels; "
                    "superseded provenance/audit records were retained and marked non-current."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=31").fetchone():
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (31, now_utc(), (
                    "Versioned AACSB official-site scan evidence so legacy parser results remain visible but are not counted as checks under the current faculty-role/business-scope rules."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=32").fetchone():
            scope_stats = _repair_faculty_market_boundary(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (32, now_utc(), (
                    "Replayed expanded non-business and ambiguous-management field rules; "
                    f"changed {scope_stats['changed']} jobs and cleared {scope_stats['school_links_cleared']} unsupported school links while preserving source evidence."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=33").fetchone():
            scope_stats = _repair_faculty_market_boundary(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (33, now_utc(), (
                    "Revalidated legacy IHE school associations against the current bounded posting-evidence rule; "
                    f"changed {scope_stats['changed']} jobs and cleared {scope_stats['school_links_cleared']} stale school links "
                    "without deleting source records or private application state."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=34").fetchone():
            school_stats = _repair_business_school_entity_labels(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (34, now_utc(), (
                    "Removed bounded job-board chrome from derived business-school labels, merged "
                    f"{school_stats['merged']} duplicate school entities, renamed {school_stats['renamed']}, "
                    f"and deactivated {school_stats['orphans_deactivated']} unreferenced derived rows; source and evidence ledgers were preserved."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=35").fetchone():
            scope_stats = _repair_faculty_market_boundary(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (35, now_utc(), (
                    "Applied the explicit law-school and late title-boundary follow-up after v33 had already run; "
                    f"changed {scope_stats['changed']} jobs and cleared {scope_stats['school_links_cleared']} school links."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=36").fetchone():
            status_stats = _repair_job_status_recency(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (36, now_utc(), (
                    "Reclassified active-looking records with passed fixed deadlines or posting dates older than 365 days; "
                    f"changed {status_stats['changed']} statuses while retaining every source record and history row."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=37").fetchone():
            scope_stats = _repair_faculty_market_boundary(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (37, now_utc(), (
                    "Replayed the strict role/business-unit boundary after a long-lived pre-repair server process "
                    "silently rewrote derived scope fields; "
                    f"changed {scope_stats['changed']} jobs and cleared {scope_stats['school_links_cleared']} school links."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=38").fetchone():
            location_stats = _repair_source_location_country_mismatches(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (38, now_utc(), (
                    "Replayed preserved source locations after the Washington D.C. boundary fix; "
                    f"changed {location_stats['changed_jobs']} jobs and repaired "
                    f"{location_stats['institution_links_repaired']} institution links without changing source records."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=39").fetchone():
            school_stats = _repair_inside_higher_ed_school_links_from_records(conn)
            boundary_stats = _repair_faculty_market_boundary(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (39, now_utc(), (
                    "Replayed the expanded bounded IHE detail-school parser over preserved excerpts; "
                    f"restored {school_stats['changed_jobs']} posting-level school links and "
                    f"changed {boundary_stats['changed']} derived boundary rows without refetching or deleting source records."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=40").fetchone():
            label_stats = _repair_business_school_entity_labels(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (40, now_utc(), (
                    "Cleaned remaining derived IHE school labels with bounded portal chrome; "
                    f"merged {label_stats['merged']} duplicate entities, renamed {label_stats['renamed']}, "
                    f"and deactivated {label_stats['orphans_deactivated']} unreferenced rows while preserving source evidence."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=41").fetchone():
            label_stats = _repair_business_school_entity_labels(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (41, now_utc(), (
                    "Cleaned a bounded source-detail school prefix such as 'Ohio The Raj Soin College of Business' "
                    f"and reconciled {label_stats['merged']} duplicate entities, renamed {label_stats['renamed']}, "
                    f"and deactivated {label_stats['orphans_deactivated']} unreferenced rows without changing source records."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=42").fetchone():
            repair_stats = _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (42, now_utc(), (
                    "Replayed all canonical derived fields from preserved source records after the deadline/detail-parser fixes; "
                    f"reprocessed {repair_stats['links']} source links across {repair_stats['groups']} safe identity groups, "
                    f"split {repair_stats['split']} same-source placements and merged {repair_stats['merged']} exact-identity groups "
                    "without deleting source records, provenance, history, or private application state."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=43").fetchone():
            repaired = _repair_inside_higher_ed_institutions_from_excerpts(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (43, now_utc(), (
                    "Recovered bounded explicit IHE university names separated from campus/business-school punctuation; "
                    f"repaired {repaired} institution links without using city text or refetching source pages."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=44").fetchone():
            repair_stats = _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (44, now_utc(), (
                    "Replayed the IHE employer/campus separator after recovering punctuation-delimited university names; "
                    f"reprocessed {repair_stats['links']} source links and removed institution labels from derived city values "
                    "without changing source records."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=45").fetchone():
            repair_stats = _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (45, now_utc(), (
                    "Corrected punctuation-delimited IHE campus parsing after the case-insensitive employer/location guard; "
                    f"reprocessed {repair_stats['links']} source links while preserving source and private records."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=46").fetchone():
            repair_stats = _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (46, now_utc(), (
                    "Reused majority-country evidence for normalized institutions when public cards omitted country text and "
                    f"reprocessed {repair_stats['links']} source links; ambiguous institutions remain Unknown rather than guessed."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=47").fetchone():
            repair_stats = _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (47, now_utc(), (
                    "Preferred a previously evidenced majority-country institution row even when an empty-country duplicate existed; "
                    f"reprocessed {repair_stats['links']} source links and retained conflicting aliases for audit."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=48").fetchone():
            repair_stats = _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (48, now_utc(), (
                    "Cleared IHE description/card chrome from derived city values when no structured location survived and "
                    f"reprocessed {repair_stats['links']} source links; retained bounded excerpts as evidence."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=49").fetchone():
            repair_stats = _repair_derived_data(conn)
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (49, now_utc(), (
                    "Cleared remaining IHE narrative phrases containing university/system text from city fields; "
                    f"reprocessed {repair_stats['links']} source links without replacing them with guessed cities."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=50").fetchone():
            # business_scope is derived at ingest, so classifier improvements do
            # not reach stored rows on their own.  35% of jobs sat in 'unknown';
            # replaying the boundary applies the 2026-08-26 role and field rules
            # (plural professor titles, bare "business", French postings, senior
            # administration, observed non-business fields) to existing records.
            # Derived fields only: no source row, source link or raw excerpt is
            # touched, and quarantined records are skipped as always.
            before = dict(conn.execute(
                "SELECT business_scope, COUNT(*) FROM jobs GROUP BY business_scope").fetchall())
            _backfill_business_scope(conn)
            after = dict(conn.execute(
                "SELECT business_scope, COUNT(*) FROM jobs GROUP BY business_scope").fetchall())
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (50, now_utc(), (
                    "Replayed business_scope with the 2026-08-26 role/field rules. "
                    f"unknown {before.get('unknown', 0)} -> {after.get('unknown', 0)}; "
                    f"business_school {before.get('business_school', 0)} -> {after.get('business_school', 0)}; "
                    f"business_discipline {before.get('business_discipline', 0)} -> {after.get('business_discipline', 0)}; "
                    f"non_business {before.get('non_business', 0)} -> {after.get('non_business', 0)}."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=51").fetchone():
            # visa_status was inverted for every job it claimed to know about:
            # the affirmative pattern "eligible.*sponsorship" matched inside
            # "not eligible for sponsorship" and ran before the refusal check.
            # Replay it with the corrected precedence over the same title +
            # department + excerpt text the ingest path uses.
            before = dict(conn.execute(
                "SELECT COALESCE(visa_status,'unknown'), COUNT(*) FROM jobs GROUP BY 1").fetchall())
            changed = 0
            for row in conn.execute(
                "SELECT id, title_raw, department, description_excerpt, visa_status FROM jobs"
            ).fetchall():
                combined = " ".join(item for item in (
                    row["title_raw"] or "", row["department"] or "",
                    row["description_excerpt"] or "") if item)
                status = infer_visa(combined)
                if status == (row["visa_status"] or "unknown"):
                    continue
                # visa_text holds source-quoted text, not derived evidence, so
                # the replay touches the derived status only.
                conn.execute("UPDATE jobs SET visa_status=? WHERE id=?", (status, row["id"]))
                changed += 1
            after = dict(conn.execute(
                "SELECT COALESCE(visa_status,'unknown'), COUNT(*) FROM jobs GROUP BY 1").fetchall())
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (51, now_utc(), (
                    "Replayed visa_status after correcting refusal/offer precedence. "
                    f"{changed} rows changed; explicit_yes "
                    f"{before.get('sponsorship_explicit_yes', 0)} -> {after.get('sponsorship_explicit_yes', 0)}; "
                    f"explicit_no {before.get('sponsorship_explicit_no', 0)} -> "
                    f"{after.get('sponsorship_explicit_no', 0)}. Every previous explicit_yes was wrong; "
                    "two stated the opposite of the posting."
                )),
            )
        if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=52").fetchone():
            # Fuzzy confidence was scored over a string that included the
            # institution, city and state, all of which the candidate gate had
            # already forced to be equal.  The shared prefix inflated every
            # ratio, so unrelated jobs at one school cleared the 0.82 threshold
            # ("Dean and Principal" vs "Executive Director of Chiropractic"
            # scored 0.825).  Re-score the open queue on the discriminating
            # fields and close the ones that never should have been raised.
            # Rows are resolved with a recorded reason, never deleted.
            rescored = closed = 0
            for row in conn.execute("""
                SELECT p.id, p.confidence, a.title_normalized AS ta, b.title_normalized AS tb,
                       a.discipline_primary AS da, b.discipline_primary AS db
                FROM possible_duplicates p
                JOIN jobs a ON a.id=p.job_id JOIN jobs b ON b.id=p.possible_job_id
                WHERE p.resolved=0 AND p.match_basis='fuzzy_review_only'
            """).fetchall():
                score = difflib.SequenceMatcher(
                    None,
                    "|".join((row["ta"] or "", row["da"] or "")),
                    "|".join((row["tb"] or "", row["db"] or "")),
                ).ratio()
                if abs(score - (row["confidence"] or 0.0)) > 1e-9:
                    conn.execute("UPDATE possible_duplicates SET confidence=? WHERE id=?",
                                 (round(score, 4), row["id"]))
                    rescored += 1
                if score < 0.82:
                    conn.execute("""
                        UPDATE possible_duplicates
                        SET resolved=1, resolution='rejected', resolved_at=?, resolution_reason=?
                        WHERE id=?
                    """, (now_utc(),
                          "Auto-closed by migration 52: re-scored on title/discipline only "
                          f"({score:.3f} < 0.82). The original score was inflated by "
                          "institution/city/state segments the candidate gate already "
                          "required to be equal.", row["id"]))
                    closed += 1
            remaining = conn.execute(
                "SELECT COUNT(*) FROM possible_duplicates WHERE resolved=0").fetchone()[0]
            conn.execute(
                "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
                (52, now_utc(), (
                    f"Re-scored fuzzy duplicate candidates on discriminating fields only: "
                    f"{rescored} rescored, {closed} auto-closed as rejected, "
                    f"{remaining} left for review. No candidate row was deleted."
                )),
            )
        _seed_source_coverage_history_if_empty(conn)
        conn.commit()
    finally:
        conn.close()
    return str(db_path or FACULTY_DB_PATH)


def _sync_source_catalog(conn):
    timestamp = now_utc()
    for adapter in adapter_catalog():
        existing = conn.execute("SELECT id FROM sources WHERE name=?", (adapter.name,)).fetchone()
        if existing:
            conn.execute("""
                UPDATE sources SET region=?, base_url=?, adapter_name=?, priority=?, method=?,
                  support_status=?, support_reason=?, updated_at=? WHERE name=?
            """, (adapter.region, adapter.base_url, adapter.adapter_name, adapter.priority,
                   adapter.method, adapter.support_status, adapter.support_reason, timestamp, adapter.name))
        else:
            conn.execute("""
                INSERT INTO sources
                  (name,region,base_url,enabled,adapter_name,priority,method,support_status,support_reason,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (adapter.name, adapter.region, adapter.base_url, int(bool(adapter.enabled)),
                  adapter.adapter_name, adapter.priority, adapter.method, adapter.support_status,
                adapter.support_reason, timestamp, timestamp))


def _record_source_coverage_history(conn, scope="business", notes=None):
    enabled = [row[0] for row in conn.execute("SELECT name FROM sources WHERE enabled=1 ORDER BY priority,name")]
    successful = [row[0] for row in conn.execute("SELECT name FROM sources WHERE last_status='ok' ORDER BY priority,name")]
    total_jobs = conn.execute("SELECT COUNT(DISTINCT job_id) FROM job_sources WHERE active=1").fetchone()[0]
    business_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE derived_quality='accepted' AND faculty_market_eligible=1 AND business_scope IN ('business_school','business_discipline')").fetchone()[0]
    explicit_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE derived_quality='accepted' AND faculty_market_eligible=1 AND business_scope='business_school'").fetchone()[0]
    conn.execute("""
        INSERT INTO source_coverage_history
          (observed_at,enabled_sources_json,successful_sources_json,scope,jobs_observed,business_jobs_observed,explicit_school_jobs,notes)
        VALUES (?,?,?,?,?,?,?,?)
    """, (now_utc(), json.dumps(enabled, ensure_ascii=False), json.dumps(successful, ensure_ascii=False),
          scope, total_jobs, business_jobs, explicit_jobs, notes))


def _seed_source_coverage_history_if_empty(conn):
    if conn.execute("SELECT 1 FROM source_coverage_history LIMIT 1").fetchone():
        return
    if conn.execute("SELECT 1 FROM jobs LIMIT 1").fetchone():
        _record_source_coverage_history(
            conn,
            notes="Seeded from the preserved local snapshot after the Academic Career derived-field repair; not a longitudinal trend.",
        )


def _row_value(row, key):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _json_load(value, default=None):
    if default is None:
        default = []
    try:
        parsed = json.loads(value or "")
        return parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


_INSTITUTION_CANONICAL_ALIASES = {
    "uw madison": "University of Wisconsin–Madison",
    "university of wisconsin madison": "University of Wisconsin–Madison",
    "university of wisconsin–madison": "University of Wisconsin–Madison",
    "cuny bernard m baruch college": "Baruch College",
    "baruch college": "Baruch College",
    "wpi": "Worcester Polytechnic Institute",
    "worcester polytechnic institute": "Worcester Polytechnic Institute",
}
_UNKNOWN_INSTITUTIONS = {"", "unknown", "unknown institution", "not provided", "n/a"}
_SCHOOL_PREFIX_WORDS = {
    "management", "finance", "marketing", "accounting", "operations", "strategy",
    "business", "analytics", "information", "organizational", "organization",
}


def _canonical_institution_name(value):
    raw = str(value or "").strip()
    # Some source cards append the country to the employer label
    # (``University of Auckland, New Zealand``).  Country belongs in the
    # location fields, not in the university entity name; retain the original
    # string later as an alias/provenance value.
    suffix = re.search(r",\s*([^,]{2,40})$", raw)
    if suffix and country_code_for(suffix.group(1)):
        raw = raw[:suffix.start()].strip(" ,")
    # Source cards sometimes put the business-school name into the
    # institution field (``University of Tulsa's Collins College of
    # Business``).  Keep the university and school entities separate.
    possessive = re.match(
        r"^(?:The\s+)?(.+?)['’]s\s+(?:.+\s+)?(?:School|College|Faculty)\s+of\s+",
        raw, re.I,
    )
    if possessive:
        raw = possessive.group(1).strip()
    raw = re.sub(r"^The\s+", "", raw, flags=re.I)
    return _INSTITUTION_CANONICAL_ALIASES.get(normalize_name(raw), raw)


def _clean_derived_school_label(value):
    """Remove bounded job-board chrome from a derived school label.

    This does not rewrite preserved source text.  It handles only phrases
    observed at the start of IHE detail excerpts and leaves ordinary official
    names unchanged.
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:-")
    if not text:
        return text
    patterns = (
        r"^(?:Full|Part)[- ]time\s+Fully\s+On[- ]Campus\s+",
        r"^Faculty\s+Tenure\s+Track\s+",
        r"^Position\s+Overview\s*(?:The\s+)?",
        r"^Position\s+Summary\s+(?:The\s+)?",
        r"^(?:JOB\s+SUMMARY|Summary)\s+(?:The\s+)?",
        r"^About\s+(?:The\s+)?",
        r"^Behavior\s+The\s+",
        r"^(?:Teaching\s+)?Office\s+(?=(?:School|College|Faculty)\s+of\s+)",
        r"^University\.\s+(?=The\s+)",
        r"^[A-Z][\w&'’.-]+\s+The\s+(?=(?:[A-Z][\w&'’.-]+\s+){1,4}(?:School|College|Faculty)\s+of\b)",
    )
    previous = None
    while text and text != previous:
        previous = text
        for pattern in patterns:
            text = re.sub(pattern, "", text, count=1, flags=re.I).strip(" ,;:-")
    return text


def _extract_school_name(raw_school, description, institution=None):
    value = _clean_derived_school_label(raw_school)
    # Inside Higher Ed detail pages expose a portal chrome prefix such as
    # ``Description The Darden School of Business``.  Preserve the raw
    # excerpt/provenance, but keep that label out of the derived school entity.
    value = re.sub(r"^(?:Job\s+)?Description\s+", "", value, flags=re.I).strip()
    text = value or str(description or "")
    text = re.sub(r"^(?:Job\s+)?Description\s+", "", text, flags=re.I).strip()
    # DMSB is the source's explicit abbreviation for the University of South
    # Carolina's Darla Moore School of Business. Keep this mapping guarded by
    # the institution; do not turn an arbitrary department code into a school.
    if (
        institution
        and normalize_name(institution) == normalize_name("University of South Carolina")
        and re.search(r"\bDMSB\b", text, re.I)
    ):
        return "Darla Moore School of Business"
    text = re.sub(
        r"^(?:The\s+)?[^,;]+?'s\s+(?=(?:.+\s+)?(?:School|College|Faculty)\s+of\b)",
        "", text, flags=re.I,
    ).strip()
    matches = list(re.finditer(
        r"(?P<anchor>(?:School|College|Faculty)\s+of\s+"
        r"(?:Business|Management|Accounting|Finance|Economics|Commerce)"
        r"(?:\s+Administration|\s+and\s+Law)?)",
        text, re.I,
    ))
    if matches:
        match = matches[-1]
        candidate = match.group("anchor").strip(" ,;:-")
        prefix = text[max(0, match.start() - 80):match.start()]
        prefix_words = re.findall(r"[A-Z][\w&'’.-]*", prefix)
        # Preserve short proper names such as Darla Moore or Collins, but do
        # not absorb title/discipline words immediately before the anchor.
        proper_prefix = []
        for word in reversed(prefix_words[-4:]):
            if word.casefold() in _SCHOOL_PREFIX_WORDS or word.casefold() in {
                "lecturer", "professor", "assistant", "associate", "in", "and", "for",
                "temp", "temporary", "year", "term", "five", "full", "time",
            }:
                break
            proper_prefix.insert(0, word)
        # Detail text can put a location or article before the actual named
        # school, e.g. ``Ohio The Raj Soin College of Business``.  Once an
        # explicit ``The`` begins the named unit, discard the preceding
        # fragment while retaining the source wording in provenance.
        the_positions = [index for index, word in enumerate(proper_prefix) if word.casefold() == "the"]
        if the_positions:
            proper_prefix = proper_prefix[the_positions[-1] + 1:]
        if proper_prefix:
            candidate = " ".join(proper_prefix + candidate.split())
        return candidate
    business_school_matches = list(re.finditer(
        r"(?P<anchor>(?:[A-Z][\w&'’.-]+\s+)?(?:Business|Management|Commerce)\s+School)",
        text,
    ))
    if business_school_matches:
        candidate = business_school_matches[-1].group("anchor").strip(" ,;:-")
        candidate = re.sub(r"^The\s+", "", candidate, flags=re.I)
        words = candidate.split()
        if len(words) > 2 and words[0].casefold() in _SCHOOL_PREFIX_WORDS:
            candidate = " ".join(words[1:])
        return candidate
    # Short official labels such as ``UCD Business`` are explicit source
    # values, but remain unverified until an evidence row is added.
    if value and re.search(r"\b(?:business|management|commerce)\b", value, re.I):
        return value
    return None


def _prepare_entity_fields(normalized):
    """Split only explicit school/university shapes from a source employer.

    This is deliberately conservative. It handles known structured forms such
    as ``WPI Business School`` and ``King's Business School King's College
    London``; it does not infer a school from an arbitrary title abbreviation.
    The original source employer is retained in ``source_institution_raw``.
    """
    value = re.sub(r"\s+", " ", str(normalized.get("institution_raw") or "")).strip()
    if not value:
        return normalized
    normalized = dict(normalized)
    normalized.setdefault("source_institution_raw", value)
    school = str(normalized.get("school_raw") or "").strip() or None
    institution = value
    if normalized.get("institution_only_school"):
        normalized["institution_entity_raw"] = institution
        normalized["institution_normalized"] = normalize_name(institution)
        normalized["fingerprint"] = fingerprint_fields(
            institution, normalized.get("title_raw"), normalized.get("city"),
            normalized.get("state_province"), normalized.get("discipline_primary"),
            normalized.get("start_year"),
        )
        normalized["canonical_key"] = canonical_key(normalized.get("official_url"), normalized["fingerprint"])
        return normalized
    possessive = re.match(
        r"^(?:The\s+)?(.+?)['’]s\s+((?:.+\s+)?(?:School|College|Faculty)\s+of\s+.+)$",
        value, re.I,
    )
    if possessive:
        institution = possessive.group(1).strip()
        school = school or possessive.group(2).strip()
    else:
        school_first = re.match(
            r"^((?:[A-Z][\w&'’.-]+\s+){0,3}(?:Business|Management|Commerce)\s+School)\s+(.+(?:University|College|Institute|London))$",
            value,
        )
        if school_first:
            school = school or school_first.group(1).strip()
            institution = school_first.group(2).strip()
        else:
            institution_first = re.match(
                r"^(?:The\s+)?(.+?)\s+((?:Business|Management|Commerce)\s+School)$",
                value,
                re.I,
            )
            if institution_first:
                institution = institution_first.group(1).strip()
                school = school or re.sub(r"^The\s+", "", value, flags=re.I).strip()
    if institution.casefold().startswith("the "):
        institution = institution[4:].strip()
    if school:
        normalized["source_school_raw"] = school
        normalized["school_raw"] = school
    normalized["institution_entity_raw"] = institution
    normalized["institution_normalized"] = normalize_name(institution)
    normalized["fingerprint"] = fingerprint_fields(
        institution, normalized.get("title_raw"), normalized.get("city"),
        normalized.get("state_province"), normalized.get("discipline_primary"),
        normalized.get("start_year"),
    )
    normalized["canonical_key"] = canonical_key(normalized.get("official_url"), normalized["fingerprint"])
    return normalized


def _institution(conn, normalized, source_job):
    raw = normalized.get("institution_entity_raw") or normalized["institution_raw"]
    if normalize_name(raw) in _UNKNOWN_INSTITUTIONS:
        return None
    canonical = _canonical_institution_name(raw)
    manual = conn.execute(
        "SELECT canonical_name FROM institution_aliases WHERE alias_normalized=?",
        (normalize_name(raw),),
    ).fetchone()
    if manual:
        canonical = manual["canonical_name"]
    key = normalize_name(canonical)
    code = normalized.get("country_code")
    row = conn.execute("SELECT * FROM institutions WHERE normalized_name=? AND country_code IS ?", (key, code)).fetchone()
    if (row is None or (not code and not row["country_code"])) and not code:
        # Reuse a previously evidenced country for the same normalized
        # institution when the current public card supplies only a city. The
        # majority-country ordering protects against a single polluted legacy
        # alias (for example ``Augusta University`` tagged as Indonesia).
        row = conn.execute(
            """
            SELECT i.*
            FROM institutions i
            WHERE i.normalized_name=? AND i.country_code IS NOT NULL
            ORDER BY (
                SELECT COUNT(*) FROM institutions i2
                WHERE i2.normalized_name=i.normalized_name
                  AND i2.country_code=i.country_code
            ) DESC, i.is_current DESC, i.id ASC
            LIMIT 1
            """,
            (key,),
        ).fetchone()
    timestamp = now_utc()
    if row:
        if not normalized.get("country_code") and row["country_code"]:
            normalized["country_code"] = row["country_code"]
            normalized["country"] = row["country"]
            normalized["region_group"] = row["region_group"] or normalized.get("region_group")
            normalized["location_evidence"] = "institution_entity"
        aliases = _json_load(row["aliases_json"], [])
        source_raw = normalized.get("source_institution_raw") or raw
        if source_raw not in aliases and source_raw != row["official_name"]:
            aliases.append(source_raw)
        conn.execute("""
            UPDATE institutions SET aliases_json=?, institution_url=COALESCE(?, institution_url),
              country=COALESCE(?,country), region_group=COALESCE(?,region_group),
              state_province=COALESCE(?,state_province), city=COALESCE(?,city), is_current=1, updated_at=? WHERE id=?
        """, (json.dumps(aliases[:50], ensure_ascii=False), source_job.extra.get("institution_url"),
              normalized.get("country"), normalized.get("region_group"), normalized.get("state_province"),
              normalized.get("city"), timestamp, row["id"]))
        return row["id"]
    cur = conn.execute("""
        INSERT INTO institutions
          (official_name,normalized_name,aliases_json,country,country_code,region_group,state_province,city,institution_url,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (canonical, key, json.dumps([raw] if raw != canonical else [], ensure_ascii=False), normalized.get("country"), code,
          normalized.get("region_group"), normalized.get("state_province"), normalized.get("city"),
          source_job.extra.get("institution_url"), timestamp, timestamp))
    return cur.lastrowid


def _school(conn, institution_id, school_raw, source_job):
    if institution_id is None:
        return None
    # A public IHE detail page can explicitly expose structured
    # Faculty/Division/Department metadata without naming a business school.
    # In that case do not fall back to a later free-text cross-appointment or
    # generic ``School of Management`` mention.
    detail_extra = source_job.extra if isinstance(source_job.extra, dict) else {}
    # AACSB roster metadata identifies the school being checked, not the unit
    # that owns every vacancy on a university-wide career page.  Keep that
    # target association in the AACSB directory ledger; create a job-school
    # link only from posting-level evidence.
    if detail_extra.get("school_evidence_context") == "aacsb_roster_target":
        return None
    if detail_extra.get("detail_schema") and not detail_extra.get("detail_school_found"):
        return None
    institution = conn.execute("SELECT official_name FROM institutions WHERE id=?", (institution_id,)).fetchone()
    name = _extract_school_name(
        school_raw,
        source_job.description_excerpt,
        institution["official_name"] if institution else None,
    )
    if not name:
        return None
    # The jobs.ac.uk listing uses the shorthand ``Faculty of Business`` for
    # Leeds. The university's official business-school page supplies the
    # stable public entity name; keep the source wording in the excerpt and
    # provenance while normalizing the derived directory entity.
    if (
        institution
        and normalize_name(institution["official_name"]) == normalize_name("University of Leeds")
        and normalize_name(name) == normalize_name("Faculty of Business")
    ):
        # During a legacy replay, migration 13 still needs to see the old
        # ``Faculty of Business`` row so it can rename it in place. Once the
        # migration has run, the official target row exists and normal
        # ingestion can use it directly.
        legacy = conn.execute(
            "SELECT id FROM business_schools WHERE institution_id=? AND normalized_name=?",
            (institution_id, normalize_name("Faculty of Business")),
        ).fetchone()
        target = conn.execute(
            "SELECT id FROM business_schools WHERE institution_id=? AND normalized_name=?",
            (institution_id, normalize_name("Leeds University Business School")),
        ).fetchone()
        if legacy and not target:
            timestamp = now_utc()
            conn.execute(
                "UPDATE business_schools SET website=COALESCE(?,website), is_current=1, updated_at=? WHERE id=?",
                (source_job.extra.get("school_url"), timestamp, legacy["id"]),
            )
            return legacy["id"]
        name = "Leeds University Business School"
    normalized_name = normalize_name(name)
    row = conn.execute("SELECT id FROM business_schools WHERE institution_id=? AND normalized_name=?", (institution_id, normalized_name)).fetchone()
    timestamp = now_utc()
    if row:
        conn.execute("UPDATE business_schools SET website=COALESCE(?,website), is_current=1, updated_at=? WHERE id=?",
                     (source_job.extra.get("school_url"), timestamp, row["id"]))
        return row["id"]
    cur = conn.execute("""
        INSERT INTO business_schools
          (institution_id,official_name,normalized_name,website,created_at,updated_at)
        VALUES (?,?,?,?,?,?)
    """, (institution_id, name, normalized_name, source_job.extra.get("school_url"), timestamp, timestamp))
    return cur.lastrowid


def _backfill_business_scope(conn):
    """Recompute the auditable business-market boundary for existing rows.

    This is intentionally an in-place derived-field migration only.  It does
    not remove source rows, change source links, or rewrite raw excerpts.
    """
    rows = conn.execute("""
        SELECT j.id, j.title_raw, j.department, j.description_excerpt, j.official_url,j.institution_id,
               j.school_id, j.business_scope, j.business_scope_confidence, j.business_scope_reason,
               j.faculty_market_role,j.faculty_market_eligible,j.faculty_market_reason,
               j.school_evidence_context,j.derived_quality,
               i.official_name AS institution_name,
               bs.official_name AS business_school_name
        FROM jobs j
        LEFT JOIN institutions i ON i.id=j.institution_id
        LEFT JOIN business_schools bs ON bs.id=j.school_id
    """).fetchall()
    for row in rows:
        if row["derived_quality"] == "quarantined":
            continue
        role = classify_faculty_market_role(
            row["title_raw"], row["description_excerpt"], row["official_url"],
        )
        result = classify_business_scope(
            department=row["department"],
            title=row["title_raw"],
            description=row["description_excerpt"],
            institution=row["institution_name"],
            school=row["business_school_name"],
            school_is_posting_evidence=(
                row["school_id"] is not None
                and row["school_evidence_context"] != "aacsb_roster_target"
            ),
            faculty_role=role,
        )
        if (
            row["business_scope"] == result["scope"]
            and row["business_scope_confidence"] == result["confidence"]
            and row["business_scope_reason"] == result["reason"]
            and row["faculty_market_role"] == role["role"]
            and int(row["faculty_market_eligible"] or 0) == int(bool(role["eligible"]))
            and row["faculty_market_reason"] == role["reason"]
        ):
            continue
        conn.execute("""
            UPDATE jobs
            SET business_scope=?, business_scope_confidence=?, business_scope_reason=?,
                faculty_market_role=?,faculty_market_eligible=?,faculty_market_reason=?
            WHERE id=?
        """, (
            result["scope"], result["confidence"], result["reason"],
            role["role"], int(bool(role["eligible"])), role["reason"], row["id"],
        ))


def _status_for(normalized):
    today = date.today()
    deadline = normalized.get("deadline_date")
    if deadline:
        try:
            deadline_date = date.fromisoformat(deadline)
            if deadline_date < today:
                return "closed", "The explicit application deadline has passed; a public board page may remain archived."
            if deadline_date <= today + timedelta(days=14):
                return "closing_soon", None
            return "open", None
        except ValueError:
            pass
    posted = normalized.get("posted_date")
    if posted:
        try:
            posted_date = date.fromisoformat(str(posted)[:10])
            if posted_date < today - timedelta(days=365):
                return "unknown", "Posting date is more than 365 days old and no future fixed deadline verifies that it remains open."
        except ValueError:
            pass
    if normalized.get("deadline_mode") in {"open_until_filled", "rolling"}:
        return "likely_open", None
    return "likely_open", "Public source is live but no fixed deadline was parsed."


def _find_existing_job(conn, source_id, source_job, normalized):
    source_id_value = str(source_job.source_job_id)
    row = conn.execute("""
        SELECT j.id, 'source_id' AS basis FROM jobs j JOIN job_sources js ON js.job_id=j.id
        WHERE js.source_id=? AND js.source_job_id=? LIMIT 1
    """, (source_id, source_id_value)).fetchone()
    if row:
        return row["id"], "source_id", 1.0, None
    official = normalized.get("official_url")
    if official and is_mergeable_official_url(official):
        row = conn.execute("SELECT id FROM jobs WHERE official_url=? LIMIT 1", (official,)).fetchone()
        if row:
            return row["id"], "official_url", 1.0, None
    fingerprint = normalized.get("fingerprint")
    # Fingerprints are an exact identity fallback only when the fields that
    # make the identity meaningful are present.  In particular, unknown city,
    # institution, discipline, or title values must never collapse records.
    fingerprint_parts = str(fingerprint or "").split("|")
    fingerprint_complete = len(fingerprint_parts) >= 6 and all(fingerprint_parts[index] for index in (0, 1, 2, 4))
    if fingerprint and fingerprint_complete:
        row = conn.execute(
            """SELECT id FROM jobs WHERE fingerprint=?
               AND NOT EXISTS (SELECT 1 FROM job_sources js0
                               WHERE js0.job_id=jobs.id AND js0.source_id=?)
               LIMIT 1""",
            (fingerprint, source_id),
        ).fetchone()
        if row:
            return row["id"], "fingerprint", 0.98, None

    # Conservative fuzzy check: only compare recent same-country rows and
    # create a possible_duplicate record instead of merging borderline jobs.
    candidates = conn.execute("""
        SELECT j.id, i.normalized_name AS institution_normalized, j.title_normalized,
               j.city, j.state_province, j.discipline_primary, j.rank_normalized
        FROM jobs j LEFT JOIN institutions i ON i.id=j.institution_id
        WHERE j.country_code IS ? ORDER BY j.last_seen_at DESC LIMIT 200
    """, (normalized.get("country_code"),)).fetchall()
    best = None
    for candidate in candidates:
        if not normalized.get("institution_normalized") or not candidate["institution_normalized"]:
            continue
        if normalized.get("institution_normalized") != candidate["institution_normalized"]:
            continue
        if normalized.get("city") and candidate["city"] and normalize_name(normalized.get("city")) != normalize_name(candidate["city"]):
            continue
        # Score only the fields that can actually differ.  Institution, city
        # and state are already required to be equal by the gate above, so
        # including them compared two strings with a long identical prefix and
        # inflated every ratio: "Dean and Principal" versus "Executive Director
        # of Chiropractic" scored 0.825 on a 0.82 threshold, purely from the
        # shared institution segment.
        left = "|".join((normalized.get("title_normalized") or "",
                         normalized.get("discipline_primary") or ""))
        right = "|".join((candidate["title_normalized"] or "",
                          candidate["discipline_primary"] or ""))
        score = difflib.SequenceMatcher(None, left, right).ratio()
        if best is None or score > best[1]:
            best = (candidate["id"], score)
    # Fuzzy similarity is a review signal only.  It is never an identity
    # decision, because role/field collisions such as Finance versus Marketing
    # can be visually very similar on short job-board titles.
    if best and best[1] >= 0.82:
        return None, None, best[1], best[0]
    return None, None, best[1] if best else 0.0, best[0] if best else None


def _job_payload_values(normalized, institution_id, school_id, first_seen, last_seen):
    status, note = _status_for(normalized)
    values = dict(normalized)
    values.setdefault("derived_quality", "accepted")
    if values["derived_quality"] != "accepted":
        status = "unknown"
        note = values.get("faculty_market_reason") or "Record is retained outside the default market pending evidence review."
    values.update({
        "institution_id": institution_id, "school_id": school_id,
        "first_seen_at": first_seen, "last_seen_at": last_seen,
        "status": status, "verification_note": note,
        "hiring_cycle": hiring_cycle(first_seen, normalized.get("start_year")),
        "hiring_cycle_reason": hiring_cycle_reason(first_seen, normalized.get("start_year")),
        "created_at": first_seen, "updated_at": last_seen,
    })
    return values


_JOB_WRITE_COLUMNS = (
    "canonical_key", "title_raw", "title_normalized", "institution_id", "school_id", "department",
    "description_excerpt", "discipline_primary", "discipline_secondary_json", "classification_reason",
    "business_scope", "business_scope_confidence", "business_scope_reason",
    "faculty_market_role", "faculty_market_eligible", "faculty_market_reason",
    "school_evidence_context", "keywords_json", "rank_raw",
    "rank_normalized", "career_stage", "rank_mapping_confidence", "rank_mapping_explanation", "track_type",
    "contract_type", "employment_type", "contract_length", "country", "country_code", "region_group",
    "state_province", "city", "location_evidence", "remote_type", "posted_date", "deadline_date",
    "deadline_mode", "deadline_evidence", "deadline_parse_reason", "start_term", "start_year",
    "hiring_cycle", "hiring_cycle_reason", "salary_raw", "salary_min", "salary_max", "salary_currency",
    "salary_period", "phd_required", "phd_required_by", "teaching_areas_json", "research_areas_json",
    "teaching_load_raw", "visa_text", "visa_status", "language_requirements", "official_url",
    "original_title", "first_seen_at", "last_seen_at", "status", "verification_note", "derived_quality", "fingerprint",
    "created_at", "updated_at",
)


def _insert_job_from_values(conn, values):
    """Insert one canonical job from normalized values.

    The helper is shared by normal ingestion and the repair migration.  A
    collision is retained as a separate canonical record with an auditable
    suffix; raw source identity remains in ``job_sources``.
    """
    columns = list(_JOB_WRITE_COLUMNS)
    try:
        cur = conn.execute(
            f"INSERT INTO jobs ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            [values.get(column) for column in columns],
        )
    except sqlite3.IntegrityError:
        original = values.get("canonical_key") or "repair"
        values = dict(values)
        values["canonical_key"] = f"{original}:repair:{values.get('fingerprint') or values.get('title_normalized') or 'record'}"
        # A repeated repair collision is still a separate record.  The
        # numeric suffix is deterministic for the current transaction.
        suffix = 2
        while True:
            try:
                cur = conn.execute(
                    f"INSERT INTO jobs ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    [values.get(column) for column in columns],
                )
                break
            except sqlite3.IntegrityError:
                values["canonical_key"] = f"{original}:repair:{suffix}"
                suffix += 1
    return cur.lastrowid, values


def _update_job_from_values(conn, job_id, values, *, preserve_created=True):
    values = dict(values)
    if preserve_created:
        values.pop("created_at", None)
    columns = [column for column in _JOB_WRITE_COLUMNS if column in values and column not in {"canonical_key", "first_seen_at"}]
    if not columns:
        return
    conn.execute(
        "UPDATE jobs SET " + ",".join(f"{column}=?" for column in columns) + " WHERE id=?",
        [values.get(column) for column in columns] + [job_id],
    )


def _insert_provenance(conn, job_id, source_id, source_job, normalized):
    timestamp = normalized.get("captured_at") or now_utc()
    fields = {
        "salary_raw": (normalized.get("salary_raw"), normalized.get("salary_raw")),
        "deadline_date": (normalized.get("deadline_date"), normalized.get("deadline_evidence") or normalized.get("deadline_mode")),
        "deadline_mode": (normalized.get("deadline_mode"), normalized.get("deadline_parse_reason")),
        "location": (normalized.get("location_raw"), normalized.get("location_evidence")),
        "country": (normalized.get("country"), normalized.get("location_evidence")),
        "institution": (normalized.get("institution_entity_raw") or normalized.get("institution_raw"), normalized.get("source_institution_raw") or normalized.get("institution_raw")),
        "title_raw": (normalized.get("original_title") or normalized.get("title_raw"), normalized.get("title_raw")),
        "track_type": (normalized.get("track_type"), normalized.get("track_evidence")),
        "visa_status": (normalized.get("visa_status"), normalized.get("visa_evidence")),
        "discipline_primary": (normalized.get("discipline_primary"), normalized.get("classification_reason")),
        "rank_normalized": (normalized.get("rank_normalized"), normalized.get("rank_mapping_explanation")),
        "official_url": (normalized.get("official_url"), normalized.get("official_url")),
    }
    for field_name, (value, evidence) in fields.items():
        if value in (None, "", "unknown", "Unknown"):
            continue
        conn.execute(
            "UPDATE job_field_provenance SET is_current=0 WHERE job_id=? AND field_name=?",
            (job_id, field_name),
        )
        conn.execute("""
            INSERT INTO job_field_provenance
              (job_id,field_name,source_id,source_job_id,source_url,value_text,evidence_text,captured_at,is_current)
            VALUES (?,?,?,?,?,?,?,?,1)
        """, (job_id, field_name, source_id, source_job.source_job_id, source_job.source_url,
              str(value), str(evidence or "")[:3000], timestamp))


def _upsert_job(conn, source_id, source_job, normalized, run_started):
    normalized = _prepare_entity_fields(normalized)
    if source_job.source == "aacsb_official":
        # Only a role-eligible, posting-level business match may restore an
        # older quarantined AACSB record.  The roster school itself is not job
        # evidence.
        normalized["derived_quality"] = (
            "accepted"
            if normalized.get("faculty_market_eligible") == 1
            and normalized.get("business_scope") in {"business_school", "business_discipline"}
            else "quarantined"
        )
    institution_id = _institution(conn, normalized, source_job)
    # A school association is useful only after the record itself has passed
    # both the individual-faculty gate and the business-market boundary. Raw
    # school text is still preserved in ``source_job_records`` for audit.
    school_id = None
    if (
        normalized.get("faculty_market_eligible") == 1
        and normalized.get("business_scope") in {"business_school", "business_discipline"}
    ):
        school_id = _school(conn, institution_id, normalized.get("school_raw"), source_job)
    now = normalized.get("captured_at") or now_utc()
    existing_id, basis, confidence, possible_candidate_id = _find_existing_job(conn, source_id, source_job, normalized)
    previous = None
    if existing_id is None:
        values = _job_payload_values(normalized, institution_id, school_id, now, now)
        job_id, values = _insert_job_from_values(conn, values)
        action = "inserted"
        if possible_candidate_id and confidence >= 0.82 and possible_candidate_id != job_id:
            conn.execute("""
                INSERT OR IGNORE INTO possible_duplicates
                  (job_id,possible_job_id,confidence,match_basis,resolved,created_at)
                VALUES (?,?,?,?,0,?)
                """, (job_id, possible_candidate_id, confidence, "fuzzy_review_only", now))
    else:
        job_id = existing_id
        action = "merged" if basis in {"official_url", "fingerprint"} else "updated"
        current = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        previous = current
        changes = []
        update_fields = [
            "title_raw", "title_normalized", "institution_id", "school_id", "department", "description_excerpt", "discipline_primary",
            "discipline_secondary_json", "classification_reason", "business_scope", "business_scope_confidence",
            "business_scope_reason", "keywords_json", "rank_raw", "rank_normalized",
            "faculty_market_role", "faculty_market_eligible", "faculty_market_reason",
            "school_evidence_context",
            "career_stage", "rank_mapping_confidence", "rank_mapping_explanation", "track_type", "contract_type",
            "employment_type", "country", "country_code", "region_group", "state_province", "city", "location_evidence", "remote_type",
            "posted_date", "deadline_date", "deadline_mode", "deadline_evidence", "deadline_parse_reason", "start_term", "start_year", "hiring_cycle", "hiring_cycle_reason",
            "salary_raw", "salary_min", "salary_max", "salary_currency", "salary_period", "phd_required",
            "visa_status", "official_url", "original_title", "status", "verification_note", "fingerprint", "updated_at",
            "derived_quality",
        ]
        values = _job_payload_values(normalized, institution_id, school_id, current["first_seen_at"], now)
        for field in update_fields:
            new_value = values.get(field)
            old_value = current[field]
            # These fields are authoritative derived values for the current
            # source observation.  Clearing a stale deadline or location is
            # necessary when a source no longer provides that evidence.
            clearable = {
                "posted_date", "deadline_date", "deadline_mode", "deadline_evidence",
                "deadline_parse_reason", "location_evidence", "city", "state_province",
                "country", "country_code", "region_group", "original_title", "institution_id", "school_id",
            }
            if ((field in clearable and new_value != old_value) or
                    (field not in clearable and new_value not in (None, "") and new_value != old_value)):
                changes.append(field)
        if changes:
            conn.execute("UPDATE jobs SET " + ",".join(f"{field}=?" for field in changes) + " WHERE id=?",
                         [values[field] for field in changes] + [job_id])

    conn.execute("""
        INSERT INTO job_sources
          (job_id,source_id,source_job_id,source_url,official_url,first_seen,last_seen,active,consecutive_missing_runs)
        VALUES (?,?,?,?,?,?,?,1,0)
        ON CONFLICT(source_id,source_job_id) DO UPDATE SET
          job_id=excluded.job_id, source_url=excluded.source_url,
          official_url=COALESCE(excluded.official_url,job_sources.official_url),
          last_seen=excluded.last_seen, active=1, consecutive_missing_runs=0
    """, (job_id, source_id, source_job.source_job_id, source_job.source_url, normalized.get("official_url"), now, now))
    extraction = {key: value for key, value in normalized.items() if key not in {"description_excerpt", "track_evidence", "visa_evidence"}}
    excerpt = normalized.get("description_excerpt")
    content_hash = hashlib.sha256(json.dumps(extraction, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    conn.execute("""
        INSERT INTO source_job_records
          (source_id,source_job_id,source_url,official_url,content_hash,short_excerpt,structured_extraction,first_seen,last_seen)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_id,source_job_id) DO UPDATE SET source_url=excluded.source_url,
          official_url=COALESCE(excluded.official_url,source_job_records.official_url),
          content_hash=excluded.content_hash, short_excerpt=excluded.short_excerpt,
          structured_extraction=excluded.structured_extraction, last_seen=excluded.last_seen
    """, (source_id, source_job.source_job_id, source_job.source_url, normalized.get("official_url"), content_hash,
          excerpt[:2000] if excerpt else None, json.dumps(extraction, ensure_ascii=False), now, now))
    _insert_provenance(conn, job_id, source_id, source_job, normalized)
    source_count = conn.execute("SELECT COUNT(DISTINCT source_id) FROM job_sources WHERE job_id=? AND active=1", (job_id,)).fetchone()[0]
    status = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    conn.execute("""
        INSERT INTO job_status_history
          (job_id,observed_at,status,deadline,salary_raw,title_raw,source_count,change_reason)
        VALUES (?,?,?,?,?,?,?,?)
    """, (job_id, now, status, normalized.get("deadline_date"), normalized.get("salary_raw"), normalized.get("title_raw"), source_count,
          "source_observed" if not previous else ("field_changed:" + ",".join(changes) if 'changes' in locals() and changes else "source_reobserved")))
    return job_id, action


def _repair_date_after_keyword(text, pattern):
    match = re.search(pattern, str(text or ""), re.I)
    if not match:
        return None
    value = match.group(1).strip(" :-|,;")
    # Keep this raw.  ``normalize_source_job`` applies the captured date as
    # the reference year for year-less closing dates.
    return value[:180] or None


def _repair_source_job(conn, link, record):
    """Rebuild a SourceJob from bounded local evidence.

    This deliberately reads only the saved structured extraction and bounded
    excerpt.  It does not refetch public pages during a database migration.
    """
    from services.faculty_jobs_sources.base import SourceJob

    source_name = link["source_name"]
    source_region = link["source_region"]
    source_url = record["source_url"] if record else link["source_url"]
    excerpt = (record["short_excerpt"] if record else None) or ""
    try:
        extraction = json.loads((record["structured_extraction"] if record else "{}") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        extraction = {}
    title = extraction.get("title_raw") or "Untitled academic posting"
    institution = extraction.get("institution_raw") or "Unknown institution"
    school = extraction.get("school_raw")
    department = extraction.get("department")
    location = extraction.get("location_raw")
    posted = None
    deadline = None
    salary = extraction.get("salary_raw")
    official = (record["official_url"] if record else None) or link["official_url"]

    if source_name == "inside_higher_ed":
        from services.faculty_jobs_sources.insidehighered import InsideHigherEdAdapter
        recovered = InsideHigherEdAdapter._institution_from_text(excerpt, title)
        if recovered:
            institution = recovered
        recovered_location = _repair_date_after_keyword(
            excerpt,
            r"(?:work\s+)?location\s*:\s*(.*?)(?=\s*(?:type\s+of|categories?\s*:|view\s+details|save\b|$))",
        )
        if recovered_location:
            inside = re.search(r"\(([A-Z][^()]{1,70},\s*[A-Z]{2})\)", recovered_location)
            if inside:
                location = inside.group(1)
            elif re.fullmatch(r"[A-Z][A-Za-z .'-]{1,50},\s*[A-Z]{2}", recovered_location):
                location = recovered_location
            elif re.search(r"\b(?:university|college|institute|polytechnic)\b", recovered_location, re.I):
                # A few IHE cards put the employer and campus in the
                # location slot: ``The University of Tennessee, Knoxville,
                # Haslam College of Business``. Keep only the explicit campus
                # token; the employer remains institution evidence and must
                # never be displayed as the city.
                campus = re.search(
                    r"\b(?:university|college|institute|polytechnic)\b[^,]{0,140},\s*"
                    r"([A-Z][A-Za-z.' -]{1,60}?)(?=,\s*(?:[A-Z]{2}|[A-Z][a-z]+)|"
                    r"\s+(?:Haslam|College|School|Faculty|Open|Posted|View|Save)\b|$)",
                    recovered_location,
                    re.I,
                )
                location = campus.group(1).strip(" ,:-") if campus else None
            # A few cards expose the university name in the location field
            # (for example ``Augusta University Full/Part Time``).  Retain a
            # separate city from the card when it is usable instead of
            # turning the organization into a city.
            elif not location or re.search(r"\b(?:college|school|university)\b", str(location), re.I):
                location = None
        elif re.search(r"\b(?:college|school)\s+of\s+business\b", str(location or ""), re.I):
            location = None
        posted = _repair_date_after_keyword(
            excerpt, r"(?:posting\s+date|date\s+placed|posted(?:\s+on)?)\s*:?\s*([^.;]{1,80})"
        )
        deadline = _repair_date_after_keyword(
            excerpt, r"(?:application\s+deadline|deadline|closing(?:\s+date)?|closes|apply\s+by|expires?)\s*:?\s*([^.;]{1,120})"
        )
        if location and (
            len(str(location)) > 80
            or re.search(
                r"\b(?:department|division|school|faculty|university|job\s+summary|"
                r"full/part\s+time|regular/temporary|pay\s+information|"
                r"position\s+number)\b",
                str(location),
                re.I,
            )
        ):
            # IHE career templates sometimes place a department/division
            # label in the card's location slot. Preserve it in the excerpt,
            # but do not expose it as a city.
            location = None
    elif source_name == "euraxess":
        from services.faculty_jobs_sources.euraxess import EuraxessAdapter
        work_location = extraction.get("location_raw") or _repair_date_after_keyword(
            excerpt, r"work\s+locations?\s*:\s*(.*?)(?=\s+research\s+field|\s+application\s+deadline|$)"
        )
        parsed_location, host = EuraxessAdapter._work_location(work_location)
        if parsed_location:
            location = parsed_location
        if host:
            institution = host
        posted = _repair_date_after_keyword(
            excerpt, r"posted\s+on\s*:?\s*([^.;]{1,80})"
        )
        deadline = _repair_date_after_keyword(
            excerpt, r"application\s+deadline\s*:?\s*([^.;]{1,120})"
        )
    elif source_name == "jobs_ac_uk":
        from services.faculty_jobs_sources.jobs_ac_uk import _deadline_raw, _posted_raw
        posted = _posted_raw(excerpt)
        deadline = _deadline_raw(excerpt)
        if not salary:
            salary = _repair_date_after_keyword(excerpt, r"salary\s*:?\s*(.*?)(?=\s+date\s+placed|\s+closes\b|\s+location\b|$)")
    elif source_name == "university_affairs":
        posted = _repair_date_after_keyword(
            excerpt, r"(?:posting\s+date|date\s+placed|posted(?:\s+on)?)\s*:?\s*([^.;]{1,80})"
        )
        deadline = _repair_date_after_keyword(
            excerpt, r"(?:application\s+deadline|deadline|closing(?:\s+date)?|closes|apply\s+by|expires?)\s*:?\s*([^.;]{1,120})"
        )

    # A board may expose the business-school/department as the employer
    # label while the bounded excerpt contains the university.  Recover only
    # an explicit University/College/Institute phrase; never use a city as a
    # substitute institution.
    if re.search(r"\b(?:school|college|faculty)\b", str(institution), re.I) and not re.search(
        r"\b(?:university|institute|polytechnic)\b", str(institution), re.I
    ):
        from services.faculty_jobs_sources.insidehighered import InsideHigherEdAdapter
        recovered = InsideHigherEdAdapter._institution_from_text(excerpt, title)
        if recovered:
            institution = recovered

    # For all sources, use the bounded text as a last-resort evidence source;
    # never reuse the old normalized deadline_date because it may be the very
    # posted-date error this migration is repairing.
    if posted is None:
        posted = extraction.get("posted_date")
    if deadline is None and re.search(r"\b(?:deadline|closing|closes|apply\s+by|expires?)\b", excerpt, re.I):
        deadline = _repair_date_after_keyword(
            excerpt, r"(?:application\s+deadline|deadline|closing(?:\s+date)?|closes|apply\s+by|expires?)\s*:?\s*([^.;]{1,120})"
        )
    if not salary:
        salary = _repair_date_after_keyword(
            excerpt, r"(?:salary|hiring\s+salary|advertised\s+salary)\s*:?\s*([^.;]{1,180})"
        )
    if not salary:
        currency_match = re.search(
            r"([$£€]\s*\d[\d,]*(?:\.\d+)?(?:\s*[-–]\s*[$£€]?\s*\d[\d,]*(?:\.\d+)?)?(?:\s+per\s+[A-Za-z]+)?)",
            excerpt,
        )
        salary = currency_match.group(1) if currency_match else None
    # The repair parser often extracts only the value after an explicit
    # ``Application Deadline``/``Closes`` label.  Put the label back so a
    # visible fixed date cannot be mistaken for an unlabeled JSON-LD expiry
    # when the same excerpt also says ``Open Until Filled: No``.
    if deadline and not re.search(r"\b(?:deadline|closing|closes|apply\s+by|expires?)\b", str(deadline), re.I):
        deadline = f"Deadline: {deadline}"
    official = normalize_url(official)
    if official and normalize_url(source_url) == official:
        # A board listing is not an official application destination.
        official = None
    extra = {}
    if extraction.get("institution_url"):
        extra["institution_url"] = extraction.get("institution_url")
    if extraction.get("school_url"):
        extra["school_url"] = extraction.get("school_url")
    if source_name == "aacsb_official":
        # ``school_raw`` in legacy AACSB records came from the accreditation
        # roster, not necessarily from the vacancy itself.
        extra["school_evidence_context"] = "aacsb_roster_target"
    elif source_name == "inside_higher_ed":
        strict_school = InsideHigherEdAdapter._detail_school(excerpt)
        school = strict_school
        extra["school_evidence_context"] = "structured_posting" if strict_school else "unknown"
        extra["detail_schema"] = bool(excerpt)
        extra["detail_school_found"] = bool(strict_school)
        extra["school_evidence_rule_version"] = IHE_SCHOOL_EVIDENCE_RULE_VERSION
        if location is None:
            extra["suppress_location_description"] = True
    else:
        extra["school_evidence_context"] = extraction.get("school_evidence_context") or "posting"
    if extraction.get("institution_only_school"):
        extra["detail_institution_only_school"] = True
    captured = (record["first_seen"] if record else None) or link["first_seen"] or now_utc()
    return SourceJob(
        source=source_name,
        source_job_id=str(link["source_job_id"]),
        source_url=source_url,
        official_url=official,
        title_raw=title,
        institution_raw=institution or "Unknown institution",
        school_raw=school,
        department_raw=department,
        location_raw=location,
        description_excerpt=excerpt,
        posted_date_raw=posted,
        deadline_raw=deadline,
        salary_raw=salary,
        captured_at=captured,
        extra=extra,
    )


def _repair_derived_data(conn):
    """Repair derived Academic Career fields without deleting source data.

    The migration is intentionally source-record-first.  Each existing
    ``(source_id, source_job_id)`` gets a fresh normalization pass.  A
    non-mergeable generic board URL never becomes an identity key; links that
    were incorrectly placed in one same-source canonical job are split while
    the original source record, provenance and status history remain intact.
    """
    links = conn.execute("""
        SELECT js.*, s.name AS source_name, s.region AS source_region,
               sr.id AS source_record_id, sr.source_url AS record_source_url,
               sr.official_url AS record_official_url, sr.short_excerpt,
               sr.structured_extraction, sr.first_seen AS record_first_seen,
               sr.last_seen AS record_last_seen
        FROM job_sources js
        JOIN sources s ON s.id=js.source_id
        LEFT JOIN source_job_records sr
          ON sr.source_id=js.source_id AND sr.source_job_id=js.source_job_id
        ORDER BY js.job_id, js.source_id, js.source_job_id
    """).fetchall()
    if not links:
        return {"links": 0, "groups": 0, "split": 0, "merged": 0}

    items = []
    for row in links:
        record = {
            "source_url": row["record_source_url"] or row["source_url"],
            "official_url": row["record_official_url"] or row["official_url"],
            "short_excerpt": row["short_excerpt"],
            "structured_extraction": row["structured_extraction"],
            "first_seen": row["record_first_seen"] or row["first_seen"],
            "last_seen": row["record_last_seen"] or row["last_seen"],
        }
        source_job = _repair_source_job(conn, row, record)
        normalized = _prepare_entity_fields(normalize_source_job(source_job, row["source_region"]))
        official = normalized.get("official_url")
        if official and is_mergeable_official_url(official):
            group_key = ("official_url", official)
        else:
            # Source identity is the safe fallback.  Repair does not use
            # fuzzy similarity or incomplete fingerprints to join records.
            group_key = ("source_record", int(row["source_id"]), str(row["source_job_id"]))
        items.append({
            "row": row, "record": record, "source_job": source_job,
            "normalized": normalized, "group_key": group_key,
            "current_job_id": int(row["job_id"]),
        })

    grouped = defaultdict(list)
    for item in items:
        grouped[item["group_key"]].append(item)

    reserved = set()
    stats = {"links": len(items), "groups": len(grouped), "split": 0, "merged": 0}
    for group_key in sorted(grouped, key=lambda value: tuple(str(item) for item in value)):
        group = grouped[group_key]
        current_ids = sorted({item["current_job_id"] for item in group if item["current_job_id"] not in reserved})
        base_id = current_ids[0] if current_ids else None
        was_reserved = base_id in reserved if base_id is not None else False
        if base_id is not None:
            reserved.add(base_id)
        if len({item["current_job_id"] for item in group}) > 1:
            stats["merged"] += len({item["current_job_id"] for item in group}) - 1
        if was_reserved or any(item["current_job_id"] in reserved and item["current_job_id"] != base_id for item in group[1:]):
            stats["split"] += 1

        representative = group[0]
        normalized = representative["normalized"]
        institution_id = _institution(conn, normalized, representative["source_job"])
        school_id = _school(conn, institution_id, normalized.get("school_raw"), representative["source_job"])
        seen_values = [item["source_job"].captured_at for item in group if item["source_job"].captured_at]
        first_seen = min(seen_values or [now_utc()])
        last_seen_values = [item["record"].get("last_seen") or item["source_job"].captured_at for item in group]
        last_seen = max(last_seen_values or [now_utc()])
        values = _job_payload_values(normalized, institution_id, school_id, first_seen, last_seen)
        existing_before = conn.execute("SELECT * FROM jobs WHERE id=?", (base_id,)).fetchone() if base_id else None
        if base_id is None:
            base_id, values = _insert_job_from_values(conn, values)
        else:
            # Keep canonical URL/fingerprint identity deterministic while
            # allowing a previously merged record to split safely.
            desired_key = values.get("canonical_key")
            owner = conn.execute("SELECT id FROM jobs WHERE canonical_key=? AND id<>?", (desired_key, base_id)).fetchone()
            if owner:
                desired_key = f"{desired_key}:repair:{representative['row']['source_id']}:{representative['row']['source_job_id']}"
                values["canonical_key"] = desired_key
            try:
                conn.execute("UPDATE jobs SET canonical_key=? WHERE id=?", (desired_key, base_id))
            except sqlite3.IntegrityError:
                values["canonical_key"] = f"{desired_key}:repair:2"
                conn.execute("UPDATE jobs SET canonical_key=? WHERE id=?", (values["canonical_key"], base_id))
            conn.execute("UPDATE job_field_provenance SET is_current=0 WHERE job_id=?", (base_id,))
            _update_job_from_values(conn, base_id, values)

        # Attach every original source link to the repaired canonical job.
        for item in group:
            row = item["row"]
            conn.execute("""
                UPDATE job_sources
                SET job_id=?, source_url=?, official_url=?, last_seen=?, active=1,
                    consecutive_missing_runs=0
                WHERE source_id=? AND source_job_id=?
            """, (base_id, item["source_job"].source_url, item["normalized"].get("official_url"),
                  item["record"].get("last_seen") or now_utc(), row["source_id"], row["source_job_id"]))
            _insert_provenance(conn, base_id, row["source_id"], item["source_job"], item["normalized"])
            conn.execute("""
                INSERT INTO faculty_job_repair_audit
                  (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
                VALUES (?,?,?,?,?,?,?,?)
            """, (now_utc(), "rederive", base_id, row["source_id"], row["source_job_id"],
                  json.dumps({"job_id": row["job_id"], "institution": item["record"].get("institution_raw")}, ensure_ascii=False),
                  json.dumps({"institution": item["normalized"].get("institution_raw"), "country": item["normalized"].get("country"),
                              "city": item["normalized"].get("city"), "deadline": item["normalized"].get("deadline_date")}, ensure_ascii=False),
                  "Rebuilt derived fields from preserved source record and bounded excerpt."))
        source_count = conn.execute("SELECT COUNT(DISTINCT source_id) FROM job_sources WHERE job_id=? AND active=1", (base_id,)).fetchone()[0]
        status = conn.execute("SELECT status FROM jobs WHERE id=?", (base_id,)).fetchone()[0]
        conn.execute("""
            INSERT INTO job_status_history
              (job_id,observed_at,status,deadline,salary_raw,title_raw,source_count,change_reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (base_id, now_utc(), status, normalized.get("deadline_date"), normalized.get("salary_raw"),
              normalized.get("title_raw"), source_count, "repair_rederived_source_record"))

    # Preserve legacy derived rows for auditability but remove them from the
    # active School Explorer when no corrected job/entity still references
    # them.  No source record, provenance row, status history, or user state is
    # deleted.
    orphan_schools = conn.execute("""
        SELECT bs.id FROM business_schools bs
        WHERE bs.is_current=1
          AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.school_id=bs.id)
          AND NOT EXISTS (SELECT 1 FROM school_evidence se WHERE se.school_id=bs.id)
          AND NOT EXISTS (SELECT 1 FROM school_tier_overrides sto WHERE sto.school_id=bs.id)
    """).fetchall()
    for row in orphan_schools:
        conn.execute("UPDATE business_schools SET is_current=0, updated_at=? WHERE id=?", (now_utc(), row["id"]))
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?)
        """, (now_utc(), "deactivate_orphan_school", None, str(row["id"]), "is_current=0",
              "Legacy derived school entity has no corrected job link and was retained outside the active explorer."))
    orphan_institutions = conn.execute("""
        SELECT i.id FROM institutions i
        WHERE i.is_current=1
          AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.institution_id=i.id)
          AND NOT EXISTS (SELECT 1 FROM business_schools bs WHERE bs.institution_id=i.id AND bs.is_current=1)
    """).fetchall()
    for row in orphan_institutions:
        conn.execute("UPDATE institutions SET is_current=0, updated_at=? WHERE id=?", (now_utc(), row["id"]))
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?)
        """, (now_utc(), "deactivate_orphan_institution", None, str(row["id"]), "is_current=0",
              "Legacy derived institution entity has no corrected job or active school link and was retained outside active views."))

    return stats


def _repair_inside_higher_ed_location_labels(conn):
    """Clear department/school labels that survived as IHE city values.

    The source excerpt is deliberately not rewritten.  This is a narrow
    derived-field repair for a known card-layout failure: Inside Higher Ed
    sometimes exposes ``College of Business Administration`` in the location
    slot while the actual location is absent.  Country evidence remains
    usable, but an institutional unit must never be displayed as a city.
    """
    source = conn.execute("SELECT id FROM sources WHERE name='inside_higher_ed'").fetchone()
    if not source:
        return 0
    source_id = int(source["id"])
    label_re = re.compile(
        r"^(?:the\s+)?(?:college|school|faculty)\s+of\s+business"
        r"(?:\s+administration)?$", re.I,
    )
    rows = conn.execute("""
        SELECT DISTINCT j.id,j.city,j.country,j.country_code,j.region_group,
               js.source_job_id,js.source_url
        FROM jobs j JOIN job_sources js ON js.job_id=j.id
        WHERE js.source_id=? AND js.active=1 AND j.city IS NOT NULL
    """, (source_id,)).fetchall()
    repaired = 0
    for row in rows:
        if not label_re.fullmatch(str(row["city"] or "").strip()):
            continue
        now = now_utc()
        conn.execute(
            "UPDATE jobs SET city=NULL,location_evidence='source_region_country',updated_at=? WHERE id=?",
            (now, row["id"]),
        )
        conn.execute(
            "UPDATE job_field_provenance SET is_current=0 WHERE job_id=? AND field_name='location'",
            (row["id"],),
        )
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            now, "ihe_location_label_repair", row["id"], source_id,
            row["source_job_id"], json.dumps({"city": row["city"]}, ensure_ascii=False),
            json.dumps({"city": None, "country": row["country"], "country_code": row["country_code"]}, ensure_ascii=False),
            "Inside Higher Ed card exposed a business-school/department label in the location slot; city cleared without inventing a replacement.",
        ))
        repaired += 1
    return repaired


def _repair_inside_higher_ed_institutions_from_excerpts(conn):
    """Recover explicit IHE employers already present in bounded excerpts.

    This migration is deliberately offline.  It does not refetch third-party
    pages or rewrite raw excerpts; it only replays a stricter institution
    parser over source evidence already stored in ``source_job_records``.
    Detail-page enrichment is an explicit, separately budgeted operation.
    """
    source = conn.execute("SELECT id,region FROM sources WHERE name='inside_higher_ed'").fetchone()
    if not source:
        return 0
    rows = conn.execute("""
        SELECT j.*, sjr.source_job_id, sjr.source_url, sjr.official_url AS record_official_url,
               sjr.short_excerpt, sjr.structured_extraction, sjr.last_seen AS record_last_seen
        FROM jobs j
        JOIN job_sources js ON js.job_id=j.id AND js.source_id=?
        JOIN source_job_records sjr ON sjr.source_id=js.source_id AND sjr.source_job_id=js.source_job_id
        WHERE j.institution_id IS NULL
        ORDER BY j.id
    """, (source["id"],)).fetchall()
    repaired = 0
    for row in rows:
        candidate = InsideHigherEdAdapter._institution_from_text(row["short_excerpt"], row["title_raw"])
        if not candidate:
            continue
        try:
            extraction = json.loads(row["structured_extraction"] or "{}")
        except (TypeError, ValueError):
            extraction = {}
        source_job = SourceJob(
            source="inside_higher_ed",
            source_job_id=str(row["source_job_id"]),
            source_url=row["source_url"],
            official_url=row["record_official_url"] or extraction.get("official_url"),
            title_raw=row["title_raw"],
            institution_raw=candidate,
            school_raw=extraction.get("school_raw"),
            department_raw=extraction.get("department"),
            location_raw=extraction.get("location_raw") or row["city"],
            description_excerpt=row["short_excerpt"] or row["description_excerpt"],
            posted_date_raw=extraction.get("posted_date") or row["posted_date"],
            deadline_raw=extraction.get("deadline_date") or extraction.get("deadline_mode") or row["deadline_date"],
            salary_raw=extraction.get("salary_raw") or row["salary_raw"],
            captured_at=row["record_last_seen"] or row["last_seen_at"] or now_utc(),
            extra={"search_query": InsideHigherEdAdapter.search_query},
        )
        normalized = normalize_source_job(source_job, source["region"])
        # This is an institution-only evidence replay.  Never clear a better
        # derived value merely because the short card excerpt omitted it.
        for field in (
            "posted_date", "deadline_date", "deadline_mode", "deadline_evidence",
            "deadline_parse_reason", "country", "country_code", "region_group",
            "state_province", "city", "location_evidence", "salary_raw", "salary_min",
            "salary_max", "salary_currency", "salary_period", "start_term", "start_year",
            "visa_status", "official_url",
        ):
            if normalized.get(field) in (None, "", "unknown") and row[field] not in (None, "", "unknown"):
                normalized[field] = row[field]
        _upsert_job(conn, source["id"], source_job, normalized, now_utc())
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            now_utc(), "ihe_institution_excerpt_repair", row["id"], source["id"], row["source_job_id"],
            json.dumps({"institution_id": None}, ensure_ascii=False),
            json.dumps({"institution_raw": candidate}, ensure_ascii=False),
            "Recovered an explicit employer phrase from the preserved Inside Higher Ed listing excerpt; detail-page verification is separate.",
        ))
        repaired += 1
    return repaired


def _repair_inside_higher_ed_institution_names(conn):
    """Trim concatenated IHE employer/card chrome from stored detail fields."""
    source = conn.execute("SELECT id,region FROM sources WHERE name='inside_higher_ed'").fetchone()
    if not source:
        return 0
    rows = conn.execute("""
        SELECT j.*, js.source_job_id, js.source_url AS link_source_url,
               js.official_url AS link_official_url, sjr.source_url,
               sjr.official_url AS record_official_url, sjr.short_excerpt,
               sjr.structured_extraction, sjr.last_seen AS record_last_seen,
               i.official_name AS current_institution
        FROM jobs j
        JOIN job_sources js ON js.job_id=j.id AND js.source_id=? AND js.active=1
        JOIN source_job_records sjr ON sjr.source_id=js.source_id AND sjr.source_job_id=js.source_job_id
        LEFT JOIN institutions i ON i.id=j.institution_id
        ORDER BY j.id
    """, (source["id"],)).fetchall()
    repaired = 0
    for row in rows:
        try:
            extraction = json.loads(row["structured_extraction"] or "{}")
        except (TypeError, ValueError):
            extraction = {}
        raw = extraction.get("institution_raw") or row["current_institution"]
        location_hint = extraction.get("location_raw") or row["city"]
        candidate = InsideHigherEdAdapter._clean_institution_value(raw, location_hint)
        if not candidate or not raw or candidate == raw:
            continue
        source_job = SourceJob(
            source="inside_higher_ed",
            source_job_id=str(row["source_job_id"]),
            source_url=row["source_url"] or row["link_source_url"],
            official_url=row["record_official_url"] or row["link_official_url"] or extraction.get("official_url"),
            title_raw=row["title_raw"],
            institution_raw=candidate,
            school_raw=extraction.get("school_raw"),
            department_raw=extraction.get("department"),
            location_raw=location_hint,
            description_excerpt=row["short_excerpt"] or row["description_excerpt"],
            posted_date_raw=extraction.get("posted_date") or row["posted_date"],
            deadline_raw=extraction.get("deadline_date") or extraction.get("deadline_mode") or row["deadline_date"],
            salary_raw=extraction.get("salary_raw") or row["salary_raw"],
            captured_at=row["record_last_seen"] or row["last_seen_at"] or now_utc(),
            extra={"search_query": InsideHigherEdAdapter.search_query},
        )
        normalized = normalize_source_job(source_job, source["region"])
        for field in (
            "posted_date", "deadline_date", "deadline_mode", "deadline_evidence",
            "deadline_parse_reason", "country", "country_code", "region_group",
            "state_province", "city", "location_evidence", "salary_raw", "salary_min",
            "salary_max", "salary_currency", "salary_period", "start_term", "start_year",
            "visa_status", "official_url",
        ):
            if normalized.get(field) in (None, "", "unknown") and row[field] not in (None, "", "unknown"):
                normalized[field] = row[field]
        _upsert_job(conn, source["id"], source_job, normalized, now_utc())
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            now_utc(), "ihe_institution_value_cleanup", row["id"], source["id"], row["source_job_id"],
            json.dumps({"institution_raw": raw}, ensure_ascii=False),
            json.dumps({"institution_raw": candidate}, ensure_ascii=False),
            "Removed concatenated location/department/UI text from an explicit Inside Higher Ed employer value; source excerpt remains preserved.",
        ))
        repaired += 1
    return repaired


def _repair_inside_higher_ed_valid_through_deadlines(conn):
    """Replace IHE board-expiry dates with explicit posting evidence.

    The IHE JobPosting JSON-LD ``validThrough`` value is often a generic
    multi-year listing expiry.  It is not an employer application deadline.
    Existing derived rows therefore need to be replayed from the bounded
    detail excerpt, where ``deadline``/``closing``/``apply by`` and rolling
    language are the only accepted evidence.  Source URLs, source IDs and
    excerpts remain unchanged; only derived JSON fields and provenance are
    refreshed.
    """
    source = conn.execute("SELECT id FROM sources WHERE name='inside_higher_ed'").fetchone()
    if not source:
        return 0
    rows = conn.execute("""
        SELECT j.*, js.source_job_id, js.source_url, sjr.structured_extraction,
               sjr.short_excerpt, sjr.last_seen AS record_last_seen
        FROM jobs j
        JOIN job_sources js ON js.job_id=j.id AND js.source_id=? AND js.active=1
        JOIN source_job_records sjr ON sjr.source_id=js.source_id AND sjr.source_job_id=js.source_job_id
        ORDER BY j.id
    """, (source["id"],)).fetchall()
    repaired = 0
    for row in rows:
        evidence_text = row["description_excerpt"] or row["short_excerpt"] or ""
        parsed = parse_deadline(
            "", evidence_text, reference_date=row["first_seen_at"], return_details=True,
        )
        new_values = {
            "deadline_date": parsed["date"],
            "deadline_mode": parsed["mode"],
            "deadline_evidence": parsed.get("evidence"),
            "deadline_parse_reason": parsed.get("reason"),
        }
        old_values = {
            key: row[key] for key in new_values
        }
        if all(old_values[key] == new_values[key] for key in new_values):
            continue
        observed = now_utc()
        status, note = _status_for(new_values)
        conn.execute("""
            UPDATE jobs SET deadline_date=?,deadline_mode=?,deadline_evidence=?,
              deadline_parse_reason=?,status=?,verification_note=?,updated_at=?
            WHERE id=?
        """, (
            new_values["deadline_date"], new_values["deadline_mode"],
            new_values["deadline_evidence"], new_values["deadline_parse_reason"],
            status, note, observed, row["id"],
        ))

        try:
            extraction = json.loads(row["structured_extraction"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            extraction = {}
        extraction.update(new_values)
        content_hash = hashlib.sha256(
            json.dumps(extraction, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        conn.execute("""
            UPDATE source_job_records SET content_hash=?,structured_extraction=?
            WHERE source_id=? AND source_job_id=?
        """, (
            content_hash, json.dumps(extraction, ensure_ascii=False),
            source["id"], row["source_job_id"],
        ))

        for field_name in ("deadline_date", "deadline_mode"):
            conn.execute(
                "UPDATE job_field_provenance SET is_current=0 WHERE job_id=? AND field_name=?",
                (row["id"], field_name),
            )
        if new_values["deadline_date"]:
            conn.execute("""
                INSERT INTO job_field_provenance
                  (job_id,field_name,source_id,source_job_id,source_url,value_text,evidence_text,captured_at,is_current)
                VALUES (?,?,?,?,?,?,?,?,1)
            """, (
                row["id"], "deadline_date", source["id"], row["source_job_id"],
                row["source_url"], new_values["deadline_date"],
                new_values["deadline_evidence"] or "", observed,
            ))
        if new_values["deadline_mode"] != "unknown":
            conn.execute("""
                INSERT INTO job_field_provenance
                  (job_id,field_name,source_id,source_job_id,source_url,value_text,evidence_text,captured_at,is_current)
                VALUES (?,?,?,?,?,?,?,?,1)
            """, (
                row["id"], "deadline_mode", source["id"], row["source_job_id"],
                row["source_url"], new_values["deadline_mode"],
                new_values["deadline_evidence"] or new_values["deadline_parse_reason"] or "",
                observed,
            ))
        source_count = conn.execute(
            "SELECT COUNT(DISTINCT source_id) FROM job_sources WHERE job_id=? AND active=1",
            (row["id"],),
        ).fetchone()[0]
        conn.execute("""
            INSERT INTO job_status_history
              (job_id,observed_at,status,deadline,salary_raw,title_raw,source_count,change_reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            row["id"], observed, status, new_values["deadline_date"], row["salary_raw"],
            row["title_raw"], source_count, "ihe_valid_through_deadline_repair",
        ))
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            observed, "ihe_valid_through_deadline_repair", row["id"], source["id"],
            row["source_job_id"], json.dumps(old_values, ensure_ascii=False),
            json.dumps(new_values, ensure_ascii=False),
            "Removed a JobPosting validThrough/board-expiry derivative unless bounded detail text supplied explicit deadline or rolling evidence.",
        ))
        repaired += 1
    return repaired


def _repair_academic_entity_labels_and_country_aliases(conn):
    """Repair a small set of deterministic derived entity/geography errors.

    The affected values were created by public-board card parsing, not by the
    preserved source records themselves.  This migration therefore moves
    derived foreign-key links and updates provenance/audit rows while leaving
    ``source_job_records``, source URLs, excerpts, and private application
    state untouched.
    """
    institution_rules = {
        normalize_name("University of Toronto"): ("University of Toronto", "CA"),
        normalize_name("University of Auckland"): ("University of Auckland", "NZ"),
        normalize_name("The University of Auckland"): ("University of Auckland", "NZ"),
    }
    source = conn.execute("SELECT id FROM sources WHERE name='inside_higher_ed'").fetchone()
    ihe_source_id = int(source["id"]) if source else None
    changed_jobs = set()
    timestamp = now_utc()

    def json_aliases(value):
        try:
            parsed = json.loads(value or "[]")
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def merge_school(old_id, target_id):
        """Repoint a derived school without dropping evidence or job links."""
        if old_id == target_id:
            return
        conn.execute("UPDATE jobs SET school_id=? WHERE school_id=?", (target_id, old_id))
        conn.execute("UPDATE school_evidence SET school_id=? WHERE school_id=?", (target_id, old_id))
        override = conn.execute("SELECT * FROM school_tier_overrides WHERE school_id=?", (old_id,)).fetchone()
        target_override = conn.execute("SELECT 1 FROM school_tier_overrides WHERE school_id=?", (target_id,)).fetchone()
        if override and not target_override:
            conn.execute("UPDATE school_tier_overrides SET school_id=? WHERE school_id=?", (target_id, old_id))
        conn.execute("UPDATE aacsb_directory_schools SET linked_business_school_id=? WHERE linked_business_school_id=?", (target_id, old_id))
        conn.execute("UPDATE business_schools SET is_current=0, updated_at=? WHERE id=?", (now_utc(), old_id))

    def merge_institution(old_id, target_id):
        """Merge two derived institution rows while retaining old aliases."""
        if old_id == target_id:
            return
        old = conn.execute("SELECT * FROM institutions WHERE id=?", (old_id,)).fetchone()
        target = conn.execute("SELECT * FROM institutions WHERE id=?", (target_id,)).fetchone()
        if not old or not target:
            return
        aliases = json_aliases(target["aliases_json"])
        for value in [old["official_name"], *json_aliases(old["aliases_json"])]:
            if value and value != target["official_name"] and value not in aliases:
                aliases.append(value)
        conn.execute("UPDATE institutions SET aliases_json=?,updated_at=? WHERE id=?", (json.dumps(aliases[:80], ensure_ascii=False), now_utc(), target_id))
        old_schools = conn.execute("SELECT id,normalized_name FROM business_schools WHERE institution_id=?", (old_id,)).fetchall()
        for school in old_schools:
            target_school = conn.execute(
                "SELECT id FROM business_schools WHERE institution_id=? AND normalized_name=? AND is_current=1 LIMIT 1",
                (target_id, school["normalized_name"]),
            ).fetchone()
            if target_school:
                merge_school(int(school["id"]), int(target_school["id"]))
            else:
                conn.execute("UPDATE business_schools SET institution_id=?,updated_at=? WHERE id=?", (target_id, now_utc(), school["id"]))
        conn.execute("UPDATE jobs SET institution_id=? WHERE institution_id=?", (target_id, old_id))
        if not conn.execute("SELECT 1 FROM jobs WHERE institution_id=?", (old_id,)).fetchone():
            conn.execute("UPDATE institutions SET is_current=0,updated_at=? WHERE id=?", (now_utc(), old_id))

    def record_field(job_id, field_name, value, evidence):
        if value in (None, "") or ihe_source_id is None:
            return
        link = conn.execute(
            "SELECT source_job_id,source_url FROM job_sources WHERE job_id=? AND source_id=? AND active=1 LIMIT 1",
            (job_id, ihe_source_id),
        ).fetchone()
        if not link:
            return
        conn.execute("UPDATE job_field_provenance SET is_current=0 WHERE job_id=? AND field_name=?", (job_id, field_name))
        conn.execute(
            """INSERT INTO job_field_provenance
               (job_id,field_name,source_id,source_job_id,source_url,value_text,evidence_text,captured_at,is_current)
               VALUES (?,?,?,?,?,?,?,?,1)""",
            (job_id, field_name, ihe_source_id, link["source_job_id"], link["source_url"], str(value), evidence, timestamp),
        )

    # First merge institution names that are known to be the same university
    # but differ because a card appended a country or used an ambiguous code.
    institutions = conn.execute("SELECT * FROM institutions WHERE is_current=1 ORDER BY id").fetchall()
    for row in institutions:
        canonical = _canonical_institution_name(row["official_name"])
        rule = institution_rules.get(normalize_name(canonical))
        if not rule:
            continue
        canonical_name, desired_code = rule
        target = conn.execute(
            "SELECT * FROM institutions WHERE normalized_name=? AND country_code=? AND is_current=1 ORDER BY id LIMIT 1",
            (normalize_name(canonical_name), desired_code),
        ).fetchone()
        if target and int(target["id"]) != int(row["id"]):
            merge_institution(int(row["id"]), int(target["id"]))
            row_id = int(target["id"])
        else:
            row_id = int(row["id"])
            conn.execute(
                """UPDATE institutions SET official_name=?,normalized_name=?,country=?,country_code=?,
                   region_group=?,updated_at=? WHERE id=?""",
                (canonical_name, normalize_name(canonical_name), country_display(desired_code), desired_code,
                 REGION_GROUPS.get(country_display(desired_code), "Other"), now_utc(), row_id),
            )
        # A known institution-country rule is evidence for the derived
        # location only where the existing source normalization was ambiguous.
        jobs = conn.execute(
            """SELECT j.* FROM jobs j
               JOIN job_sources js ON js.job_id=j.id AND js.active=1
               WHERE j.institution_id=? AND (? IS NULL OR js.source_id=?)""",
            (row_id, ihe_source_id, ihe_source_id),
        ).fetchall()
        for job in jobs:
            old = {key: job[key] for key in ("country", "country_code", "region_group", "state_province", "location_evidence")}
            new_state = job["state_province"]
            new_city = job["city"]
            if desired_code == "CA" and normalize_name(canonical_name) == normalize_name("University of Toronto"):
                if normalize_name(new_city) == "toronto" or new_state == "CA":
                    new_state = "ON"
                    if not new_city:
                        new_city = "Toronto"
            if desired_code == "NZ" and normalize_name(canonical_name) == normalize_name("University of Auckland"):
                if not new_city or normalize_name(new_city) in {"new zealand", "nz"}:
                    new_city = "Auckland"
                new_state = None
            if desired_code == "MO" and normalize_name(new_city) == "mo":
                new_city = None
            values = {
                "country": country_display(desired_code), "country_code": desired_code,
                "region_group": REGION_GROUPS.get(country_display(desired_code), "Other"),
                "state_province": new_state, "city": new_city,
                "location_evidence": "institution_hint",
            }
            if any(old[key] != values[key] for key in values):
                conn.execute(
                    """UPDATE jobs SET country=?,country_code=?,region_group=?,state_province=?,city=?,
                       location_evidence=?,updated_at=? WHERE id=?""",
                    (values["country"], values["country_code"], values["region_group"], values["state_province"],
                     values["city"], values["location_evidence"], now_utc(), job["id"]),
                )
                changed_jobs.add(int(job["id"]))
                for field_name in ("country", "country_code", "region_group", "state_province", "city"):
                    record_field(job["id"], field_name, values[field_name], "Central institution-country alias and explicit public-board location context.")
                conn.execute(
                    """INSERT INTO faculty_job_repair_audit
                       (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
                       SELECT ?,?,?,?,?,?,?,?""",
                    (now_utc(), "institution_country_alias_repair", job["id"], ihe_source_id,
                     (conn.execute("SELECT source_job_id FROM job_sources WHERE job_id=? AND source_id=? AND active=1 LIMIT 1", (job["id"], ihe_source_id)).fetchone() or {"source_job_id": None})["source_job_id"],
                     json.dumps(old, ensure_ascii=False), json.dumps(values, ensure_ascii=False),
                     "Corrected a deterministic institution-country/location alias; raw source records were preserved."),
                )

    # Strip portal labels from school entities that are still linked to jobs.
    school_rows = conn.execute("SELECT * FROM business_schools WHERE is_current=1 ORDER BY id").fetchall()
    for row in school_rows:
        clean = re.sub(r"^(?:Job\s+)?Description\s+", "", row["official_name"], flags=re.I).strip()
        clean = re.sub(r"^Office\s+Next\s+", "", clean, flags=re.I).strip()
        clean = re.sub(r"^The\s+", "", clean, flags=re.I).strip()
        clean = re.sub(r"\s+Department$", "", clean, flags=re.I).strip()
        if not clean or clean == row["official_name"]:
            continue
        target = conn.execute(
            "SELECT id FROM business_schools WHERE institution_id=? AND normalized_name=? AND is_current=1 LIMIT 1",
            (row["institution_id"], normalize_name(clean)),
        ).fetchone()
        if target:
            merge_school(int(row["id"]), int(target["id"]))
        else:
            conn.execute("UPDATE business_schools SET official_name=?,normalized_name=?,updated_at=? WHERE id=?", (clean, normalize_name(clean), now_utc(), row["id"]))
        conn.execute(
            """INSERT INTO faculty_job_repair_audit
               (observed_at,action,old_value,new_value,reason)
               VALUES (?,?,?,?,?)""",
            (now_utc(), "school_entity_label_repair", row["official_name"], clean,
             "Removed a portal Description/Office label from the derived school entity; source wording remains in the preserved excerpt."),
        )

    # Deactivate only unreferenced derived entities.  This keeps the old rows
    # available for audit and avoids presenting stale duplicates in Explorer.
    conn.execute(
        """UPDATE business_schools SET is_current=0,updated_at=?
           WHERE is_current=1
             AND NOT EXISTS (SELECT 1 FROM jobs WHERE jobs.school_id=business_schools.id)
             AND NOT EXISTS (SELECT 1 FROM school_evidence WHERE school_evidence.school_id=business_schools.id)
             AND NOT EXISTS (SELECT 1 FROM school_tier_overrides WHERE school_tier_overrides.school_id=business_schools.id)""",
        (now_utc(),),
    )
    for job_id in changed_jobs:
        row = conn.execute("SELECT status,deadline_date,salary_raw,title_raw FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row:
            source_count = conn.execute("SELECT COUNT(DISTINCT source_id) FROM job_sources WHERE job_id=? AND active=1", (job_id,)).fetchone()[0]
            conn.execute(
                """INSERT INTO job_status_history
                   (job_id,observed_at,status,deadline,salary_raw,title_raw,source_count,change_reason)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (job_id, now_utc(), row["status"], row["deadline_date"], row["salary_raw"], row["title_raw"], source_count, "institution_country_alias_repair"),
            )
    return {"changed_jobs": len(changed_jobs)}


def _repair_inside_higher_ed_iso_only_locations(conn):
    """Repair IHE records where a bare country code was stored as a city.

    Older normalized rows treated structured values such as ``CN`` and
    ``AE`` as the first comma-separated location component. The preserved
    source-record JSON contains the original location token, so this repair
    can re-derive country evidence locally without a network request or any
    source-record deletion.
    """
    source = conn.execute(
        "SELECT id,region FROM sources WHERE name='inside_higher_ed'"
    ).fetchone()
    if not source:
        return {"changed_jobs": 0}
    changed_jobs = set()
    observed = now_utc()
    rows = conn.execute("""
        SELECT DISTINCT j.*, js.source_job_id, js.source_url AS link_source_url,
               sjr.source_url, sjr.structured_extraction, s.region
        FROM jobs j
        JOIN job_sources js ON js.job_id=j.id AND js.source_id=? AND js.active=1
        JOIN source_job_records sjr
          ON sjr.source_id=js.source_id AND sjr.source_job_id=js.source_job_id
        JOIN sources s ON s.id=js.source_id
        WHERE j.city IS NOT NULL AND length(trim(j.city))=2
          AND upper(trim(j.city))=trim(j.city)
    """, (source["id"],)).fetchall()
    for row in rows:
        try:
            extraction = json.loads(row["structured_extraction"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            extraction = {}
        raw_location = str(extraction.get("location_raw") or "").strip()
        if not re.fullmatch(r"[A-Za-z]{2}", raw_location):
            continue
        parsed = parse_location(
            raw_location, row["region"],
            institution_text=extraction.get("institution_raw"),
            description=row["description_excerpt"],
        )
        if not parsed.get("country_code") or parsed.get("city") is not None:
            continue
        values = {
            "country": parsed.get("country"),
            "country_code": parsed.get("country_code"),
            "region_group": parsed.get("region_group"),
            "state_province": parsed.get("state_province"),
            "city": None,
            "location_evidence": "location_raw_iso_code",
        }
        old = {key: row[key] for key in values}
        if all(old[key] == values[key] for key in values):
            continue
        conn.execute("""
            UPDATE jobs SET country=?,country_code=?,region_group=?,state_province=?,city=?,
              location_evidence=?,updated_at=? WHERE id=?
        """, (
            values["country"], values["country_code"], values["region_group"],
            values["state_province"], values["city"], values["location_evidence"],
            observed, row["id"],
        ))
        for field_name in ("country", "country_code", "region_group", "state_province", "city"):
            conn.execute(
                "UPDATE job_field_provenance SET is_current=0 WHERE job_id=? AND field_name=?",
                (row["id"], field_name),
            )
            if values[field_name] in (None, ""):
                continue
            conn.execute("""
                INSERT INTO job_field_provenance
                  (job_id,field_name,source_id,source_job_id,source_url,value_text,evidence_text,captured_at,is_current)
                VALUES (?,?,?,?,?,?,?,?,1)
            """, (
                row["id"], field_name, source["id"], row["source_job_id"],
                row["source_url"] or row["link_source_url"], str(values[field_name]),
                f"Structured IHE location code: {raw_location}", observed,
            ))
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            observed, "ihe_iso_location_repair", row["id"], source["id"],
            row["source_job_id"], json.dumps(old, ensure_ascii=False),
            json.dumps(values, ensure_ascii=False),
            "Reclassified a bare structured country code as country evidence; it was not a city.",
        ))
        source_count = conn.execute(
            "SELECT COUNT(DISTINCT source_id) FROM job_sources WHERE job_id=? AND active=1",
            (row["id"],),
        ).fetchone()[0]
        conn.execute("""
            INSERT INTO job_status_history
              (job_id,observed_at,status,deadline,salary_raw,title_raw,source_count,change_reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            row["id"], observed, row["status"], row["deadline_date"],
            row["salary_raw"], row["title_raw"], source_count,
            "ihe_iso_location_repair",
        ))
        changed_jobs.add(int(row["id"]))
    return {"changed_jobs": len(changed_jobs)}


def _repair_inside_higher_ed_school_links_from_records(conn):
    """Restore only IHE school entities supported by current posting evidence."""
    source = conn.execute(
        "SELECT id,region FROM sources WHERE name='inside_higher_ed'"
    ).fetchone()
    if not source:
        return {"changed_jobs": 0}
    observed = now_utc()
    changed_jobs = set()
    rows = conn.execute("""
        SELECT j.*, i.official_name AS institution_name,
               js.source_job_id, js.source_url AS link_source_url,
               sjr.source_url, sjr.official_url AS record_official_url,
               sjr.short_excerpt, sjr.structured_extraction,
               sjr.first_seen AS record_first_seen, sjr.last_seen AS record_last_seen
        FROM jobs j
        JOIN job_sources js ON js.job_id=j.id AND js.source_id=? AND js.active=1
        JOIN source_job_records sjr
          ON sjr.source_id=js.source_id AND sjr.source_job_id=js.source_job_id
        LEFT JOIN institutions i ON i.id=j.institution_id
        WHERE j.school_id IS NULL
        ORDER BY j.id
    """, (source["id"],)).fetchall()
    for row in rows:
        try:
            extraction = json.loads(row["structured_extraction"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            extraction = {}
        excerpt = row["short_excerpt"] or row["description_excerpt"] or ""
        school_raw = InsideHigherEdAdapter._detail_school(excerpt)
        if (
            not school_raw
            and extraction.get("school_evidence_rule_version") == IHE_SCHOOL_EVIDENCE_RULE_VERSION
        ):
            school_raw = str(extraction.get("school_raw") or "").strip() or None
        if not school_raw or row["institution_id"] is None:
            continue
        source_job = SourceJob(
            source="inside_higher_ed",
            source_job_id=str(row["source_job_id"]),
            source_url=row["source_url"] or row["link_source_url"],
            official_url=row["record_official_url"],
            title_raw=row["title_raw"],
            institution_raw=row["institution_name"] or extraction.get("institution_raw") or "Unknown institution",
            school_raw=school_raw,
            department_raw=extraction.get("department"),
            location_raw=extraction.get("location_raw") or row["city"],
            description_excerpt=excerpt,
            captured_at=row["record_last_seen"] or row["record_first_seen"] or observed,
            extra={
                "school_evidence_context": "structured_posting",
                "school_evidence_rule_version": IHE_SCHOOL_EVIDENCE_RULE_VERSION,
            },
        )
        school_id = _school(conn, int(row["institution_id"]), school_raw, source_job)
        if school_id is None:
            continue
        conn.execute(
            "UPDATE jobs SET school_id=?,school_evidence_context='structured_posting',updated_at=? WHERE id=?",
            (school_id, observed, row["id"]),
        )
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            observed, "ihe_school_link_repair", row["id"], source["id"],
            row["source_job_id"], json.dumps({"school_id": None}, ensure_ascii=False),
            json.dumps({"school_id": school_id, "school_raw": school_raw}, ensure_ascii=False),
            "Restored a business-school field revalidated by the current bounded IHE posting parser; no school was inferred from location or legacy collaborator text.",
        ))
        source_count = conn.execute(
            "SELECT COUNT(DISTINCT source_id) FROM job_sources WHERE job_id=? AND active=1",
            (row["id"],),
        ).fetchone()[0]
        conn.execute("""
            INSERT INTO job_status_history
              (job_id,observed_at,status,deadline,salary_raw,title_raw,source_count,change_reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            row["id"], observed, row["status"], row["deadline_date"], row["salary_raw"],
            row["title_raw"], source_count, "ihe_school_link_repair",
        ))
        changed_jobs.add(int(row["id"]))
    return {"changed_jobs": len(changed_jobs)}


def _repair_business_school_entity_labels(conn):
    """Clean portal chrome and merge deterministic same-institution schools."""
    observed = now_utc()
    stats = {"merged": 0, "renamed": 0, "orphans_deactivated": 0}
    generic_keys = {
        normalize_name(value) for value in (
            "Business School", "School of Business", "College of Business",
            "College of Business Administration", "Faculty of Business",
            "Faculty of Business Administration", "School of Management",
            "College of Management", "Faculty of Management",
        )
    }
    stop = {
        "the", "of", "and", "business", "school", "college", "faculty",
        "management", "administration", "university", "graduate", "technology",
    }

    def core_tokens(value):
        return {token for token in normalize_name(value).split() if token not in stop}

    def merge_school(old, target, cleaned):
        old_id, target_id = int(old["id"]), int(target["id"])
        if old_id == target_id:
            return
        conn.execute("UPDATE jobs SET school_id=? WHERE school_id=?", (target_id, old_id))
        conn.execute("UPDATE school_evidence SET school_id=? WHERE school_id=?", (target_id, old_id))
        old_override = conn.execute(
            "SELECT 1 FROM school_tier_overrides WHERE school_id=?", (old_id,),
        ).fetchone()
        target_override = conn.execute(
            "SELECT 1 FROM school_tier_overrides WHERE school_id=?", (target_id,),
        ).fetchone()
        if old_override and not target_override:
            conn.execute(
                "UPDATE school_tier_overrides SET school_id=? WHERE school_id=?",
                (target_id, old_id),
            )
        conn.execute(
            "UPDATE aacsb_directory_schools SET linked_business_school_id=?,updated_at=? "
            "WHERE linked_business_school_id=?",
            (target_id, observed, old_id),
        )
        conn.execute(
            """UPDATE business_schools SET
                 website=COALESCE(website,?),aacsb=CASE WHEN ?=1 THEN 1 ELSE aacsb END,
                 equis=CASE WHEN ?=1 THEN 1 ELSE equis END,
                 amba=CASE WHEN ?=1 THEN 1 ELSE amba END,
                 doctoral_business_program=COALESCE(doctoral_business_program,?),
                 last_verified_at=COALESCE(last_verified_at,?),is_current=1,updated_at=?
               WHERE id=?""",
            (old["website"], old["aacsb"], old["equis"], old["amba"],
             old["doctoral_business_program"], old["last_verified_at"], observed, target_id),
        )
        conn.execute(
            "UPDATE business_schools SET is_current=0,updated_at=? WHERE id=?",
            (observed, old_id),
        )
        refresh_school_classification(conn, target_id)
        conn.execute(
            """INSERT INTO faculty_job_repair_audit
                 (observed_at,action,old_value,new_value,reason)
               VALUES (?,?,?,?,?)""",
            (observed, "school_entity_label_merge",
             json.dumps({"school_id": old_id, "name": old["official_name"]}, ensure_ascii=False),
             json.dumps({"school_id": target_id, "name": target["official_name"]}, ensure_ascii=False),
             "Merged a same-institution derived school label after removing bounded job-board chrome or reconciling it to the institution's sole AACSB-evidenced business school."),
        )
        stats["merged"] += 1

    rows = conn.execute(
        "SELECT * FROM business_schools WHERE is_current=1 ORDER BY id"
    ).fetchall()
    for row in rows:
        # A row may already have been merged while processing an earlier alias.
        current = conn.execute(
            "SELECT * FROM business_schools WHERE id=? AND is_current=1", (row["id"],),
        ).fetchone()
        if not current:
            continue
        cleaned = _clean_derived_school_label(current["official_name"])
        cleaned_key = normalize_name(cleaned)
        candidates = conn.execute(
            "SELECT * FROM business_schools WHERE institution_id=? AND id!=? ORDER BY is_current DESC,id",
            (current["institution_id"], current["id"]),
        ).fetchall()
        target = next((candidate for candidate in candidates
                       if candidate["normalized_name"] == cleaned_key), None)
        if target is None:
            aacsb_targets = conn.execute(
                """SELECT DISTINCT bs.* FROM business_schools bs
                   JOIN school_evidence se ON se.school_id=bs.id AND se.evidence_type='AACSB'
                   WHERE bs.institution_id=? AND bs.id!=? AND bs.is_current=1
                   ORDER BY bs.id""",
                (current["institution_id"], current["id"]),
            ).fetchall()
            if len(aacsb_targets) == 1:
                candidate = aacsb_targets[0]
                current_core = core_tokens(cleaned)
                target_core = core_tokens(candidate["official_name"])
                if (
                    cleaned_key in generic_keys
                    or candidate["normalized_name"] in generic_keys
                    or bool(current_core and target_core and current_core.intersection(target_core))
                    or cleaned_key in candidate["normalized_name"]
                    or candidate["normalized_name"] in cleaned_key
                ):
                    target = candidate
        if target is not None:
            merge_school(current, target, cleaned)
            continue
        if cleaned and cleaned != current["official_name"]:
            conn.execute(
                "UPDATE business_schools SET official_name=?,normalized_name=?,updated_at=? WHERE id=?",
                (cleaned, cleaned_key, observed, current["id"]),
            )
            conn.execute(
                """INSERT INTO faculty_job_repair_audit
                     (observed_at,action,old_value,new_value,reason)
                   VALUES (?,?,?,?,?)""",
                (observed, "school_entity_label_repair", current["official_name"], cleaned,
                 "Removed bounded job-board chrome from a derived school entity; preserved source excerpts were not changed."),
            )
            stats["renamed"] += 1

    cur = conn.execute(
        """UPDATE business_schools SET is_current=0,updated_at=?
           WHERE is_current=1
             AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.school_id=business_schools.id)
             AND NOT EXISTS (SELECT 1 FROM school_evidence se WHERE se.school_id=business_schools.id)
             AND NOT EXISTS (SELECT 1 FROM school_tier_overrides so WHERE so.school_id=business_schools.id)
             AND NOT EXISTS (SELECT 1 FROM aacsb_directory_schools d WHERE d.linked_business_school_id=business_schools.id)""",
        (observed,),
    )
    stats["orphans_deactivated"] = max(0, int(cur.rowcount or 0))
    return stats


def _repair_job_status_recency(conn):
    """Forward-correct stale active labels from preserved date evidence."""
    rows = conn.execute(
        """SELECT j.*,MIN(js.source_id) AS audit_source_id,
                  MIN(js.source_job_id) AS audit_source_job_id,
                  COUNT(DISTINCT js.source_id) AS source_count
           FROM jobs j
           LEFT JOIN job_sources js ON js.job_id=j.id AND js.active=1
           WHERE j.derived_quality='accepted'
             AND j.status IN ('open','likely_open','closing_soon')
           GROUP BY j.id ORDER BY j.id"""
    ).fetchall()
    changed = 0
    for row in rows:
        desired_status, desired_note = _status_for(dict(row))
        if desired_status == row["status"]:
            continue
        observed = now_utc()
        conn.execute(
            "UPDATE jobs SET status=?,verification_note=?,updated_at=? WHERE id=?",
            (desired_status, desired_note, observed, row["id"]),
        )
        conn.execute(
            """INSERT INTO faculty_job_repair_audit
                 (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
               VALUES (?,?,?,?,?,?,?,?)""",
            (observed, "job_status_recency_repair", row["id"], row["audit_source_id"],
             row["audit_source_job_id"],
             json.dumps({"status": row["status"], "verification_note": row["verification_note"]}, ensure_ascii=False),
             json.dumps({"status": desired_status, "verification_note": desired_note}, ensure_ascii=False),
             "Applied fixed-deadline and 365-day posting-recency boundaries; a still-public board page was not treated as proof that an old vacancy remains open."),
        )
        conn.execute(
            """INSERT INTO job_status_history
                 (job_id,observed_at,status,deadline,salary_raw,title_raw,source_count,change_reason)
               VALUES (?,?,?,?,?,?,?,?)""",
            (row["id"], observed, desired_status, row["deadline_date"], row["salary_raw"],
             row["title_raw"], int(row["source_count"] or 0), "job_status_recency_repair"),
        )
        changed += 1
    return {"changed": changed}


def _run_faculty_jobs_repair_if_needed(conn):
    stats = None
    if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=1").fetchone():
        stats = _repair_derived_data(conn)
        conn.execute(
            "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
            (1, now_utc(), "P0 derived-field repair: deadline, location, country, institution and conservative source-record dedup."),
        )
    # Version 2 replays the same source-record migration after the
    # EURAXESS work-location parser was corrected (city-before-country cards
    # such as Amsterdam must not regress to country-only locations).
    if not conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=2").fetchone():
        stats = _repair_derived_data(conn)
        conn.execute(
            "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
            (2, now_utc(), "P0 derived-field replay after source-specific location/institution parser corrections."),
        )
    return stats


def _repair_duplicate_review_metadata(conn):
    """Convert legacy fuzzy labels to explicit review-only semantics."""
    conn.execute(
        "UPDATE possible_duplicates SET match_basis='fuzzy_review_only' WHERE match_basis='conservative_fuzzy'"
    )
    rows = conn.execute("""
        SELECT fingerprint, GROUP_CONCAT(id) AS ids
        FROM jobs
        WHERE fingerprint IS NOT NULL AND fingerprint!=''
        GROUP BY fingerprint HAVING COUNT(*)>1
    """).fetchall()
    inserted = 0
    for row in rows:
        ids = [int(item) for item in str(row["ids"] or "").split(",") if item.isdigit()]
        for left, right in zip(ids, ids[1:]):
            cur = conn.execute("""
                INSERT OR IGNORE INTO possible_duplicates
                  (job_id,possible_job_id,confidence,match_basis,resolved,created_at)
                VALUES (?,?,?,?,0,?)
            """, (left, right, 0.98, "fingerprint_review_only", now_utc()))
            inserted += int(cur.rowcount > 0)
    return inserted


def repair_faculty_jobs_database(db_path=None):
    """Run the idempotent repair migration explicitly and return its stats."""
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        if conn.execute("SELECT 1 FROM faculty_job_migrations WHERE version=1").fetchone():
            return {"ok": True, "skipped": True, "reason": "repair migration already applied"}
        stats = _repair_derived_data(conn)
        conn.execute(
            "INSERT INTO faculty_job_migrations (version,applied_at,note) VALUES (?,?,?)",
            (1, now_utc(), "Explicit Academic Career derived-field repair."),
        )
        conn.commit()
        return {"ok": True, **(stats or {})}
    finally:
        conn.close()


def _mark_missing_after_success(conn, source_id, seen_source_job_ids):
    seen = set(str(item) for item in seen_source_job_ids)
    rows = conn.execute("SELECT job_id,source_job_id,consecutive_missing_runs FROM job_sources WHERE source_id=? AND active=1", (source_id,)).fetchall()
    for row in rows:
        if str(row["source_job_id"]) in seen:
            continue
        missing = int(row["consecutive_missing_runs"] or 0) + 1
        active = 1 if missing < 3 else 0
        conn.execute("UPDATE job_sources SET consecutive_missing_runs=?, active=? WHERE job_id=? AND source_id=? AND source_job_id=?", (missing, active, row["job_id"], source_id, row["source_job_id"]))
        if not active:
            active_count = conn.execute("SELECT COUNT(*) FROM job_sources WHERE job_id=? AND active=1", (row["job_id"],)).fetchone()[0]
            if active_count == 0:
                conn.execute("UPDATE jobs SET status='closed', closed_at=COALESCE(closed_at,?), updated_at=?, verification_note=? WHERE id=? AND status NOT IN ('closed','unknown')", (now_utc(), now_utc(), "No active source has listed this job for three successful runs.", row["job_id"]))


def _safe_error(exc):
    text = re.sub(r"[\r\n\t]+", " ", str(exc or ""))
    text = re.sub(r"(?i)(token|password|cookie|authorization)\s*[:=]\s*\S+", r"\1=[redacted]", text)
    return text[:500]


def update_faculty_jobs(db_path=None, source_names=None, timeout=None, max_pages=None,
                        adapters=None, detail_budget=None):
    """Run selected public adapters independently and transactionally."""
    db_path = db_path or FACULTY_DB_PATH
    ensure_faculty_jobs_tables(db_path)
    with _FACULTY_UPDATE_LOCK:
        conn = _connect(db_path)
        try:
            rows = conn.execute("SELECT * FROM sources ORDER BY priority,name").fetchall()
            requested = {str(item).strip() for item in (source_names or []) if str(item).strip()}
            selected = [row for row in rows if (not requested or row["name"] in requested)]
            if requested:
                known = {row["name"] for row in rows}
                missing = sorted(requested - known)
            else:
                missing = []
            adapter_map = {adapter.name: adapter for adapter in (adapters or adapter_catalog())}
            results = []
            for source in selected:
                started = now_utc()
                conn.execute("UPDATE sources SET last_attempt_at=?, last_status='running', last_error=NULL, updated_at=? WHERE id=?", (started, started, source["id"]))
                run_id = conn.execute("INSERT INTO ingestion_runs (source_id,started_at,status) VALUES (?,?,?)", (source["id"], started, "running")).lastrowid
                conn.commit()
                if not source["enabled"] or source["support_status"] not in {"enabled", "degraded"}:
                    reason = source["support_reason"] or "Source disabled by policy."
                    conn.execute("UPDATE ingestion_runs SET finished_at=?,status='skipped',error_summary=? WHERE id=?", (now_utc(), reason, run_id))
                    conn.execute("UPDATE sources SET last_status='skipped',last_error=?,updated_at=? WHERE id=?", (reason[:500], now_utc(), source["id"]))
                    conn.commit()
                    results.append({"source": source["name"], "status": "skipped", "reason": reason, "items_seen": 0})
                    continue
                adapter = adapter_map.get(source["adapter_name"])
                if not adapter:
                    error = "adapter not installed"
                    conn.execute("UPDATE ingestion_runs SET finished_at=?,status='error',error_count=1,error_summary=? WHERE id=?", (now_utc(), error, run_id))
                    conn.execute("UPDATE sources SET last_status='error',last_error=?,updated_at=? WHERE id=?", (error, now_utc(), source["id"]))
                    conn.commit()
                    results.append({"source": source["name"], "status": "error", "error": error})
                    continue
                if timeout is not None:
                    adapter.timeout = max(3, int(timeout))
                if max_pages is not None:
                    adapter.max_pages = max(1, int(max_pages))
                if detail_budget is not None and hasattr(adapter, "detail_budget"):
                    adapter.detail_budget = max(0, min(1000, int(detail_budget)))
                try:
                    response = adapter.fetch()
                    inserted = updated = merged = 0
                    seen = []
                    with conn:
                        for source_job in response.jobs:
                            normalized = normalize_source_job(source_job, source["region"])
                            _job_id, action = _upsert_job(conn, source["id"], source_job, normalized, started)
                            seen.append(source_job.source_job_id)
                            if action == "inserted": inserted += 1
                            elif action == "merged": merged += 1
                            else: updated += 1
                        _mark_missing_after_success(conn, source["id"], seen)
                        finished = now_utc()
                        run_notes = "; ".join(str(note) for note in (response.notes or []) if note).strip()[:500] or None
                        conn.execute("""
                            UPDATE ingestion_runs SET finished_at=?,status='success',pages_fetched=?,items_seen=?,
                              items_inserted=?,items_updated=?,items_merged=?,error_count=0,error_summary=? WHERE id=?
                        """, (finished, response.pages_fetched, len(response.jobs), inserted, updated, merged,
                              run_notes, run_id))
                        conn.execute("UPDATE sources SET last_success_at=?,last_status='ok',last_error=NULL,updated_at=? WHERE id=?", (finished, finished, source["id"]))
                    results.append({"source": source["name"], "status": "success", "pages_fetched": response.pages_fetched, "items_seen": len(response.jobs), "items_inserted": inserted, "items_updated": updated, "items_merged": merged, "notes": response.notes})
                except Exception as exc:
                    error = _safe_error(exc)
                    conn.execute("UPDATE ingestion_runs SET finished_at=?,status='error',error_count=1,error_summary=? WHERE id=?", (now_utc(), error, run_id))
                    conn.execute("UPDATE sources SET last_status='error',last_error=?,updated_at=? WHERE id=?", (error, now_utc(), source["id"]))
                    conn.commit()
                    LOG.warning("faculty source failed source=%s run_id=%s error=%s", source["name"], run_id, error)
                    results.append({"source": source["name"], "status": "error", "error": error})
            if missing:
                results.append({"source": "request", "status": "error", "error": "unknown sources: " + ", ".join(missing)})
            if any(item.get("status") == "success" for item in results):
                _record_source_coverage_history(
                    conn,
                    notes="Recorded after a bounded public-source ingestion run; changing source coverage is not market growth.",
                )
                conn.commit()
            return {"ok": not any(item.get("status") == "error" for item in results), "sources": results, "updated_at": now_utc()}
        finally:
            conn.close()


def _source_names(conn, job_id):
    return [dict(row) for row in conn.execute("""
        SELECT s.name,s.region,s.base_url,js.source_job_id,js.source_url,js.official_url,js.first_seen,js.last_seen,js.active
        FROM job_sources js JOIN sources s ON s.id=js.source_id WHERE js.job_id=? ORDER BY s.priority,s.name
    """, (job_id,)).fetchall()]


def _job_dict(conn, row, include_private=False):
    value = dict(row)
    value["discipline_secondary"] = _json_load(value.get("discipline_secondary_json"), [])
    value["keywords"] = _json_load(value.get("keywords_json"), [])
    value["teaching_areas"] = _json_load(value.get("teaching_areas_json"), [])
    value["research_areas"] = _json_load(value.get("research_areas_json"), [])
    value["school_tier"] = value.get("business_research_tier") or "Unclassified"
    value["university_level"] = value.get("university_research_level") or "Unknown"
    if value.get("school_id"):
        evidence_count = conn.execute(
            "SELECT COUNT(*) FROM school_evidence WHERE school_id=?", (value["school_id"],)
        ).fetchone()[0]
        override = conn.execute(
            "SELECT 1 FROM school_tier_overrides WHERE school_id=?", (value["school_id"],)
        ).fetchone()
        if evidence_count:
            value["school_evidence_status"] = "verified_school_evidence"
        elif override:
            value["school_evidence_status"] = "manual_school_override"
        else:
            value["school_evidence_status"] = "linked_school_entity"
    else:
        value["school_evidence_status"] = "explicit_business_school_text" if value.get("business_scope") == "business_school" else "none"
    value["school_evidence_label"] = {
        "explicit_business_school_text": "Explicit business-school text",
        "linked_school_entity": "Linked local school entity; not independently verified",
        "verified_school_evidence": "Verified school evidence",
        "manual_school_override": "Manual school classification override; independent verification not claimed",
        "none": "No school evidence",
    }.get(value["school_evidence_status"], "Unknown")
    value["scope_override"] = {
        "action": value.get("scope_override_action"),
        "reason": value.get("scope_override_reason"),
        "source_url": value.get("scope_override_source_url"),
    } if value.get("scope_override_action") else None
    value["sources"] = _source_names(conn, value["id"])
    if include_private:
        state = conn.execute("SELECT * FROM user_job_state WHERE job_id=?", (value["id"],)).fetchone()
        value["personal_state"] = dict(state) if state else None
        value["application_events"] = [dict(event) for event in conn.execute(
            "SELECT id,event_type,event_date,note,created_at FROM application_events WHERE job_id=? ORDER BY event_date DESC,id DESC",
            (value["id"],),
        ).fetchall()]
        value["fit"] = score_job(value, load_profile())
    else:
        for key in ("personal_state", "fit", "notes", "cv_version"):
            value.pop(key, None)
    return value


def _job_select():
    return """
      SELECT j.*, i.official_name AS institution_name, i.institution_url,
             i.university_research_level, i.university_research_level_system,
             i.research_memberships_json, i.carnegie_class, i.u15_member,
             bs.official_name AS business_school_name, bs.website AS school_website,
             bs.aacsb, bs.equis, bs.amba, bs.doctoral_business_program,
             bs.business_research_tier, bs.business_research_tier_score,
             bs.business_research_tier_confidence,
             bs.management_strength, bs.is_strength, bs.marketing_strength,
             bs.finance_strength, bs.accounting_strength, bs.operations_strength,
             so.action AS scope_override_action, so.reason AS scope_override_reason,
             so.source_url AS scope_override_source_url
      FROM jobs j
      LEFT JOIN institutions i ON i.id=j.institution_id
      LEFT JOIN business_schools bs ON bs.id=j.school_id
      LEFT JOIN job_scope_overrides so ON so.job_id=j.id
    """


def _requested_scope(query=None):
    """Return the public market view requested by a caller.

    The business-market view is the safe default for this domain.  The raw
    source catalogue remains available explicitly through ``scope=all``.
    """
    value = str((query or {}).get("scope") or "business").strip().casefold()
    if value in {"all", "audit", "all_postings"}:
        return "all"
    if value in {"business_school", "verified_business_school", "school"}:
        return "business_school"
    return "business"


def _scope_conditions(query=None, prefix=""):
    scope = _requested_scope(query)
    column = f"{prefix}business_scope" if prefix else "business_scope"
    override = "so.action" if prefix else "scope_override_action"
    quality = f"{prefix}derived_quality" if prefix else "derived_quality"
    eligible = f"{prefix}faculty_market_eligible" if prefix else "faculty_market_eligible"
    status = f"{prefix}status" if prefix else "status"
    active = "" if str((query or {}).get("status") or "").strip() else (
        f" AND {status} IN ('open','likely_open','closing_soon')"
    )
    if scope == "business_school":
        return [f"({quality}='accepted' AND {eligible}=1 AND {column}='business_school' AND COALESCE({override},'')!='exclude'{active})"], [], scope
    if scope == "business":
        return [f"((({quality}='accepted' AND {eligible}=1 AND {column} IN ('business_school','business_discipline') AND COALESCE({override},'')!='exclude') OR {override}='include'){active})"], [], scope
    return [], [], scope


def _summary_scope_conditions(query=None):
    """Build the same normalized subset used by list, KPI and export APIs."""
    clauses, args = _query_conditions(query)
    return clauses, args, _requested_scope(query)


def _query_conditions(query):
    query = query or {}
    clauses, args, _scope = _scope_conditions(query, "j.")
    q = str(query.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        clauses.append("(j.title_raw LIKE ? OR i.official_name LIKE ? OR bs.official_name LIKE ? OR j.department LIKE ? OR j.description_excerpt LIKE ? OR j.city LIKE ?)")
        args.extend([like] * 6)
    country = str(query.get("country") or "").strip()
    if country:
        code = country_code_for(country)
        if code:
            clauses.append("j.country_code=?")
            args.append(code)
        else:
            # An unsupported country value is a valid filter with no matches,
            # not a server error or a silent source-region fallback.
            clauses.append("1=0")
    for key, column in (("region", "j.region_group"), ("state_province", "j.state_province"),
                        ("discipline", "j.discipline_primary"), ("rank", "j.rank_normalized"),
                        ("career_stage", "j.career_stage"), ("track", "j.track_type"),
                        ("status", "j.status"), ("school_tier", "COALESCE(bs.business_research_tier,'Unclassified')"),
                        ("university_level", "COALESCE(i.university_research_level,'Unknown')")):
        value = str(query.get(key) or "").strip()
        if value:
            clauses.append(f"{column}=?")
            args.append(value)
    posted_after = str(query.get("posted_after") or "").strip()
    if posted_after:
        clauses.append("j.posted_date>=?")
        args.append(posted_after)
    closing_before = str(query.get("closing_before") or "").strip()
    if closing_before:
        clauses.append("j.deadline_date IS NOT NULL AND j.deadline_date<=?")
        args.append(closing_before)
    salary_known = str(query.get("salary_known") or "").lower()
    if salary_known in {"1", "true", "yes"}:
        clauses.append("j.salary_min IS NOT NULL")
    elif salary_known in {"0", "false", "no"}:
        clauses.append("j.salary_min IS NULL")
    return clauses, args


def build_faculty_jobs_payload(db_path=None, query=None, include_private=False):
    ensure_faculty_jobs_tables(db_path)
    query = query or {}
    conn = _connect(db_path)
    try:
        clauses, args = _query_conditions(query)
        scope = _requested_scope(query)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        filtered_where = " AND ".join(clauses) if clauses else "1=1"
        sort = str(query.get("sort") or ("fit" if include_private else "newest"))
        order = {
            "newest": "j.first_seen_at DESC, j.id DESC",
            "closing_soon": "CASE WHEN j.deadline_date IS NULL THEN 1 ELSE 0 END, j.deadline_date ASC, j.first_seen_at DESC",
            "salary": "CASE WHEN j.salary_max IS NULL THEN 1 ELSE 0 END, j.salary_max DESC, j.first_seen_at DESC",
            "school_tier": "CASE COALESCE(bs.business_research_tier,'Unclassified') WHEN 'T1' THEN 1 WHEN 'T2' THEN 2 WHEN 'T3' THEN 3 WHEN 'T4' THEN 4 ELSE 5 END, j.first_seen_at DESC",
        }.get(sort, "j.first_seen_at DESC, j.id DESC")
        try:
            limit = max(1, min(200, int(query.get("limit", 50))))
            offset = max(0, int(query.get("offset", 0)))
        except (TypeError, ValueError):
            limit, offset = 50, 0
        total = conn.execute("SELECT COUNT(*) FROM (" + _job_select() + where + ")", args).fetchone()[0]
        if include_private and sort == "fit":
            # Fit is a private, derived ranking.  Score the complete filtered
            # result before pagination so a high-fit older job cannot be
            # excluded by an arbitrary newest-50 window.
            all_rows = conn.execute(_job_select() + where + " ORDER BY j.id DESC", args).fetchall()
            all_jobs = [_job_dict(conn, row, include_private=True) for row in all_rows]
            all_jobs.sort(key=lambda item: ((item.get("fit") or {}).get("score", -1), item.get("first_seen_at") or ""), reverse=True)
            jobs = all_jobs[offset:offset + limit]
        else:
            rows = conn.execute(_job_select() + where + f" ORDER BY {order} LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
            jobs = [_job_dict(conn, row, include_private=include_private) for row in rows]
        return {
            "ok": True, "jobs": jobs,
            "pagination": {"total": total, "limit": limit, "offset": offset, "has_more": offset + len(jobs) < total},
            "meta": {
                "updated_at": now_utc(), "private_fields": bool(include_private), "scope": scope,
                "scope_counts": _business_scope_counts_filtered(conn, filtered_where, args),
                "source_coverage": _coverage(conn, filtered_where, args),
            },
        }
    finally:
        conn.close()


def enrich_inside_higher_ed_details(db_path=None, source_job_ids=None, max_records=25,
                                    timeout=20, delay=0.75, include_known=False):
    """Fetch a bounded set of public IHE detail pages for existing records.

    The normal listing refresh intentionally has a small detail budget.  This
    explicit operation lets an operator repair older records without
    refetching all result pages, while preserving the source-record grain and
    committing each successful detail independently.  It never follows login
    or anti-bot flows and never marks an unvisited record missing.
    """
    db_path = db_path or FACULTY_DB_PATH
    ensure_faculty_jobs_tables(db_path)
    requested_ids = {str(item).strip() for item in (source_job_ids or []) if str(item).strip()}
    budget = max(0, min(1000, int(max_records)))
    with _FACULTY_UPDATE_LOCK:
        conn = _connect(db_path)
        try:
            source = conn.execute("SELECT * FROM sources WHERE name='inside_higher_ed'").fetchone()
            if not source:
                return {"ok": False, "error": "inside_higher_ed source is not catalogued"}
            started = now_utc()
            run_id = conn.execute(
                "INSERT INTO ingestion_runs (source_id,started_at,status) VALUES (?,?,?)",
                (source["id"], started, "running"),
            ).lastrowid
            conn.commit()
            clauses = ["s.name='inside_higher_ed'"]
            args = []
            if requested_ids:
                placeholders = ",".join("?" for _ in requested_ids)
                clauses.append(f"js.source_job_id IN ({placeholders})")
                args.extend(sorted(requested_ids))
            elif not include_known:
                clauses.append("j.institution_id IS NULL")
            rows = conn.execute(f"""
                SELECT j.*, js.source_job_id, js.source_url AS link_source_url,
                       js.official_url AS link_official_url, sjr.source_url,
                       sjr.official_url AS record_official_url, sjr.short_excerpt,
                       sjr.structured_extraction, sjr.last_seen AS record_last_seen
                FROM jobs j
                JOIN job_sources js ON js.job_id=j.id AND js.active=1
                JOIN sources s ON s.id=js.source_id
                JOIN source_job_records sjr ON sjr.source_id=js.source_id AND sjr.source_job_id=js.source_job_id
                WHERE {' AND '.join(clauses)}
                ORDER BY CASE WHEN j.institution_id IS NULL THEN 0 ELSE 1 END,
                         CASE WHEN j.posted_date IS NULL THEN 0 ELSE 1 END,
                         j.id
                LIMIT ?
            """, (*args, budget)).fetchall()
            adapter = InsideHigherEdAdapter(timeout=max(3, int(timeout)), max_pages=1, max_items=1)
            adapter.detail_delay = max(0.25, float(delay))
            updated = skipped = errors = 0
            source_ids = []
            for row in rows:
                source_ids.append(str(row["source_job_id"]))
                try:
                    try:
                        extraction = json.loads(row["structured_extraction"] or "{}")
                    except (TypeError, ValueError):
                        extraction = {}
                    current_location = ", ".join(
                        str(item) for item in (row["city"], row["state_province"], row["country"])
                        if item
                    ) or None
                    source_job = SourceJob(
                        source="inside_higher_ed",
                        source_job_id=str(row["source_job_id"]),
                        source_url=row["source_url"] or row["link_source_url"],
                        official_url=row["record_official_url"] or row["link_official_url"] or extraction.get("official_url"),
                        title_raw=row["title_raw"],
                        institution_raw=extraction.get("institution_raw") or "Unknown institution",
                        school_raw=extraction.get("school_raw"),
                        department_raw=extraction.get("department"),
                        location_raw=extraction.get("location_raw") or current_location,
                        description_excerpt=row["short_excerpt"] or row["description_excerpt"],
                        posted_date_raw=extraction.get("posted_date") or row["posted_date"],
                        deadline_raw=extraction.get("deadline_date") or extraction.get("deadline_mode") or row["deadline_date"],
                        salary_raw=extraction.get("salary_raw") or row["salary_raw"],
                        captured_at=now_utc(),
                        extra={"search_query": InsideHigherEdAdapter.search_query, "detail_enrichment": True},
                    )
                    enriched = adapter._enrich_detail(source_job)
                    changed = any((
                        enriched.institution_raw != source_job.institution_raw,
                        enriched.location_raw != source_job.location_raw,
                        enriched.department_raw != source_job.department_raw,
                        enriched.school_raw != source_job.school_raw,
                        enriched.posted_date_raw != source_job.posted_date_raw,
                        enriched.deadline_raw != source_job.deadline_raw,
                        enriched.salary_raw != source_job.salary_raw,
                        enriched.official_url != source_job.official_url,
                        len(enriched.description_excerpt or "") > len(source_job.description_excerpt or ""),
                    ))
                    if not changed:
                        skipped += 1
                        continue
                    normalized = normalize_source_job(enriched, source["region"])
                    with conn:
                        _upsert_job(conn, source["id"], enriched, normalized, started)
                    updated += 1
                except Exception as exc:
                    errors += 1
                    LOG.warning("inside higher ed detail enrichment failed source_job_id=%s error=%s", row["source_job_id"], _safe_error(exc))
            finished = now_utc()
            note = (
                f"bounded detail enrichment processed {len(rows)} existing record(s); "
                f"updated {updated}, unchanged {skipped}, errors {errors}; no source identities were removed"
            )
            conn.execute("""
                UPDATE ingestion_runs SET finished_at=?,status='success',pages_fetched=0,items_seen=?,
                  items_inserted=0,items_updated=?,items_merged=0,error_count=?,error_summary=? WHERE id=?
            """, (finished, len(rows), updated, errors, note[:500], run_id))
            conn.execute("UPDATE sources SET last_attempt_at=?,updated_at=? WHERE id=?", (finished, finished, source["id"]))
            conn.commit()
            return {
                "ok": errors == 0,
                "run_id": run_id,
                "items_seen": len(rows),
                "items_updated": updated,
                "items_unchanged": skipped,
                "errors": errors,
                "source_job_ids": source_ids,
                "note": note,
            }
        finally:
            conn.close()


def build_faculty_job_detail(db_path, job_id, include_private=False):
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(_job_select() + " WHERE j.id=?", (int(job_id),)).fetchone()
        if not row:
            return {"ok": False, "error": "job not found"}
        result = _job_dict(conn, row, include_private=include_private)
        provenance = defaultdict(list)
        for item in conn.execute("""
            SELECT p.*, s.name AS source_name FROM job_field_provenance p
            LEFT JOIN sources s ON s.id=p.source_id WHERE p.job_id=? ORDER BY p.captured_at DESC, p.id DESC
        """, (int(job_id),)).fetchall():
            provenance[item["field_name"]].append(dict(item))
        result["provenance"] = dict(provenance)
        result["status_history"] = [dict(item) for item in conn.execute("""
            SELECT * FROM job_status_history WHERE job_id=? ORDER BY observed_at DESC LIMIT 30
        """, (int(job_id),)).fetchall()]
        result["possible_duplicates"] = [dict(item) for item in conn.execute("""
            SELECT p.*, j2.title_raw AS possible_title FROM possible_duplicates p JOIN jobs j2 ON j2.id=p.possible_job_id
            WHERE p.job_id=? AND p.resolved=0 ORDER BY p.confidence DESC
        """, (int(job_id),)).fetchall()]
        return {"ok": True, "job": result}
    finally:
        conn.close()


def _business_scope_counts(conn, where="1=1", args=()):
    rows = conn.execute(
        f"SELECT COALESCE(business_scope,'unknown') AS label, COUNT(*) AS count "
        f"FROM jobs WHERE {where} GROUP BY business_scope ORDER BY count DESC, label",
        args,
    ).fetchall()
    return [{"label": row["label"], "count": row["count"]} for row in rows]


def _coverage(conn, where="1=1", args=()):
    sources = conn.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS enabled,
               SUM(CASE WHEN enabled=1 AND last_status='ok' THEN 1 ELSE 0 END) AS healthy
        FROM sources
    """).fetchone()
    filtered = _job_select() + " WHERE " + where
    total_jobs = conn.execute("SELECT COUNT(*) FROM (" + filtered + ")", args).fetchone()[0]
    def pct(sql):
        if not total_jobs: return None
        return round(100 * conn.execute(
            "SELECT COUNT(*) FROM (" + filtered + " AND (" + sql + "))", args
        ).fetchone()[0] / total_jobs, 1)
    return {
        "sources_total": sources["total"] or 0, "sources_enabled": sources["enabled"] or 0,
            "sources_healthy": sources["healthy"] or 0, "jobs": total_jobs,
        "official_url_percent": pct("j.official_url IS NOT NULL"),
        "deadline_percent": pct("j.deadline_date IS NOT NULL OR j.deadline_mode IN ('open_until_filled','rolling')"),
        "salary_percent": pct("j.salary_min IS NOT NULL"),
        "school_classification_percent": pct("j.school_id IS NOT NULL AND COALESCE(bs.business_research_tier,'Unclassified')!='Unclassified'"),
        "possible_duplicates": conn.execute(
            "SELECT COUNT(*) FROM possible_duplicates p WHERE p.resolved=0 "
            "AND EXISTS (SELECT 1 FROM (" + filtered + ") f WHERE f.id=p.job_id)", args,
        ).fetchone()[0],
    }


def build_faculty_job_summary(db_path=None, query=None):
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        scope_clauses, scope_args, scope = _summary_scope_conditions(query)
        scope_where = " AND ".join(scope_clauses) if scope_clauses else "1=1"
        today = date.today().isoformat()
        seven = (date.today() - timedelta(days=7)).isoformat()
        thirty = (date.today() - timedelta(days=30)).isoformat()
        fourteen = (date.today() + timedelta(days=14)).isoformat()
        def count(extra="1=1", extra_args=()):
            where = " AND ".join([scope_where, extra]) if scope_where != "1=1" else extra
            return conn.execute("SELECT COUNT(*) FROM (" + _job_select() + " WHERE " + where + ")", (*scope_args, *extra_args)).fetchone()[0]
        active = "j.status IN ('open','likely_open','closing_soon')"
        active_where = " AND ".join([scope_where, active]) if scope_where != "1=1" else active
        return {"ok": True, "summary": {
            "scope": scope,
            "active_jobs": count(active), "new_7d": count("j.first_seen_at>=?", (seven,)),
            "new_30d": count("j.first_seen_at>=?", (thirty,)),
            "closing_next_14d": count("j.deadline_date IS NOT NULL AND j.deadline_date>=? AND j.deadline_date<=? AND j.status!='closed'", (today, fourteen)),
            "by_region": _group_counts_filtered(conn, "region_group", active_where, scope_args),
            "by_discipline": _group_counts_filtered(conn, "discipline_primary", active_where, scope_args),
            "business_scope_counts": _business_scope_counts_filtered(conn, scope_where, scope_args),
            "coverage": _coverage(conn, scope_where, scope_args), "updated_at": now_utc(),
        }}
    finally:
        conn.close()


def _group_counts(conn, column, where="1=1", args=()):
    allowed = {"region_group", "discipline_primary", "country", "country_code", "state_province", "rank_normalized", "career_stage", "track_type", "status"}
    if column not in allowed:
        return []
    return [{"label": row["label"] or "Unknown", "count": row["count"]} for row in conn.execute(f"SELECT {column} AS label, COUNT(*) AS count FROM jobs WHERE {where} GROUP BY {column} ORDER BY count DESC, label", args).fetchall()]


def _group_counts_filtered(conn, column, where="1=1", args=()):
    allowed = {"region_group", "discipline_primary", "country", "country_code", "state_province", "rank_normalized", "career_stage", "track_type", "status", "business_research_tier", "university_research_level"}
    if column not in allowed:
        return []
    select_column = {
        "business_research_tier": "COALESCE(f.business_research_tier,'Unclassified')",
        "university_research_level": "COALESCE(f.university_research_level,'Unknown')",
    }.get(column, f"f.{column}")
    return [{"label": row["label"] or "Unknown", "count": row["count"]} for row in conn.execute(
        "SELECT " + select_column + " AS label, COUNT(*) AS count FROM (" + _job_select() + " WHERE " + where + ") f GROUP BY label ORDER BY count DESC, label",
        args,
    ).fetchall()]


def _business_scope_counts_filtered(conn, where="1=1", args=()):
    return [{"label": row["label"] or "unknown", "count": row["count"]} for row in conn.execute(
        "SELECT COALESCE(f.business_scope,'unknown') AS label, COUNT(*) AS count FROM (" + _job_select() + " WHERE " + where + ") f GROUP BY label ORDER BY count DESC,label",
        args,
    ).fetchall()]


def build_faculty_job_filters(db_path=None, query=None):
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        scope_clauses, scope_args = _query_conditions({**(query or {}), "q": "", "country": "", "region": "", "state_province": "", "discipline": "", "rank": "", "career_stage": "", "track": "", "status": "", "school_tier": "", "university_level": "", "posted_after": "", "closing_before": "", "salary_known": ""})
        scope = _requested_scope(query)
        scope_where = " AND ".join(scope_clauses) if scope_clauses else "1=1"
        def values(column, table="jobs"):
            return [row[0] for row in conn.execute(
                "SELECT DISTINCT f." + column + " FROM (" + _job_select() + " WHERE " + scope_where + ") f WHERE f." + column + " IS NOT NULL AND f." + column + "!='' ORDER BY f." + column,
                scope_args,
            ).fetchall()]
        return {"ok": True, "filters": {
            "scope": scope,
            "regions": values("region_group"), "countries": values("country"),
            "country_options": list(COUNTRY_OPTIONS),
            "states_provinces": values("state_province"), "disciplines": list(DISCIPLINES),
            "ranks": values("rank_normalized"), "career_stages": values("career_stage"), "tracks": values("track_type"),
            "statuses": ["open", "likely_open", "closing_soon", "closed", "unknown"],
            "school_tiers": ["T1", "T2", "T3", "T4", "Unclassified"],
            "university_levels": ["R1", "R2", "RCU", "Other", "Unknown"],
            "salary_known": ["yes", "no"],
        }}
    finally:
        conn.close()


def build_faculty_job_sources(db_path=None):
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        def source_field_coverage(source_id):
            base = """
                FROM job_sources js
                JOIN jobs j ON j.id=js.job_id
                LEFT JOIN institutions i ON i.id=j.institution_id
                WHERE js.source_id=? AND js.active=1
            """
            # Source health is expressed over active source links (the raw
            # record grain), not distinct canonical jobs.  A source can have
            # more than one preserved source record attached to one job after
            # an exact-URL merge, and the UI must keep that denominator honest.
            total = conn.execute("SELECT COUNT(*) " + base, (source_id,)).fetchone()[0]
            fields = {
                "title": "j.title_raw IS NOT NULL AND j.title_raw!=''",
                "institution": "i.official_name IS NOT NULL AND i.official_name!='' AND lower(i.official_name)!='unknown institution'",
                "location": "j.country_code IS NOT NULL OR j.city IS NOT NULL OR j.state_province IS NOT NULL",
                "posted_date": "j.posted_date IS NOT NULL",
                "deadline_or_rolling": "j.deadline_date IS NOT NULL OR j.deadline_mode IN ('open_until_filled','rolling')",
                "salary": "j.salary_min IS NOT NULL",
                "official_url": "j.official_url IS NOT NULL AND j.official_url!=''",
                "rank": "j.rank_normalized IS NOT NULL AND j.rank_normalized!='unknown'",
                "phd": "j.phd_required IS NOT NULL",
                "visa": "j.visa_status IS NOT NULL AND j.visa_status!='unknown'",
                "start_term_or_year": "j.start_term IS NOT NULL OR j.start_year IS NOT NULL",
            }
            result = {"records": total}
            for name, expression in fields.items():
                count = conn.execute("SELECT COUNT(*) " + base + " AND (" + expression + ")", (source_id,)).fetchone()[0]
                result[name] = {"count": count, "percent": round(100 * count / total, 1) if total else None}
            return result

        rows = conn.execute("""
            SELECT s.*, (SELECT COUNT(*) FROM job_sources js WHERE js.source_id=s.id AND js.active=1) AS active_jobs,
                   (SELECT COUNT(DISTINCT js.job_id) FROM job_sources js JOIN jobs j ON j.id=js.job_id
                    WHERE js.source_id=s.id AND js.active=1
                      AND j.derived_quality='accepted' AND j.faculty_market_eligible=1
                      AND j.business_scope IN ('business_school','business_discipline')) AS business_scope_jobs,
                   (SELECT COUNT(DISTINCT js.job_id) FROM job_sources js JOIN jobs j ON j.id=js.job_id
                    WHERE js.source_id=s.id AND js.active=1 AND j.derived_quality='accepted' AND j.faculty_market_eligible=1 AND j.business_scope='business_school') AS explicit_school_jobs,
                   (SELECT COUNT(*) FROM ingestion_runs ir WHERE ir.source_id=s.id AND ir.status='success') AS successful_runs
            FROM sources s ORDER BY priority,name
        """).fetchall()
        sources = []
        for row in rows:
            item = dict(row)
            item["field_coverage"] = source_field_coverage(row["id"])
            sources.append(item)
        return {"ok": True, "sources": sources, "updated_at": now_utc()}
    finally:
        conn.close()


def build_faculty_job_runs(db_path=None, limit=50):
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute("""
            SELECT ir.*, s.name AS source_name FROM ingestion_runs ir JOIN sources s ON s.id=ir.source_id
            ORDER BY ir.started_at DESC LIMIT ?
        """, (max(1, min(200, int(limit))),)).fetchall()
        return {"ok": True, "runs": [dict(row) for row in rows]}
    finally:
        conn.close()


def _aacsb_source_id(conn):
    row = conn.execute("SELECT id FROM sources WHERE name='aacsb_official'").fetchone()
    if not row:
        _ensure_aacsb_tables(conn)
        row = conn.execute("SELECT id FROM sources WHERE name='aacsb_official'").fetchone()
    return int(row["id"])


def _aacsb_record_value(record, key, default=None):
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _upsert_aacsb_directory_row(conn, record):
    """Upsert roster/detail fields without touching official-site scan state."""
    from services.faculty_jobs_sources.aacsb import AACSB_DIRECTORY_URL
    captured = _aacsb_record_value(record, "captured_at") or now_utc()
    institution = str(_aacsb_record_value(record, "institution_name") or "").strip()
    directory_url = str(_aacsb_record_value(record, "directory_url") or "").strip()
    result_id = str(_aacsb_record_value(record, "directory_result_id") or "").strip()
    if not institution or not directory_url or not result_id:
        raise ValueError("AACSB roster record is missing its stable identity")
    location_raw = _aacsb_record_value(record, "location_raw")
    location = parse_location(location_raw, "Global", institution_text=institution, description=_aacsb_record_value(record, "detail_excerpt"))
    values = {
        "directory_result_id": result_id,
        "directory_url": directory_url,
        "institution_name": institution,
        "school_name": _aacsb_record_value(record, "school_name"),
        "directory_title": _aacsb_record_value(record, "directory_title") or institution,
        "location_raw": location_raw,
        "city": location.get("city"),
        "state_province": location.get("state_province"),
        "country": location.get("country"),
        "country_code": location.get("country_code"),
        "region_group": location.get("region_group"),
        "official_website": _aacsb_record_value(record, "official_website"),
        "accreditation_scope": _aacsb_record_value(record, "accreditation_scope") or "Business",
        "roster_source_url": _aacsb_record_value(record, "roster_source_url") or AACSB_DIRECTORY_URL,
        "record_excerpt": " ".join(item for item in (
            _aacsb_record_value(record, "directory_title"), _aacsb_record_value(record, "detail_excerpt")
        ) if item)[:1200] or None,
        "source_hash": _aacsb_record_value(record, "source_hash"),
        "detail_status": _aacsb_record_value(record, "detail_status") or "not_checked",
        "detail_checked_at": captured if (_aacsb_record_value(record, "detail_status") or "").casefold() == "ok" else None,
        "last_seen_at": captured,
        "updated_at": now_utc(),
    }
    if not values["source_hash"]:
        from services.faculty_jobs_sources.aacsb import AACSBDirectoryRecord
        try:
            values["source_hash"] = hashlib.sha256(json.dumps({
                key: values.get(key) for key in ("directory_result_id", "directory_url", "institution_name", "school_name", "location_raw", "official_website", "accreditation_scope")
            }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        except Exception:
            values["source_hash"] = None
    existing = conn.execute(
        "SELECT id, first_seen_at FROM aacsb_directory_schools WHERE directory_result_id=? OR directory_url=? LIMIT 1",
        (result_id, directory_url),
    ).fetchone()
    if existing:
        conn.execute("""
            UPDATE aacsb_directory_schools SET
              directory_result_id=?, directory_url=?, institution_name=?, school_name=?, directory_title=?,
              location_raw=?, city=?, state_province=?, country=?, country_code=?, region_group=?,
              official_website=COALESCE(?,official_website), accreditation_scope=COALESCE(?,accreditation_scope),
              roster_source_url=?, record_excerpt=?, source_hash=?, last_seen_at=?,
              detail_status=CASE WHEN ?='ok' THEN 'ok' ELSE detail_status END,
              detail_checked_at=CASE WHEN ?='ok' THEN ? ELSE detail_checked_at END,
              active=1, updated_at=?
            WHERE id=?
        """, (
            values["directory_result_id"], values["directory_url"], values["institution_name"], values["school_name"], values["directory_title"],
            values["location_raw"], values["city"], values["state_province"], values["country"], values["country_code"], values["region_group"],
            values["official_website"], values["accreditation_scope"], values["roster_source_url"], values["record_excerpt"], values["source_hash"], values["last_seen_at"],
            values["detail_status"], values["detail_status"], values["detail_checked_at"], values["updated_at"], existing["id"],
        ))
        return int(existing["id"])
    cur = conn.execute("""
        INSERT INTO aacsb_directory_schools
          (directory_result_id,directory_url,institution_name,school_name,directory_title,location_raw,city,state_province,
           country,country_code,region_group,official_website,accreditation_scope,roster_source_url,record_excerpt,source_hash,
           first_seen_at,last_seen_at,detail_status,detail_checked_at,active,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)
    """, (
        values["directory_result_id"], values["directory_url"], values["institution_name"], values["school_name"], values["directory_title"],
        values["location_raw"], values["city"], values["state_province"], values["country"], values["country_code"], values["region_group"],
        values["official_website"], values["accreditation_scope"], values["roster_source_url"], values["record_excerpt"], values["source_hash"],
        captured, values["last_seen_at"], values["detail_status"], values["detail_checked_at"], captured, values["updated_at"],
    ))
    return int(cur.lastrowid)


def _sync_aacsb_school_entity(conn, directory_id):
    """Link an explicit AACSB school to the existing evidence-first entities."""
    row = conn.execute("SELECT * FROM aacsb_directory_schools WHERE id=?", (directory_id,)).fetchone()
    if not row or not row["school_name"]:
        return None
    canonical = _canonical_institution_name(row["institution_name"])
    manual = conn.execute(
        "SELECT canonical_name FROM institution_aliases WHERE alias_normalized=?",
        (normalize_name(canonical),),
    ).fetchone()
    if manual:
        canonical = manual["canonical_name"]
    institution_key = normalize_name(canonical)
    institution = conn.execute(
        "SELECT * FROM institutions WHERE normalized_name=? AND country_code IS ? LIMIT 1",
        (institution_key, row["country_code"]),
    ).fetchone()
    if not institution and row["country_code"]:
        # A prior source observation may have created the same institution
        # with an unknown country.  Reuse that conservative entity when the
        # AACSB roster now supplies explicit location evidence; do not create
        # a second entity merely because the country was previously unknown.
        institution = conn.execute(
            "SELECT * FROM institutions WHERE normalized_name=? AND country_code IS NULL LIMIT 1",
            (institution_key,),
        ).fetchone()
    timestamp = row["detail_checked_at"] or row["last_seen_at"] or now_utc()
    if institution:
        institution_id = int(institution["id"])
        aliases = _json_load(institution["aliases_json"], [])
        if row["institution_name"] != institution["official_name"] and row["institution_name"] not in aliases:
            aliases.append(row["institution_name"])
        conn.execute("""
            UPDATE institutions SET aliases_json=?, institution_url=COALESCE(?,institution_url), country=COALESCE(?,country),
              country_code=COALESCE(?,country_code), region_group=COALESCE(?,region_group), city=COALESCE(?,city),
              state_province=COALESCE(?,state_province), is_current=1, updated_at=? WHERE id=?
        """, (json.dumps(aliases[:50], ensure_ascii=False), row["official_website"], row["country"], row["country_code"], row["region_group"], row["city"], row["state_province"], timestamp, institution_id))
    else:
        cur = conn.execute("""
            INSERT INTO institutions
              (official_name,normalized_name,aliases_json,country,country_code,region_group,state_province,city,institution_url,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (canonical, institution_key, json.dumps([row["institution_name"]] if row["institution_name"] != canonical else [], ensure_ascii=False),
               row["country"], row["country_code"], row["region_group"], row["state_province"], row["city"], row["official_website"], timestamp, timestamp))
        institution_id = int(cur.lastrowid)

    school_name = str(row["school_name"]).strip()
    school_key = normalize_name(school_name)
    school = conn.execute(
        "SELECT id FROM business_schools WHERE institution_id=? AND normalized_name=? LIMIT 1",
        (institution_id, school_key),
    ).fetchone()
    if school:
        school_id = int(school["id"])
        conn.execute("""
            UPDATE business_schools SET website=COALESCE(?,website), aacsb=1, last_verified_at=?, is_current=1, updated_at=? WHERE id=?
        """, (row["official_website"], timestamp, now_utc(), school_id))
    else:
        cur = conn.execute("""
            INSERT INTO business_schools
              (institution_id,official_name,normalized_name,website,aacsb,last_verified_at,created_at,updated_at)
            VALUES (?,?,?,?,1,?,?,?)
        """, (institution_id, school_name, school_key, row["official_website"], timestamp, timestamp, now_utc()))
        school_id = int(cur.lastrowid)
    evidence = conn.execute(
        "SELECT 1 FROM school_evidence WHERE school_id=? AND evidence_type='AACSB' AND source_url=? LIMIT 1",
        (school_id, row["directory_url"]),
    ).fetchone()
    if not evidence:
        conn.execute("""
            INSERT INTO school_evidence
              (school_id,evidence_type,value,source_name,source_url,source_date,verified_at,confidence,notes)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (school_id, "AACSB", row["accreditation_scope"] or "Business",
               "AACSB Accredited School Search", row["directory_url"],
               str(timestamp)[:10], now_utc(), "high",
               "AACSB public accredited-school directory evidence; this establishes accreditation only, not hiring or research tier."))
    refresh_school_classification(conn, school_id)
    conn.execute("UPDATE aacsb_directory_schools SET linked_business_school_id=?, updated_at=? WHERE id=?", (school_id, now_utc(), directory_id))
    return school_id


def _aacsb_record_from_row(row):
    from services.faculty_jobs_sources.aacsb import AACSBDirectoryRecord
    return AACSBDirectoryRecord(
        directory_result_id=row["directory_result_id"], directory_url=row["directory_url"],
        institution_name=row["institution_name"], school_name=row["school_name"], location_raw=row["location_raw"],
        directory_title=row["directory_title"], roster_source_url=row["roster_source_url"],
        captured_at=row["last_seen_at"], official_website=row["official_website"],
        accreditation_scope=row["accreditation_scope"], detail_excerpt=row["record_excerpt"],
        detail_status=row["detail_status"],
    )


def _quarantine_aacsb_explicit_nonbusiness_jobs(conn):
    """Remove clearly non-business titles from the accepted default grain."""
    from services.faculty_jobs_sources.aacsb import BUSINESS_CONTEXT_RE, NON_BUSINESS_TITLE_RE

    source = conn.execute("SELECT id FROM sources WHERE name='aacsb_official'").fetchone()
    if not source:
        return
    source_id = int(source["id"])
    rows = conn.execute(
        """SELECT DISTINCT j.id,j.title_raw,j.derived_quality,j.business_scope,j.status
           FROM jobs j JOIN job_sources js ON js.job_id=j.id
           WHERE js.source_id=? AND j.derived_quality='accepted'""", (source_id,)
    ).fetchall()
    reason = "Explicit non-business field on a mixed official-site page; retained as quarantined source evidence rather than default business-market data."
    for row in rows:
        title = str(row["title_raw"] or "")
        if not NON_BUSINESS_TITLE_RE.search(title) or BUSINESS_CONTEXT_RE.search(title):
            continue
        conn.execute(
            """UPDATE jobs SET derived_quality='quarantined',business_scope='unknown',
               business_scope_confidence='low',business_scope_reason=?,status='unknown',updated_at=?
               WHERE id=?""", (reason, now_utc(), row["id"]),
        )
        link = conn.execute(
            """SELECT source_job_id FROM job_sources
               WHERE source_id=? AND job_id=? ORDER BY source_job_id LIMIT 1""", (source_id, row["id"])
        ).fetchone()
        conn.execute(
            """INSERT INTO faculty_job_repair_audit
               (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
               VALUES (?,?,?,?,?,?,?,?)""",
            (now_utc(), "aacsb_nonbusiness_quarantine", row["id"], source_id,
             link["source_job_id"] if link else None,
             json.dumps({"derived_quality": row["derived_quality"], "business_scope": row["business_scope"]}, ensure_ascii=False),
             json.dumps({"derived_quality": "quarantined", "business_scope": "unknown"}, ensure_ascii=False), reason),
        )


def _repair_overbroad_location_replay(conn):
    """Reverse v28 evidence-only writes while retaining their audit trail.

    An early v28 implementation changed ``location_evidence`` even when every
    substantive location field already matched.  The source and audit rows
    were always preserved; this forward repair restores the prior label and
    provenance-current flags without deleting the superseded records.
    """
    rows = conn.execute("""
        SELECT id,observed_at,job_id,old_value,new_value
        FROM faculty_job_repair_audit
        WHERE action='source_location_country_replay'
        ORDER BY id
    """).fetchall()
    restored = 0
    provenance_rows_superseded = 0
    for row in rows:
        try:
            old = json.loads(row["old_value"] or "{}")
            new = json.loads(row["new_value"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        changed = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
        if changed != {"location_evidence"}:
            continue
        job = conn.execute(
            "SELECT location_evidence FROM jobs WHERE id=?", (row["job_id"],),
        ).fetchone()
        if not job:
            continue
        if job["location_evidence"] == new.get("location_evidence"):
            conn.execute(
                "UPDATE jobs SET location_evidence=?,updated_at=? WHERE id=?",
                (old.get("location_evidence"), now_utc(), row["job_id"]),
            )
        for field_name in ("country", "country_code", "region_group", "state_province", "city"):
            cur = conn.execute("""
                UPDATE job_field_provenance SET is_current=0
                WHERE job_id=? AND field_name=? AND captured_at=?
                  AND evidence_text LIKE 'Structured source location:%'
            """, (row["job_id"], field_name, row["observed_at"]))
            provenance_rows_superseded += max(0, int(cur.rowcount or 0))
            previous = conn.execute("""
                SELECT id FROM job_field_provenance
                WHERE job_id=? AND field_name=?
                  AND NOT (captured_at=? AND evidence_text LIKE 'Structured source location:%')
                ORDER BY captured_at DESC,id DESC LIMIT 1
            """, (row["job_id"], field_name, row["observed_at"])).fetchone()
            if previous:
                conn.execute(
                    "UPDATE job_field_provenance SET is_current=1 WHERE id=?",
                    (previous["id"],),
                )
        conn.execute("""
            UPDATE job_status_history
            SET change_reason='source_location_country_replay_noop_superseded'
            WHERE job_id=? AND observed_at=?
              AND change_reason='source_location_country_replay'
        """, (row["job_id"], row["observed_at"]))
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?)
        """, (
            now_utc(), "source_location_replay_noop_reversal", row["job_id"],
            json.dumps({"location_evidence": new.get("location_evidence")}, ensure_ascii=False),
            json.dumps({"location_evidence": old.get("location_evidence")}, ensure_ascii=False),
            "Restored the prior evidence label because v28 changed no country, region, state, city, or institution value; superseded provenance rows were retained as non-current.",
        ))
        restored += 1
    return {
        "restored_jobs": restored,
        "provenance_rows_superseded": provenance_rows_superseded,
    }


def _repair_source_location_country_mismatches(conn):
    """Replay high-confidence country evidence from preserved source rows.

    A job is changed only when every active source row with usable structured
    location evidence agrees on one country.  This repairs values such as
    ``Hamilton, Ontario, CA`` that older code interpreted as California while
    leaving conflicting or source-region-only guesses untouched.
    """
    rows = conn.execute("""
        SELECT j.id,j.title_raw,j.institution_id,j.school_id,j.country,j.country_code,
               j.region_group,j.state_province,j.city,j.location_evidence,
               j.status,j.deadline_date,j.salary_raw,j.description_excerpt,
               i.normalized_name AS institution_normalized,
               s.id AS source_id,s.name AS source_name,s.region,
               js.source_job_id,COALESCE(sjr.source_url,js.source_url) AS source_url,
               sjr.structured_extraction
        FROM jobs j
        JOIN job_sources js ON js.job_id=j.id AND js.active=1
        JOIN sources s ON s.id=js.source_id
        JOIN source_job_records sjr
          ON sjr.source_id=js.source_id AND sjr.source_job_id=js.source_job_id
        LEFT JOIN institutions i ON i.id=j.institution_id
        ORDER BY j.id,s.priority,s.name
    """).fetchall()
    grouped = {}
    evidence_priority = {
        "state_province": 5,
        "institution_hint": 4,
        "location_raw": 3,
        "city_hint": 2,
    }
    for row in rows:
        try:
            extraction = json.loads(row["structured_extraction"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            extraction = {}
        raw_location = str(extraction.get("location_raw") or "").strip()
        if not raw_location:
            continue
        parsed = parse_location(
            raw_location,
            row["region"],
            institution_text=extraction.get("institution_raw"),
            description=row["description_excerpt"],
        )
        code = parsed.get("country_code")
        evidence = parsed.get("location_evidence")
        if not code or evidence not in evidence_priority:
            continue
        grouped.setdefault(int(row["id"]), []).append((row, extraction, parsed, raw_location))

    changed = 0
    institution_links_repaired = 0
    for job_id, candidates in grouped.items():
        country_codes = {item[2].get("country_code") for item in candidates if item[2].get("country_code")}
        if len(country_codes) != 1:
            continue
        state_codes = {item[2].get("state_province") for item in candidates if item[2].get("state_province")}
        best = max(candidates, key=lambda item: evidence_priority.get(item[2].get("location_evidence"), 0))
        row, _extraction, parsed, raw_location = best
        desired_code = parsed.get("country_code")
        current_code = row["country_code"]
        country_name = parsed.get("country") or country_display(desired_code)
        explicit_country = bool(
            country_name and re.search(rf"(?<!\w){re.escape(country_name)}(?!\w)", raw_location, re.I)
        )
        explicit_iso = bool(re.search(rf"(?:^|,\s*){re.escape(desired_code)}\s*$", raw_location, re.I))
        conflict_is_safe = (
            parsed.get("location_evidence") in {"state_province", "institution_hint"}
            or explicit_country
            or explicit_iso
        )
        if current_code and current_code != desired_code and not conflict_is_safe:
            continue

        desired_state = row["state_province"]
        if parsed.get("state_province") and len(state_codes) <= 1 and (
            not desired_state or current_code != desired_code or desired_state != parsed.get("state_province")
        ):
            desired_state = parsed.get("state_province")
        desired_city = row["city"] or parsed.get("city")
        desired_values = {
            "country": country_name,
            "country_code": desired_code,
            "region_group": parsed.get("region_group"),
            "state_province": desired_state,
            "city": desired_city,
            "location_evidence": "source_location_replay",
        }
        old_values = {key: row[key] for key in desired_values}

        desired_institution_id = row["institution_id"]
        desired_school_id = row["school_id"]
        if row["institution_id"] and row["institution_normalized"]:
            target = conn.execute("""
                SELECT id FROM institutions
                WHERE normalized_name=? AND country_code=? AND is_current=1 AND id!=?
                ORDER BY id LIMIT 1
            """, (row["institution_normalized"], desired_code, row["institution_id"])).fetchone()
            if target:
                target_school_id = None
                if row["school_id"] is not None:
                    school = conn.execute(
                        "SELECT normalized_name FROM business_schools WHERE id=?",
                        (row["school_id"],),
                    ).fetchone()
                    if school:
                        target_school = conn.execute("""
                            SELECT id FROM business_schools
                            WHERE institution_id=? AND normalized_name=? AND is_current=1
                            ORDER BY id LIMIT 1
                        """, (target["id"], school["normalized_name"])).fetchone()
                        target_school_id = target_school["id"] if target_school else None
                if row["school_id"] is None or target_school_id is not None:
                    desired_institution_id = int(target["id"])
                    desired_school_id = target_school_id

        substantive_fields = ("country", "country_code", "region_group", "state_province", "city")
        if (
            all(old_values[key] == desired_values[key] for key in substantive_fields)
            and desired_institution_id == row["institution_id"]
            and desired_school_id == row["school_id"]
        ):
            # Do not relabel already-correct rows merely because a newer
            # parser reached the same value through a different code path.
            continue
        if (
            all(old_values[key] == desired_values[key] for key in desired_values)
            and desired_institution_id == row["institution_id"]
            and desired_school_id == row["school_id"]
        ):
            continue
        observed = now_utc()
        conn.execute("""
            UPDATE jobs SET institution_id=?,school_id=?,country=?,country_code=?,region_group=?,
              state_province=?,city=?,location_evidence=?,updated_at=? WHERE id=?
        """, (
            desired_institution_id, desired_school_id,
            desired_values["country"], desired_values["country_code"],
            desired_values["region_group"], desired_values["state_province"],
            desired_values["city"], desired_values["location_evidence"], observed, job_id,
        ))
        if desired_institution_id != row["institution_id"]:
            institution_links_repaired += 1
        for field_name in ("country", "country_code", "region_group", "state_province", "city"):
            conn.execute(
                "UPDATE job_field_provenance SET is_current=0 WHERE job_id=? AND field_name=?",
                (job_id, field_name),
            )
            if desired_values[field_name] in (None, ""):
                continue
            conn.execute("""
                INSERT INTO job_field_provenance
                  (job_id,field_name,source_id,source_job_id,source_url,value_text,evidence_text,captured_at,is_current)
                VALUES (?,?,?,?,?,?,?,?,1)
            """, (
                job_id, field_name, row["source_id"], row["source_job_id"], row["source_url"],
                str(desired_values[field_name]), f"Structured source location: {raw_location}", observed,
            ))
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            observed, "source_location_country_replay", job_id, row["source_id"],
            row["source_job_id"],
            json.dumps({**old_values, "institution_id": row["institution_id"]}, ensure_ascii=False),
            json.dumps({**desired_values, "institution_id": desired_institution_id}, ensure_ascii=False),
            "All usable active source-location records agreed on one country; replayed current parser evidence without changing source records.",
        ))
        source_count = conn.execute(
            "SELECT COUNT(DISTINCT source_id) FROM job_sources WHERE job_id=? AND active=1",
            (job_id,),
        ).fetchone()[0]
        conn.execute("""
            INSERT INTO job_status_history
              (job_id,observed_at,status,deadline,salary_raw,title_raw,source_count,change_reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            job_id, observed, row["status"], row["deadline_date"], row["salary_raw"],
            row["title_raw"], source_count, "source_location_country_replay",
        ))
        changed += 1
    return {
        "changed_jobs": changed,
        "institution_links_repaired": institution_links_repaired,
    }


def _repair_faculty_market_boundary(conn):
    """Rebuild the faculty-role/business boundary from preserved local evidence.

    The migration is derived-field-only.  Source records, source links,
    excerpts, private application state, and AACSB roster evidence are never
    deleted.  Roster-target school names are separated from posting-level
    school evidence so university-wide vacancies cannot inherit AACSB scope.
    """
    rows = conn.execute("""
        SELECT j.*,i.official_name AS institution_name,
               bs.official_name AS current_school_name,
               GROUP_CONCAT(DISTINCT s.name) AS source_names,
               MIN(js.source_id) AS audit_source_id,
               MIN(js.source_job_id) AS audit_source_job_id
        FROM jobs j
        LEFT JOIN institutions i ON i.id=j.institution_id
        LEFT JOIN business_schools bs ON bs.id=j.school_id
        LEFT JOIN job_sources js ON js.job_id=j.id AND js.active=1
        LEFT JOIN sources s ON s.id=js.source_id
        GROUP BY j.id
        ORDER BY j.id
    """).fetchall()
    stats = {
        "rows": len(rows), "changed": 0, "school_links_cleared": 0,
        "aacsb_quarantined": 0,
    }
    for row in rows:
        sources = {item for item in str(row["source_names"] or "").split(",") if item}
        only_aacsb = sources == {"aacsb_official"}
        only_ihe = sources == {"inside_higher_ed"}
        title = row["title_raw"] or ""
        department = row["department"] or ""
        description = row["description_excerpt"] or ""
        institution = row["institution_name"] or ""
        current_school = row["current_school_name"] or ""
        role = classify_faculty_market_role(title, description, row["official_url"])

        posting_school = None
        context = row["school_evidence_context"] or "unknown"
        title_school = _extract_school_name(None, " ".join((title, department)), institution)
        if only_aacsb:
            posting_school = title_school
            context = "posting" if posting_school else "aacsb_roster_target"
        elif only_ihe:
            # Legacy IHE ``school_raw`` values did not identify which parser
            # rule produced them and sometimes captured a later collaborator
            # or cross-appointment. Trust a stored value only when it carries
            # the current evidence-rule version; otherwise re-derive the home
            # unit from the preserved bounded posting excerpt.
            structured_school = None
            structured_rows = conn.execute(
                """
                SELECT sjr.structured_extraction
                FROM job_sources js
                JOIN source_job_records sjr
                  ON sjr.source_id=js.source_id
                 AND sjr.source_job_id=js.source_job_id
                JOIN sources src ON src.id=js.source_id
                WHERE js.job_id=? AND js.active=1 AND src.name='inside_higher_ed'
                ORDER BY sjr.last_seen DESC, sjr.id DESC
                """,
                (row["id"],),
            ).fetchall()
            for structured_row in structured_rows:
                try:
                    extraction = json.loads(structured_row["structured_extraction"] or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    extraction = {}
                if extraction.get("school_evidence_rule_version") != IHE_SCHOOL_EVIDENCE_RULE_VERSION:
                    continue
                candidate = _extract_school_name(extraction.get("school_raw"), "", institution)
                if candidate:
                    structured_school = candidate
                    break
            posting_school = (
                title_school
                or InsideHigherEdAdapter._detail_school(description)
                or structured_school
            )
            context = "structured_posting" if posting_school else "unknown"
        else:
            # A merged record can have AACSB plus another source.  If its
            # existing school link came only from the AACSB scan target, the
            # additional source does not magically upgrade that roster link
            # to posting-level evidence.
            posting_school = title_school or (
                current_school if context != "aacsb_roster_target" else None
            )
            if posting_school and context in {"", "unknown", "aacsb_roster_target"}:
                context = "posting"

        result = classify_business_scope(
            department=department,
            title=title,
            description=description,
            institution=institution,
            school=posting_school,
            source=next(iter(sources), None),
            school_is_posting_evidence=bool(posting_school),
            faculty_role=role,
        )

        desired_school_id = row["school_id"]
        if (
            not role.get("eligible")
            or result["scope"] not in {"business_school", "business_discipline"}
            or ((only_aacsb or only_ihe) and not posting_school)
        ):
            desired_school_id = None

        desired_quality = row["derived_quality"]
        desired_status = row["status"]
        desired_note = row["verification_note"]
        if only_aacsb and row["derived_quality"] == "accepted" and (
            not role.get("eligible")
            or result["scope"] not in {"business_school", "business_discipline"}
        ):
            desired_quality = "quarantined"
            desired_status = "unknown"
            desired_note = (
                "AACSB official-site candidate lacked an eligible individual business-faculty role; "
                "source evidence is retained in the audit catalogue."
            )
            stats["aacsb_quarantined"] += 1

        old_value = {
            "school_id": row["school_id"],
            "school_evidence_context": row["school_evidence_context"],
            "business_scope": row["business_scope"],
            "faculty_market_role": row["faculty_market_role"],
            "faculty_market_eligible": row["faculty_market_eligible"],
            "derived_quality": row["derived_quality"],
        }
        new_value = {
            "school_id": desired_school_id,
            "school_evidence_context": context,
            "business_scope": result["scope"],
            "faculty_market_role": role["role"],
            "faculty_market_eligible": int(bool(role["eligible"])),
            "derived_quality": desired_quality,
        }
        if old_value == new_value:
            continue
        observed = now_utc()
        conn.execute("""
            UPDATE jobs SET school_id=?,business_scope=?,business_scope_confidence=?,
              business_scope_reason=?,faculty_market_role=?,faculty_market_eligible=?,
              faculty_market_reason=?,school_evidence_context=?,derived_quality=?,status=?,
              verification_note=?,updated_at=? WHERE id=?
        """, (
            desired_school_id, result["scope"], result["confidence"], result["reason"],
            role["role"], int(bool(role["eligible"])), role["reason"], context,
            desired_quality, desired_status, desired_note, observed, row["id"],
        ))
        if row["school_id"] is not None and desired_school_id is None:
            stats["school_links_cleared"] += 1
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            observed, "faculty_market_boundary_repair", row["id"],
            row["audit_source_id"], row["audit_source_job_id"],
            json.dumps(old_value, ensure_ascii=False),
            json.dumps(new_value, ensure_ascii=False),
            "Reclassified the individual faculty-role gate and business scope; AACSB roster affiliation was not treated as posting-level school evidence.",
        ))
        stats["changed"] += 1
    return stats


def _repair_aacsb_directory_location_evidence(conn):
    """Replay stored AACSB location text and repair derived geography.

    The public roster is already stored locally, so this migration does not
    make network requests.  Directory location text is stronger evidence for
    an institution than a noisy faculty-detail page footer; it can therefore
    correct a derived job country without changing the preserved source
    record or claiming that the job page itself stated the country.
    """
    from services.faculty_jobs_normalizer import parse_location

    rows = conn.execute("SELECT * FROM aacsb_directory_schools ORDER BY id").fetchall()
    for row in rows:
        parsed = parse_location(
            row["location_raw"], "Global", institution_text=row["institution_name"],
            description=row["record_excerpt"],
        )
        if not parsed.get("country_code"):
            continue
        changed = any(row[key] != parsed.get(key) for key in ("city", "state_province", "country", "country_code", "region_group"))
        if changed:
            conn.execute(
                """UPDATE aacsb_directory_schools
                   SET city=?,state_province=?,country=?,country_code=?,region_group=?,updated_at=?
                   WHERE id=?""",
                (parsed["city"], parsed["state_province"], parsed["country"], parsed["country_code"],
                 parsed["region_group"], now_utc(), row["id"]),
            )
        if row["school_name"]:
            _sync_aacsb_school_entity(conn, int(row["id"]))

    source = conn.execute("SELECT id FROM sources WHERE name='aacsb_official'").fetchone()
    if not source:
        return
    source_id = int(source["id"])
    directory_rows = conn.execute(
        """SELECT id,directory_url,linked_business_school_id,location_raw,country,country_code,region_group,city,state_province
           FROM aacsb_directory_schools
           WHERE linked_business_school_id IS NOT NULL AND country_code IS NOT NULL"""
    ).fetchall()
    for directory in directory_rows:
        jobs = conn.execute(
            """SELECT DISTINCT j.*
               FROM jobs j JOIN job_sources js ON js.job_id=j.id
               WHERE js.source_id=? AND j.school_id=?""",
            (source_id, directory["linked_business_school_id"]),
        ).fetchall()
        for job in jobs:
            new_city = directory["city"] or job["city"]
            new_state = directory["state_province"] or job["state_province"]
            if (job["country_code"], job["country"], job["region_group"], job["city"], job["state_province"]) != (
                directory["country_code"], directory["country"], directory["region_group"], new_city, new_state,
            ):
                conn.execute(
                    """UPDATE jobs SET country=?,country_code=?,region_group=?,city=?,state_province=?,
                       location_evidence=?,updated_at=? WHERE id=?""",
                    (directory["country"], directory["country_code"], directory["region_group"], new_city, new_state,
                     "AACSB directory location: " + str(directory["location_raw"] or ""), now_utc(), job["id"]),
                )
                links = conn.execute(
                    """SELECT source_job_id,source_url FROM job_sources
                       WHERE source_id=? AND job_id=?""", (source_id, job["id"])
                ).fetchall()
                for link in links:
                    conn.execute(
                        "UPDATE job_field_provenance SET is_current=0 WHERE job_id=? AND field_name='country'",
                        (job["id"],),
                    )
                    conn.execute(
                        """INSERT INTO job_field_provenance
                           (job_id,field_name,source_id,source_job_id,source_url,value_text,evidence_text,captured_at,is_current)
                           VALUES (?,?,?,?,?,?,?,?,1)""",
                        (job["id"], "country", source_id, link["source_job_id"], directory["directory_url"],
                         directory["country"], "AACSB directory location: " + str(directory["location_raw"] or ""),
                         now_utc()),
                    )
                conn.execute(
                    """INSERT INTO faculty_job_repair_audit
                       (observed_at,action,job_id,source_id,old_value,new_value,reason)
                       VALUES (?,?,?,?,?,?,?)""",
                    (now_utc(), "aacsb_directory_country_repair", job["id"], source_id,
                     json.dumps({"country": job["country"], "country_code": job["country_code"]}, ensure_ascii=False),
                     json.dumps({"country": directory["country"], "country_code": directory["country_code"]}, ensure_ascii=False),
                     "Official AACSB roster location takes precedence over a conflicting derived detail-page location."),
                )


def _save_aacsb_scan_result(conn, directory_id, scan, checked_at):
    from services.faculty_jobs_sources.aacsb import AACSB_SCAN_RULE_VERSION
    jobs = scan.jobs or []
    conn.execute("""
        UPDATE aacsb_directory_schools SET website_status=?, website_checked_at=?, career_page_url=?, career_page_status=?,
          job_scan_status=?, jobs_found=?, candidates_seen=?,candidates_rejected=?,
          scan_rule_version=?,last_job_scan_at=?, job_scan_reason=?, updated_at=? WHERE id=?
    """, (scan.website_status, checked_at, scan.career_page_url, scan.career_page_status,
           scan.job_scan_status, len(jobs), int(scan.candidates_seen or 0),
           int(scan.candidates_rejected or 0), AACSB_SCAN_RULE_VERSION,
           checked_at, scan.reason, checked_at, directory_id))
    conn.execute("""
        INSERT INTO aacsb_scan_history
          (directory_school_id,checked_at,official_website,career_page_url,website_status,career_page_status,
          job_scan_status,jobs_found,candidates_seen,candidates_rejected,scan_rule_version,response_status,reason)
        SELECT id,? AS checked_at,official_website,? AS career_page_url,? AS website_status,
               ? AS career_page_status,? AS job_scan_status,? AS jobs_found,
               ? AS candidates_seen,? AS candidates_rejected,? AS scan_rule_version,
               ? AS response_status,? AS reason
        FROM aacsb_directory_schools WHERE id=?
    """, (checked_at, scan.career_page_url, scan.website_status, scan.career_page_status,
           scan.job_scan_status, len(jobs), int(scan.candidates_seen or 0),
           int(scan.candidates_rejected or 0), AACSB_SCAN_RULE_VERSION,
           scan.response_status, scan.reason, directory_id))


def update_aacsb_directory(db_path=None, max_pages=110, max_records=None, fetch_details=True,
                           refresh_details=False, scan_websites=False, max_details=None,
                           max_schools=None, timeout=20, delay=0.45, max_jobs_per_school=20,
                           site_max_pages=2, progress=None):
    """Import the AACSB roster and optionally scan official school job pages.

    ``max_records``/``max_details``/``max_schools`` are hard safety budgets.
    A partial website scan never marks the unvisited schools as having no jobs.
    """
    from services.faculty_jobs_sources.aacsb import AACSB_SCAN_RULE_VERSION
    db_path = db_path or FACULTY_DB_PATH
    ensure_faculty_jobs_tables(db_path)
    with _FACULTY_UPDATE_LOCK:
        conn = _connect(db_path)
        started = now_utc()
        source_id = _aacsb_source_id(conn)
        run_id = conn.execute("""
            INSERT INTO aacsb_scan_runs
              (started_at,status,max_pages,max_schools,scan_websites,scan_rule_version)
            VALUES (?,?,?,?,?,?)
        """, (started, "running", int(max_pages), max_schools, int(bool(scan_websites)),
               AACSB_SCAN_RULE_VERSION if scan_websites else None)).lastrowid
        ingestion_id = conn.execute(
            "INSERT INTO ingestion_runs (source_id,started_at,status) VALUES (?,?,?)",
            (source_id, started, "running"),
        ).lastrowid
        conn.execute("UPDATE sources SET last_attempt_at=?,last_status='running',last_error=NULL,updated_at=? WHERE id=?", (started, started, source_id))
        conn.commit()
        try:
            from services.faculty_jobs_sources.aacsb import AACSBDirectoryClient
            client = AACSBDirectoryClient(timeout=timeout, max_pages=max_pages, delay=delay)
            records, pages_fetched, total = client.fetch_directory(max_pages=max_pages, max_records=max_records)
            directory_meta = getattr(client, "last_directory_metadata", {}) or {}
            directory_ids = []
            for index, record in enumerate(records, 1):
                with conn:
                    directory_id = _upsert_aacsb_directory_row(conn, record)
                    directory_ids.append(directory_id)
                if progress and (index == 1 or index % 25 == 0):
                    progress(f"AACSB roster {index}/{len(records)}")

            details_fetched = 0
            detail_budget = len(records) if max_details is None else max(0, min(len(records), int(max_details)))
            if fetch_details:
                for index, directory_id in enumerate(directory_ids):
                    row = conn.execute("SELECT * FROM aacsb_directory_schools WHERE id=?", (directory_id,)).fetchone()
                    if not row:
                        continue
                    if not refresh_details and row["detail_status"] == "ok" and row["official_website"]:
                        continue
                    if details_fetched >= detail_budget:
                        break
                    try:
                        detail = client.fetch_detail(_aacsb_record_from_row(row))
                        with conn:
                            _upsert_aacsb_directory_row(conn, detail)
                        details_fetched += 1
                    except Exception as exc:
                        with conn:
                            conn.execute("UPDATE aacsb_directory_schools SET detail_status='error',detail_checked_at=?,job_scan_reason=?,updated_at=? WHERE id=?", (now_utc(), str(exc)[:300], now_utc(), directory_id))
                    if progress and (details_fetched == 1 or details_fetched % 25 == 0):
                        progress(f"AACSB detail pages {details_fetched}/{detail_budget}")

            # Link every roster school for which AACSB exposed an explicit
            # school label.  Directory-only rows remain visible even when no
            # local business_schools entity can be safely constructed.
            linked = 0
            for directory_id in directory_ids:
                with conn:
                    if _sync_aacsb_school_entity(conn, directory_id):
                        linked += 1

            websites_checked = 0
            jobs_found = 0
            candidates_seen = candidates_rejected = 0
            inserted = updated = merged = source_errors = 0
            if scan_websites:
                rows = [conn.execute("SELECT * FROM aacsb_directory_schools WHERE id=?", (directory_id,)).fetchone() for directory_id in directory_ids]
                rows = [row for row in rows if row and row["official_website"]]
                if max_schools is not None:
                    rows = rows[:max(0, min(len(rows), int(max_schools)))]
                for index, row in enumerate(rows, 1):
                    record = _aacsb_record_from_row(row)
                    try:
                        scan = client.scan_official_site(
                            record, max_pages=site_max_pages, max_jobs=max_jobs_per_school,
                        )
                        checked = now_utc()
                        with conn:
                            _save_aacsb_scan_result(conn, row["id"], scan, checked)
                            for job in scan.jobs or []:
                                try:
                                    normalized = normalize_source_job(job, "Global")
                                    _job_id, action = _upsert_job(conn, source_id, job, normalized, started)
                                    if action == "inserted": inserted += 1
                                    elif action == "merged": merged += 1
                                    else: updated += 1
                                except Exception as exc:
                                    source_errors += 1
                                    LOG.warning("AACSB official job failed school=%s error=%s", row["institution_name"], _safe_error(exc))
                        websites_checked += 1
                        jobs_found += len(scan.jobs or [])
                        candidates_seen += int(scan.candidates_seen or 0)
                        candidates_rejected += int(scan.candidates_rejected or 0)
                    except Exception as exc:
                        source_errors += 1
                        with conn:
                            conn.execute("UPDATE aacsb_directory_schools SET website_status='error',job_scan_status='unknown',last_job_scan_at=?,job_scan_reason=?,updated_at=? WHERE id=?", (now_utc(), str(exc)[:300], now_utc(), row["id"]))
                    if progress and (index == 1 or index % 10 == 0):
                        progress(f"AACSB official websites {index}/{len(rows)}; jobs={jobs_found}")

            finished = now_utc()
            with conn:
                conn.execute("""
                    UPDATE aacsb_scan_runs SET finished_at=?,status='success',pages_fetched=?,records_seen=?,records_upserted=?,details_fetched=?,
                      websites_checked=?,jobs_found=?,candidates_seen=?,candidates_rejected=?,
                      directory_results_reported=?,directory_results_observed=?,
                      non_accredited_results_excluded=?,directory_observation_complete=?,
                      error_count=?,error_summary=? WHERE id=?
                """, (finished, pages_fetched, len(records), len(directory_ids), details_fetched, websites_checked, jobs_found,
                       candidates_seen, candidates_rejected,
                       directory_meta.get("reported_results"), directory_meta.get("raw_results_observed"),
                       directory_meta.get("non_accredited_results_excluded"), int(bool(directory_meta.get("complete"))),
                       source_errors,
                       f"{source_errors} bounded per-school errors" if source_errors else None, run_id))
                conn.execute("""
                    UPDATE ingestion_runs SET finished_at=?,status='success',pages_fetched=?,items_seen=?,items_inserted=?,items_updated=?,items_merged=?,error_count=?,error_summary=? WHERE id=?
                """, (finished, pages_fetched, jobs_found, inserted, updated, merged, source_errors,
                       f"{source_errors} bounded per-school errors" if source_errors else None, ingestion_id))
                conn.execute("UPDATE sources SET last_success_at=?,last_status='ok',last_error=?,updated_at=? WHERE id=?", (finished, f"{source_errors} bounded per-school errors" if source_errors else None, finished, source_id))
                conn.commit()
            return {
                "ok": True, "source": "aacsb_official", "pages_fetched": pages_fetched,
                "directory_total_reported": total, "records_seen": len(records),
                "directory_results_observed": directory_meta.get("raw_results_observed"),
                "non_accredited_results_excluded": directory_meta.get("non_accredited_results_excluded"),
                "directory_observation_complete": bool(directory_meta.get("complete")),
                "records_upserted": len(directory_ids), "linked_business_schools": linked,
                "details_fetched": details_fetched, "websites_checked": websites_checked,
                "jobs_found": jobs_found, "items_inserted": inserted, "items_updated": updated,
                "items_merged": merged, "candidates_seen": candidates_seen,
                "candidates_rejected": candidates_rejected,
                "errors": source_errors, "updated_at": finished,
            }
        except Exception as exc:
            error = _safe_error(exc)
            finished = now_utc()
            conn.execute("UPDATE aacsb_scan_runs SET finished_at=?,status='error',error_count=1,error_summary=? WHERE id=?", (finished, error, run_id))
            conn.execute("UPDATE ingestion_runs SET finished_at=?,status='error',error_count=1,error_summary=? WHERE id=?", (finished, error, ingestion_id))
            conn.execute("UPDATE sources SET last_status='error',last_error=?,updated_at=? WHERE id=?", (error, finished, source_id))
            conn.commit()
            LOG.warning("AACSB directory update failed: %s", error)
            return {"ok": False, "source": "aacsb_official", "error": error, "updated_at": finished}
        finally:
            conn.close()


def scan_aacsb_official_websites(db_path=None, max_schools=25, offset=0,
                                 include_checked=False, timeout=20, delay=0.75,
                                 max_jobs_per_school=20, site_max_pages=2, progress=None):
    """Scan already-imported AACSB official websites in a bounded batch.

    This deliberately does not refetch the AACSB roster. It is the resumable
    second stage for a full roster run: unchecked rows and rows last checked by
    an older rule version are candidates, while all other rows retain their
    recorded state.
    """
    from services.faculty_jobs_sources.aacsb import AACSB_SCAN_RULE_VERSION
    db_path = db_path or FACULTY_DB_PATH
    ensure_faculty_jobs_tables(db_path)
    with _FACULTY_UPDATE_LOCK:
        conn = _connect(db_path)
        started = now_utc()
        source_id = _aacsb_source_id(conn)
        bounded = max(1, min(2000, int(max_schools)))
        start_offset = max(0, int(offset))
        where = "active=1 AND official_website IS NOT NULL AND official_website!=''"
        where_args = []
        if not include_checked:
            where += " AND (website_checked_at IS NULL OR COALESCE(scan_rule_version,'')!=?)"
            where_args.append(AACSB_SCAN_RULE_VERSION)
        rows = conn.execute(
            f"SELECT * FROM aacsb_directory_schools WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
            (*where_args, bounded, start_offset),
        ).fetchall()
        run_id = conn.execute("""
            INSERT INTO aacsb_scan_runs
              (started_at,status,max_pages,max_schools,scan_websites,scan_rule_version)
            VALUES (?,?,?,?,1,?)
        """, (started, "running", 0, len(rows), AACSB_SCAN_RULE_VERSION)).lastrowid
        ingestion_id = conn.execute(
            "INSERT INTO ingestion_runs (source_id,started_at,status) VALUES (?,?,?)",
            (source_id, started, "running"),
        ).lastrowid
        conn.execute("UPDATE sources SET last_attempt_at=?,last_status='running',last_error=NULL,updated_at=? WHERE id=?", (started, started, source_id))
        conn.commit()
        try:
            from services.faculty_jobs_sources.aacsb import AACSBDirectoryClient
            client = AACSBDirectoryClient(timeout=timeout, max_pages=2, delay=delay)
            websites_checked = jobs_found = candidates_seen = candidates_rejected = inserted = updated = merged = errors = 0
            for index, row in enumerate(rows, 1):
                try:
                    scan = client.scan_official_site(
                        _aacsb_record_from_row(row), max_pages=site_max_pages,
                        max_jobs=max_jobs_per_school,
                    )
                    checked = now_utc()
                    with conn:
                        _save_aacsb_scan_result(conn, row["id"], scan, checked)
                        for job in scan.jobs or []:
                            try:
                                normalized = normalize_source_job(job, "Global")
                                _job_id, action = _upsert_job(conn, source_id, job, normalized, started)
                                if action == "inserted": inserted += 1
                                elif action == "merged": merged += 1
                                else: updated += 1
                            except Exception as exc:
                                errors += 1
                                LOG.warning("AACSB official job failed school=%s error=%s", row["institution_name"], _safe_error(exc))
                    websites_checked += 1
                    jobs_found += len(scan.jobs or [])
                    candidates_seen += int(scan.candidates_seen or 0)
                    candidates_rejected += int(scan.candidates_rejected or 0)
                except Exception as exc:
                    errors += 1
                    checked = now_utc()
                    with conn:
                        conn.execute("""
                            UPDATE aacsb_directory_schools
                            SET website_status='error',website_checked_at=?,job_scan_status='unknown',
                                last_job_scan_at=?,job_scan_reason=?,updated_at=? WHERE id=?
                        """, (checked, checked, str(exc)[:300], checked, row["id"]))
                if progress and (index == 1 or index % 10 == 0):
                    progress(f"AACSB official websites {index}/{len(rows)}; jobs={jobs_found}")

            finished = now_utc()
            with conn:
                conn.execute("""
                    UPDATE aacsb_scan_runs SET finished_at=?,status='success',pages_fetched=0,
                      records_seen=?,records_upserted=?,details_fetched=0,websites_checked=?,
                      jobs_found=?,candidates_seen=?,candidates_rejected=?,error_count=?,error_summary=? WHERE id=?
                """, (finished, len(rows), len(rows), websites_checked, jobs_found,
                       candidates_seen, candidates_rejected, errors,
                       f"{errors} bounded per-school errors" if errors else None, run_id))
                conn.execute("""
                    UPDATE ingestion_runs SET finished_at=?,status='success',pages_fetched=0,
                      items_seen=?,items_inserted=?,items_updated=?,items_merged=?,error_count=?,error_summary=? WHERE id=?
                """, (finished, jobs_found, inserted, updated, merged, errors,
                       f"{errors} bounded per-school errors" if errors else None, ingestion_id))
                conn.execute("UPDATE sources SET last_success_at=?,last_status='ok',last_error=?,updated_at=? WHERE id=?", (finished, f"{errors} bounded per-school errors" if errors else None, finished, source_id))
                conn.commit()
            stale_remaining = conn.execute("""
                SELECT COUNT(*) FROM aacsb_directory_schools
                WHERE active=1 AND official_website IS NOT NULL AND official_website!=''
                  AND (website_checked_at IS NULL OR COALESCE(scan_rule_version,'')!=?)
            """, (AACSB_SCAN_RULE_VERSION,)).fetchone()[0]
            return {
                "ok": True, "source": "aacsb_official", "records_seen": len(rows),
                "offset": start_offset, "websites_checked": websites_checked,
                "jobs_found": jobs_found, "items_inserted": inserted,
                "items_updated": updated, "items_merged": merged,
                "candidates_seen": candidates_seen, "candidates_rejected": candidates_rejected,
                "scan_rule_version": AACSB_SCAN_RULE_VERSION,
                "stale_or_unchecked_remaining": int(stale_remaining or 0),
                "errors": errors,
                "updated_at": finished,
            }
        except Exception as exc:
            error = _safe_error(exc)
            finished = now_utc()
            conn.execute("UPDATE aacsb_scan_runs SET finished_at=?,status='error',error_count=1,error_summary=? WHERE id=?", (finished, error, run_id))
            conn.execute("UPDATE ingestion_runs SET finished_at=?,status='error',error_count=1,error_summary=? WHERE id=?", (finished, error, ingestion_id))
            conn.execute("UPDATE sources SET last_status='error',last_error=?,updated_at=? WHERE id=?", (error, finished, source_id))
            conn.commit()
            return {"ok": False, "source": "aacsb_official", "error": error, "updated_at": finished}
        finally:
            conn.close()


def list_aacsb_directory(db_path=None, query=None, limit=50, offset=0):
    from services.faculty_jobs_sources.aacsb import AACSB_SCAN_RULE_VERSION
    ensure_faculty_jobs_tables(db_path)
    query = query or {}
    conn = _connect(db_path)
    try:
        clauses = ["d.active=1"]
        args = []
        text = str(query.get("q") or "").strip()
        if text:
            like = f"%{text}%"
            clauses.append("(d.institution_name LIKE ? OR d.school_name LIKE ? OR d.city LIKE ? OR d.country LIKE ?)")
            args.extend([like] * 4)
        country = str(query.get("country") or "").strip()
        if country:
            code = country_code_for(country)
            clauses.append("d.country_code=?" if code else "1=0")
            if code:
                args.append(code)
        status = str(query.get("job_scan_status") or "").strip()
        if status:
            clauses.append("d.job_scan_status=?")
            args.append(status)
        website_status = str(query.get("website_status") or "").strip()
        if website_status:
            clauses.append("d.website_status=?")
            args.append(website_status)
        if str(query.get("has_jobs") or "").lower() in {"1", "true", "yes"}:
            clauses.append("d.jobs_found>0")
        where = " AND ".join(clauses)
        total = conn.execute(f"SELECT COUNT(*) FROM aacsb_directory_schools d WHERE {where}", args).fetchone()[0]
        bounded = max(1, min(200, int(limit)))
        start = max(0, int(offset))
        rows = conn.execute(f"""
            SELECT d.*, bs.official_name AS linked_school_name,
                   (SELECT COUNT(*) FROM jobs j WHERE j.school_id=d.linked_business_school_id AND j.derived_quality='accepted' AND j.faculty_market_eligible=1 AND j.business_scope IN ('business_school','business_discipline') AND j.status IN ('open','likely_open','closing_soon')) AS current_openings
            FROM aacsb_directory_schools d
            LEFT JOIN business_schools bs ON bs.id=d.linked_business_school_id
            WHERE {where}
            ORDER BY CASE WHEN d.scan_rule_version=? THEN 0 ELSE 1 END,
                     CASE WHEN d.jobs_found>0 THEN 0 ELSE 1 END,
                     d.country, d.institution_name, d.school_name
            LIMIT ? OFFSET ?
        """, args + [AACSB_SCAN_RULE_VERSION, bounded, start]).fetchall()
        return {
            "ok": True,
            "schools": [dict(row) for row in rows],
            "current_scan_rule_version": AACSB_SCAN_RULE_VERSION,
            "pagination": {"total": total, "limit": bounded, "offset": start, "has_more": start + len(rows) < total},
        }
    finally:
        conn.close()


def build_aacsb_directory_summary(db_path=None):
    from services.faculty_jobs_sources.aacsb import AACSB_SCAN_RULE_VERSION
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        def count(sql, args=()):
            return int(conn.execute(sql, args).fetchone()[0] or 0)
        total = count("SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1")
        statuses = [dict(row) for row in conn.execute("SELECT job_scan_status AS status, COUNT(*) AS count FROM aacsb_directory_schools WHERE active=1 GROUP BY job_scan_status ORDER BY status").fetchall()]
        current_rule_statuses = [dict(row) for row in conn.execute("""
            SELECT job_scan_status AS status,COUNT(*) AS count
            FROM aacsb_directory_schools
            WHERE active=1 AND scan_rule_version=?
            GROUP BY job_scan_status ORDER BY status
        """, (AACSB_SCAN_RULE_VERSION,)).fetchall()]
        countries = [dict(row) for row in conn.execute("SELECT COALESCE(country,'Unknown') AS country, COUNT(*) AS count FROM aacsb_directory_schools WHERE active=1 GROUP BY country ORDER BY count DESC,country LIMIT 40").fetchall()]
        last_run = conn.execute("SELECT * FROM aacsb_scan_runs ORDER BY id DESC LIMIT 1").fetchone()
        roster_run = conn.execute("""
            SELECT * FROM aacsb_scan_runs
            WHERE status='success' AND directory_results_reported IS NOT NULL
            ORDER BY id DESC LIMIT 1
        """).fetchone()
        source = conn.execute("SELECT id FROM sources WHERE name='aacsb_official'").fetchone()
        accepted_jobs = quarantined_jobs = 0
        if source:
            accepted_jobs = count("""SELECT COUNT(DISTINCT js.job_id) FROM job_sources js JOIN jobs j ON j.id=js.job_id
                                    WHERE js.source_id=? AND j.derived_quality='accepted'
                                      AND j.faculty_market_eligible=1
                                      AND j.business_scope IN ('business_school','business_discipline')""", (source["id"],))
            quarantined_jobs = count("""SELECT COUNT(DISTINCT js.job_id) FROM job_sources js JOIN jobs j ON j.id=js.job_id
                                      WHERE js.source_id=? AND j.derived_quality='quarantined'""", (source["id"],))
        return {"ok": True, "summary": {
            "total": total,
            "school_unit_records": count(
                "SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1 AND school_name IS NOT NULL AND TRIM(school_name)!=''"
            ),
            "organization_level_records": count(
                "SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1 AND (school_name IS NULL OR TRIM(school_name)='')"
            ),
            "linked_school_entities": count(
                "SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1 AND linked_business_school_id IS NOT NULL"
            ),
            "directory_results_reported": roster_run["directory_results_reported"] if roster_run else None,
            "directory_results_observed": roster_run["directory_results_observed"] if roster_run else None,
            "non_accredited_results_excluded": roster_run["non_accredited_results_excluded"] if roster_run else None,
            "directory_observation_complete": bool(roster_run["directory_observation_complete"]) if roster_run else False,
            "detail_ok": count("SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1 AND detail_status='ok'"),
            "official_website": count("SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1 AND official_website IS NOT NULL AND official_website!=''"),
            "website_checked": count("SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1 AND website_checked_at IS NOT NULL"),
            "current_rule_version": AACSB_SCAN_RULE_VERSION,
            "website_checked_current_rule": count(
                "SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1 AND scan_rule_version=?",
                (AACSB_SCAN_RULE_VERSION,),
            ),
            "stale_or_unchecked_websites": count("""
                SELECT COUNT(*) FROM aacsb_directory_schools
                WHERE active=1 AND official_website IS NOT NULL AND official_website!=''
                  AND (website_checked_at IS NULL OR COALESCE(scan_rule_version,'')!=?)
            """, (AACSB_SCAN_RULE_VERSION,)),
            "career_page_found": count("SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1 AND career_page_status='found'"),
            "jobs_found_schools": count("SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1 AND jobs_found>0"),
            "jobs_found": count("SELECT COALESCE(SUM(jobs_found),0) FROM aacsb_directory_schools WHERE active=1"),
            "jobs_found_current_rule": count(
                "SELECT COALESCE(SUM(jobs_found),0) FROM aacsb_directory_schools WHERE active=1 AND scan_rule_version=?",
                (AACSB_SCAN_RULE_VERSION,),
            ),
            "candidates_seen": count("SELECT COALESCE(SUM(candidates_seen),0) FROM aacsb_directory_schools WHERE active=1"),
            "candidates_rejected": count("SELECT COALESCE(SUM(candidates_rejected),0) FROM aacsb_directory_schools WHERE active=1"),
            "candidates_seen_current_rule": count(
                "SELECT COALESCE(SUM(candidates_seen),0) FROM aacsb_directory_schools WHERE active=1 AND scan_rule_version=?",
                (AACSB_SCAN_RULE_VERSION,),
            ),
            "candidates_rejected_current_rule": count(
                "SELECT COALESCE(SUM(candidates_rejected),0) FROM aacsb_directory_schools WHERE active=1 AND scan_rule_version=?",
                (AACSB_SCAN_RULE_VERSION,),
            ),
            "accepted_job_records": accepted_jobs,
            "quarantined_source_linked_records": quarantined_jobs,
            "statuses": statuses, "current_rule_statuses": current_rule_statuses,
            "countries": countries,
            "last_run": dict(last_run) if last_run else None,
            "method_note": "The AACSB result count can include explicitly non-accredited educational-member insertions; only /accredited/ records enter the roster. Accreditation is a school-directory signal, not vacancy evidence. Only individual role-eligible postings with posting-level business evidence enter the default market; rejected or quarantined source-linked records remain auditable.",
        }}
    finally:
        conn.close()


def build_aacsb_directory_filters(db_path=None):
    """Return the centralized country vocabulary plus observed roster counts."""
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        observed = [dict(row) for row in conn.execute(
            """SELECT country_code AS code, COALESCE(country,'Unknown') AS label, COUNT(*) AS count
               FROM aacsb_directory_schools
               WHERE active=1 AND country_code IS NOT NULL
               GROUP BY country_code,country ORDER BY label"""
        ).fetchall()]
        return {"ok": True, "country_options": list(COUNTRY_OPTIONS), "observed_countries": observed}
    finally:
        conn.close()


def _discipline_observed_coverage(conn, filtered_where, active_where, args):
    """Summarize observed field coverage by discipline.

    This is intentionally named observed coverage rather than market strength:
    it describes the current local source snapshot and does not infer demand,
    quality, or a complete labor market.
    """
    sql = (
        "SELECT COALESCE(f.discipline_primary,'Other') AS discipline, "
        "COUNT(*) AS jobs, "
        "SUM(CASE WHEN f.salary_min IS NOT NULL THEN 1 ELSE 0 END) AS salary_known, "
        "SUM(CASE WHEN f.deadline_date IS NOT NULL OR f.deadline_mode IN ('open_until_filled','rolling') THEN 1 ELSE 0 END) AS deadline_known, "
        "SUM(CASE WHEN f.school_id IS NOT NULL AND EXISTS (SELECT 1 FROM school_evidence se WHERE se.school_id=f.school_id) THEN 1 ELSE 0 END) AS school_evidence, "
        "COUNT(DISTINCT f.country_code) AS geographies "
        "FROM (" + _job_select() + " WHERE " + active_where + ") f "
        "GROUP BY f.discipline_primary ORDER BY jobs DESC, discipline"
    )
    rows = conn.execute(sql, args).fetchall()
    result = []
    for row in rows:
        total = int(row["jobs"] or 0)
        result.append({
            "discipline": row["discipline"] or "Other",
            "jobs": total,
            "salary_known": int(row["salary_known"] or 0),
            "salary_percent": round(100 * int(row["salary_known"] or 0) / total, 1) if total else None,
            "deadline_known": int(row["deadline_known"] or 0),
            "deadline_percent": round(100 * int(row["deadline_known"] or 0) / total, 1) if total else None,
            "school_evidence": int(row["school_evidence"] or 0),
            "school_evidence_percent": round(100 * int(row["school_evidence"] or 0) / total, 1) if total else None,
            "geographies": int(row["geographies"] or 0),
            "interpretation": "Observed source coverage only; not a discipline-strength or demand estimate.",
        })
    return result


def build_job_market_analytics(db_path=None, query=None):
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        clauses, args = _query_conditions(query)
        scope = _requested_scope(query)
        filtered_where = " AND ".join(clauses) if clauses else "1=1"
        active_where = " AND ".join([filtered_where, "j.status IN ('open','likely_open','closing_soon')"])
        def grouped(column):
            return _group_counts_filtered(conn, column, active_where, args)
        weeks = [dict(row) for row in conn.execute(
            "SELECT substr(f.first_seen_at,1,7) AS period, COUNT(*) AS count FROM (" + _job_select() + " WHERE " + filtered_where + ") f GROUP BY period ORDER BY period",
            args,
        ).fetchall()]
        cycles = [dict(row) for row in conn.execute(
            "SELECT COALESCE(f.hiring_cycle,'Unknown') AS cycle, COUNT(*) AS count FROM (" + _job_select() + " WHERE " + filtered_where + ") f GROUP BY cycle ORDER BY cycle",
            args,
        ).fetchall()]
        history_rows = [dict(row) for row in conn.execute(
            "SELECT * FROM source_coverage_history ORDER BY observed_at"
        ).fetchall()]
        history_periods = sorted({str(item.get("observed_at") or "")[:10] for item in history_rows if item.get("observed_at")})
        history_status = "sufficient_history" if len(history_periods) >= 2 else "insufficient_history"
        history_note = (
            "At least two source-coverage observations are available; counts remain source-coverage observations, not a market-size estimate."
            if history_status == "sufficient_history" else
            "Only one source-coverage observation is available; this page is a snapshot and cannot support a longitudinal trend."
        )
        return {"ok": True, "analytics": {
            "scope": scope,
            "overview": build_faculty_job_summary(db_path, query)["summary"],
            "by_discipline": grouped("discipline_primary"), "by_region": grouped("region_group"),
            "by_country": grouped("country"), "by_state_province": grouped("state_province"),
            "by_rank": grouped("rank_normalized"), "by_career_stage": grouped("career_stage"),
            "by_contract": grouped("track_type"), "by_university_level": grouped("university_research_level"),
            "by_business_tier": grouped("business_research_tier"),
            "discipline_observed_coverage": _discipline_observed_coverage(conn, filtered_where, active_where, args),
            "history_month": weeks, "hiring_cycles": cycles,
            "source_coverage_history": history_rows, "history_status": history_status,
            "history_note": history_note,
            "coverage": _coverage(conn, filtered_where, args),
            "interpretation_note": "Counts are observed postings in the enabled-source coverage, not an estimate of the whole academic labor market. A new source or wider crawl can raise counts without implying market growth.",
            "updated_at": now_utc(),
        }}
    finally:
        conn.close()


def export_faculty_jobs_csv(db_path=None, query=None, include_private=False):
    base_query = dict(query or {})
    # Export is a current-results operation.  Read every bounded API page so
    # a large local snapshot is never silently truncated at 200 rows.
    jobs = []
    offset = 0
    page_limit = 200
    while True:
        payload = build_faculty_jobs_payload(
            db_path, {**base_query, "limit": page_limit, "offset": offset},
            include_private=include_private,
        )
        page = payload.get("jobs", [])
        jobs.extend(page)
        pagination = payload.get("pagination", {})
        if not page or not pagination.get("has_more"):
            break
        offset += len(page)
    output = io.StringIO()
    fields = ["institution", "business_school", "title", "rank", "career_stage", "discipline", "city", "state_province", "country", "contract", "salary", "deadline", "school_tier", "university_level", "official_url", "first_seen", "last_seen", "status"]
    if include_private:
        fields.extend(["fit_score", "application_state", "notes"])
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for job in jobs:
        row = {"institution": job.get("institution_name"), "business_school": job.get("business_school_name"), "title": job.get("title_raw"), "rank": job.get("rank_normalized"), "career_stage": job.get("career_stage"), "discipline": job.get("discipline_primary"), "city": job.get("city"), "state_province": job.get("state_province"), "country": job.get("country"), "contract": job.get("track_type"), "salary": job.get("salary_raw"), "deadline": job.get("deadline_date") or job.get("deadline_mode"), "school_tier": job.get("school_tier"), "university_level": job.get("university_level"), "official_url": job.get("official_url"), "first_seen": job.get("first_seen_at"), "last_seen": job.get("last_seen_at"), "status": job.get("status")}
        if include_private:
            row["fit_score"] = (job.get("fit") or {}).get("score")
            row["application_state"] = (job.get("personal_state") or {}).get("state")
            row["notes"] = (job.get("personal_state") or {}).get("notes")
        writer.writerow(row)
    return output.getvalue()


def get_profile():
    profile = load_profile()
    return {"ok": True, "profile": profile, "private": True}


def save_profile_payload(payload):
    return {"ok": True, "profile": save_profile(payload), "private": True}


def list_my_applications(db_path=None):
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(_job_select() + " JOIN user_job_state ujs ON ujs.job_id=j.id ORDER BY ujs.priority DESC,ujs.updated_at DESC").fetchall()
        return {"ok": True, "applications": [_job_dict(conn, row, include_private=True) for row in rows], "states": list(APPLICATION_STATES)}
    finally:
        conn.close()


def _validate_application_payload(payload, partial=False):
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    if not partial and str(payload.get("state") or "Saved") not in APPLICATION_STATES:
        raise ValueError("invalid application state")
    if "state" in payload and payload["state"] not in APPLICATION_STATES:
        raise ValueError("invalid application state")
    if "priority" in payload:
        try: payload["priority"] = max(0, min(5, int(payload["priority"])))
        except (TypeError, ValueError): raise ValueError("priority must be an integer")
    if "notes" in payload: payload["notes"] = str(payload["notes"] or "")[:10000]
    if "cv_version" in payload: payload["cv_version"] = str(payload["cv_version"] or "")[:300]
    if "event_type" in payload: payload["event_type"] = str(payload["event_type"] or "")[:200]
    if "event_note" in payload: payload["event_note"] = str(payload["event_note"] or "")[:2000]
    if "event_date" in payload:
        event_date = str(payload.get("event_date") or "")
        if event_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date):
            raise ValueError("event_date must use YYYY-MM-DD")
        payload["event_date"] = event_date or None
    return payload


def create_application(db_path, job_id, payload):
    payload = _validate_application_payload(dict(payload or {}))
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        if not conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
            return {"ok": False, "error": "job not found"}
        now = now_utc()
        state = payload.get("state", "Saved")
        applied_at = now if state in {"Applied", "Screening Interview", "Campus Interview", "Offer", "Rejected", "Withdrawn", "Closed"} else None
        conn.execute("""
            INSERT INTO user_job_state (job_id,state,priority,saved_at,applied_at,updated_at,notes,cv_version)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET state=excluded.state,priority=excluded.priority,
              applied_at=COALESCE(excluded.applied_at,user_job_state.applied_at),updated_at=excluded.updated_at,
              notes=excluded.notes,cv_version=excluded.cv_version
        """, (job_id, state, payload.get("priority", 0), now, applied_at, now, payload.get("notes", ""), payload.get("cv_version")))
        if payload.get("event_type"):
            conn.execute("INSERT INTO application_events (job_id,event_type,event_date,note,created_at) VALUES (?,?,?,?,?)", (job_id, str(payload["event_type"])[:200], payload.get("event_date") or now[:10], str(payload.get("event_note") or "")[:2000], now))
        conn.commit()
        return {"ok": True, "job_id": job_id, "state": state, "private": True}
    finally:
        conn.close()


def patch_application(db_path, job_id, payload):
    payload = _validate_application_payload(dict(payload or {}), partial=True)
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM user_job_state WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return create_application(db_path, job_id, payload)
        now = now_utc()
        allowed = {"state", "priority", "notes", "cv_version"}
        updates = [(key, payload[key]) for key in allowed if key in payload]
        if updates:
            conn.execute("UPDATE user_job_state SET " + ",".join(f"{key}=?" for key, _ in updates) + ", updated_at=? WHERE job_id=?", [value for _, value in updates] + [now, job_id])
        if payload.get("event_type"):
            conn.execute("INSERT INTO application_events (job_id,event_type,event_date,note,created_at) VALUES (?,?,?,?,?)", (job_id, str(payload["event_type"])[:200], payload.get("event_date") or now[:10], str(payload.get("event_note") or "")[:2000], now))
        conn.commit()
        return {"ok": True, "job_id": job_id, "private": True}
    finally:
        conn.close()


def save_scope_override(db_path, job_id, payload):
    """Record a local include/exclude decision without changing raw fields."""
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    action = str(payload.get("action") or "").strip().casefold()
    reason = str(payload.get("reason") or "").strip()
    source_url = str(payload.get("source_url") or "").strip() or None
    if action not in {"include", "exclude"}:
        raise ValueError("action must be include or exclude")
    if len(reason) < 10:
        raise ValueError("a reason of at least 10 characters is required")
    if source_url and urlparse(source_url).scheme not in {"http", "https"}:
        raise ValueError("source_url must be http or https")
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        if not conn.execute("SELECT 1 FROM jobs WHERE id=?", (int(job_id),)).fetchone():
            return {"ok": False, "error": "job not found"}
        now = now_utc()
        conn.execute("""
            INSERT INTO job_scope_overrides (job_id,action,reason,source_url,created_at,updated_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET action=excluded.action, reason=excluded.reason,
              source_url=excluded.source_url, updated_at=excluded.updated_at
        """, (int(job_id), action, reason[:2000], source_url, now, now))
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?)
        """, (now, "scope_override", int(job_id), None, action, reason[:2000]))
        conn.commit()
        return {"ok": True, "job_id": int(job_id), "action": action, "reason": reason, "private": True}
    finally:
        conn.close()


# Saved searches are a deliberately small local alert inbox.  They do not
# send email, call a SaaS service, or expose profile/application state.
_SAVED_SEARCH_KEYS = (
    "q", "scope", "region", "country", "state_province", "discipline", "rank",
    "career_stage", "track", "status", "school_tier", "university_level",
    "posted_after", "closing_before", "salary_known", "sort",
)
_SAVED_SEARCH_VALUE_LIMITS = {
    "q": 200, "scope": 40, "region": 80, "country": 80, "state_province": 100,
    "discipline": 100, "rank": 100, "career_stage": 80, "track": 100,
    "status": 40, "school_tier": 40, "university_level": 40,
    "posted_after": 10, "closing_before": 10, "salary_known": 10, "sort": 40,
}


def _sanitize_saved_search_query(query):
    if query is None:
        query = {}
    if not isinstance(query, dict):
        raise ValueError("saved search query must be an object")
    result = {}
    for key in _SAVED_SEARCH_KEYS:
        value = query.get(key)
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            raise ValueError(f"saved search field {key} must be scalar")
        text = str(value).strip()
        if not text:
            continue
        text = text[:_SAVED_SEARCH_VALUE_LIMITS[key]]
        if key == "scope":
            lowered = text.casefold()
            if lowered in {"all", "audit", "all_postings"}:
                text = "all"
            elif lowered in {"business_school", "verified_business_school", "school"}:
                text = "business_school"
            elif lowered == "business":
                text = "business"
            else:
                raise ValueError("saved search scope must be business, business_school, or all")
        elif key == "country":
            code = country_code_for(text)
            if not code:
                raise ValueError("saved search country must be a supported display name or ISO code")
            text = code
        elif key in {"posted_after", "closing_before"}:
            try:
                date.fromisoformat(text)
            except ValueError as exc:
                raise ValueError(f"saved search {key} must use YYYY-MM-DD") from exc
        elif key == "salary_known":
            lowered = text.casefold()
            if lowered in {"1", "true", "yes"}:
                text = "yes"
            elif lowered in {"0", "false", "no"}:
                text = "no"
            else:
                raise ValueError("saved search salary_known must be yes or no")
        elif key == "sort" and text not in {"newest", "closing_soon", "salary", "school_tier"}:
            raise ValueError("saved search sort is not supported")
        result[key] = text
    result.setdefault("scope", "business")
    return result


def _saved_search_matches(conn, query):
    clauses, args = _query_conditions(query)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return conn.execute(_job_select() + where + " ORDER BY j.id DESC", args).fetchall()


def list_saved_searches(db_path=None):
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM saved_searches ORDER BY updated_at DESC, id DESC").fetchall()
        searches = []
        for row in rows:
            try:
                query = _sanitize_saved_search_query(json.loads(row["query_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                query = {"scope": "business"}
            match_count = len(_saved_search_matches(conn, query))
            unread = conn.execute(
                "SELECT COUNT(*) FROM saved_search_alerts WHERE search_id=? AND seen_at IS NULL",
                (row["id"],),
            ).fetchone()[0]
            item = dict(row)
            item.update({
                "query": query,
                "match_count": match_count,
                "new_alert_count": unread,
                "private": True,
            })
            searches.append(item)
        return {"ok": True, "saved_searches": searches, "private": True}
    finally:
        conn.close()


def save_saved_search(db_path, payload):
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    name = str(payload.get("name") or "").strip()
    if len(name) < 2:
        raise ValueError("saved search name is required")
    query = _sanitize_saved_search_query(payload.get("query") or {})
    enabled = 1 if payload.get("enabled", True) not in {False, 0, "0", "false"} else 0
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        now = now_utc()
        search_id = payload.get("id")
        if search_id is not None:
            try:
                search_id = int(search_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("saved search id must be an integer") from exc
            if not conn.execute("SELECT 1 FROM saved_searches WHERE id=?", (search_id,)).fetchone():
                raise ValueError("saved search not found")
            conn.execute(
                "UPDATE saved_searches SET name=?, query_json=?, enabled=?, updated_at=? WHERE id=?",
                (name[:120], json.dumps(query, ensure_ascii=False, sort_keys=True), enabled, now, search_id),
            )
        else:
            search_id = conn.execute(
                "INSERT INTO saved_searches (name,query_json,enabled,created_at,updated_at) VALUES (?,?,?,?,?)",
                (name[:120], json.dumps(query, ensure_ascii=False, sort_keys=True), enabled, now, now),
            ).lastrowid
        conn.commit()
    finally:
        conn.close()
    alert_result = run_saved_search_alerts(db_path, search_id=search_id)
    result = next((item for item in list_saved_searches(db_path)["saved_searches"] if item["id"] == search_id), None)
    return {"ok": True, "saved_search": result, "alert_run": alert_result, "private": True}


def delete_saved_search(db_path, search_id):
    ensure_faculty_jobs_tables(db_path)
    try:
        search_id = int(search_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("saved search id must be an integer") from exc
    conn = _connect(db_path)
    try:
        if not conn.execute("SELECT 1 FROM saved_searches WHERE id=?", (search_id,)).fetchone():
            return {"ok": False, "error": "saved search not found", "private": True}
        conn.execute("DELETE FROM saved_searches WHERE id=?", (search_id,))
        conn.commit()
        return {"ok": True, "deleted_id": search_id, "private": True}
    finally:
        conn.close()


def run_saved_search_alerts(db_path=None, search_id=None):
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        if search_id is None:
            rows = conn.execute("SELECT * FROM saved_searches WHERE enabled=1 ORDER BY id").fetchall()
        else:
            try:
                search_id = int(search_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("saved search id must be an integer") from exc
            rows = conn.execute("SELECT * FROM saved_searches WHERE id=?", (search_id,)).fetchall()
        checked_at = now_utc()
        results = []
        with conn:
            for search in rows:
                try:
                    query = _sanitize_saved_search_query(json.loads(search["query_json"] or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    query = {"scope": "business"}
                matches = _saved_search_matches(conn, query)
                new_count = 0
                for row in matches:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO saved_search_alerts (search_id,job_id,matched_at) VALUES (?,?,?)",
                        (search["id"], row["id"], checked_at),
                    )
                    new_count += int(cur.rowcount > 0)
                conn.execute("UPDATE saved_searches SET last_checked_at=?, updated_at=? WHERE id=?", (checked_at, checked_at, search["id"]))
                results.append({
                    "search_id": search["id"], "name": search["name"],
                    "matched_count": len(matches), "new_alert_count": new_count,
                    "checked_at": checked_at,
                })
        return {"ok": True, "runs": results, "private": True}
    finally:
        conn.close()


def list_saved_search_alerts(db_path=None, search_id=None, unread_only=False, limit=100):
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        clauses = []
        args = []
        if search_id not in (None, ""):
            try:
                clauses.append("a.search_id=?")
                args.append(int(search_id))
            except (TypeError, ValueError) as exc:
                raise ValueError("saved search id must be an integer") from exc
        if unread_only:
            clauses.append("a.seen_at IS NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        bounded = max(1, min(200, int(limit)))
        rows = conn.execute(f"""
            SELECT a.id, a.search_id, a.job_id, a.matched_at, a.seen_at,
                   ss.name AS search_name, j.title_raw, j.original_title,
                   i.official_name AS institution_name, j.city, j.state_province,
                   j.country, j.country_code, j.deadline_date, j.deadline_mode,
                   j.status, j.business_scope, j.discipline_primary, j.rank_normalized,
                   j.official_url
            FROM saved_search_alerts a
            JOIN saved_searches ss ON ss.id=a.search_id
            JOIN jobs j ON j.id=a.job_id
            LEFT JOIN institutions i ON i.id=j.institution_id
            {where}
            ORDER BY a.seen_at IS NOT NULL, a.matched_at DESC, a.id DESC LIMIT ?
        """, args + [bounded]).fetchall()
        alerts = []
        for row in rows:
            item = dict(row)
            item["job"] = {
                key: item.pop(key) for key in (
                    "job_id", "title_raw", "original_title", "institution_name", "city",
                    "state_province", "country", "country_code", "deadline_date",
                    "deadline_mode", "status", "business_scope", "discipline_primary",
                    "rank_normalized", "official_url",
                )
            }
            alerts.append(item)
        return {"ok": True, "alerts": alerts, "private": True}
    finally:
        conn.close()


def mark_saved_search_alerts_seen(db_path, alert_ids):
    if not isinstance(alert_ids, list):
        raise ValueError("alert_ids must be an array")
    ids = []
    for value in alert_ids[:200]:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        now = now_utc()
        if ids:
            conn.executemany("UPDATE saved_search_alerts SET seen_at=COALESCE(seen_at,?) WHERE id=?", [(now, item) for item in ids])
            conn.commit()
        return {"ok": True, "marked": len(ids), "private": True}
    finally:
        conn.close()


def list_possible_duplicates(db_path=None, include_resolved=False, limit=100, offset=0):
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        bounded = max(1, min(200, int(limit)))
        start = max(0, int(offset))
        where = "" if include_resolved else " WHERE p.resolved=0"
        total = conn.execute("SELECT COUNT(*) FROM possible_duplicates p" + where).fetchone()[0]
        rows = conn.execute(f"""
            SELECT p.*, j1.title_raw AS job_title, j1.original_title AS job_original_title,
                   j1.official_url AS job_official_url, j1.city AS job_city,
                   j1.country AS job_country, i1.official_name AS job_institution,
                   j2.title_raw AS possible_title, j2.original_title AS possible_original_title,
                   j2.official_url AS possible_official_url, j2.city AS possible_city,
                   j2.country AS possible_country, i2.official_name AS possible_institution
            FROM possible_duplicates p
            JOIN jobs j1 ON j1.id=p.job_id
            JOIN jobs j2 ON j2.id=p.possible_job_id
            LEFT JOIN institutions i1 ON i1.id=j1.institution_id
            LEFT JOIN institutions i2 ON i2.id=j2.institution_id
            {where}
            ORDER BY p.resolved, p.confidence DESC, p.id DESC LIMIT ? OFFSET ?
        """, (bounded, start)).fetchall()
        duplicates = []
        for row in rows:
            item = dict(row)
            item["job_sources"] = _source_names(conn, row["job_id"])
            item["possible_job_sources"] = _source_names(conn, row["possible_job_id"])
            duplicates.append(item)
        return {"ok": True, "duplicates": duplicates, "pagination": {"total": total, "limit": bounded, "offset": start}, "private": True}
    finally:
        conn.close()


def resolve_possible_duplicates_batch(db_path, payload):
    """Resolve many review-only duplicate candidates in one recorded decision.

    Merge is deliberately not batchable.  Rejecting or marking distinct only
    annotates a review row, but a merge repoints job links and can absorb
    private application state, so it keeps needing per-pair evidence.

    The single reason is stored on every row it closes, so a batch decision
    stays as auditable as the individual ones it replaces.
    """
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    action = str(payload.get("action") or "").strip().casefold()
    reason = str(payload.get("reason") or "").strip()
    if action not in {"reject", "confirm_distinct"}:
        raise ValueError("batch action must be reject or confirm_distinct; "
                         "merge requires per-pair review")
    if len(reason) < 10:
        raise ValueError("a review reason of at least 10 characters is required")
    raw_ids = payload.get("ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise ValueError("ids must be a non-empty list")
    if len(raw_ids) > 500:
        raise ValueError("at most 500 candidates can be resolved in one batch")
    ids = []
    for value in raw_ids:
        try:
            ids.append(int(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("every id must be an integer") from exc

    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        now = now_utc()
        resolution = "rejected" if action == "reject" else "confirmed_distinct"
        placeholders = ",".join("?" * len(ids))
        open_ids = [row["id"] for row in conn.execute(
            f"SELECT id FROM possible_duplicates WHERE id IN ({placeholders}) AND resolved=0",
            ids).fetchall()]
        with conn:
            if open_ids:
                conn.executemany(
                    "UPDATE possible_duplicates SET resolved=1, resolution=?, resolved_at=?, "
                    "resolution_reason=? WHERE id=? AND resolved=0",
                    [(resolution, now, reason[:2000], item) for item in open_ids])
                conn.executemany("""
                    INSERT INTO faculty_job_repair_audit
                      (observed_at,action,job_id,old_value,new_value,reason)
                    SELECT ?,?,job_id,?,?,? FROM possible_duplicates WHERE id=?
                """, [(now, "duplicate_review_batch", str(item), resolution,
                       reason[:2000], item) for item in open_ids])
        skipped = sorted(set(ids) - set(open_ids))
        return {
            "ok": True, "action": action, "resolution": resolution,
            "resolved": len(open_ids), "resolved_ids": open_ids,
            # Already-resolved or unknown ids are reported rather than
            # silently counted as successes.
            "skipped": len(skipped), "skipped_ids": skipped,
            "remaining_open": conn.execute(
                "SELECT COUNT(*) FROM possible_duplicates WHERE resolved=0").fetchone()[0],
            "private": True,
        }
    finally:
        conn.close()


def _merge_exact_duplicate(conn, duplicate, reason):
    left = conn.execute("SELECT * FROM jobs WHERE id=?", (duplicate["job_id"],)).fetchone()
    right = conn.execute("SELECT * FROM jobs WHERE id=?", (duplicate["possible_job_id"],)).fetchone()
    if not left or not right:
        raise ValueError("duplicate job no longer exists")
    left_url = normalize_url(left["official_url"])
    right_url = normalize_url(right["official_url"])
    if not left_url or left_url != right_url or not is_mergeable_official_url(left_url):
        raise ValueError("manual merge requires the same verified official application URL")
    canonical_id, old_id = sorted((int(left["id"]), int(right["id"])))
    canonical = conn.execute("SELECT * FROM jobs WHERE id=?", (canonical_id,)).fetchone()
    old = conn.execute("SELECT * FROM jobs WHERE id=?", (old_id,)).fetchone()

    canonical_state = conn.execute("SELECT * FROM user_job_state WHERE job_id=?", (canonical_id,)).fetchone()
    old_state = conn.execute("SELECT * FROM user_job_state WHERE job_id=?", (old_id,)).fetchone()
    if canonical_state and old_state:
        raise ValueError("manual merge stopped because both jobs have private application state")
    canonical_override = conn.execute("SELECT * FROM job_scope_overrides WHERE job_id=?", (canonical_id,)).fetchone()
    old_override = conn.execute("SELECT * FROM job_scope_overrides WHERE job_id=?", (old_id,)).fetchone()
    if canonical_override and old_override:
        raise ValueError("manual merge stopped because both jobs have independent scope overrides")

    links = conn.execute("SELECT * FROM job_sources WHERE job_id=?", (old_id,)).fetchall()
    for link in links:
        conflict = conn.execute(
            "SELECT 1 FROM job_sources WHERE source_id=? AND source_job_id=? AND job_id<>?",
            (link["source_id"], link["source_job_id"], old_id),
        ).fetchone()
        if conflict:
            raise ValueError("manual merge stopped because a source identity is already attached elsewhere")
    for link in links:
        conn.execute(
            "UPDATE job_sources SET job_id=? WHERE source_id=? AND source_job_id=?",
            (canonical_id, link["source_id"], link["source_job_id"]),
        )
    for table in ("job_field_provenance", "job_status_history", "application_events"):
        conn.execute(f"UPDATE {table} SET job_id=? WHERE job_id=?", (canonical_id, old_id))
    conn.execute("UPDATE faculty_job_repair_audit SET job_id=? WHERE job_id=?", (canonical_id, old_id))
    if old_state:
        conn.execute("UPDATE user_job_state SET job_id=? WHERE job_id=?", (canonical_id, old_id))
    if old_override:
        conn.execute("UPDATE job_scope_overrides SET job_id=? WHERE job_id=?", (canonical_id, old_id))
    for alert in conn.execute("SELECT id,search_id FROM saved_search_alerts WHERE job_id=?", (old_id,)).fetchall():
        if conn.execute("SELECT 1 FROM saved_search_alerts WHERE search_id=? AND job_id=?", (alert["search_id"], canonical_id)).fetchone():
            conn.execute("DELETE FROM saved_search_alerts WHERE id=?", (alert["id"],))
        else:
            conn.execute("UPDATE saved_search_alerts SET job_id=? WHERE id=?", (canonical_id, alert["id"]))
    # Duplicate-review rows are derived metadata.  Their decision is retained
    # in repair_audit before the old canonical row is removed.
    conn.execute("DELETE FROM possible_duplicates WHERE job_id=? OR possible_job_id=?", (old_id, old_id))
    first_seen = min(str(canonical["first_seen_at"] or now_utc()), str(old["first_seen_at"] or now_utc()))
    last_seen = max(str(canonical["last_seen_at"] or now_utc()), str(old["last_seen_at"] or now_utc()))
    conn.execute("UPDATE jobs SET first_seen_at=?, last_seen_at=?, updated_at=? WHERE id=?", (first_seen, last_seen, now_utc(), canonical_id))
    now = now_utc()
    conn.execute("""
        INSERT INTO faculty_job_repair_audit
          (observed_at,action,job_id,old_value,new_value,reason)
        VALUES (?,?,?,?,?,?)
    """, (now, "manual_duplicate_merge", canonical_id,
          json.dumps({"merged_job_id": old_id, "duplicate_review_id": duplicate["id"]}, ensure_ascii=False),
          json.dumps({"canonical_job_id": canonical_id, "official_url": left_url}, ensure_ascii=False), reason[:2000]))
    conn.execute("DELETE FROM jobs WHERE id=?", (old_id,))
    return canonical_id, old_id


def resolve_possible_duplicate(db_path, duplicate_id, payload):
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    action = str(payload.get("action") or "").strip().casefold()
    reason = str(payload.get("reason") or "").strip()
    if action not in {"reject", "confirm_distinct", "merge"}:
        raise ValueError("action must be reject, confirm_distinct, or merge")
    if len(reason) < 10:
        raise ValueError("a review reason of at least 10 characters is required")
    try:
        duplicate_id = int(duplicate_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("duplicate id must be an integer") from exc
    ensure_faculty_jobs_tables(db_path)
    conn = _connect(db_path)
    try:
        duplicate = conn.execute("SELECT * FROM possible_duplicates WHERE id=?", (duplicate_id,)).fetchone()
        if not duplicate:
            return {"ok": False, "error": "possible duplicate not found", "private": True}
        now = now_utc()
        with conn:
            if action == "merge":
                canonical_id, old_id = _merge_exact_duplicate(conn, duplicate, reason)
                conn.execute("""
                    INSERT INTO faculty_job_repair_audit
                      (observed_at,action,job_id,old_value,new_value,reason)
                    VALUES (?,?,?,?,?,?)
                """, (now, "duplicate_review", canonical_id, str(duplicate_id), "merged", reason[:2000]))
                return {"ok": True, "action": "merge", "canonical_job_id": canonical_id, "merged_job_id": old_id, "private": True}
            resolution = "rejected" if action == "reject" else "confirmed_distinct"
            conn.execute("""
                UPDATE possible_duplicates
                SET resolved=1, resolution=?, resolved_at=?, resolution_reason=?
                WHERE id=?
            """, (resolution, now, reason[:2000], duplicate_id))
            conn.execute("""
                INSERT INTO faculty_job_repair_audit
                  (observed_at,action,job_id,old_value,new_value,reason)
                VALUES (?,?,?,?,?,?)
            """, (now, "duplicate_review", duplicate["job_id"], str(duplicate_id), resolution, reason[:2000]))
            return {"ok": True, "action": action, "duplicate_id": duplicate_id, "resolution": resolution, "private": True}
    finally:
        conn.close()


__all__ = [
    "FACULTY_DB_PATH", "FACULTY_CACHE_DIR", "APPLICATION_STATES", "ensure_faculty_jobs_tables",
    "update_faculty_jobs", "build_faculty_jobs_payload", "build_faculty_job_detail",
    "build_faculty_job_summary", "build_faculty_job_filters", "build_faculty_job_sources",
    "build_faculty_job_runs", "build_job_market_analytics", "export_faculty_jobs_csv",
    "update_aacsb_directory", "scan_aacsb_official_websites", "list_aacsb_directory", "build_aacsb_directory_summary",
    "build_aacsb_directory_filters",
    "get_profile", "save_profile_payload", "list_my_applications", "create_application",
    "patch_application", "list_schools", "school_detail", "compare_schools", "add_evidence",
    "save_override", "save_scope_override", "list_saved_searches", "save_saved_search",
    "delete_saved_search", "run_saved_search_alerts", "list_saved_search_alerts",
    "mark_saved_search_alerts_seen", "list_possible_duplicates", "resolve_possible_duplicate",
    "list_institution_aliases", "save_institution_alias",
]
