#!/usr/bin/env python3
"""Audit the dynamic project registry and public/private Git boundary.

The registry is intentionally count-agnostic: a new project domain can be
added without editing the audit's business logic. The report contains paths
and aggregate sizes only, never secret values or private file contents.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "projects" / "registry.json"
TEXT_SUFFIXES = {
    ".bat", ".cmd", ".css", ".csv", ".html", ".ini", ".js", ".json",
    ".jsonl", ".md", ".py", ".sh", ".toml", ".tsv", ".txt", ".vbs",
    ".yaml", ".yml",
}
SECRET_PATTERNS = (
    ("aws_access_key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(rb"gh[pousr]_[A-Za-z0-9_]{30,}")),
    ("huggingface_token", re.compile(rb"hf_[A-Za-z0-9]{20,}")),
    ("openai_key", re.compile(rb"sk-[A-Za-z0-9]{20,}")),
    ("google_api_key", re.compile(rb"AIza[0-9A-Za-z_-]{30,}")),
    ("private_key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("credential_url", re.compile(rb"[A-Za-z][A-Za-z0-9+.-]*://[^/@\s]+:[^/@\s]+@")),
)
SKIP_DIRS = {".git", ".codex", ".claude", ".agents", ".playwright-cli", "node_modules", "__pycache__", ".venv", "venv", "env"}


def git_bytes(repo_root: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(["git", *args], cwd=repo_root, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout


def git_paths(repo_root: Path, *args: str) -> set[str]:
    output = git_bytes(repo_root, *args, "-z")
    return {item.decode("utf-8", "surrogateescape") for item in output.split(b"\0") if item}


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("project registry must be a JSON object")
    return value


def iter_pattern_files(repo_root: Path, pattern: str) -> Iterable[Path]:
    """Glob a pattern without descending into known large tool directories."""
    for match in repo_root.glob(pattern):
        if any(part in SKIP_DIRS for part in match.parts):
            continue
        if match.is_file() or match.is_symlink():
            yield match
        elif match.is_dir():
            for child in match.rglob("*"):
                if any(part in SKIP_DIRS for part in child.parts):
                    continue
                if child.is_file() or child.is_symlink():
                    yield child


def relative_path(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _matches(path: str, pattern: str) -> bool:
    """Match repository-relative paths for common Git-style registry globs."""
    normalized = path.replace(os.sep, "/")
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    if fnmatch.fnmatch(normalized, pattern):
        return True
    # Git-style patterns without a slash (for example *.db) apply to a file
    # name at any depth, while patterns containing a slash stay anchored.
    return "/" not in pattern and fnmatch.fnmatch(normalized.rsplit("/", 1)[-1], pattern)


def collect_matches(repo_root: Path, patterns: Iterable[str], known_paths: Iterable[str] | None = None) -> set[str]:
    """Collect registry matches; use Git's path universe when available."""
    matches: set[str] = set()
    if known_paths is not None:
        universe = set(known_paths)
        for pattern in patterns:
            matches.update(path for path in universe if _matches(path, pattern))
        return matches
    for pattern in patterns:
        for path in iter_pattern_files(repo_root, pattern):
            matches.add(relative_path(repo_root, path))
    return matches


def scan_high_confidence_secrets(repo_root: Path, public_paths: Iterable[str], max_bytes: int = 5 * 1024 * 1024) -> list[dict]:
    findings: list[dict] = []
    for rel_path in sorted(set(public_paths)):
        path = repo_root / rel_path
        try:
            if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file() or path.stat().st_size > max_bytes:
                continue
            payload = path.read_bytes()
        except OSError:
            continue
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(payload)
            if match:
                findings.append({"path": rel_path, "line": payload[:match.start()].count(b"\n") + 1, "kind": label})
    return findings


