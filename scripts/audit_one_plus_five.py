#!/usr/bin/env python3
"""Audit the public Git boundary and the one-plus-five project registry.

The report contains paths and aggregate sizes, but never secret values or file
contents. It is safe to use before staging or publishing a branch.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
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
    (
        "private_key",
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "credential_url",
        re.compile(rb"[A-Za-z][A-Za-z0-9+.-]*://[^/@\s]+:[^/@\s]+@"),
    ),
)


def git_bytes(repo_root: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return result.stdout


def git_paths(repo_root: Path, *args: str) -> set[str]:
    output = git_bytes(repo_root, *args, "-z")
    return {
        item.decode("utf-8", "surrogateescape")
        for item in output.split(b"\0")
        if item
    }


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        registry = json.load(handle)
    if not isinstance(registry, dict):
        raise ValueError("project registry must be a JSON object")
    return registry


def iter_pattern_files(repo_root: Path, pattern: str) -> Iterable[Path]:
    for match in repo_root.glob(pattern):
        if ".git" in match.parts:
            continue
        if match.is_file() or match.is_symlink():
            yield match
        elif match.is_dir():
            for child in match.rglob("*"):
                if child.is_file() or child.is_symlink():
                    yield child


def relative_path(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def collect_matches(repo_root: Path, patterns: Iterable[str]) -> set[str]:
    matches: set[str] = set()
    for pattern in patterns:
        for path in iter_pattern_files(repo_root, pattern):
            matches.add(relative_path(repo_root, path))
    return matches


def scan_high_confidence_secrets(
    repo_root: Path,
    public_paths: Iterable[str],
    max_bytes: int = 5 * 1024 * 1024,
) -> list[dict]:
    findings: list[dict] = []
    for rel_path in sorted(set(public_paths)):
        path = repo_root / rel_path
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            continue
        if path.stat().st_size > max_bytes:
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(payload)
            if match:
                findings.append(
                    {
                        "path": rel_path,
                        "line": payload[: match.start()].count(b"\n") + 1,
                        "kind": label,
                    }
                )
    return findings


def validate_registry(repo_root: Path, registry: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    projects = registry.get("projects")
    if not isinstance(projects, list) or len(projects) != 5:
        errors.append("registry must define exactly five projects")
        return errors, warnings

    project_ids = [project.get("id") for project in projects]
    nav_keys = [project.get("nav_key") for project in projects]
    if len(set(project_ids)) != len(project_ids):
        errors.append("project ids must be unique")
    if len(set(nav_keys)) != len(nav_keys):
        errors.append("navigation keys must be unique")

    owned_routes: set[str] = set()
    nav_text = (repo_root / "static" / "research-nav.js").read_text(
        encoding="utf-8"
    )
    for project in projects:
        project_id = str(project.get("id", "unknown"))
        routes = project.get("routes") or []
        default_route = project.get("default_route")
        if default_route not in routes:
            errors.append(f"{project_id}: default route is not an owned route")
        for route in routes:
            if not isinstance(route, str) or not route.startswith("/"):
                errors.append(f"{project_id}: invalid route {route!r}")
                continue
            if route in owned_routes:
                errors.append(f"{project_id}: duplicate owned route {route}")
            owned_routes.add(route)
            if route not in nav_text:
                warnings.append(f"{project_id}: route absent from research-nav.js: {route}")
        if str(project.get("nav_label", project.get("name", ""))) not in nav_text:
            warnings.append(
                f"{project_id}: display name differs from navigation label"
            )
        for pattern in project.get("source_globs") or []:
            if not any(iter_pattern_files(repo_root, pattern)):
                warnings.append(f"{project_id}: source glob has no match: {pattern}")
        for tracked_path in project.get("tracked_data") or []:
            if not (repo_root / tracked_path).is_file():
                errors.append(f"{project_id}: tracked data is missing: {tracked_path}")
    return errors, warnings


def build_report(repo_root: Path, registry: dict) -> dict:
    errors, warnings = validate_registry(repo_root, registry)
    tracked = git_paths(repo_root, "ls-files")
    untracked = git_paths(repo_root, "ls-files", "--others", "--exclude-standard")
    ignored = git_paths(
        repo_root, "ls-files", "--others", "--ignored", "--exclude-standard"
    )
    changed_tracked = git_paths(repo_root, "diff", "--name-only")
    changed_staged = git_paths(repo_root, "diff", "--cached", "--name-only")

    shared = registry.get("shared") or {}
    private_patterns = list(shared.get("private_data_globs") or [])
    for project in registry["projects"]:
        private_patterns.extend(project.get("private_data_globs") or [])
    private_matches = collect_matches(repo_root, private_patterns)

    tracked_private = sorted(tracked & private_matches)
    if tracked_private:
        errors.extend(
            f"private path is tracked by Git: {path}" for path in tracked_private
        )
    unignored_private = sorted(
        path
        for path in private_matches
        if path not in tracked and path not in ignored
    )
    if unignored_private:
        errors.extend(
            f"private path is not ignored by Git: {path}"
            for path in unignored_private[:100]
        )
        if len(unignored_private) > 100:
            errors.append(
                f"{len(unignored_private) - 100} additional private paths are not ignored"
            )

    max_public_bytes = int(
        registry.get("repository", {}).get("max_public_file_bytes", 20 * 1024 * 1024)
    )
    oversized_tracked = []
    for path in sorted(tracked):
        absolute = repo_root / path
        if absolute.is_file() and absolute.stat().st_size > max_public_bytes:
            oversized_tracked.append(
                {"path": path, "bytes": absolute.stat().st_size}
            )
    if oversized_tracked:
        errors.extend(
            f"tracked file exceeds public size policy: {item['path']}"
            for item in oversized_tracked
        )

    public_candidates = (tracked | untracked) - private_matches - ignored
    secret_findings = scan_high_confidence_secrets(repo_root, public_candidates)
    if secret_findings:
        errors.extend(
            f"high-confidence secret pattern: {item['path']}:{item['line']} "
            f"({item['kind']})"
            for item in secret_findings
        )

    project_summaries = []
    for project in registry["projects"]:
        matches = collect_matches(repo_root, project.get("source_globs") or [])
        project_summaries.append(
            {
                "id": project["id"],
                "name": project["name"],
                "routes": project["routes"],
                "source_file_count": len(matches),
                "source_bytes": sum(
                    (repo_root / path).stat().st_size
                    for path in matches
                    if (repo_root / path).is_file()
                ),
            }
        )

    private_bytes = sum(
        (repo_root / path).stat().st_size
        for path in private_matches
        if (repo_root / path).is_file()
    )
    branch = git_bytes(repo_root, "branch", "--show-current").decode().strip()
    commit = git_bytes(repo_root, "rev-parse", "HEAD").decode().strip()
    remote = git_bytes(
        repo_root, "remote", "get-url", "origin", check=False
    ).decode("utf-8", "replace").strip()

    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "layout": registry.get("layout"),
        "git": {
            "branch": branch,
            "commit": commit,
            "origin": remote,
            "tracked_file_count": len(tracked),
            "changed_tracked_file_count": len(changed_tracked | changed_staged),
            "untracked_file_count": len(untracked),
            "ignored_file_count": len(ignored),
        },
        "projects": project_summaries,
        "private_boundary": {
            "matched_file_count": len(private_matches),
            "matched_bytes": private_bytes,
            "tracked_private_files": tracked_private,
            "unignored_private_file_count": len(unignored_private),
        },
        "public_boundary": {
            "max_file_bytes": max_public_bytes,
            "oversized_tracked_files": oversized_tracked,
            "high_confidence_secret_findings": secret_findings,
        },
        "warnings": sorted(set(warnings)),
        "errors": sorted(set(errors)),
        "status": "pass" if not errors else "fail",
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=REGISTRY_PATH,
        help="project registry JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional JSON report path; relative paths resolve from the repository",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    registry_path = args.registry
    if not registry_path.is_absolute():
        registry_path = ROOT / registry_path
    registry = load_registry(registry_path)
    report = build_report(ROOT, registry)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = args.output
        if not output.is_absolute():
            output = ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
        print(f"wrote {output.relative_to(ROOT)}")
    print(
        f"one_plus_five_audit={report['status']} "
        f"projects={len(report['projects'])} "
        f"errors={len(report['errors'])} "
        f"warnings={len(report['warnings'])}"
    )
    for error in report["errors"]:
        print(f"ERROR: {error}")
    for warning in report["warnings"]:
        print(f"WARNING: {warning}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
