#!/usr/bin/env python3
"""Stage public Semantic Scholar abstracts for the current research-interest scope.

This command is read-only with respect to the research database. It snapshots
only missing-abstract, nonduplicate DOI records in the existing Management,
Marketing, Information Systems, OB/HR, and explicit personal-interest tags;
then queries the official Semantic Scholar paper-batch API for title, abstract,
and DOI identity fields. It writes a resumable private review package and never
changes article, classification, score, vector, or source tables.

The staged abstract candidates require a separate guarded application step.
No full text is requested or stored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import uuid
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "pboc_data.db"
S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_FIELDS = "title,abstract,externalIds"
MAX_BATCH_SIZE = 500
DEFAULT_BATCH_DELAY = 5.0
SCOPE_VERSION = "research-interest-areas-v1-20261016"

AREA_FIELDS = (
    "Management / Strategy",
    "Marketing",
    "Information Systems",
    "OB / HR",
)
TOPIC_TAGS = (
    "AI_in_organizations", "algorithmic_management", "remote_work",
    "hybrid_work", "return_to_office", "work_family_boundary", "burnout",
    "turnover", "voice", "surveillance_monitoring", "autonomy_control",
    "platform_work", "gig_work", "logistics_delivery", "labor_market",
    "customer_reviews", "employee_wellbeing", "engagement",
)
METHOD_TAGS = ("NLP", "text_mining", "machine_learning")
DATA_TAGS = (
    "job_postings", "Glassdoor", "Indeed", "O*NET", "BLS",
    "online_reviews", "social_media_text", "app_store_reviews",
)

TARGET_QUERY = """
SELECT a.id, a.doi, a.title, a.publisher, a.journal_title,
       a.publication_year, a.journal_abdc_rating, c.broad_area,
       c.ai_related_score, c.work_related_score, c.wfh_rto_related_score,
       c.ob_hr_related_score, c.is_related_to_my_research,
       c.research_topic, c.method_tags_json, c.data_type_tags_json
FROM astar_articles a INDEXED BY idx_astar_visible_rating
JOIN astar_article_classifications c ON c.article_id=a.id
WHERE a.is_duplicate=0
  AND a.abstract_status='missing'
  AND (a.abstract IS NULL OR trim(a.abstract)='')
  AND a.doi IS NOT NULL AND trim(a.doi)<>''
  AND NOT EXISTS (
      SELECT 1 FROM astar_article_sources s
      WHERE s.article_id=a.id AND s.source_name='Semantic Scholar'
  )
  AND (
      c.broad_area IN ('Management / Strategy','Marketing','Information Systems','OB / HR')
      OR c.ai_related_score>0 OR c.work_related_score>0
      OR c.wfh_rto_related_score>0 OR c.ob_hr_related_score>0
      OR c.is_related_to_my_research=1
      OR lower(COALESCE(c.research_topic,'')) LIKE '%ai_in_organizations%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%algorithmic_management%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%remote_work%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%hybrid_work%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%return_to_office%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%work_family_boundary%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%burnout%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%turnover%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%voice%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%surveillance_monitoring%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%autonomy_control%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%platform_work%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%gig_work%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%logistics_delivery%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%labor_market%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%customer_reviews%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%employee_wellbeing%'
      OR lower(COALESCE(c.research_topic,'')) LIKE '%engagement%'
      OR lower(COALESCE(c.method_tags_json,'')) LIKE '%nlp%'
      OR lower(COALESCE(c.method_tags_json,'')) LIKE '%text_mining%'
      OR lower(COALESCE(c.method_tags_json,'')) LIKE '%machine_learning%'
      OR lower(COALESCE(c.data_type_tags_json,'')) LIKE '%job_postings%'
      OR lower(COALESCE(c.data_type_tags_json,'')) LIKE '%glassdoor%'
      OR lower(COALESCE(c.data_type_tags_json,'')) LIKE '%indeed%'
      OR lower(COALESCE(c.data_type_tags_json,'')) LIKE '%o*net%'
      OR lower(COALESCE(c.data_type_tags_json,'')) LIKE '%bls%'
      OR lower(COALESCE(c.data_type_tags_json,'')) LIKE '%online_reviews%'
      OR lower(COALESCE(c.data_type_tags_json,'')) LIKE '%social_media_text%'
      OR lower(COALESCE(c.data_type_tags_json,'')) LIKE '%app_store_reviews%'
  )