def validate_registry(repo_root: Path, registry: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    projects = registry.get("projects")
    if not isinstance(projects, list) or not projects:
        return ["registry must define at least one project"], warnings
    required = {"id", "nav_key", "nav_label", "name", "default_route", "routes", "source_globs", "tracked_data", "private_data_globs"}
    ids = [project.get("id") for project in projects if isinstance(project, dict)]
    nav_keys = [project.get("nav_key") for project in projects if isinstance(project, dict)]
    if len(set(ids)) != len(ids): errors.append("project ids must be unique")
    if len(set(nav_keys)) != len(nav_keys): errors.append("navigation keys must be unique")
    nav_path = repo_root / "static" / "research-nav.js"
    nav_text = nav_path.read_text(encoding="utf-8") if nav_path.is_file() else ""
    owned_routes: set[str] = set()
    route_owners: dict[str, str] = {}
    known_paths = None
    try:
        known_paths = git_paths(repo_root, "ls-files") | git_paths(repo_root, "ls-files", "--others", "--exclude-standard") | git_paths(repo_root, "ls-files", "--others", "--ignored", "--exclude-standard")
    except (OSError, RuntimeError):
        pass
    for project in projects:
        if not isinstance(project, dict):
            errors.append("each project must be an object")
            continue
        project_id = str(project.get("id", "unknown"))
        missing = sorted(required - set(project))
        errors.extend(f"{project_id}: missing registry field {field}" for field in missing)
        routes = project.get("routes") or []
        if not isinstance(routes, list):
            errors.append(f"{project_id}: routes must be a list")
            routes = []
        if project.get("default_route") not in routes:
            errors.append(f"{project_id}: default route is not an owned route")
        for route in routes:
            if not isinstance(route, str) or not route.startswith("/"):
                errors.append(f"{project_id}: invalid route {route!r}")
                continue
            if route in owned_routes and route not in (project.get("shared_routes") or []):
                warnings.append(f"{project_id}: route is also owned elsewhere: {route}")
            owned_routes.add(route); route_owners.setdefault(route, project_id)
            if route not in nav_text: warnings.append(f"{project_id}: route absent from research-nav.js: {route}")
        if str(project.get("nav_label", project.get("name", ""))) not in nav_text:
            warnings.append(f"{project_id}: display name differs from navigation label")
        for pattern in project.get("source_globs") or []:
            if not collect_matches(repo_root, [pattern], known_paths):
                warnings.append(f"{project_id}: source glob has no match: {pattern}")
        for tracked_path in project.get("tracked_data") or []:
            if not (repo_root / tracked_path).is_file(): errors.append(f"{project_id}: tracked data is missing: {tracked_path}")
    if not registry.get("layout"):
        warnings.append("registry layout is not declared")
    return errors, warnings


def _file_size(repo_root: Path, rel_path: str) -> int:
    try:
        return (repo_root / rel_path).stat().st_size
    except OSError:
        return 0


def build_report(repo_root: Path, registry: dict) -> dict:
    errors, warnings = validate_registry(repo_root, registry)
    tracked = git_paths(repo_root, "ls-files")
    untracked = git_paths(repo_root, "ls-files", "--others", "--exclude-standard")
    ignored = git_paths(repo_root, "ls-files", "--others", "--ignored", "--exclude-standard")
    changed_tracked = git_paths(repo_root, "diff", "--name-only")
    changed_staged = git_paths(repo_root, "diff", "--cached", "--name-only")
    all_paths = tracked | untracked | ignored
    shared = registry.get("shared") or {}
    private_patterns = list(shared.get("private_data_globs") or [])
    for project in registry["projects"]: private_patterns.extend(project.get("private_data_globs") or [])
    private_matches = collect_matches(repo_root, private_patterns, all_paths)
    disposable_matches = collect_matches(repo_root, shared.get("disposable_globs") or [], all_paths)
    tracked_private = sorted(tracked & private_matches)
    if tracked_private: errors.extend(f"private path is tracked by Git: {path}" for path in tracked_private)
    unignored_private = sorted(path for path in private_matches if path not in tracked and path not in ignored)
    if unignored_private: errors.extend(f"private path is not ignored by Git: {path}" for path in unignored_private[:100])
    unexplained_ignored = sorted(ignored - private_matches - disposable_matches)
    if unexplained_ignored:
        errors.extend(f"ignored path has no migration policy: {path}" for path in unexplained_ignored[:100])
        if len(unexplained_ignored) > 100: errors.append(f"{len(unexplained_ignored) - 100} additional ignored paths have no migration policy")
    max_public_bytes = int(registry.get("repository", {}).get("max_public_file_bytes", 20 * 1024 * 1024))
    oversized = [{"path": path, "bytes": _file_size(repo_root, path)} for path in sorted(tracked) if _file_size(repo_root, path) > max_public_bytes]
    errors.extend(f"tracked file exceeds public size policy: {item['path']}" for item in oversized)
    public_candidates = (tracked | untracked) - private_matches - ignored
    secret_findings = scan_high_confidence_secrets(repo_root, public_candidates)
    errors.extend(f"high-confidence secret pattern: {item['path']}:{item['line']} ({item['kind']})" for item in secret_findings)
    project_summaries = []
    for project in registry["projects"]:
        matches = collect_matches(repo_root, project.get("source_globs") or [], all_paths)
        project_summaries.append({"id": project["id"], "name": project["name"], "routes": project["routes"], "source_file_count": len(matches), "source_bytes": sum(_file_size(repo_root, path) for path in matches)})
    return {
        "schema_version": 1, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "layout": registry.get("layout"),
        "git": {"branch": git_bytes(repo_root, "branch", "--show-current").decode().strip(), "commit": git_bytes(repo_root, "rev-parse", "HEAD").decode().strip(), "origin": git_bytes(repo_root, "remote", "get-url", "origin", check=False).decode("utf-8", "replace").strip(), "tracked_file_count": len(tracked), "changed_tracked_file_count": len(changed_tracked | changed_staged), "untracked_file_count": len(untracked), "ignored_file_count": len(ignored)},
        "projects": project_summaries, "private_boundary": {"matched_file_count": len(private_matches), "matched_bytes": sum(_file_size(repo_root, path) for path in private_matches), "tracked_private_files": tracked_private, "unignored_private_file_count": len(unignored_private)},
        "ignored_policy": {"ignored_file_count": len(ignored), "registered_private_file_count": len(ignored & private_matches), "disposable_only_file_count": len((ignored - private_matches) & disposable_matches), "unexplained_file_count": len(unexplained_ignored)},
        "public_boundary": {"max_file_bytes": max_public_bytes, "oversized_tracked_files": oversized, "high_confidence_secret_findings": secret_findings},
        "warnings": sorted(set(warnings)), "errors": sorted(set(errors)), "status": "pass" if not errors else "fail",
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv); registry_path = args.registry if args.registry.is_absolute() else ROOT / args.registry
    report = build_report(ROOT, load_registry(registry_path)); encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output; output.parent.mkdir(parents=True, exist_ok=True); output.write_text(encoded, encoding="utf-8"); print(f"wrote {output.relative_to(ROOT)}")
    print(f"projects_audit={report['status']} projects={len(report['projects'])} errors={len(report['errors'])} warnings={len(report['warnings'])}")
    for error in report["errors"]: print(f"ERROR: {error}")
    for warning in report["warnings"]: print(f"WARNING: {warning}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__": sys.exit(main())
