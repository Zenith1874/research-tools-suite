#!/usr/bin/env python3
"""Stage DOI/title-verified OpenAlex abstracts for a frozen ABDC interest scope.

Reads an existing Semantic Scholar research-scope snapshot, queries OpenAlex in
bounded DOI batches, reconstructs only OpenAlex's abstract inverted index, and
writes a resumable staging package. It never writes to the research database or
requests article full text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
OPENALEX_URL = "https://api.openalex.org/works"
MAX_BATCH_SIZE = 100
SOURCE_NAME = "OpenAlex"
SOURCE_TYPE = "openalex_abstract"
FIELDS = "id,doi,title,abstract_inverted_index"

sys.path.insert(0, str(ROOT))
from scripts.enrich_abdc_research_scope_abstracts import (  # noqa: E402
    normalize_doi,
    is_placeholder_abstract,
    sha256_file,
    titles_match,
    utc_now,
)


class OpenAlexBatchError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None,
                 retry_after: str | None = None, excerpt: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.excerpt = excerpt


def load_openalex_api_key(env: dict[str, str] | None = None,
                          secrets_path: Path | None = None) -> tuple[str | None, str]:
    """Read only the named local key; callers must never log its value."""
    env = os.environ if env is None else env
    if env.get("OPENALEX_API_KEY", "").strip():
        return env["OPENALEX_API_KEY"].strip(), "environment:OPENALEX_API_KEY"
    path = secrets_path or (ROOT / ".secrets")
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                if key.strip() == "OPENALEX_API_KEY" and value.strip():
                    return value.strip(), "local_secrets:OPENALEX_API_KEY"
    except OSError:
        pass
    return None, "none"


def reconstruct_abstract(index: Any) -> str:
    """Rebuild OpenAlex's abstract index without adding or inferring words."""
    if not isinstance(index, dict):
        return ""
    words: dict[int, str] = {}
    for token, positions in index.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and not isinstance(position, bool) and position >= 0:
                words.setdefault(position, token)
    if not words:
        return ""
    return " ".join(words[position] for position in sorted(words))