ORDER BY a.id
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_semantic_scholar_api_key(env: dict[str, str] | None = None,
                                 secrets_path: Path | None = None) -> tuple[str | None, str]:
    """Read only the S2 key; never persist its value to logs or receipts."""
    env = os.environ if env is None else env
    names = ("SEMANTIC_SCHOLAR_API_KEY", "S2_API_KEY")
    for name in names:
        if env.get(name):
            return env[name].strip(), "environment:" + name
    path = secrets_path or (ROOT / ".secrets")
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                if key.strip() in names and value.strip():
                    return value.strip(), "local_secrets:" + key.strip()
    except OSError:
        pass
    return None, "none"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_doi(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    return text.strip().rstrip(".,; ")


def normalize_title(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    return "".join(character for character in text if character.isalnum())


def titles_match(expected: str, observed: str) -> bool:
    left, right = normalize_title(expected), normalize_title(observed)
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.92


def is_placeholder_abstract(value: str | None) -> bool:
    """Reject known metadata placeholders that are not scholarly abstracts."""
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = " ".join(re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).split())
    return normalized in {
        "no description provided",
        "no description available",
        "no abstract available",
        "abstract not available",
        "abstract unavailable",
        "no abstract",
        "not available",
        "n a",
        "none",
    }


def scope_tags(row: dict[str, Any]) -> list[str]:
    tags: set[str] = set()
    area = row.get("broad_area")
    if area in AREA_FIELDS:
        tags.add("field:" + str(area))
    for column, label in (
        ("ai_related_score", "interest:ai"),
        ("work_related_score", "interest:work"),
        ("wfh_rto_related_score", "interest:wfh_rto"),
        ("ob_hr_related_score", "interest:ob_hr"),
    ):
        if float(row.get(column) or 0) > 0:
            tags.add(label)
    if row.get("is_related_to_my_research"):
        tags.add("interest:existing_related_flag")
    for column, values, prefix in (
        ("research_topic", TOPIC_TAGS, "topic:"),
        ("method_tags_json", METHOD_TAGS, "method:"),
        ("data_type_tags_json", DATA_TAGS, "data:"),
    ):
        text = str(row.get(column) or "").lower()
        for value in values:
            if value.lower() in text:
                tags.add(prefix + value)
    return sorted(tags)


def target_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_id": int(row["id"]),
        "doi": str(row["doi"]).strip(),
        "title": row["title"],
        "publisher": row["publisher"],
        "journal_title": row["journal_title"],
        "publication_year": row["publication_year"],
        "journal_abdc_rating": row["journal_abdc_rating"],
        "broad_area": row["broad_area"],
        "scope_tags": scope_tags(row),
    }


def classify_response(target: dict[str, Any], record: dict[str, Any] | None) -> dict[str, Any]:
    base = {
        "article_id": target["article_id"],
        "doi": target["doi"],
        "title": target["title"],
        "publisher": target.get("publisher"),
        "journal_title": target.get("journal_title"),
        "broad_area": target.get("broad_area"),
        "scope_tags": target.get("scope_tags", []),
        "checked_at_utc": utc_now(),
        "source": "Semantic Scholar",
    }
    if not record:
        return {**base, "status": "no_match"}

    external_ids = record.get("externalIds") or {}
    returned_doi = external_ids.get("DOI")
    if normalize_doi(returned_doi) != normalize_doi(target["doi"]):
        return {**base, "status": "doi_mismatch", "returned_doi": returned_doi,
                "returned_title": record.get("title")}

    returned_title = record.get("title") or ""
    if not titles_match(target["title"] or "", returned_title):
        return {**base, "status": "title_mismatch", "returned_doi": returned_doi,
                "returned_title": returned_title}

    abstract = (record.get("abstract") or "").strip()
    paper_id = record.get("paperId")
    common = {**base, "status": "no_abstract", "returned_doi": returned_doi,
              "returned_title": returned_title, "paper_id": paper_id}
    if not abstract:
        return common
    if is_placeholder_abstract(abstract):
        return {**common, "status": "placeholder_abstract"}
    abstract_bytes = abstract.encode("utf-8")
    return {
        **common,
        "status": "abstract_candidate",
        "abstract": abstract,
        "abstract_chars": len(abstract),
        "abstract_sha256": hashlib.sha256(abstract_bytes).hexdigest(),
        "source_url": f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else None,
    }


