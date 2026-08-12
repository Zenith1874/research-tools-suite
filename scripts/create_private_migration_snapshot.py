#!/usr/bin/env python3
"""Create a resumable, private snapshot for files intentionally excluded from Git.

The destination must be outside the repository. SQLite databases are copied
with SQLite's online backup API; ordinary files are streamed through .part
files and receive SHA-256 checksums. No private content is printed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "projects" / "registry.json"
CHUNK_BYTES = 8 * 1024 * 1024
SNAPSHOT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


def collect_private_files(
    repo_root: Path,
    registry: dict,
    include_temporary: bool = False,
) -> dict[str, set[str]]:
    patterns: list[tuple[str, str]] = []
    for pattern in registry.get("shared", {}).get("private_data_globs", []):
        patterns.append(("shared", pattern))
    for project in registry.get("projects", []):
        for pattern in project.get("private_data_globs", []):
            patterns.append((project["id"], pattern))

    files: dict[str, set[str]] = {}
    for category, pattern in patterns:
        if not include_temporary and (
            pattern == "tmp/**" or pattern.startswith("tmp/")
        ):
            continue
        for path in iter_pattern_files(repo_root, pattern):
            rel_path = path.relative_to(repo_root).as_posix()
            files.setdefault(rel_path, set()).add(category)
    return files


def exclude_manifest_paths(
    files: dict[str, set[str]],
    manifest_path: Path,
) -> dict[str, set[str]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    covered = {
        entry.get("path")
        for entry in manifest.get("files", [])
        if isinstance(entry, dict) and entry.get("path")
    }
    return {
        path: categories
        for path, categories in files.items()
        if path not in covered
    }


def human_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = float(value)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    raise AssertionError("unreachable")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_regular_resumable(source: Path, destination: Path) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    source_before = source.stat()
    offset = part.stat().st_size if part.exists() else 0
    if offset > source_before.st_size:
        raise RuntimeError("partial destination is larger than source")

    digest = hashlib.sha256()
    with source.open("rb") as source_handle:
        if offset:
            with part.open("rb") as part_handle:
                remaining = offset
                while remaining:
                    size = min(CHUNK_BYTES, remaining)
                    source_chunk = source_handle.read(size)
                    part_chunk = part_handle.read(size)
                    if source_chunk != part_chunk:
                        raise RuntimeError("partial destination differs from source")
                    digest.update(source_chunk)
                    remaining -= len(source_chunk)
        with part.open("ab") as destination_handle:
            for chunk in iter(lambda: source_handle.read(CHUNK_BYTES), b""):
                destination_handle.write(chunk)
                digest.update(chunk)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())

    source_after = source.stat()
    if (
        source_after.st_size != source_before.st_size
        or source_after.st_mtime_ns != source_before.st_mtime_ns
    ):
        raise RuntimeError("source changed while it was being copied")
    if part.stat().st_size != source_before.st_size:
        raise RuntimeError("copied size does not match source")
    part.replace(destination)
    shutil.copystat(source, destination, follow_symlinks=False)
    return digest.hexdigest(), destination.stat().st_size


def is_live_sqlite(rel_path: str) -> bool:
    lower = rel_path.lower()
    if lower.startswith(("backups/", "tmp/")):
        return False
    return lower.endswith((".db", ".sqlite", ".sqlite3"))


def finish_sqlite_backup(
    source_conn: sqlite3.Connection,
    part: Path,
    destination: Path,
) -> tuple[str, int]:
    destination_conn = sqlite3.connect(part)
    try:
        source_conn.backup(destination_conn, pages=2048, sleep=0.05)
        check = destination_conn.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError("SQLite quick_check failed")
    finally:
        destination_conn.close()
        source_conn.close()
    part.replace(destination)
    return sha256_file(destination), destination.stat().st_size


def sqlite_triplet_signature(source: Path) -> list[tuple[str, int, int]]:
    paths = [source, Path(str(source) + "-wal"), Path(str(source) + "-shm")]
    signature = []
    for path in paths:
        if path.exists():
            stat = path.stat()
            signature.append((path.name, stat.st_size, stat.st_mtime_ns))
    return signature


def backup_sqlite_from_triplet(
    source: Path,
    part: Path,
    destination: Path,
) -> tuple[str, int]:
    before = sqlite_triplet_signature(source)
    with tempfile.TemporaryDirectory(prefix="research-tools-sqlite-") as temporary:
        temporary_root = Path(temporary)
        for name, _size, _mtime_ns in before:
            original = source.parent / name
            shutil.copy2(original, temporary_root / name)
        after = sqlite_triplet_signature(source)
        if before != after:
            raise RuntimeError("SQLite database or WAL changed during triplet copy")
        copied_database = temporary_root / source.name
        copied_conn = sqlite3.connect(copied_database, timeout=30)
        copied_conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return finish_sqlite_backup(copied_conn, part, destination)


def backup_sqlite(source: Path, destination: Path) -> tuple[str, int, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    if part.exists():
        part.unlink()
    source_uri = source.resolve().as_uri() + "?mode=ro"
    try:
        source_conn = sqlite3.connect(source_uri, uri=True, timeout=30)
        source_conn.execute(
            "SELECT count(*) FROM sqlite_master"
        ).fetchone()
    except sqlite3.OperationalError:
        try:
            source_conn.close()
        except UnboundLocalError:
            pass
        wal_path = Path(str(source) + "-wal")
        if wal_path.exists() and wal_path.stat().st_size:
            digest, size = backup_sqlite_from_triplet(
                source, part, destination
            )
            return digest, size, "sqlite_backup_from_triplet"
        immutable_uri = source.resolve().as_uri() + "?mode=ro&immutable=1"
        source_conn = sqlite3.connect(immutable_uri, uri=True, timeout=30)
        digest, size = finish_sqlite_backup(source_conn, part, destination)
        return digest, size, "sqlite_backup_immutable_empty_wal"
    digest, size = finish_sqlite_backup(source_conn, part, destination)
    return digest, size, "sqlite_backup"


def git_value(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def write_json_atomic(path: Path, payload: dict) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def create_snapshot(
    repo_root: Path,
    destination_root: Path,
    snapshot_name: str,
    registry: dict,
    include_temporary: bool = False,
    selected_files: dict[str, set[str]] | None = None,
    supplement_manifest: Path | None = None,
) -> Path:
    repo_resolved = repo_root.resolve()
    destination_resolved = destination_root.resolve()
    if destination_resolved == repo_resolved or repo_resolved in destination_resolved.parents:
        raise ValueError("destination must be outside the repository")
    if not SNAPSHOT_NAME.fullmatch(snapshot_name):
        raise ValueError("snapshot name may contain only letters, numbers, dot, dash, underscore")

    files = selected_files
    if files is None:
        files = collect_private_files(
            repo_root, registry, include_temporary=include_temporary
        )
    final_root = destination_resolved / snapshot_name
    partial_root = destination_resolved / f"{snapshot_name}.partial"
    if final_root.exists():
        raise FileExistsError(f"completed snapshot already exists: {final_root}")
    partial_root.mkdir(parents=True, exist_ok=True)

    started = dt.datetime.now(dt.timezone.utc)
    entries: list[dict] = []
    total_files = len(files)
    total_source_bytes = sum(
        (repo_root / rel_path).stat().st_size
        for rel_path in files
        if (repo_root / rel_path).is_file()
    )
    copied_bytes = 0
    print(
        f"private_snapshot_start files={total_files} "
        f"source_bytes={total_source_bytes}",
        flush=True,
    )

    wal_companions = {
        rel_path
        for rel_path in files
        if rel_path.endswith(("-wal", "-shm"))
        and rel_path.rsplit("-", 1)[0] in files
        and is_live_sqlite(rel_path.rsplit("-", 1)[0])
    }
    for index, rel_path in enumerate(sorted(files), start=1):
        source = repo_root / rel_path
        if source.is_symlink():
            raise RuntimeError(f"refusing to dereference private symlink: {rel_path}")
        if rel_path in wal_companions:
            entries.append(
                {
                    "path": rel_path,
                    "categories": sorted(files[rel_path]),
                    "method": "covered_by_sqlite_backup",
                    "source_bytes": source.stat().st_size,
                }
            )
            continue

        destination = partial_root / "workspace" / rel_path
        if destination.exists() and not is_live_sqlite(rel_path):
            source_hash = sha256_file(source)
            destination_hash = sha256_file(destination)
            if (
                source.stat().st_size != destination.stat().st_size
                or source_hash != destination_hash
            ):
                raise RuntimeError(f"existing snapshot file differs: {rel_path}")
            digest = destination_hash
            destination_bytes = destination.stat().st_size
            method = "verified_existing"
        elif is_live_sqlite(rel_path):
            try:
                digest, destination_bytes, method = backup_sqlite(
                    source, destination
                )
            except Exception as exc:
                raise RuntimeError(
                    f"private snapshot failed for {rel_path}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        else:
            digest, destination_bytes = copy_regular_resumable(
                source, destination
            )
            method = "resumable_copy"
        if rel_path == ".secrets":
            destination.chmod(0o600)
        copied_bytes += destination_bytes
        entries.append(
            {
                "path": rel_path,
                "categories": sorted(files[rel_path]),
                "method": method,
                "source_bytes": source.stat().st_size,
                "snapshot_bytes": destination_bytes,
                "sha256": digest,
            }
        )
        if index == total_files or index % 100 == 0:
            print(
                f"private_snapshot_progress files={index}/{total_files} "
                f"copied_bytes={copied_bytes}",
                flush=True,
            )

    manifest = {
        "schema_version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {
            "repository_name": repo_root.name,
            "git_branch": git_value(repo_root, "branch", "--show-current"),
            "git_commit": git_value(repo_root, "rev-parse", "HEAD"),
            "git_dirty": bool(git_value(repo_root, "status", "--porcelain")),
        },
        "snapshot": {
            "name": snapshot_name,
            "include_temporary": include_temporary,
            "supplement_manifest": (
                str(supplement_manifest) if supplement_manifest else None
            ),
            "file_entry_count": len(entries),
            "source_bytes": total_source_bytes,
            "snapshot_bytes": copied_bytes,
            "started_at": started.isoformat(),
        },
        "files": entries,
    }
    write_json_atomic(partial_root / "migration-manifest.json", manifest)
    partial_root.replace(final_root)
    print(
        f"private_snapshot_complete files={len(entries)} "
        f"snapshot_bytes={copied_bytes}",
        flush=True,
    )
    return final_root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--snapshot-name",
        default=f"research-tools-private-{dt.date.today():%Y%m%d}",
    )
    parser.add_argument("--include-temporary", action="store_true")
    parser.add_argument(
        "--supplement-manifest",
        type=Path,
        help=(
            "copy only currently registered private paths absent from an "
            "earlier snapshot manifest; intended for a coverage supplement, "
            "not for detecting changed files"
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="copy data; without this flag only print the planned scope",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    registry = load_registry()
    files = collect_private_files(
        ROOT, registry, include_temporary=args.include_temporary
    )
    supplement_manifest = args.supplement_manifest
    if supplement_manifest:
        supplement_manifest = supplement_manifest.expanduser().resolve()
        files = exclude_manifest_paths(files, supplement_manifest)
    total_bytes = sum(
        (ROOT / rel_path).stat().st_size
        for rel_path in files
        if (ROOT / rel_path).is_file()
    )
    print(
        f"private_snapshot_plan files={len(files)} "
        f"source_bytes={total_bytes} source_human={human_bytes(total_bytes)} "
        f"temporary={'included' if args.include_temporary else 'excluded'}"
    )
    if not args.execute:
        print("dry_run=true; pass --execute to create the snapshot")
        return 0
    create_snapshot(
        ROOT,
        args.destination,
        args.snapshot_name,
        registry,
        include_temporary=args.include_temporary,
        selected_files=files,
        supplement_manifest=supplement_manifest,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