def classify_record(target: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    base = {
        "article_id": int(target["article_id"]),
        "doi": target["doi"],
        "title": target.get("title"),
        "publisher": target.get("publisher"),
        "journal_title": target.get("journal_title"),
        "broad_area": target.get("broad_area"),
        "scope_tags": target.get("scope_tags", []),
        "checked_at_utc": utc_now(),
        "source": SOURCE_NAME,
        "source_type": SOURCE_TYPE,
    }
    doi = normalize_doi(target.get("doi"))
    exact = [record for record in records if normalize_doi(record.get("doi")) == doi]
    if not exact:
        return {**base, "status": "no_match"}
    matches = [record for record in exact
               if titles_match(target.get("title") or "", record.get("title") or record.get("display_name") or "")]
    if not matches:
        record = exact[0]
        return {**base, "status": "title_mismatch", "returned_doi": record.get("doi"),
                "returned_title": record.get("title") or record.get("display_name")}
    if len(matches) > 1:
        return {**base, "status": "ambiguous_match", "matching_record_count": len(matches)}
    record = matches[0]
    returned_doi = record.get("doi")
    returned_title = record.get("title") or record.get("display_name") or ""
    abstract = reconstruct_abstract(record.get("abstract_inverted_index")).strip()
    work_id = str(record.get("id") or "").rstrip("/").rsplit("/", 1)[-1] or None
    common = {
        **base,
        "returned_doi": returned_doi,
        "returned_title": returned_title,
        "openalex_id": work_id,
        "source_url": f"https://openalex.org/{work_id}" if work_id else None,
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


def read_ids(path: Path | None) -> set[int]:
    ids: set[int] = set()
    if path is None:
        return ids
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") != "abstract_candidate":
                raise ValueError(f"Noncandidate row in exclusion file at {path}:{line_number}")
            ids.add(int(row["article_id"]))
    return ids


def read_completed(path: Path) -> set[int]:
    completed: set[int] = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                article_id = int(json.loads(line)["article_id"])
                if article_id in completed:
                    raise ValueError(f"Duplicate staged article id: {article_id}")
                completed.add(article_id)
    return completed


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


def retry_wait(response: requests.Response | None, attempt: int) -> float:
    value = response.headers.get("Retry-After") if response is not None else None
    if value:
        try:
            return max(1.0, min(300.0, float(value)))
        except ValueError:
            pass
    return min(60.0, float(2 ** attempt))


def fetch_openalex_batch(session: requests.Session, targets: list[dict[str, Any]],
                         max_retries: int, connect_timeout: float, read_timeout: float,
                         stats: dict[str, Any]) -> list[dict[str, Any]]:
    params = {
        "filter": "doi:" + "|".join(normalize_doi(target["doi"]) for target in targets),
        "per_page": MAX_BATCH_SIZE,
        "select": FIELDS,
    }
    response: requests.Response | None = None
    for attempt in range(max_retries + 1):
        try:
            response = session.get(OPENALEX_URL, params=params,
                                   timeout=(connect_timeout, read_timeout))
            if response.status_code == 414 and len(targets) > 1:
                midpoint = len(targets) // 2
                return (fetch_openalex_batch(session, targets[:midpoint], max_retries,
                                             connect_timeout, read_timeout, stats)
                        + fetch_openalex_batch(session, targets[midpoint:], max_retries,
                                               connect_timeout, read_timeout, stats))
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= max_retries:
                    raise OpenAlexBatchError(
                        f"HTTP {response.status_code} after {attempt + 1} attempts",
                        response.status_code, response.headers.get("Retry-After"),
                        (response.text or "")[:300],
                    )
                time.sleep(retry_wait(response, attempt))
                continue
            if response.status_code >= 400:
                raise OpenAlexBatchError(
                    f"Non-retryable HTTP {response.status_code}", response.status_code,
                    excerpt=(response.text or "")[:300],
                )
            body = response.json()
            records = body.get("results")
            if not isinstance(records, list):
                raise RuntimeError("OpenAlex returned a non-list results field")
            stats["api_calls"] += 1
            try:
                stats["credits_used"] += int(response.headers.get("X-RateLimit-Credits-Used", "0"))
            except (TypeError, ValueError):
                pass
            stats["last_rate_limit_remaining"] = response.headers.get("X-RateLimit-Remaining")
            stats["last_rate_limit_limit"] = response.headers.get("X-RateLimit-Limit")
            count = body.get("meta", {}).get("count")
            if isinstance(count, int) and count > MAX_BATCH_SIZE:
                if len(targets) == 1:
                    raise RuntimeError("One DOI returned more than 100 OpenAlex works; refusing truncation")
                midpoint = len(targets) // 2
                return (fetch_openalex_batch(session, targets[:midpoint], max_retries,
                                             connect_timeout, read_timeout, stats)
                        + fetch_openalex_batch(session, targets[midpoint:], max_retries,
                                               connect_timeout, read_timeout, stats))
            return records
        except OpenAlexBatchError:
            raise
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            if isinstance(exc, RuntimeError) and "more than 100 OpenAlex works" in str(exc):
                raise
            if attempt >= max_retries:
                raise OpenAlexBatchError(f"Request failed after {attempt + 1} attempts: {type(exc).__name__}") from exc
            time.sleep(retry_wait(response, attempt))
    raise OpenAlexBatchError("OpenAlex request exhausted retries")


def summarize(run_dir: Path, targets_path: Path, results_path: Path,
              manifest: dict[str, Any]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    areas: dict[str, Counter[str]] = defaultdict(Counter)
    candidates_path = run_dir / "abstract_candidates.jsonl"
    candidate_hash = hashlib.sha256()
    with candidates_path.open("x", encoding="utf-8") as candidates:
        with results_path.open(encoding="utf-8") as results:
            for line in results:
                if not line.strip():
                    continue
                row = json.loads(line)
                counts[row["status"]] += 1
                areas[row.get("broad_area") or "(no broad area)"][row["status"]] += 1
                if row["status"] == "abstract_candidate":
                    encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                    candidates.write(encoded)
                    candidate_hash.update(encoded.encode("utf-8"))
        candidates.flush()
        os.fsync(candidates.fileno())
    return {
        "completed_at_utc": utc_now(),
        "provider": SOURCE_NAME,
        "target_count": manifest["target_count"],
        "completed_count": sum(counts.values()),
        "status_counts": dict(counts),
        "abstract_candidate_count": counts["abstract_candidate"],
        "abstract_candidates_file": str(candidates_path),
        "abstract_candidates_file_sha256": sha256_file(candidates_path),
        "abstract_candidates_serialized_sha256": candidate_hash.hexdigest(),
        "by_broad_area": {key: dict(value) for key, value in sorted(areas.items())},
        "targets_sha256": sha256_file(targets_path),
        "results_sha256": sha256_file(results_path),
        "production_database_writes": 0,
        "full_text_requested": False,
    }


def create_target_snapshot(source_run: Path, run_dir: Path,
                           exclude_path: Path | None) -> dict[str, Any]:
    source_manifest_path = source_run / "manifest.json"
    source_targets = source_run / "targets.jsonl"
    if not source_manifest_path.is_file() or not source_targets.is_file():
        raise SystemExit("Source scope package is missing manifest.json or targets.jsonl")
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("scope_version") != "research-interest-areas-v1-20261016":
        raise SystemExit("Source scope version is not the approved research-interest snapshot")
    actual_source_hash = sha256_file(source_targets)
    if actual_source_hash != source_manifest.get("target_file_sha256"):
        raise SystemExit("Source target snapshot hash differs from its manifest")
    excluded = read_ids(exclude_path)
    target_path = run_dir / "targets.jsonl"
    count = 0
    ids: set[int] = set()
    with source_targets.open(encoding="utf-8") as input_stream, target_path.open("x", encoding="utf-8") as output:
        for line_number, line in enumerate(input_stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            article_id = int(row["article_id"])
            if article_id in ids:
                raise ValueError(f"Duplicate article id in source target snapshot at line {line_number}")
            ids.add(article_id)
            if article_id in excluded:
                continue
            output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    unknown = excluded - ids
    if unknown:
        raise ValueError(f"Exclusion file contains {len(unknown)} IDs outside the frozen target snapshot")
    manifest = {
        "scope_version": source_manifest["scope_version"],
        "created_at_utc": utc_now(),
        "provider": SOURCE_NAME,
        "endpoint": OPENALEX_URL,
        "fields_requested": FIELDS,
        "doi_batch_max": MAX_BATCH_SIZE,
        "target_count": count,
        "source_scope_run_dir": str(source_run),
        "source_target_file_sha256": actual_source_hash,
        "source_target_count": source_manifest["target_count"],
        "excluded_applied_candidate_file": str(exclude_path) if exclude_path else None,
        "excluded_applied_candidate_sha256": sha256_file(exclude_path) if exclude_path else None,
        "excluded_applied_candidate_count": len(excluded),
        "target_file": str(target_path),
        "target_file_sha256": sha256_file(target_path),
        "stage_only": True,
        "database_writes": 0,
        "full_text_requested": False,
        "script_path": str(Path(__file__).resolve()),
        "script_sha256": sha256_file(Path(__file__).resolve()),
    }
    return manifest


def run(args: argparse.Namespace) -> int:
    source_run = Path(args.source_run_dir).resolve()
    run_dir = Path(args.run_dir).resolve()
    key, key_source = load_openalex_api_key()
    if not key:
        raise SystemExit("OPENALEX_API_KEY is not configured in the environment or D:\\claude\\.secrets")
    if args.resume:
        if not run_dir.is_dir():
            raise SystemExit("--resume requires an existing OpenAlex staging directory")
        manifest_path = run_dir / "manifest.json"
        targets_path = run_dir / "targets.jsonl"
        results_path = run_dir / "results.jsonl"
        if not all(path.is_file() for path in (manifest_path, targets_path, results_path)):
            raise SystemExit("Resume package is missing manifest, target snapshot, or results file")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if Path(manifest["source_scope_run_dir"]).resolve() != source_run:
            raise SystemExit("Source scope path differs from the original OpenAlex run")
        if sha256_file(targets_path) != manifest.get("target_file_sha256"):
            raise SystemExit("OpenAlex target snapshot hash differs from manifest")
    else:
        if run_dir.exists():
            raise SystemExit(f"Refusing to reuse existing directory without --resume: {run_dir}")
        run_dir.mkdir(parents=True)
        manifest = create_target_snapshot(source_run, run_dir,
                                          Path(args.exclude_candidate_file).resolve()
                                          if args.exclude_candidate_file else None)
        with (run_dir / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        (run_dir / "results.jsonl").open("x", encoding="utf-8").close()
        targets_path = run_dir / "targets.jsonl"
        results_path = run_dir / "results.jsonl"
    if manifest.get("database_writes") != 0:
        raise SystemExit("Manifest does not declare read-only staging")
    target_count = int(manifest["target_count"])
    if target_count <= 0:
        raise SystemExit("No remaining DOI targets to stage")
    completed = read_completed(results_path)
    if len(completed) > target_count:
        raise SystemExit("Staged result count exceeds frozen target count")
    if len(completed) == target_count:
        summary_path = run_dir / "summary.json"
        if summary_path.exists():
            raise SystemExit("Staging is already complete; inspect summary.json")
        summary = summarize(run_dir, targets_path, results_path, manifest)
        write_json_atomic(summary_path, summary)
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
    stats: dict[str, Any] = {"api_calls": 0, "credits_used": 0,
                             "last_rate_limit_remaining": None, "last_rate_limit_limit": None}
    stage_run = {
        "started_at_utc": utc_now(),
        "resume": bool(args.resume),
        "batch_size": args.batch_size,
        "batch_delay_seconds": args.batch_delay,
        "max_batches": args.max_batches,
        "max_retries": args.max_retries,
        "api_key_source": key_source,
        "database_writes": 0,
        "script_sha256": sha256_file(Path(__file__).resolve()),
    }
    with (run_dir / "stage_runs.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(stage_run, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())

    processed_batches = 0
    pending: list[dict[str, Any]] = []
    with targets_path.open(encoding="utf-8") as target_stream, results_path.open("a", encoding="utf-8") as result_stream:
        while True:
            pending.clear()
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
                records = fetch_openalex_batch(session, pending, args.max_retries,
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
                failure_path = run_dir / (
                    "batch_failure_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    + "_" + os.urandom(4).hex() + ".json"
                )
                write_json_atomic(failure_path, failure)
                print(json.dumps({"status": "stopped_retryable_batch_failure", **failure,
                                  "run_dir": str(run_dir)}, ensure_ascii=False), flush=True)
                return 2
            by_doi: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for record in records:
                if record.get("doi"):
                    by_doi[normalize_doi(record["doi"])].append(record)
            for target in pending:
                result = classify_record(target, by_doi.get(normalize_doi(target["doi"]), []))
                encoded = json.dumps(result, ensure_ascii=False) + "\n"
                result_stream.write(encoded)
                completed.add(int(target["article_id"]))
            result_stream.flush()
            os.fsync(result_stream.fileno())
            processed_batches += 1
            if processed_batches % 100 == 0:
                progress = {
                    "updated_at_utc": utc_now(),
                    "target_count": target_count,
                    "completed_count": len(completed),
                    "completed_batches_this_run": processed_batches,
                    "api_calls_this_run": stats["api_calls"],
                    "credits_used_this_run": stats["credits_used"],
                    "rate_limit_remaining": stats["last_rate_limit_remaining"],
                    "database_writes": 0,
                }
                with (run_dir / "progress.jsonl").open("a", encoding="utf-8") as progress_stream:
                    progress_stream.write(json.dumps(progress, ensure_ascii=False) + "\n")
                    progress_stream.flush()
                    os.fsync(progress_stream.fileno())
                print(json.dumps({"status": "staging", "run_dir": str(run_dir), **progress},
                                 ensure_ascii=False), flush=True)
            if args.max_batches and processed_batches >= args.max_batches:
                break
            if len(completed) < target_count:
                time.sleep(args.batch_delay)

    if len(completed) == target_count:
        summary = summarize(run_dir, targets_path, results_path, manifest)
        summary.update({"api_calls_this_run": stats["api_calls"],
                        "credits_used_this_run": stats["credits_used"],
                        "last_rate_limit_remaining": stats["last_rate_limit_remaining"]})
        write_json_atomic(run_dir / "summary.json", summary)
        print(json.dumps({"status": "staging_complete", "run_dir": str(run_dir),
                          "target_count": target_count,
                          "abstract_candidate_count": summary["abstract_candidate_count"],
                          "api_calls_this_run": stats["api_calls"],
                          "credits_used_this_run": stats["credits_used"],
                          "last_rate_limit_remaining": stats["last_rate_limit_remaining"],
                          "production_database_writes": 0}, ensure_ascii=False), flush=True)
    else:
        progress = {
            "updated_at_utc": utc_now(),
            "target_count": target_count,
            "completed_count": len(completed),
            "completed_batches_this_run": processed_batches,
            "api_calls_this_run": stats["api_calls"],
            "credits_used_this_run": stats["credits_used"],
            "rate_limit_remaining": stats["last_rate_limit_remaining"],
            "database_writes": 0,
        }
        with (run_dir / "progress.jsonl").open("a", encoding="utf-8") as progress_stream:
            progress_stream.write(json.dumps(progress, ensure_ascii=False) + "\n")
            progress_stream.flush()
            os.fsync(progress_stream.fileno())
        print(json.dumps({"status": "staging_paused", "run_dir": str(run_dir), **progress},
                         ensure_ascii=False), flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-dir", required=True,
                        help="Frozen Semantic Scholar scope run whose targets are reused")
    parser.add_argument("--run-dir", required=True, help="New private OpenAlex staging directory")
    parser.add_argument("--exclude-candidate-file",
                        help="Previously applied candidate JSONL to skip from API queries")
    parser.add_argument("--batch-size", type=int, default=MAX_BATCH_SIZE)
    parser.add_argument("--batch-delay", type=float, default=0.15)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=40.0)
    parser.add_argument("--max-batches", type=int,
                        help="Bound this run; omit to process the remaining frozen snapshot")
    parser.add_argument("--resume", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        raise SystemExit(f"--batch-size must be 1..{MAX_BATCH_SIZE}")
    if args.batch_delay < 0.1:
        raise SystemExit("--batch-delay must be at least 0.1 seconds")
    if args.max_retries < 0:
        raise SystemExit("--max-retries must be non-negative")
    if args.connect_timeout <= 0 or args.read_timeout <= 0:
        raise SystemExit("Timeouts must be positive")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