def open_read_only(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    return conn


def write_target_snapshot(db_path: Path, run_dir: Path) -> dict[str, Any]:
    conn = open_read_only(db_path)
    try:
        plan = [list(row) for row in conn.execute("EXPLAIN QUERY PLAN " + TARGET_QUERY)]
        plan_text = " ".join(str(item) for row in plan for item in row).lower()
        if ("idx_astar_visible_rating" not in plan_text
                or "idx_src_uniq" not in plan_text
                or "sqlite_autoindex_astar_article_classifications_1" not in plan_text):
            raise RuntimeError("Target query did not use the expected article, source, and classification indexes")
        max_article_id = conn.execute("SELECT max(id) FROM astar_articles").fetchone()[0]
        article_watermark = conn.execute(
            "SELECT max(updated_at),max(created_at) FROM astar_articles").fetchone()
        classification_watermark = conn.execute(
            "SELECT max(classified_at) FROM astar_article_classifications").fetchone()[0]
        target_path = run_dir / "targets.jsonl"
        count = 0
        with target_path.open("x", encoding="utf-8") as output:
            cursor = conn.execute(TARGET_QUERY)
            while True:
                batch = cursor.fetchmany(5000)
                if not batch:
                    break
                for row in batch:
                    output.write(json.dumps(target_record(dict(row)), ensure_ascii=False) + "\n")
                    count += 1
                output.flush()
                os.fsync(output.fileno())
        return {
            "scope_version": SCOPE_VERSION,
            "created_at_utc": utc_now(),
            "database_read_only": True,
            "target_count": count,
            "target_file": str(target_path),
            "target_file_sha256": sha256_file(target_path),
            "database_signature": {
                "max_article_id": str(max_article_id),
                "article_updated_created_watermark": [article_watermark[0], article_watermark[1]],
                "classification_watermark": classification_watermark,
            },
            "query_plan": plan,
            "selection": {
                "nonduplicate": True,
                "abstract_status": "missing",
                "abstract_field": "NULL or whitespace-only",
                "doi_required": True,
                "Semantic_Scholar_source_record_required_absent": True,
                "fields": list(AREA_FIELDS),
                "interest_scores_topics_methods_and_data_tags": {
                    "topics": list(TOPIC_TAGS), "methods": list(METHOD_TAGS),
                    "data_types": list(DATA_TAGS),
                    "scores": ["ai_related_score", "work_related_score",
                               "wfh_rto_related_score", "ob_hr_related_score",
                               "is_related_to_my_research"],
                },
            },
        }
    finally:
        conn.rollback()
        conn.close()


def read_completed_ids(path: Path) -> set[int]:
    if not path.exists():
        return set()
    completed: set[int] = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("status") in {
                "no_match", "doi_mismatch", "title_mismatch", "no_abstract", "abstract_candidate"
            }:
                completed.add(int(item["article_id"]))
    return completed


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp." + uuid.uuid4().hex)
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class SemanticScholarBatchError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None,
                 retry_after: str | None = None, response_excerpt: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.response_excerpt = response_excerpt


def _retry_wait(retry_after: str | None, attempt: int) -> float:
    if retry_after:
        try:
            return max(1.0, float(retry_after))
        except ValueError:
            try:
                target = parsedate_to_datetime(retry_after)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                return max(1.0, min(300.0, (target - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(300.0, max(1.0, float(2 ** attempt)))


def post_batch(session: requests.Session, doi_values: list[str], max_retries: int,
               connect_timeout: float, read_timeout: float) -> list[dict[str, Any] | None]:
    payload = {"ids": ["DOI:" + doi for doi in doi_values]}
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = session.post(
                S2_BATCH_URL, params={"fields": S2_FIELDS}, json=payload,
                timeout=(connect_timeout, read_timeout)
            )
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After")
                if attempt >= max_retries:
                    excerpt = (response.text or "")[:300]
                    raise SemanticScholarBatchError(
                        f"HTTP {response.status_code} after {attempt + 1} attempts",
                        status_code=response.status_code, retry_after=retry_after,
                        response_excerpt=excerpt,
                    )
                time.sleep(_retry_wait(retry_after, attempt))
                continue
            if response.status_code >= 400:
                raise SemanticScholarBatchError(
                    f"Non-retryable HTTP {response.status_code}",
                    status_code=response.status_code,
                    response_excerpt=(response.text or "")[:300],
                )
            data = response.json()
            if not isinstance(data, list) or len(data) != len(doi_values):
                raise RuntimeError(
                    f"Semantic Scholar returned {len(data) if isinstance(data, list) else 'non-list'} "
                    f"items for {len(doi_values)} DOI inputs"
                )
            return data
        except SemanticScholarBatchError:
            raise
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            time.sleep(max(1.0, min(60.0, 2 ** attempt)))
    raise RuntimeError(f"Semantic Scholar batch failed after retries: {last_error}")


def summarize_results(results_path: Path, target_count: int) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    by_area: dict[str, Counter[str]] = defaultdict(Counter)
    by_publisher: dict[str, Counter[str]] = defaultdict(Counter)
    candidate_hashes = hashlib.sha256()
    candidate_path = results_path.parent / "abstract_candidates.jsonl"
    with candidate_path.open("x", encoding="utf-8") as candidate_stream:
        with results_path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                result = json.loads(line)
                status = result["status"]
                counts[status] += 1
                area = result.get("broad_area") or "(no broad area)"
                publisher = result.get("publisher") or "(unknown publisher)"
                by_area[area][status] += 1
                by_publisher[publisher][status] += 1
                if status == "abstract_candidate":
                    raw = json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
                    candidate_stream.write(raw)
                    candidate_hashes.update(raw.encode("utf-8"))
        candidate_stream.flush()
        os.fsync(candidate_stream.fileno())
    return {
        "completed_at_utc": utc_now(),
        "target_count": target_count,
        "completed_count": sum(counts.values()),
        "status_counts": dict(counts),
        "abstract_candidate_count": counts["abstract_candidate"],
        "abstract_candidates_file": str(candidate_path),
        "abstract_candidates_sha256": candidate_hashes.hexdigest(),
        "abstract_candidates_file_sha256": sha256_file(candidate_path),
        "by_broad_area": {key: dict(value) for key, value in sorted(by_area.items())},
        "top_publishers_by_abstract_candidate": [
            {"publisher": key, **dict(value)}
            for key, value in sorted(by_publisher.items(),
                                     key=lambda item: item[1]["abstract_candidate"], reverse=True)[:30]
        ],
        "production_database_writes": 0,
        "full_text_requested": False,
    }


def run_stage(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    db_path = Path(args.db).resolve()
    if args.resume:
        if not run_dir.is_dir():
            raise SystemExit("--resume requires an existing run directory")
        manifest_path = run_dir / "manifest.json"
        targets_path = run_dir / "targets.jsonl"
        results_path = run_dir / "results.jsonl"
        if not all(path.exists() for path in (manifest_path, targets_path, results_path)):
            raise SystemExit("Resume package is missing manifest, target snapshot, or results file")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("scope_version") != SCOPE_VERSION:
            raise SystemExit("Scope version differs; create a new run directory")
    else:
        if run_dir.exists():
            raise SystemExit(f"Refusing to reuse existing run directory without --resume: {run_dir}")
        run_dir.mkdir(parents=True)
        manifest = write_target_snapshot(db_path, run_dir)
        manifest.update({
            "s2_endpoint": S2_BATCH_URL,
            "s2_fields_requested": S2_FIELDS,
            "batch_size": args.batch_size,
            "batch_delay_seconds": args.batch_delay,
            "stage_only": True,
            "database_path": str(db_path),
            "script_path": str(Path(__file__).resolve()),
            "script_sha256": sha256_file(Path(__file__)),
        })
        manifest_path = run_dir / "manifest.json"
        with manifest_path.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        targets_path = run_dir / "targets.jsonl"
        results_path = run_dir / "results.jsonl"
        results_path.open("x", encoding="utf-8").close()

    stage_runs_path = run_dir / "stage_runs.jsonl"
    with stage_runs_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "started_at_utc": utc_now(), "resume": bool(args.resume),
            "batch_size": args.batch_size, "batch_delay_seconds": args.batch_delay,
            "max_batches": args.max_batches, "max_retries": args.max_retries,
            "connect_timeout_seconds": args.connect_timeout,
            "read_timeout_seconds": args.read_timeout,
            "api_key_source": load_semantic_scholar_api_key()[1],
            "script_sha256": sha256_file(Path(__file__)),
        }, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())

    if manifest.get("database_path") and Path(manifest["database_path"]).resolve() != db_path:
        raise SystemExit("Database path differs from the original manifest")
    target_count = int(manifest["target_count"])
    completed = read_completed_ids(results_path)
    if len(completed) >= target_count:
        raise SystemExit("All targets are already staged; summary.json should be inspected")

    session = requests.Session()
    session.headers.update({"User-Agent": "ABDC-Research-Radar/1.0 (public abstract metadata only)"})
    api_key, _api_key_source = load_semantic_scholar_api_key()
    if api_key:
        session.headers["x-api-key"] = api_key
    processed_batches = 0
    pending: list[dict[str, Any]] = []
    batch_index = 0
    with targets_path.open(encoding="utf-8") as targets_stream, results_path.open("a", encoding="utf-8") as results_stream:
        while True:
            pending.clear()
            while len(pending) < args.batch_size:
                line = targets_stream.readline()
                if not line:
                    break
                target = json.loads(line)
                if int(target["article_id"]) not in completed:
                    pending.append(target)
            if not pending:
                break
            batch_index += 1
            try:
                response_rows = post_batch(session, [row["doi"] for row in pending], args.max_retries,
                                           args.connect_timeout, args.read_timeout)
            except Exception as exc:
                error_file = run_dir / ("batch_failure_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
                failure = {
                    "failed_at_utc": utc_now(), "batch_number": batch_index,
                    "pending_count": len(pending),
                    "first_article_id": pending[0]["article_id"] if pending else None,
                    "last_article_id": pending[-1]["article_id"] if pending else None,
                    "pending_dois_sha256": hashlib.sha256(
                        "\n".join(row["doi"] for row in pending).encode("utf-8")
                    ).hexdigest(),
                    "error_type": type(exc).__name__, "error": str(exc),
                    "http_status": getattr(exc, "status_code", None),
                    "retry_after": getattr(exc, "retry_after", None),
                    "response_excerpt": getattr(exc, "response_excerpt", None),
                    "database_writes": 0,
                }
                with error_file.open("x", encoding="utf-8") as stream:
                    json.dump(failure, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                print(json.dumps({"status": "stopped_retryable_batch_failure",
                                  "batch_number": batch_index, "pending_count": len(pending),
                                  "http_status": failure["http_status"],
                                  "retry_after": failure["retry_after"],
                                  "error": str(exc)}, ensure_ascii=False), flush=True)
                return 2
            if len(response_rows) != len(pending):
                raise RuntimeError("Batch length changed after response validation")
            for target, record in zip(pending, response_rows):
                result = classify_response(target, record)
                results_stream.write(json.dumps(result, ensure_ascii=False) + "\n")
                completed.add(int(target["article_id"]))
            results_stream.flush()
            os.fsync(results_stream.fileno())
            processed_batches += 1
            if processed_batches % 10 == 0:
                progress = {
                    "updated_at_utc": utc_now(), "target_count": target_count,
                    "completed_count": len(completed), "completed_batches_this_run": processed_batches,
                    "last_batch_number": batch_index, "batch_delay_seconds": args.batch_delay,
                    "production_database_writes": 0,
                }
                write_json_atomic(run_dir / "progress.json", progress)
                print(json.dumps({"status": "staging", **progress}, ensure_ascii=False), flush=True)
            if args.max_batches and processed_batches >= args.max_batches:
                break
            if len(completed) < target_count:
                time.sleep(args.batch_delay)
    if len(completed) == target_count:
        summary = summarize_results(results_path, target_count)
        summary["manifest_path"] = str(manifest_path)
        summary["results_path"] = str(results_path)
        summary["targets_sha256"] = manifest.get("target_file_sha256")
        with (run_dir / "summary.json").open("x", encoding="utf-8") as stream:
            json.dump(summary, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps({"status": "staging_complete", "run_dir": str(run_dir),
                          "target_count": target_count,
                          "abstract_candidate_count": summary["abstract_candidate_count"],
                          "abstract_candidates_sha256": summary["abstract_candidates_sha256"],
                          "production_database_writes": 0}, ensure_ascii=False), flush=True)
    else:
        progress = {
            "updated_at_utc": utc_now(), "target_count": target_count,
            "completed_count": len(completed), "completed_batches_this_run": processed_batches,
            "last_batch_number": batch_index, "batch_delay_seconds": args.batch_delay,
            "production_database_writes": 0,
        }
        write_json_atomic(run_dir / "progress.json", progress)
        print(json.dumps({"status": "staging_paused", "run_dir": str(run_dir), **progress},
                         ensure_ascii=False), flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="New private output directory; use --resume to continue")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--batch-size", type=int, default=MAX_BATCH_SIZE)
    parser.add_argument("--batch-delay", type=float, default=DEFAULT_BATCH_DELAY)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    parser.add_argument("--max-batches", type=int, default=None,
                        help="Optional bounded run for review; default processes the whole target snapshot")
    parser.add_argument("--resume", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        raise SystemExit(f"--batch-size must be 1..{MAX_BATCH_SIZE}")
    if args.batch_delay < 1.0:
        raise SystemExit("--batch-delay must be at least 1 second to avoid aggressive requests")
    if args.max_retries < 0:
        raise SystemExit("--max-retries must be non-negative")
    if args.connect_timeout <= 0 or args.read_timeout <= 0:
        raise SystemExit("Timeouts must be positive")
    return run_stage(args)


if __name__ == "__main__":
    raise SystemExit(main())
