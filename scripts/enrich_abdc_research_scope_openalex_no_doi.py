#!/usr/bin/env python3
"""Stage public OpenAlex abstracts for relevant missing-DOI article records.

The stage selects only the existing frozen Management/Marketing/IS/OB-HR and
project-interest scope, where a local OpenAlex work ID exists. It queries IDs
in batches of at most 100 and writes a resumable staging package. The database
is opened read-only; no full text is requested.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
OPENALEX_URL = "https://api.openalex.org/works"
SOURCE_NAME = "OpenAlex"
SOURCE_TYPE = "openalex_abstract"
FIELDS = "id,doi,title,abstract_inverted_index"
MAX_BATCH_SIZE = 100

sys.path.insert(0, str(ROOT))
from scripts.enrich_abdc_research_scope_abstracts import (  # noqa: E402
    SCOPE_VERSION,
    TARGET_QUERY,
    is_placeholder_abstract,
    normalize_title,
    sha256_file,
    scope_tags,
    titles_match,
    utc_now,
)
from scripts.enrich_abdc_research_scope_openalex import (  # noqa: E402
    OpenAlexBatchError,
    load_openalex_api_key,
    reconstruct_abstract,
    retry_wait,
)


NO_DOI_TARGET_QUERY = TARGET_QUERY.replace(
    "SELECT a.id, a.doi, a.title, a.publisher, a.journal_title,\n"
    "       a.publication_year, a.journal_abdc_rating, c.broad_area,",
    "SELECT a.id, a.doi, a.openalex_id, a.title, a.publisher, a.journal_title,\n"
    "       a.publication_year, a.journal_abdc_rating, c.broad_area,",
).replace(
    "  AND a.doi IS NOT NULL AND trim(a.doi)<>''\n",
    "  AND (a.doi IS NULL OR trim(a.doi)='')\n"
    "  AND a.openalex_id IS NOT NULL AND trim(a.openalex_id)<>''\n"
    "  AND NOT EXISTS (SELECT 1 FROM astar_article_sources sx "
    "      WHERE sx.article_id=a.id AND sx.source_type='openalex_abstract')\n",
)


def normalize_openalex_id(value: str | None) -> str:
    return (value or "").strip().rstrip("/").rsplit("/", 1)[-1].upper()


def read_only_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    return conn


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to replace existing artifact: {path}")
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def target_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_id": int(row["id"]),
        "doi": None,
        "openalex_id": normalize_openalex_id(row.get("openalex_id")),
        "title": row.get("title"),
        "publisher": row.get("publisher"),
        "journal_title": row.get("journal_title"),
        "publication_year": row.get("publication_year"),
        "journal_abdc_rating": row.get("journal_abdc_rating"),
        "broad_area": row.get("broad_area"),
        "scope_tags": scope_tags(row),
    }


def write_target_snapshot(db_path: Path, run_dir: Path) -> dict[str, Any]:
    conn = read_only_db(db_path)
    try:
        plan = [list(row) for row in conn.execute("EXPLAIN QUERY PLAN " + NO_DOI_TARGET_QUERY)]
        plan_text = " ".join(str(item) for row in plan for item in row).lower()
        if ("idx_astar_visible_rating" not in plan_text
                or "idx_src_uniq" not in plan_text
                or "sqlite_autoindex_astar_article_classifications_1" not in plan_text):
            raise RuntimeError("No-DOI target query did not use the expected existing indexes")
        signature = {
            "max_article_id": conn.execute("SELECT max(id) FROM astar_articles").fetchone()[0],
            "article_revision_watermark": conn.execute(
                "SELECT max(updated_at),max(created_at) FROM astar_articles").fetchone(),
            "classification_revision_watermark": conn.execute(
                "SELECT max(classified_at) FROM astar_article_classifications").fetchone()[0],
        }
        signature["article_revision_watermark"] = list(signature["article_revision_watermark"])
        target_path = run_dir / "targets.jsonl"
        count = 0
        bad_id_count = 0
        with target_path.open("x", encoding="utf-8") as output:
            cursor = conn.execute(NO_DOI_TARGET_QUERY)
            while True:
                batch = cursor.fetchmany(5000)
                if not batch:
                    break
                for raw in batch:
                    row = dict(raw)
                    target = target_record(row)
                    if not target["openalex_id"].startswith("W") or not target["openalex_id"][1:].isdigit():
                        bad_id_count += 1
                        continue
                    output.write(json.dumps(target, ensure_ascii=False) + "\n")
                    count += 1
        if count == 0:
            raise SystemExit("No missing-DOI targets with usable OpenAlex IDs were found")
        return {
            "scope_version": SCOPE_VERSION,
            "created_at_utc": utc_now(),
            "database_path": str(db_path),
            "database_read_only": True,
            "database_signature": signature,
            "selection": "same frozen research-interest union; nonduplicate; blank missing abstract; no DOI; OpenAlex work ID present; no prior openalex_abstract provenance",
            "openalex_id_invalid_rows_skipped": bad_id_count,
            "target_count": count,
            "target_file": str(target_path),
            "target_file_sha256": sha256_file(target_path),
            "query_plan": plan,
            "stage_only": True,
            "full_text_requested": False,
        }
    finally:
        conn.rollback()
        conn.close()


def classify_record(target: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    target_id = normalize_openalex_id(target.get("openalex_id"))
    base = {
        "article_id": int(target["article_id"]),
        "doi": None,
        "title": target.get("title"),
        "publisher": target.get("publisher"),
        "journal_title": target.get("journal_title"),
        "broad_area": target.get("broad_area"),
        "scope_tags": target.get("scope_tags", []),
        "checked_at_utc": utc_now(),
        "source": SOURCE_NAME,
        "source_type": SOURCE_TYPE,
        "openalex_id": target_id,
        "identity_method": "openalex_id",
    }
    exact = [record for record in records if normalize_openalex_id(record.get("id")) == target_id]
    if not exact:
        return {**base, "status": "no_match"}
    matches = [record for record in exact
               if titles_match(target.get("title") or "", record.get("title") or record.get("display_name") or "")]
    if not matches:
        record = exact[0]
        return {**base, "status": "title_mismatch",
                "returned_openalex_id": normalize_openalex_id(record.get("id")),
                "returned_doi": record.get("doi"),
                "returned_title": record.get("title") or record.get("display_name")}
    if len(matches) > 1:
        return {**base, "status": "ambiguous_match", "matching_record_count": len(matches)}
    record = matches[0]
    abstract = reconstruct_abstract(record.get("abstract_inverted_index")).strip()
    returned_id = normalize_openalex_id(record.get("id"))
    common = {
        **base,
        "returned_openalex_id": returned_id,
        "returned_doi": record.get("doi"),
        "returned_title": record.get("title") or record.get("display_name") or "",
        "source_url": f"https://openalex.org/{returned_id}",
    }
    if not abstract:
        return {**common, "status": "no_abstract"}
    if is_placeholder_abstract(abstract):
        return {**common, "status": "placeholder_abstract"}
    digest = hashlib.sha256(abstract.encode("utf-8")).hexdigest()
    return {
        **common,
        "status": "abstract_candidate",
        "abstract": abstract,
        "abstract_chars": len(abstract),
        "abstract_sha256": digest,
        "abstract_source_field": "abstract_inverted_index",
    }


def fetch_batch(session: requests.Session, targets: list[dict[str, Any]],
                max_retries: int, connect_timeout: float, read_timeout: float,
                stats: dict[str, Any]) -> list[dict[str, Any]]:
    ids = [normalize_openalex_id(row["openalex_id"]) for row in targets]
    params = {"filter": "openalex:" + "|".join(ids), "per_page": MAX_BATCH_SIZE, "select": FIELDS}
    response: requests.Response | None = None
    for attempt in range(max_retries + 1):
        try:
            response = session.get(OPENALEX_URL, params=params,
                                   timeout=(connect_timeout, read_timeout))
            if response.status_code == 414 and len(targets) > 1:
                middle = len(targets) // 2
                return (fetch_batch(session, targets[:middle], max_retries, connect_timeout, read_timeout, stats)
                        + fetch_batch(session, targets[middle:], max_retries, connect_timeout, read_timeout, stats))
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= max_retries:
                    raise OpenAlexBatchError(
                        f"HTTP {response.status_code} after {attempt + 1} attempts",
                        response.status_code, response.headers.get("Retry-After"), (response.text or "")[:300])
                time.sleep(retry_wait(response, attempt))
                continue
            if response.status_code >= 400:
                raise OpenAlexBatchError(f"Non-retryable HTTP {response.status_code}",
                                         response.status_code, excerpt=(response.text or "")[:300])
            body = response.json()
            records = body.get("results")
            if not isinstance(records, list):
                raise RuntimeError("OpenAlex returned a non-list results field")
            stats["api_calls"] += 1
            try:
                stats["credits_used"] += int(response.headers.get("X-RateLimit-Credits-Used", "0"))
            except (TypeError, ValueError):
                pass
            stats["remaining"] = response.headers.get("X-RateLimit-Remaining")
            count = body.get("meta", {}).get("count")
            if isinstance(count, int) and count > MAX_BATCH_SIZE:
                if len(targets) == 1:
                    raise RuntimeError("One OpenAlex ID returned more than 100 works; refusing truncation")
                middle = len(targets) // 2
                return (fetch_batch(session, targets[:middle], max_retries, connect_timeout, read_timeout, stats)
                        + fetch_batch(session, targets[middle:], max_retries, connect_timeout, read_timeout, stats))
            return records
        except OpenAlexBatchError:
            raise
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            if isinstance(exc, RuntimeError) and "more than 100 works" in str(exc):
                raise
            if attempt >= max_retries:
                raise OpenAlexBatchError(f"Request failed after {attempt + 1} attempts: {type(exc).__name__}") from exc
            time.sleep(retry_wait(response, attempt))
    raise OpenAlexBatchError("OpenAlex ID request exhausted retries")


def read_completed(path: Path) -> set[int]:
    completed: set[int] = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                value = int(json.loads(line)["article_id"])
                if value in completed:
                    raise ValueError(f"Duplicate staged article id {value}")
                completed.add(value)
    return completed


def summarize(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    areas: dict[str, Counter[str]] = defaultdict(Counter)
    candidate_path = run_dir / "abstract_candidates.jsonl"
    candidate_hash = hashlib.sha256()
    with candidate_path.open("x", encoding="utf-8") as candidate_stream:
        with (run_dir / "results.jsonl").open(encoding="utf-8") as results:
            for line in results:
                if not line.strip():
                    continue
                row = json.loads(line)
                counts[row["status"]] += 1
                areas[row.get("broad_area") or "(no broad area)"][row["status"]] += 1
                if row["status"] == "abstract_candidate":
                    encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                    candidate_stream.write(encoded)
                    candidate_hash.update(encoded.encode("utf-8"))
        candidate_stream.flush()
        os.fsync(candidate_stream.fileno())
    return {
        "completed_at_utc": utc_now(),
        "provider": SOURCE_NAME,
        "identity_method": "openalex_id_plus_title",
        "target_count": manifest["target_count"],
        "completed_count": sum(counts.values()),
        "status_counts": dict(counts),
        "abstract_candidate_count": counts["abstract_candidate"],
        "abstract_candidates_file": str(candidate_path),
        "abstract_candidates_file_sha256": sha256_file(candidate_path),
        "abstract_candidates_serialized_sha256": candidate_hash.hexdigest(),
        "by_broad_area": {key: dict(value) for key, value in sorted(areas.items())},
        "target_file_sha256": manifest["target_file_sha256"],
        "results_sha256": sha256_file(run_dir / "results.jsonl"),
        "production_database_writes": 0,
        "full_text_requested": False,
    }


def run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    db_path = Path(args.db).resolve()
    key, key_source = load_openalex_api_key()
    if not key:
        raise SystemExit("OPENALEX_API_KEY is not configured in the environment or D:\\claude\\.secrets")
    if args.resume:
        if not run_dir.is_dir():
            raise SystemExit("--resume requires an existing run directory")
        manifest_path = run_dir / "manifest.json"
        targets_path = run_dir / "targets.jsonl"
        results_path = run_dir / "results.jsonl"
        if not all(path.is_file() for path in (manifest_path, targets_path, results_path)):
            raise SystemExit("Resume package is missing manifest, targets, or results")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("identity_method") != "openalex_id_plus_title":
            raise SystemExit("Run manifest identity method differs")
        if sha256_file(targets_path) != manifest.get("target_file_sha256"):
            raise SystemExit("Target snapshot hash differs from manifest")
    else:
        if run_dir.exists():
            raise SystemExit(f"Refusing to reuse existing output directory without --resume: {run_dir}")
        run_dir.mkdir(parents=True)
        manifest = write_target_snapshot(db_path, run_dir)
        manifest.update({
            "provider": SOURCE_NAME,
            "endpoint": OPENALEX_URL,
            "fields_requested": FIELDS,
            "identity_method": "openalex_id_plus_title",
            "doi_required": False,
            "batch_max": MAX_BATCH_SIZE,
            "stage_only": True,
            "full_text_requested": False,
        })
        with (run_dir / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        (run_dir / "results.jsonl").open("x", encoding="utf-8").close()
        targets_path = run_dir / "targets.jsonl"
        results_path = run_dir / "results.jsonl"

    if manifest.get("database_read_only") is not True or manifest.get("doi_required") is not False:
        raise SystemExit("No-DOI run manifest did not preserve the read-only ID-based scope")
    target_count = int(manifest["target_count"])
    completed = read_completed(results_path)
    if len(completed) > target_count:
        raise SystemExit("Completed result count exceeds target count")
    if len(completed) == target_count:
        if (run_dir / "summary.json").exists():
            raise SystemExit("Stage is already complete; inspect summary.json")
        summary = summarize(run_dir, manifest)
        write_json_atomic(run_dir / "summary.json", summary)
        print(json.dumps({"status": "staging_complete", "run_dir": str(run_dir),
                          "target_count": target_count,
                          "abstract_candidate_count": summary["abstract_candidate_count"],
                          "production_database_writes": 0}, ensure_ascii=False), flush=True)
        return 0

    session = requests.Session()
    session.headers.update({
        "Authorization": "Bearer " + key,
        "User-Agent": "ABDC-Research-Radar/1.0 (public abstract metadata only)",
    })
    stats: dict[str, Any] = {"api_calls": 0, "credits_used": 0, "remaining": None}
    with (run_dir / "stage_runs.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"started_at_utc": utc_now(), "resume": bool(args.resume),
            "batch_size": args.batch_size, "batch_delay_seconds": args.batch_delay,
            "max_batches": args.max_batches, "max_retries": args.max_retries,
            "api_key_source": key_source, "database_writes": 0}, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())

    processed_batches = 0
    with targets_path.open(encoding="utf-8") as target_stream, results_path.open("a", encoding="utf-8") as result_stream:
        while True:
            pending = []
            while len(pending) < args.batch_size:
                line = target_stream.readline()
                if not line:
                    break
                target = json.loads(line)
                if int(target["article_id"]) not in completed:
                    pending.append(target)
            if not pending:
                break
            try:
                records = fetch_batch(session, pending, args.max_retries,
                                      args.connect_timeout, args.read_timeout, stats)
            except Exception as exc:
                failure = {
                    "failed_at_utc": utc_now(),
                    "completed_count": len(completed),
                    "pending_count": len(pending),
                    "first_article_id": pending[0]["article_id"],
                    "last_article_id": pending[-1]["article_id"],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "http_status": getattr(exc, "status_code", None),
                    "retry_after": getattr(exc, "retry_after", None),
                    "database_writes": 0,
                }
                failure_path = run_dir / ("batch_failure_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                                          + "_" + os.urandom(4).hex() + ".json")
                write_json_atomic(failure_path, failure)
                print(json.dumps({"status": "stopped_retryable_batch_failure", **failure,
                                  "run_dir": str(run_dir)}, ensure_ascii=False), flush=True)
                return 2
            by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for record in records:
                by_id[normalize_openalex_id(record.get("id"))].append(record)
            for target in pending:
                result = classify_record(target, by_id.get(normalize_openalex_id(target["openalex_id"]), []))
                result_stream.write(json.dumps(result, ensure_ascii=False) + "\n")
                completed.add(int(target["article_id"]))
            result_stream.flush()
            os.fsync(result_stream.fileno())
            processed_batches += 1
            if processed_batches % 25 == 0:
                progress = {"updated_at_utc": utc_now(), "target_count": target_count,
                            "completed_count": len(completed), "batches_this_run": processed_batches,
                            "api_calls_this_run": stats["api_calls"],
                            "credits_used_this_run": stats["credits_used"],
                            "rate_limit_remaining": stats["remaining"], "database_writes": 0}
                with (run_dir / "progress.jsonl").open("a", encoding="utf-8") as progress_stream:
                    progress_stream.write(json.dumps(progress, ensure_ascii=False) + "\n")
                    progress_stream.flush()
                    os.fsync(progress_stream.fileno())
                print(json.dumps({"status": "staging", "run_dir": str(run_dir), **progress},
                                 ensure_ascii=False), flush=True)
            if args.max_batches and processed_batches >= args.max_batches:
                break
            time.sleep(args.batch_delay)

    if len(completed) == target_count:
        summary = summarize(run_dir, manifest)
        summary.update({"api_calls_this_run": stats["api_calls"],
                        "credits_used_this_run": stats["credits_used"],
                        "last_rate_limit_remaining": stats["remaining"]})
        write_json_atomic(run_dir / "summary.json", summary)
        print(json.dumps({"status": "staging_complete", "run_dir": str(run_dir),
                          "target_count": target_count,
                          "abstract_candidate_count": summary["abstract_candidate_count"],
                          "api_calls_this_run": stats["api_calls"],
                          "credits_used_this_run": stats["credits_used"],
                          "last_rate_limit_remaining": stats["remaining"],
                          "production_database_writes": 0}, ensure_ascii=False), flush=True)
    else:
        progress = {"updated_at_utc": utc_now(), "target_count": target_count,
                    "completed_count": len(completed), "batches_this_run": processed_batches,
                    "api_calls_this_run": stats["api_calls"],
                    "credits_used_this_run": stats["credits_used"],
                    "rate_limit_remaining": stats["remaining"], "database_writes": 0}
        with (run_dir / "progress.jsonl").open("a", encoding="utf-8") as progress_stream:
            progress_stream.write(json.dumps(progress, ensure_ascii=False) + "\n")
            progress_stream.flush()
            os.fsync(progress_stream.fileno())
        print(json.dumps({"status": "staging_paused", "run_dir": str(run_dir), **progress},
                         ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--db", type=Path, default=ROOT / "pboc_data.db")
    parser.add_argument("--batch-size", type=int, default=MAX_BATCH_SIZE)
    parser.add_argument("--batch-delay", type=float, default=0.15)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=40.0)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        raise SystemExit("--batch-size must be 1..100")
    if args.batch_delay < 0.1 or args.max_retries < 0:
        raise SystemExit("Use batch delay >=0.1 and nonnegative retries")
    if args.connect_timeout <= 0 or args.read_timeout <= 0:
        raise SystemExit("Timeouts must be positive")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
