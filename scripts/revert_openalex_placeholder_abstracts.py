#!/usr/bin/env python3
"""Restore exact pre-images for hash-verified source-placeholder abstracts.

This guarded repair is intentionally narrow. It identifies known source
placeholders among a hash-bound abstract candidate file, verifies the original
before-images from the matching application run, restores only those rows to
their prior missing-abstract state, removes only the matching enrichment
provenance rows, then refreshes semantic/entity deltas incrementally.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.apply_abdc_abstract_candidates import (  # noqa: E402
    MAX_BATCH_SIZE,
    VECTOR_NAMES,
    check_derived_indexes,
    provider_identity,
    refresh_derived,
)
from scripts.enrich_abdc_research_scope_abstracts import (  # noqa: E402
    is_placeholder_abstract,
    normalize_doi,
    sha256_file,
    titles_match,
)
from services.astar_semantic_backend import require_encoder_headroom  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_new(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_placeholder_candidates(candidate_path: Path, expected_hash: str) -> tuple[list[dict], list[dict]]:
    actual_hash = sha256_file(candidate_path)
    if actual_hash.lower() != expected_hash.lower():
        raise SystemExit("Candidate file SHA-256 does not match the expected hash")
    valid = []
    placeholders = []
    seen: set[int] = set()
    with candidate_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") != "abstract_candidate":
                raise ValueError(f"Unexpected row status at {candidate_path}:{line_number}")
            article_id = int(row["article_id"])
            if article_id in seen:
                raise ValueError(f"Duplicate candidate article ID {article_id}")
            seen.add(article_id)
            provider_identity(row)
            abstract = row.get("abstract")
            if not isinstance(abstract, str) or not abstract.strip():
                raise ValueError(f"Candidate {article_id} has no abstract text")
            if hashlib.sha256(abstract.encode("utf-8")).hexdigest() != row.get("abstract_sha256"):
                raise ValueError(f"Candidate {article_id} abstract hash mismatch")
            if is_placeholder_abstract(abstract):
                placeholders.append(row)
            else:
                valid.append(row)
    return valid, placeholders


def load_original_before_images(application_dir: Path, candidate_hash: str) -> dict[int, dict]:
    path = application_dir / "before_images.jsonl"
    if not path.is_file():
        raise SystemExit("Application before_images.jsonl is missing")
    result = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            article_id = int(row["article_id"])
            if row.get("candidate_sha256") != candidate_hash:
                continue
            if article_id in result:
                raise ValueError(f"Duplicate before-image for article {article_id}")
            result[article_id] = row
    return result


def read_live_state(db_path: Path, entries: list[dict]) -> dict[int, dict]:
    ids = [int(row["article_id"]) for row in entries]
    live: dict[int, dict] = {}
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    try:
        for start in range(0, len(ids), 400):
            part = ids[start:start + 400]
            marks = ",".join("?" for _ in part)
            for row in conn.execute(
                "SELECT id,doi,openalex_id,title,abstract,abstract_status,data_status,updated_at,is_duplicate "
                "FROM astar_articles WHERE id IN (" + marks + ")", part
            ):
                live[int(row["id"])] = dict(row)
            for row in conn.execute(
                "SELECT id,article_id,source_name,source_type,raw_id,parser_notes "
                "FROM astar_article_sources WHERE article_id IN (" + marks + ")", part
            ):
                live.setdefault(int(row["article_id"]), {}).setdefault("placeholder_sources", []).append(dict(row))
    finally:
        conn.rollback()
        conn.close()
    return live


def build_plan(candidate_file: Path, candidate_hash: str, application_dir: Path,
               db_path: Path) -> dict[str, Any]:
    valid, placeholders = read_placeholder_candidates(candidate_file, candidate_hash)
    if not placeholders:
        raise SystemExit("No known placeholder abstracts were found")
    application_manifest = application_dir / "manifest.json"
    if not application_manifest.is_file():
        raise SystemExit("Matching application manifest is missing")
    prior_manifest = json.loads(application_manifest.read_text(encoding="utf-8"))
    if prior_manifest.get("candidate_file_sha256") != candidate_hash:
        raise SystemExit("Application manifest candidate hash differs")
    before = load_original_before_images(application_dir, candidate_hash)
    live = read_live_state(db_path, placeholders)
    plan_entries = []
    for row in placeholders:
        article_id = int(row["article_id"])
        original = before.get(article_id)
        current = live.get(article_id)
        source_name, source_type, raw_id, _ = provider_identity(row)
        if original is None or current is None:
            raise ValueError(f"Missing before-image or live article row for {article_id}")
        if (original.get("abstract") or "").strip() or original.get("abstract_status") != "missing":
            raise ValueError(f"Before-image for {article_id} was not an empty missing abstract")
        if original.get("doi") != row.get("doi") or not titles_match(
                original.get("title") or "", row.get("title") or ""):
            raise ValueError(f"Original article identity differs for {article_id}")
        if (current.get("is_duplicate") or normalize_doi(current.get("doi")) != normalize_doi(row.get("doi"))
                or not titles_match(current.get("title") or "", row.get("title") or "")):
            raise ValueError(f"Current article identity differs for {article_id}")
        if (hashlib.sha256((current.get("abstract") or "").encode()).hexdigest() != row["abstract_sha256"]
                or current.get("abstract_status") != "available"
                or current.get("data_status") != "api_metadata"):
            raise ValueError(f"Current placeholder state differs for {article_id}")
        matching_sources = [source for source in current.get("placeholder_sources", [])
                            if source.get("source_name") == source_name
                            and source.get("source_type") == source_type
                            and source.get("raw_id") == raw_id
                            and row["abstract_sha256"] in (source.get("parser_notes") or "")]
        if len(matching_sources) != 1:
            raise ValueError(f"Expected exactly one hash-matched source row for {article_id}")
        plan_entries.append({
            "article_id": article_id,
            "doi": row.get("doi"),
            "title": row.get("title"),
            "openalex_id": row.get("openalex_id"),
            "placeholder_abstract_sha256": row["abstract_sha256"],
            "source_row": matching_sources[0],
            "restore_to": {key: original.get(key) for key in (
                "abstract", "abstract_status", "data_status", "updated_at")},
            "current": {key: current.get(key) for key in (
                "abstract", "abstract_status", "data_status", "updated_at")},
        })
    return {
        "created_at_utc": utc_now(),
        "candidate_file": str(candidate_file),
        "candidate_file_sha256": candidate_hash,
        "application_run_dir": str(application_dir),
        "database": str(db_path),
        "restoration_scope": "exactly source-placeholder rows whose original before-image was blank/missing",
        "placeholder_count": len(plan_entries),
        "valid_abstract_candidates_left_untouched": len(valid),
        "article_ids": [row["article_id"] for row in plan_entries],
        "entries": plan_entries,
        "classification_rows_written": 0,
        "full_text_reviewed": 0,
        "database_writes": 0,
    }


def _matches_state(row: sqlite3.Row | None, expected: dict[str, Any],
                   doi: str | None, title: str, openalex_id: str | None,
                   *, source_placeholder: bool) -> bool:
    if row is None or row["is_duplicate"]:
        return False
    if normalize_doi(row["doi"]) != normalize_doi(doi) or not titles_match(row["title"] or "", title):
        return False
    if (openalex_id and not normalize_doi(doi)
            and (row["openalex_id"] or "").rstrip("/").rsplit("/", 1)[-1].upper() != openalex_id.upper()):
        return False
    if source_placeholder:
        return (row["abstract"] == expected.get("abstract")
                and row["abstract_status"] == expected.get("abstract_status")
                and row["data_status"] == expected.get("data_status")
                and row["updated_at"] == expected.get("updated_at"))
    return (row["abstract"] == expected.get("abstract")
            and row["abstract_status"] == expected.get("abstract_status")
            and row["data_status"] == expected.get("data_status")
            and row["updated_at"] == expected.get("updated_at"))


def restore_rows(db_path: Path, plan: dict[str, Any], before_path: Path) -> list[int]:
    entries = plan["entries"]
    now_ids = []
    if not before_path.exists():
        with before_path.open("x", encoding="utf-8") as before_stream:
            for entry in entries:
                before_stream.write(json.dumps({
                    "article_id": entry["article_id"],
                    "candidate_file_sha256": plan["candidate_file_sha256"],
                    "current_placeholder_sha256": entry["placeholder_abstract_sha256"],
                    "restore_to": entry["restore_to"],
                    "source_row": entry["source_row"],
                }, ensure_ascii=False) + "\n")
            before_stream.flush()
            os.fsync(before_stream.fileno())
    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for entry in entries:
            article_id = int(entry["article_id"])
            current = conn.execute(
                "SELECT id,doi,openalex_id,title,abstract,abstract_status,data_status,updated_at,is_duplicate "
                "FROM astar_articles WHERE id=?", (article_id,)
            ).fetchone()
            if not _matches_state(current, entry["current"], entry.get("doi"), entry["title"],
                                  entry.get("openalex_id"), source_placeholder=True):
                raise RuntimeError(f"Live placeholder article changed before repair: {article_id}")
            source = entry["source_row"]
            actual_source = conn.execute(
                "SELECT id,source_name,source_type,raw_id,parser_notes FROM astar_article_sources "
                "WHERE id=? AND article_id=?", (source["id"], article_id)
            ).fetchone()
            if (actual_source is None or actual_source["source_name"] != source["source_name"]
                    or actual_source["source_type"] != source["source_type"]
                    or actual_source["raw_id"] != source["raw_id"]
                    or actual_source["parser_notes"] != source["parser_notes"]
                    or entry["placeholder_abstract_sha256"] not in actual_source["parser_notes"]):
                raise RuntimeError(f"Hash-matched placeholder provenance changed: {article_id}")
            restore = entry["restore_to"]
            update = conn.execute(
                "UPDATE astar_articles SET abstract=?,abstract_status=?,data_status=?,updated_at=? "
                "WHERE id=? AND doi IS ? AND abstract IS ? AND abstract_status=? "
                "AND data_status=? AND updated_at=?",
                (restore.get("abstract"), restore.get("abstract_status"), restore.get("data_status"),
                 restore.get("updated_at"), article_id, entry.get("doi"),
                 entry["current"].get("abstract"), entry["current"].get("abstract_status"),
                 entry["current"].get("data_status"), entry["current"].get("updated_at")),
            )
            if update.rowcount != 1:
                raise RuntimeError(f"Article restoration did not affect exactly one row: {article_id}")
            delete = conn.execute(
                "DELETE FROM astar_article_sources WHERE id=? AND article_id=? AND source_name=? "
                "AND source_type=? AND raw_id=? AND parser_notes=?",
                (source["id"], article_id, source["source_name"], source["source_type"],
                 source["raw_id"], source["parser_notes"]),
            )
            if delete.rowcount != 1:
                raise RuntimeError(f"Placeholder provenance removal did not affect exactly one row: {article_id}")
            now_ids.append(article_id)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return now_ids


def verify_restored(db_path: Path, plan: dict[str, Any]) -> bool:
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    try:
        for entry in plan["entries"]:
            article = conn.execute(
                "SELECT id,doi,openalex_id,title,abstract,abstract_status,data_status,updated_at,is_duplicate "
                "FROM astar_articles WHERE id=?", (entry["article_id"],)
            ).fetchone()
            if (not _matches_state(article, entry["restore_to"], entry.get("doi"), entry["title"],
                                   entry.get("openalex_id"), source_placeholder=False)):
                return False
            if conn.execute("SELECT 1 FROM astar_article_sources WHERE id=? AND article_id=?",
                            (entry["source_row"]["id"], entry["article_id"])).fetchone():
                return False
        return True
    finally:
        conn.rollback()
        conn.close()


def run(args: argparse.Namespace) -> int:
    candidate_file = Path(args.candidate_file).resolve()
    application_dir = Path(args.application_run_dir).resolve()
    db_path = Path(args.db).resolve()
    state_path = Path(args.state_db).resolve()
    data_dir = Path(args.data_dir).resolve()
    run_dir = Path(args.run_dir).resolve()
    candidate_hash = sha256_file(candidate_file)
    if candidate_hash.lower() != args.expected_candidate_sha256.lower():
        raise SystemExit("Candidate file hash differs from expected SHA-256")
    if args.resume:
        if not run_dir.is_dir():
            raise SystemExit("--resume requires an existing repair run directory")
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
        if manifest.get("candidate_file_sha256") != candidate_hash:
            raise SystemExit("Candidate hash differs from repair manifest")
    else:
        if run_dir.exists():
            raise SystemExit(f"Refusing to reuse existing repair directory without --resume: {run_dir}")
        run_dir.mkdir(parents=True)
        plan = build_plan(candidate_file, candidate_hash, application_dir, db_path)
        manifest = {key: plan[key] for key in (
            "created_at_utc", "candidate_file", "candidate_file_sha256",
            "application_run_dir", "database", "restoration_scope", "placeholder_count",
            "valid_abstract_candidates_left_untouched", "database_writes")}
        write_new(run_dir / "manifest.json", manifest)
        write_new(run_dir / "plan.json", plan)
    if not args.apply:
        print(json.dumps({"status": "dry_run", "run_dir": str(run_dir),
                          "placeholder_count": plan["placeholder_count"],
                          "valid_candidates_left_untouched": plan["valid_abstract_candidates_left_untouched"],
                          "database_writes": 0}, ensure_ascii=False))
        return 0

    backup_root = Path(args.semantic_backup_root).resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(backup_root).free < 10 * 2**30 + sum(
            (data_dir / name).stat().st_size for name in VECTOR_NAMES):
        raise OSError("External semantic backup destination has insufficient free space")
    if shutil.disk_usage(data_dir).free < 2 * sum((data_dir / name).stat().st_size for name in VECTOR_NAMES) + 4 * 2**30:
        raise OSError("Active vector drive lacks the required rollback-space margin")
    if shutil.disk_usage(state_path.parent).free < state_path.stat().st_size + 2 * 2**30:
        raise OSError("Entity-state drive lacks the required snapshot-space margin")
    memory = require_encoder_headroom()
    derived_before = check_derived_indexes(db_path, state_path, data_dir, MAX_BATCH_SIZE)
    restoration_receipt = run_dir / "restoration_receipt.json"
    if not restoration_receipt.exists():
        if verify_all_current_placeholders(db_path, plan):
            restore_rows(db_path, plan, run_dir / "repair_before_images.jsonl")
        elif not verify_restored(db_path, plan):
            raise RuntimeError("Live rows are neither the planned placeholders nor their verified pre-images")
        write_new(run_dir / "restoration_receipt.json", {
            "restored_at_utc": utc_now(),
            "candidate_file_sha256": candidate_hash,
            "restored_article_ids": plan["article_ids"],
            "restored_count": plan["placeholder_count"],
            "classification_rows_written": 0,
            "relevance_scores_written": 0,
        })
    if not verify_restored(db_path, plan):
        raise RuntimeError("Restored article values or source provenance did not verify")
    derived_path = run_dir / "derived_refresh_receipt.json"
    if not derived_path.exists():
        derived = refresh_derived(db_path, state_path, data_dir, backup_root, plan["article_ids"])
        write_new(derived_path, {
            "refreshed_at_utc": utc_now(),
            "candidate_file_sha256": candidate_hash,
            "restored_count": plan["placeholder_count"],
            "derived": derived,
            "derived_preflight_before_restore": derived_before,
            "memory_preflight": memory,
            "classification_rows_written": 0,
            "existing_scores_overwritten": 0,
            "full_entity_rebuild": False,
        })
    if not verify_restored(db_path, plan):
        raise RuntimeError("Final restoration readback failed")
    completion = {
        "completed_at_utc": utc_now(),
        "candidate_file_sha256": candidate_hash,
        "placeholder_candidates_restored": plan["placeholder_count"],
        "valid_abstract_candidates_left_untouched": plan["valid_abstract_candidates_left_untouched"],
        "derived_indexes_current": True,
        "classification_rows_written": 0,
        "existing_scores_overwritten": 0,
        "full_entity_rebuild": False,
    }
    completion_path = run_dir / "completion_summary.json"
    if not completion_path.exists():
        write_new(completion_path, completion)
    print(json.dumps({"status": "restoration_complete", "run_dir": str(run_dir), **completion},
                     ensure_ascii=False), flush=True)
    return 0


def verify_all_current_placeholders(db_path: Path, plan: dict[str, Any]) -> bool:
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    try:
        for entry in plan["entries"]:
            row = conn.execute(
                "SELECT id,doi,openalex_id,title,abstract,abstract_status,data_status,updated_at,is_duplicate "
                "FROM astar_articles WHERE id=?", (entry["article_id"],)
            ).fetchone()
            if not _matches_state(row, entry["current"], entry.get("doi"), entry["title"],
                                  entry.get("openalex_id"), source_placeholder=True):
                return False
            source = entry["source_row"]
            found = conn.execute(
                "SELECT 1 FROM astar_article_sources WHERE id=? AND article_id=? AND source_name=? "
                "AND source_type=? AND raw_id=? AND parser_notes=?",
                (source["id"], entry["article_id"], source["source_name"],
                 source["source_type"], source["raw_id"], source["parser_notes"],),
            ).fetchone()
            if found is None:
                return False
        return True
    finally:
        conn.rollback()
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-file", required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--application-run-dir", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--db", type=Path, default=ROOT / "pboc_data.db")
    parser.add_argument("--state-db", type=Path, default=ROOT / "data/business_research_state.db")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--semantic-backup-root", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
