#!/usr/bin/env python3
"""Apply staged, identity-verified abstracts in bounded database/index batches.

The default mode is read-only. With --apply, this command updates only blank,
missing abstract fields for candidates in the supplied private staging file.
Each batch is capped at 2,000 rows, snapshots the exact article before-images,
refreshes only the changed semantic vectors under the existing 2,000-row guard,
and applies the existing candidate-only incremental entity-index updater. It
does not change article classifications, relevance scores, citation counts,
keywords, human review state, the frozen baseline, or full text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.enrich_abdc_research_scope_abstracts import (  # noqa: E402
    is_placeholder_abstract,
    normalize_doi,
    normalize_title,
    sha256_file,
    titles_match,
)
from services.astar_safe_semantic_update import plan_update, update_embeddings  # noqa: E402
from services.astar_semantic_backend import require_encoder_headroom  # noqa: E402
from services import business_research_service as business_research  # noqa: E402
from services.business_index_incremental import update_index  # noqa: E402


MAX_BATCH_SIZE = 2000
VECTOR_NAMES = (
    "astar_emb.npy", "astar_emb_ids.npy", "astar_emb_titleonly_ids.npy",
    "astar_emb_input_hashes.npy", "astar_emb_meta.json",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def provider_identity(candidate: dict[str, Any]) -> tuple[str, str, str, str | None]:
    source_name = candidate.get("source") or "Semantic Scholar"
    if source_name == "Semantic Scholar":
        source_type = "semantic_scholar"
        raw_id = candidate.get("paper_id")
        source_url = candidate.get("source_url") or (
            f"https://www.semanticscholar.org/paper/{raw_id}" if raw_id else None
        )
    elif source_name == "OpenAlex":
        source_type = "openalex_abstract"
        raw_id = candidate.get("openalex_id")
        source_url = candidate.get("source_url") or (
            f"https://openalex.org/{raw_id}" if raw_id else None
        )
    elif source_name == "Journal of Australian Taxation":
        source_type = candidate.get("source_type") or "publisher_abstract_document"
        raw_id = candidate.get("source_record_id")
        source_url = candidate.get("source_url")
        if (source_type not in ("publisher_abstract_document", "publisher_web_abstract")
                or not raw_id or not source_url or "journalofaustraliantax.com.au/" not in source_url):
            raise ValueError("Journal of Australian Taxation candidate lacks its public page/PDF identity")
    elif source_name == "University of Washington School of Law repository":
        source_type = "institutional_repository_abstract"
        raw_id = candidate.get("source_record_id")
        source_url = candidate.get("source_url")
        if not raw_id or not source_url or "digitalcommons.law.uw.edu/faculty-articles/" not in source_url:
            raise ValueError("University of Washington repository candidate lacks its public record identity")
    elif source_name == "University of Technology Sydney Open Publications":
        source_type = "institutional_repository_abstract"
        raw_id = candidate.get("source_record_id")
        source_url = candidate.get("source_url")
        if not raw_id or not source_url or "opus.lib.uts.edu.au/handle/10453/16002" not in source_url:
            raise ValueError("UTS repository candidate lacks its public record identity")
    elif source_name == "SSRN author repository":
        source_type = "author_manuscript_abstract"
        raw_id = candidate.get("source_record_id")
        source_url = candidate.get("source_url")
        if not raw_id or not source_url or "papers.ssrn.com/sol3/papers.cfm?abstract_id=" not in source_url:
            raise ValueError("SSRN author manuscript candidate lacks its stable paper identity")
    elif source_name == "Stanford Law School publisher version":
        source_type = "publisher_abstract_document"
        raw_id = candidate.get("source_record_id")
        source_url = candidate.get("source_url")
        if not raw_id or not source_url or "law.stanford.edu/wp-content/uploads/" not in source_url:
            raise ValueError("Stanford publisher-version candidate lacks its public PDF identity")
    elif source_name == "Private Law Theory abstract index":
        source_type = "secondary_abstract_index"
        raw_id = candidate.get("source_record_id")
        source_url = candidate.get("source_url")
        if not raw_id or not source_url or "private-law-theory.org/2025/08/14/michael-ilg-rage-against-the-machine" not in source_url:
            raise ValueError("Private Law Theory candidate lacks its identified abstract-index page")
    elif source_name == "SSRN author repository":
        source_type = "author_manuscript_abstract"
        raw_id = candidate.get("source_record_id")
        source_url = candidate.get("source_url")
        if not raw_id or not source_url or "papers.ssrn.com/sol3/papers.cfm?abstract_id=" not in source_url:
            raise ValueError("SSRN author manuscript candidate lacks its stable paper identity")
    elif source_name == "Stanford Law School publisher version":
        source_type = "publisher_abstract_document"
        raw_id = candidate.get("source_record_id")
        source_url = candidate.get("source_url")
        if not raw_id or not source_url or "law.stanford.edu/wp-content/uploads/" not in source_url:
            raise ValueError("Stanford publisher-version candidate lacks its public PDF identity")
    else:
        raise ValueError(f"Unsupported abstract provenance source: {source_name}")
    declared_type = candidate.get("source_type")
    if declared_type and declared_type != source_type:
        raise ValueError(f"Source type does not match provider {source_name}")
    raw_id = str(raw_id or candidate["doi"])
    return source_name, source_type, raw_id, source_url


def title_journal_year_match(candidate: dict[str, Any], *, returned_title: str | None,
                             returned_journal: str | None, returned_year: Any) -> bool:
    target_year = candidate.get("publication_year")
    target_journal = (candidate.get("journal_title") or "").replace("&", "and")
    source_journal = (returned_journal or "").replace("&", "and")
    return bool(
        normalize_title(candidate.get("title"))
        and normalize_title(candidate.get("title")) == normalize_title(returned_title)
        and normalize_title(target_journal)
        and normalize_title(target_journal) == normalize_title(source_journal)
        and target_year is not None
        and str(target_year) == str(returned_year)
    )


def no_doi_identity_matches(article: dict[str, Any], candidate: dict[str, Any]) -> bool:
    method = candidate.get("identity_method")
    if method == "openalex_id":
        return normalize_openalex_id(article.get("openalex_id")) == normalize_openalex_id(
            candidate.get("openalex_id"))
    if method == "title_journal_year":
        return (not article.get("openalex_id") and not article.get("semantic_scholar_id")
                and title_journal_year_match(
                    candidate,
                    returned_title=article.get("title"),
                    returned_journal=article.get("journal_title"),
                    returned_year=article.get("publication_year"),
                ))
    return False


def normalize_openalex_id(value: str | None) -> str:
    return (value or "").strip().rstrip("/").rsplit("/", 1)[-1].upper()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") != "abstract_candidate":
                raise ValueError(f"Noncandidate row at {path}:{line_number}")
            provider_identity(row)
            article_id = int(row["article_id"])
            if article_id in seen:
                raise ValueError(f"Duplicate article_id {article_id} in candidate file")
            seen.add(article_id)
            abstract = row.get("abstract")
            if not isinstance(abstract, str) or not abstract.strip():
                raise ValueError(f"Candidate {article_id} has no nonempty abstract")
            if is_placeholder_abstract(abstract):
                raise ValueError(f"Candidate {article_id} abstract is a source placeholder, not an abstract")
            if hashlib.sha256(abstract.encode("utf-8")).hexdigest() != row.get("abstract_sha256"):
                raise ValueError(f"Candidate {article_id} abstract hash mismatch")
            if normalize_doi(row.get("doi")):
                if normalize_doi(row.get("doi")) != normalize_doi(row.get("returned_doi")):
                    raise ValueError(f"Candidate {article_id} DOI identity mismatch")
            elif row.get("identity_method") == "openalex_id":
                if (row.get("source") != "OpenAlex"
                        or normalize_openalex_id(row.get("openalex_id")) != normalize_openalex_id(
                            row.get("returned_openalex_id"))):
                    raise ValueError(f"Candidate {article_id} OpenAlex ID identity mismatch")
            elif row.get("identity_method") == "title_journal_year":
                if not title_journal_year_match(
                        row, returned_title=row.get("returned_title"),
                        returned_journal=row.get("returned_journal_title"),
                        returned_year=row.get("returned_publication_year")):
                    raise ValueError(f"Candidate {article_id} title/journal/year identity mismatch")
                if row.get("source") == "OpenAlex":
                    if normalize_openalex_id(row.get("openalex_id")) != normalize_openalex_id(
                            row.get("returned_openalex_id")):
                        raise ValueError(f"Candidate {article_id} OpenAlex work ID mismatch")
                elif row.get("source") in (
                        "Journal of Australian Taxation",
                        "University of Washington School of Law repository",
                        "University of Technology Sydney Open Publications",
                        "SSRN author repository",
                        "Stanford Law School publisher version",
                        "Private Law Theory abstract index"):
                    provider_identity(row)
                else:
                    raise ValueError(f"Candidate {article_id} has unsupported no-DOI provenance")
            else:
                raise ValueError(f"Candidate {article_id} lacks verified no-DOI identity")
            if not titles_match(row.get("title") or "", row.get("returned_title") or ""):
                raise ValueError(f"Candidate {article_id} title identity mismatch")
            rows.append(row)
    return rows


def load_completed_ids(path: Path) -> set[int]:
    completed: set[int] = set()
    if not path.exists():
        return completed
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                completed.update(int(value) for value in json.loads(line)["article_ids"])
    return completed


def load_before_image_ids(path: Path) -> set[int]:
    present: set[int] = set()
    if not path.exists():
        return present
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                present.add(int(json.loads(line)["article_id"]))
    return present


def stratified_order(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    field_order = ["Management / Strategy", "Marketing", "Information Systems", "OB / HR"]
    buckets: dict[str, list[dict[str, Any]]] = {name: [] for name in field_order}
    buckets["Personal-interest topics"] = []
    for row in candidates:
        area = row.get("broad_area")
        bucket = area if area in field_order else "Personal-interest topics"
        buckets[bucket].append(row)
    for rows in buckets.values():
        rows.sort(key=lambda row: int(row["article_id"]))
    ordered = []
    while any(buckets.values()):
        for name in (*field_order, "Personal-interest topics"):
            if buckets[name]:
                ordered.append(buckets[name].pop(0))
    return ordered


def _chunks(items: list[int], size: int = 400):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def current_rows(db_path: Path, state_path: Path, candidates: list[dict[str, Any]]) -> tuple[dict[int, dict], dict[int, str]]:
    ids = [int(row["article_id"]) for row in candidates]
    articles: dict[int, dict] = {}
    provider_sources: dict[int, set[tuple[str, str]]] = {}
    reviewed_assertions: set[int] = set()
    providers = sorted({provider_identity(row)[:2] for row in candidates})

    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    try:
        for part in _chunks(ids):
            marks = ",".join("?" for _ in part)
            for row in conn.execute(
                "SELECT id,doi,openalex_id,semantic_scholar_id,title,journal_title,publication_year,"
                "abstract,abstract_status,data_status,updated_at,is_duplicate "
                "FROM astar_articles WHERE id IN (" + marks + ")", part
            ):
                articles[int(row["id"])] = dict(row)
            for source_name, source_type in providers:
                for row in conn.execute(
                    "SELECT DISTINCT article_id FROM astar_article_sources "
                    "WHERE source_name=? AND source_type=? AND article_id IN (" + marks + ")",
                    (source_name, source_type, *part),
                ):
                    provider_sources.setdefault(int(row[0]), set()).add((source_name, source_type))
    finally:
        conn.rollback()
        conn.close()

    state = sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
    state.execute("PRAGMA query_only=ON")
    state.execute("BEGIN")
    try:
        for part in _chunks(ids):
            marks = ",".join("?" for _ in part)
            reviewed_assertions.update(int(row[0]) for row in state.execute(
                "SELECT DISTINCT paper_id FROM research_entity_assertions "
                "WHERE paper_id IN (" + marks + ") "
                "AND (verification_status<>'CANDIDATE' OR reviewed_at IS NOT NULL)", part
            ))
    finally:
        state.rollback()
        state.close()

    state_by_id = {}
    candidate_by_id = {int(row["article_id"]): row for row in candidates}
    for article_id in ids:
        candidate = candidate_by_id[article_id]
        source_name, source_type, _raw_id, _source_url = provider_identity(candidate)
        source_present = (source_name, source_type) in provider_sources.get(article_id, set())
        row = articles.get(article_id)
        if row is None:
            state_by_id[article_id] = "article_missing"
        elif row["is_duplicate"]:
            state_by_id[article_id] = "duplicate"
        elif normalize_doi(row.get("doi")) != normalize_doi(candidate.get("doi")):
            state_by_id[article_id] = "doi_changed"
        elif not normalize_doi(candidate.get("doi")) and not no_doi_identity_matches(row, candidate):
            state_by_id[article_id] = (
                "openalex_id_changed" if candidate.get("identity_method") == "openalex_id"
                else "title_journal_year_changed" if candidate.get("identity_method") == "title_journal_year"
                else "no_doi_identity_method"
            )
        elif not titles_match(row.get("title") or "", candidate.get("title") or ""):
            state_by_id[article_id] = "title_changed"
        elif article_id in reviewed_assertions:
            state_by_id[article_id] = "reviewed_entity_assertion"
        elif row.get("abstract") and row["abstract"].strip():
            same = hashlib.sha256(row["abstract"].encode("utf-8")).hexdigest() == candidate["abstract_sha256"]
            if same and row.get("abstract_status") == "available" and source_present:
                state_by_id[article_id] = "already_applied"
            else:
                state_by_id[article_id] = "existing_abstract_conflict"
        elif row.get("abstract_status") != "missing":
            state_by_id[article_id] = "abstract_status_conflict"
        elif source_present:
            state_by_id[article_id] = "provider_source_already_exists"
        else:
            state_by_id[article_id] = "eligible"
    return articles, state_by_id


def fingerprint_summary(data_dir: Path) -> dict[str, Any]:
    metadata = json.loads((data_dir / "astar_emb_meta.json").read_text(encoding="utf-8"))
    assets = {name: (data_dir / name).stat().st_size for name in VECTOR_NAMES}
    return {"generation": metadata.get("generation"), "count": metadata.get("count"),
            "asset_bytes": assets, "total_asset_bytes": sum(assets.values())}


def check_derived_indexes(db_path: Path, state_path: Path, data_dir: Path,
                          max_changed: int) -> dict[str, Any]:
    vector = plan_update(db_path, data_dir, max_delta_rows=max_changed)
    try:
        vector_delta = [int(row["id"]) for row in vector["delta"]]
        vector_summary = {"delta_rows": len(vector_delta), "total": len(vector["ids"]),
                          "source_signature": vector["source_signature"]}
    finally:
        vector["conn"].close()
    entity = update_index(business_research, db_path, state_path, apply=False,
                          max_changed=max_changed)
    entity_summary = {key: entity.get(key) for key in (
        "mode", "affected_papers", "removed_inputs", "source_signature", "full_entity_rebuild",
        "database_written") if key in entity}
    if vector_summary["delta_rows"] != 0:
        raise RuntimeError(f"Pre-existing semantic delta must be resolved first: {vector_summary['delta_rows']}")
    if entity.get("affected_papers") != 0 or entity.get("mode") != "delta":
        raise RuntimeError("Entity index is not at a clean accepted incremental baseline")
    return {"semantic": vector_summary, "entity": entity_summary}


def _write_before_images(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def apply_article_batch(db_path: Path, state_path: Path, batch: list[dict[str, Any]],
                        before_path: Path, candidate_sha: str) -> list[int]:
    ids = [int(row["article_id"]) for row in batch]
    if not ids:
        return []
    current, state_by_id = current_rows(db_path, state_path, batch)
    eligible = [row for row in batch if state_by_id[int(row["article_id"])] == "eligible"]
    if len(eligible) != len(batch):
        raise RuntimeError("Batch eligibility changed during staging; re-plan before writing")
    now = utc_now()
    before = []
    for candidate in eligible:
        row = current[int(candidate["article_id"])]
        before.append({"article_id": row["id"], "doi": row["doi"], "title": row["title"],
                       "abstract": row["abstract"], "abstract_status": row["abstract_status"],
                       "data_status": row["data_status"], "updated_at": row["updated_at"],
                       "candidate_sha256": candidate_sha, "captured_at_utc": now})
    _write_before_images(before_path, before)

    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("BEGIN IMMEDIATE")
    changed = []
    try:
        for candidate in eligible:
            article_id = int(candidate["article_id"])
            row = conn.execute(
                "SELECT id,doi,openalex_id,semantic_scholar_id,title,journal_title,publication_year,"
                "abstract,abstract_status,is_duplicate FROM astar_articles WHERE id=?",
                (article_id,),
            ).fetchone()
            if (row is None or row["is_duplicate"] or row["abstract_status"] != "missing"
                    or (row["abstract"] or "").strip()
                    or normalize_doi(row["doi"]) != normalize_doi(candidate["doi"])
                    or (not normalize_doi(candidate.get("doi")) and (
                        (candidate.get("identity_method") == "openalex_id"
                         and normalize_openalex_id(row["openalex_id"]) != normalize_openalex_id(
                             candidate.get("openalex_id")))
                        or (candidate.get("identity_method") == "title_journal_year"
                            and (row["openalex_id"] or row["semantic_scholar_id"]
                                 or not title_journal_year_match(candidate,
                                     returned_title=row["title"],
                                     returned_journal=row["journal_title"],
                                     returned_year=row["publication_year"])))
                        or candidate.get("identity_method") not in ("openalex_id", "title_journal_year")
                    ))
                    or not titles_match(row["title"] or "", candidate["title"] or "")):
                raise RuntimeError(f"Article {article_id} changed after its before-image was saved")
            source_name, source_type, raw_id, source_url = provider_identity(candidate)
            if conn.execute("SELECT 1 FROM astar_article_sources WHERE article_id=? "
                            "AND source_type=? AND raw_id=? LIMIT 1",
                            (article_id, source_type, raw_id)).fetchone():
                raise RuntimeError(f"Article {article_id} already has this provider source record")
            cur = conn.execute(
                "UPDATE astar_articles SET abstract=?,abstract_status='available',"
                "data_status='api_metadata',updated_at=? WHERE id=? AND is_duplicate=0 "
                "AND abstract_status='missing' AND (abstract IS NULL OR trim(abstract)='') AND doi IS ?",
                (candidate["abstract"], now, article_id, row["doi"]),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"Article {article_id} abstract update did not affect exactly one row")
            note = ("abstract=filled; DOI/title verified; source=" + source_name
                    + "; sha256=" + candidate["abstract_sha256"])
            conn.execute("""INSERT INTO astar_article_sources
                (article_id,source_name,source_type,source_url,raw_id,raw_json,fetched_at,parser_notes)
                VALUES (?,?,?,?,?,?,?,?)""",
                (article_id, source_name, source_type, source_url,
                 raw_id, None, candidate.get("checked_at_utc") or now, note))
            readback = conn.execute(
                "SELECT abstract,abstract_status,data_status FROM astar_articles WHERE id=?", (article_id,)
            ).fetchone()
            if (hashlib.sha256(readback["abstract"].encode("utf-8")).hexdigest() != candidate["abstract_sha256"]
                    or readback["abstract_status"] != "available"
                    or readback["data_status"] != "api_metadata"):
                raise RuntimeError(f"Article {article_id} abstract readback failed")
            changed.append(article_id)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return changed


def refresh_derived(db_path: Path, state_path: Path, data_dir: Path, backup_root: Path,
                    changed_ids: list[int]) -> dict[str, Any]:
    maximum = MAX_BATCH_SIZE
    expected = set(int(value) for value in changed_ids)
    vector_plan = plan_update(db_path, data_dir, max_delta_rows=maximum)
    try:
        vector_delta_ids = {int(row["id"]) for row in vector_plan["delta"]}
    finally:
        vector_plan["conn"].close()
    if not vector_delta_ids.issubset(expected):
        raise RuntimeError("Semantic delta includes rows outside the abstract batch")
    if vector_delta_ids:
        vector = update_embeddings(db_path, data_dir, apply=True,
                                   max_delta_rows=maximum, backup_root=backup_root)
        if (not vector.get("success") or vector.get("delta_rows") != len(vector_delta_ids)
                or vector.get("refreshed") != len(vector_delta_ids)
                or vector.get("scored_new") != 0
                or vector.get("baseline_rows_touched") != 0
                or vector.get("existing_score_values_overwritten") != 0):
            raise RuntimeError("Safe semantic delta did not match the staged abstract inputs")
    else:
        vector = {"success": True, "delta_rows": 0, "refreshed": 0, "scored_new": 0,
                  "baseline_rows_touched": 0, "existing_score_values_overwritten": 0,
                  "already_current": True}

    entity_plan = update_index(business_research, db_path, state_path,
                               apply=False, max_changed=maximum)
    entity_affected = int(entity_plan.get("affected_papers") or 0)
    if entity_affected > len(expected):
        raise RuntimeError("Entity-index delta includes more papers than the abstract batch")
    if entity_affected:
        entity = update_index(business_research, db_path, state_path,
                              apply=True, max_changed=maximum)
        plan_path = Path(entity["run_dir"]) / "plan.json"
        stored_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        entity_ids = set(int(value) for value in stored_plan.get("affected_ids", []))
        if not entity_ids.issubset(expected):
            raise RuntimeError("Entity-index plan includes a paper outside the abstract batch")
    else:
        entity = {"success": True, "applied": False, "affected_papers": 0,
                  "full_entity_rebuild": False, "human_state_written": 0,
                  "reviewed_assertions_written": 0, "source_records_written": 0,
                  "already_current": True}
    if (not entity.get("success") or entity.get("full_entity_rebuild") is not False
            or entity.get("human_state_written") != 0
            or entity.get("reviewed_assertions_written") != 0):
        raise RuntimeError("Incremental entity delta did not preserve the reviewed-state boundary")
    return {
        "semantic": {key: vector.get(key) for key in (
            "delta_rows", "refreshed", "scored_new", "baseline_rows_touched",
            "existing_score_values_overwritten", "run_dir", "backup_dir")},
        "entity": {key: entity.get(key) for key in (
            "affected_papers", "inserted_assertions", "updated_assertions", "deleted_assertions",
            "full_entity_rebuild", "source_records_written", "human_state_written",
            "reviewed_assertions_written", "run_dir")},
    }


def run(args: argparse.Namespace) -> int:
    candidate_file = Path(args.candidate_file).resolve()
    candidate_hash = sha256_file(candidate_file)
    if candidate_hash.lower() != args.expected_candidate_sha256.lower():
        raise SystemExit("Candidate file SHA-256 does not match --expected-candidate-sha256")
    candidates = stratified_order(read_jsonl(candidate_file))
    db_path = Path(args.db).resolve()
    state_path = Path(args.state_db).resolve()
    data_dir = Path(args.data_dir).resolve()
    run_dir = Path(args.run_dir).resolve()
    if args.resume:
        if not run_dir.is_dir():
            raise SystemExit("--resume requires an existing application run directory")
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            raise SystemExit("Application run directory has no manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("candidate_file_sha256") != candidate_hash:
            raise SystemExit("Candidate SHA-256 differs from the frozen application manifest")
    else:
        if run_dir.exists():
            raise SystemExit(f"Refusing to reuse existing application directory without --resume: {run_dir}")
        run_dir.mkdir(parents=True)
        manifest = {
            "created_at_utc": utc_now(), "candidate_file": str(candidate_file),
            "candidate_file_sha256": candidate_hash, "candidate_count": len(candidates),
            "database": str(db_path), "state_database": str(state_path),
            "batch_size": args.batch_size, "max_delta_rows": args.batch_size,
            "abstract_only_fields_written": ["abstract", "abstract_status", "data_status", "updated_at"],
            "classification_rows_written": 0, "score_rows_written": 0,
            "full_text_reviewed": False,
        }
        with (run_dir / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        for name in ("before_images.jsonl", "skipped_candidates.jsonl", "completed_batches.jsonl"):
            (run_dir / name).open("x", encoding="utf-8").close()

    before_path = run_dir / "before_images.jsonl"
    skipped_path = run_dir / "skipped_candidates.jsonl"
    completed_path = run_dir / "completed_batches.jsonl"
    completed_ids = load_completed_ids(completed_path)
    current, statuses = current_rows(db_path, state_path, candidates)
    already_applied = [row for row in candidates if int(row["article_id"]) not in completed_ids
                       and statuses[int(row["article_id"])] == "already_applied"]
    if len(already_applied) > args.batch_size:
        raise RuntimeError("Unfinished abstract batch exceeds the 2,000-row derived-update guard")

    skipped_ids: set[int] = set()
    if skipped_path.exists():
        with skipped_path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    skipped_ids.add(int(json.loads(line)["article_id"]))
    new_skips = [row for row in candidates
                 if int(row["article_id"]) not in completed_ids
                 and int(row["article_id"]) not in skipped_ids
                 and statuses[int(row["article_id"])] not in ("eligible", "already_applied")]
    if new_skips:
        with skipped_path.open("a", encoding="utf-8") as stream:
            for row in new_skips:
                article_id = int(row["article_id"])
                stream.write(json.dumps({"article_id": article_id, "doi": row["doi"],
                    "status": statuses[article_id], "candidate_file_sha256": candidate_hash,
                    "recorded_at_utc": utc_now()}, ensure_ascii=False) + "\n")
                skipped_ids.add(article_id)
            stream.flush()
            os.fsync(stream.fileno())

    if not args.apply:
        plan = Counter(statuses[row["article_id"]] for row in candidates
                       if row["article_id"] not in completed_ids)
        derived = check_derived_indexes(db_path, state_path, data_dir, args.batch_size)
        report = {"checked_at_utc": utc_now(), "candidate_count": len(candidates),
                  "candidate_file_sha256": candidate_hash, "state_counts": dict(plan),
                  "already_completed": len(completed_ids), "unfinished_applied_rows": len(already_applied),
                  "derived_indexes": derived, "production_database_writes": 0}
        plan_path = run_dir / "plan.json"
        if plan_path.exists():
            raise SystemExit(f"Plan already exists; inspect it instead of overwriting: {plan_path}")
        with plan_path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps(report, ensure_ascii=False))
        return 0

    if not run_dir.joinpath("manifest.json").exists():
        raise SystemExit("Application manifest is missing")
    backup_root = Path(args.semantic_backup_root).resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    eligible_count = sum(1 for row in candidates
                         if int(row["article_id"]) not in completed_ids
                         and statuses[int(row["article_id"])] == "eligible")
    pending_count = len(already_applied)
    asset_bytes = sum((data_dir / name).stat().st_size for name in VECTOR_NAMES)
    vector_batches = (eligible_count + pending_count + args.batch_size - 1) // args.batch_size
    needed_backup_bytes = vector_batches * asset_bytes + 10 * 2**30
    if shutil.disk_usage(backup_root).free < needed_backup_bytes:
        raise OSError(f"External vector backup destination needs {needed_backup_bytes} free bytes")
    if shutil.disk_usage(data_dir).free < 2 * asset_bytes + 4 * 2**30:
        raise OSError("Active vector drive needs candidate/rollback space and a 4 GiB free-space margin")
    state_size = state_path.stat().st_size
    if shutil.disk_usage(state_path.parent).free < state_size + 2 * 2**30:
        raise OSError("Entity-state drive needs a migration snapshot and a 2 GiB free-space margin")
    memory = require_encoder_headroom()
    derived_preflight = check_derived_indexes(db_path, state_path, data_dir, args.batch_size)
    apply_preflight = {
        "checked_at_utc": utc_now(), "candidate_file_sha256": candidate_hash,
        "candidate_count": len(candidates), "eligible_count": eligible_count,
        "unfinished_abstract_refresh_count": pending_count,
        "batch_size_max": args.batch_size, "semantic_batches_estimate": vector_batches,
        "active_semantic_asset_bytes": asset_bytes,
        "external_before_image_bytes_estimate": vector_batches * asset_bytes,
        "memory_headroom": memory,
        "d_free_bytes": shutil.disk_usage(data_dir).free,
        "d_minimum_free_bytes_for_one_activation": 2 * asset_bytes + 4 * 2**30,
        "entity_state_size_bytes": state_size,
        "entity_state_minimum_free_bytes": state_size + 2 * 2**30,
        "e_backup_free_bytes": shutil.disk_usage(backup_root).free,
        "e_backup_estimate_with_margin_bytes": needed_backup_bytes,
        "derived_index_preflight": derived_preflight,
        "production_database_writes": 0,
    }
    apply_preflight_path = run_dir / ("apply_preflight_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    with apply_preflight_path.open("x", encoding="utf-8") as stream:
        json.dump(apply_preflight, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    plan_path = run_dir / "plan.json"
    if not plan_path.exists():
        plan_report = {
            "created_at_utc": utc_now(), "candidate_file_sha256": candidate_hash,
            "candidate_count": len(candidates), "eligible_count": eligible_count,
            "pending_derived_refresh_count": pending_count,
            "held_or_conflicting_count": len(candidates) - len(completed_ids) - eligible_count - pending_count,
            "batch_size_max": args.batch_size, "vector_batches_estimate": vector_batches,
            "semantic_asset_bytes": asset_bytes, "external_vector_backup_bytes_estimate": needed_backup_bytes,
            "d_drive_free_bytes": shutil.disk_usage(data_dir).free,
            "e_backup_free_bytes": shutil.disk_usage(backup_root).free,
            "derived_preflight": derived_preflight,
            "classification_rows_written": 0, "existing_score_values_overwritten": 0,
            "full_corpus_reembedded": False,
        }
        with plan_path.open("x", encoding="utf-8") as stream:
            json.dump(plan_report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")

    # Finish any batch whose article writes committed before an interrupted
    # semantic/entity activation. The candidate contents are hash-bound above.
    with completed_path.open(encoding="utf-8") as stream:
        batch_number = sum(1 for line in stream if line.strip()) + 1
    if already_applied:
        derived = refresh_derived(db_path, state_path, data_dir, backup_root,
                                  [int(row["article_id"]) for row in already_applied])
        receipt = {"completed_at_utc": utc_now(), "batch_number": batch_number,
                   "article_ids": [int(row["article_id"]) for row in already_applied],
                   "applied_abstracts": 0, "recovered_pending_abstracts": len(already_applied),
                   **derived}
        with completed_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        completed_ids.update(receipt["article_ids"])

    new_batches = 0
    while True:
        current, statuses = current_rows(db_path, state_path, candidates)
        remaining = [row for row in candidates
                     if int(row["article_id"]) not in completed_ids
                     and int(row["article_id"]) not in skipped_ids
                     and statuses[int(row["article_id"])] == "eligible"]
        if not remaining:
            break
        batch = remaining[:args.batch_size]

        # Keep the requested fields balanced at the start of the run.
        changed_ids = apply_article_batch(db_path, state_path, batch, before_path, candidate_hash)
        if not changed_ids:
            break
        try:
            derived = refresh_derived(db_path, state_path, data_dir, backup_root, changed_ids)
        except BaseException as exc:
            pending_path = run_dir / ("pending_batch_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
            with pending_path.open("x", encoding="utf-8") as stream:
                json.dump({"at_utc": utc_now(), "article_ids": changed_ids,
                           "candidate_file_sha256": candidate_hash,
                           "error_type": type(exc).__name__, "error": str(exc),
                           "abstract_rows_committed": True, "derived_refresh_pending": True},
                          stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            raise
        receipt = {"completed_at_utc": utc_now(), "batch_number": batch_number,
                   "article_ids": changed_ids, "applied_abstracts": len(changed_ids), **derived}
        with completed_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        completed_ids.update(changed_ids)
        batch_number += 1
        new_batches += 1
        progress = {"updated_at_utc": utc_now(), "completed_abstracts": len(completed_ids),
                    "candidate_count": len(candidates), "completed_batches": batch_number - 1,
                    "remaining_eligible": max(0, len(remaining) - len(changed_ids)),
                    "production_database_writes": len(completed_ids)}
        progress_tmp = run_dir / ("progress." + uuid.uuid4().hex + ".tmp")
        with progress_tmp.open("x", encoding="utf-8") as stream:
            json.dump(progress, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(progress_tmp, run_dir / "progress.json")
        print(json.dumps({"status": "batch_complete", **progress,
                          "last_batch_abstracts": len(changed_ids),
                          "semantic_run_dir": derived["semantic"].get("run_dir"),
                          "entity_run_dir": derived["entity"].get("run_dir")}, ensure_ascii=False), flush=True)
        if args.max_batches and new_batches >= args.max_batches:
            break

    if not args.max_batches or new_batches < args.max_batches:
        final = {"completed_at_utc": utc_now(), "candidate_file_sha256": candidate_hash,
                 "candidate_count": len(candidates), "completed_abstracts": len(completed_ids),
                 "remaining_eligible": sum(1 for row in candidates
                     if int(row["article_id"]) not in completed_ids
                     and statuses.get(int(row["article_id"])) == "eligible"),
                 "skipped_or_held": sum(1 for row in candidates
                     if statuses.get(int(row["article_id"])) not in ("eligible", "already_applied")),
                 "classification_rows_written": 0, "existing_scores_overwritten": 0,
                 "full_entity_rebuild": False}
        final_path = run_dir / "completion_summary.json"
        if not final_path.exists():
            with final_path.open("x", encoding="utf-8") as stream:
                json.dump(final, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        print(json.dumps(final, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-file", required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--db", type=Path, default=ROOT / "pboc_data.db")
    parser.add_argument("--state-db", type=Path, default=ROOT / "data/business_research_state.db")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--semantic-backup-root", required=True)
    parser.add_argument("--batch-size", type=int, default=MAX_BATCH_SIZE)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        raise SystemExit(f"--batch-size must be 1..{MAX_BATCH_SIZE}; semantic guard is 2,000")
    if args.max_batches is not None and args.max_batches < 1:
        raise SystemExit("--max-batches must be positive")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
