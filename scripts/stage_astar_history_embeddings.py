#!/usr/bin/env python3
"""Build a resumable, memory-mapped semantic pack without replacing live assets.

The document template, model, normalization, and title-only handling follow the
existing semantic service. SQLite is streamed in small chunks. Existing vectors
are copied when their metadata quality is still current; new/stale rows are
encoded with the locally cached model. No network or paid model calls are used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from services.astar_history_service import connect, digest, utc_now, write_new_json
from services.astar_semantic_service import MODEL_NAME, _doc_text
from services.astar_semantic_input_fingerprints import (SCHEMA as INPUT_HASH_SCHEMA, input_fingerprint,
                                                       fingerprint_known, seed_input_matches, forced_ids)

LOG = logging.getLogger(__name__)


def prepare(run_dir, pack_dir, seed_source=None):
    import numpy as np
    if (pack_dir / "manifest.json").exists():
        return json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    pack_dir.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    db_path = Path(manifest["db_path"])
    conn = connect(db_path, readonly=True)
    try:
        ids = np.fromiter((row["id"] for row in conn.execute(
            "SELECT id FROM astar_articles WHERE is_duplicate=0 AND title IS NOT NULL ORDER BY id")), dtype=np.int64)
    finally:
        conn.close()
    np.save(pack_dir / "astar_emb_ids.npy", ids)
    matrix = np.lib.format.open_memmap(pack_dir / "astar_emb.npy", mode="w+", dtype="float32", shape=(len(ids), 384))
    matrix.flush()
    del matrix
    done = np.lib.format.open_memmap(pack_dir / "completed.npy", mode="w+", dtype="uint8", shape=(len(ids),))
    done[:] = 0
    done.flush()
    del done
    quality = np.lib.format.open_memmap(pack_dir / "title_only_mask.npy", mode="w+", dtype="uint8", shape=(len(ids),))
    quality[:] = 0
    quality.flush()
    del quality
    fingerprints = np.lib.format.open_memmap(pack_dir / 'astar_emb_input_hashes.npy', mode='w+', dtype='uint8', shape=(len(ids), 32))
    fingerprints[:] = 0
    fingerprints.flush()
    del fingerprints
    seed_dir = pack_dir / "seed"
    seed_dir.mkdir()
    seed_hashes = {}
    seed_source = Path(seed_source or ROOT / "data").resolve()
    for name in ("astar_emb.npy", "astar_emb_ids.npy", "astar_emb_meta.json", "astar_emb_titleonly_ids.npy", 'astar_emb_input_hashes.npy'):
        source = seed_source / name
        if not source.exists():
            continue
        target = seed_dir / name
        with source.open("rb") as inp, target.open("xb") as out:
            for chunk in iter(lambda: inp.read(1024 * 1024), b""):
                out.write(chunk)
        seed_hashes[name] = digest(target)
    state = sqlite3.connect(pack_dir / "checkpoint.sqlite3")
    state.executescript("""
        CREATE TABLE runs(id INTEGER PRIMARY KEY,started_at TEXT,finished_at TEXT,pid INTEGER,status TEXT,details TEXT);
        CREATE TABLE batches(id INTEGER PRIMARY KEY,first_position INTEGER,last_position INTEGER,
                             copied_rows INTEGER,encoded_rows INTEGER,committed_at TEXT);
    """)
    state.close()
    result = {"created_at": utc_now(), "db_path": str(db_path), "run_dir": str(run_dir),
              "pack_dir": str(pack_dir), "model": MODEL_NAME, "dimension": 384,
              "target_count": len(ids), "max_target_id": int(ids[-1]) if len(ids) else 0,
              "document_template": "title + '. ' + abstract[:1500], or title when no abstract",
              "dtype": "float32", "normalize_embeddings": True,
              "offline_model_only": True, "seed_hashes": seed_hashes,
              'input_fingerprint_schema': INPUT_HASH_SCHEMA,
              "seed_source": str(seed_source),
              "script_sha256": digest(__file__), "source_service_sha256": digest(ROOT / "services/astar_semantic_service.py"),
              "frozen_scope_note": "All eligible live IDs at preparation time; later imports require an additional pack pass."}
    write_new_json(pack_dir / "manifest.json", result)
    return result


def build(run_dir, pack_dir, batch_size=32, threads=6, safe_native_cpu=False, seed_source=None,
          encoder_backend='pytorch', onnx_model=None, tokenizer_dir=None, backend_validation=None,
          force_input_ids=None):
    import importlib.metadata
    import numpy as np
    validation = None
    if encoder_backend == 'onnx':
        if not all((onnx_model, tokenizer_dir, backend_validation)):
            raise ValueError('ONNX encoding requires model, tokenizer and a verified numerical receipt')
        from services.astar_onnx_validation import validate_receipt
        validation = validate_receipt(backend_validation, onnx_model, tokenizer_dir)
    manifest = prepare(run_dir, pack_dir, seed_source)
    if (pack_dir / 'astar_emb_meta.json').exists():
        raise ValueError('Completed generations are immutable; create a new incremental pack')
    force_reencode = forced_ids(force_input_ids)
    ids = np.load(pack_dir / "astar_emb_ids.npy", mmap_mode="r")
    mat = np.lib.format.open_memmap(pack_dir / "astar_emb.npy", mode="r+")
    done = np.lib.format.open_memmap(pack_dir / "completed.npy", mode="r+")
    title_only = np.lib.format.open_memmap(pack_dir / "title_only_mask.npy", mode="r+")
    fingerprint_path = pack_dir / 'astar_emb_input_hashes.npy'
    if fingerprint_path.exists():
        fingerprints = np.load(fingerprint_path, mmap_mode='r+')
    else:
        # Existing completed rows have unknown inputs. Do not assign current
        # metadata to those old vectors as if it were their original input.
        fingerprints = np.lib.format.open_memmap(fingerprint_path, mode='w+', dtype='uint8', shape=(len(ids), 32))
        fingerprints[:] = 0
        fingerprints.flush()
    if fingerprints.shape != (len(ids), 32) or fingerprints.dtype != np.uint8:
        raise ValueError('Invalid staged encoded-input fingerprint layout')
    old_ids = np.load(pack_dir / "seed/astar_emb_ids.npy", mmap_mode="r")
    old_mat = np.load(pack_dir / "seed/astar_emb.npy", mmap_mode="r")
    old_lookup = {int(identifier): position for position, identifier in enumerate(old_ids)}
    sidecar = pack_dir / "seed/astar_emb_titleonly_ids.npy"
    old_titleonly = set(np.load(sidecar).tolist()) if sidecar.exists() else set()
    old_fingerprint_path = pack_dir / 'seed/astar_emb_input_hashes.npy'
    old_fingerprints = np.load(old_fingerprint_path, mmap_mode='r') if old_fingerprint_path.exists() else None
    if old_fingerprints is not None and (old_fingerprints.shape != (len(old_ids), 32) or old_fingerprints.dtype != np.uint8):
        raise ValueError('Invalid seed encoded-input fingerprint layout')
    if old_mat.shape != (len(old_ids), 384):
        raise ValueError("existing vector and ID shapes do not agree")
    state = sqlite3.connect(pack_dir / "checkpoint.sqlite3")
    state.execute("INSERT INTO runs(started_at,pid,status,details) VALUES (?,?,?,?)",
                  (utc_now(), os.getpid(), "RUNNING", json.dumps({"batch_size": batch_size, "threads": threads,
                   "safe_native_cpu": safe_native_cpu, "encoder_backend": encoder_backend, "validation": validation,
                   'input_fingerprint_schema': INPUT_HASH_SCHEMA, 'force_input_ids_path': str(force_input_ids) if force_input_ids else None,
                   'forced_ids_sha256': digest(force_input_ids) if force_input_ids else None})))
    run_id = state.execute("SELECT last_insert_rowid()").fetchone()[0]
    state.commit()
    db = connect(manifest["db_path"], readonly=True)
    model = None
    copied_total = encoded_total = 0
    try:
        for first in range(0, len(ids), 256):
            last = min(first + 256, len(ids))
            candidates = [position for position in range(first, last) if not done[position]
                          or fingerprint_known(fingerprints[position]) or int(ids[position]) in force_reencode
                          or manifest.get('input_fingerprint_schema') == INPUT_HASH_SCHEMA]
            if not candidates:
                continue
            from services.system_memory_gate import require_headroom
            require_headroom()
            keys = [int(ids[position]) for position in candidates]
            placeholders = ",".join("?" for _ in keys)
            rows = {row["id"]: row for row in db.execute(
                f"SELECT id,title,abstract,is_duplicate FROM astar_articles WHERE id IN ({placeholders})", keys)}
            positions, encode_positions, texts, input_hashes = [], [], [], []
            copied = 0
            for position, key in zip(candidates, keys):
                row = rows.get(key)
                if row is None or row["is_duplicate"] or row["title"] is None:
                    raise ValueError(f"frozen target {key} is no longer an eligible live article")
                has_abstract = bool((row["abstract"] or "").strip())
                current_input = input_fingerprint(row['title'], row['abstract'])
                if done[position] and seed_input_matches(fingerprints[position], current_input):
                    continue
                positions.append(position)
                done[position] = 0
                title_only[position] = 0 if has_abstract else 1
                old_position = old_lookup.get(key)
                seed_input = old_fingerprints[old_position] if old_fingerprints is not None and old_position is not None else None
                stale = (key in force_reencode or (key in old_titleonly and has_abstract)
                         or not seed_input_matches(seed_input, current_input))
                if old_position is not None and not stale:
                    mat[position] = old_mat[old_position]
                    fingerprints[position] = seed_input
                    copied += 1
                else:
                    encode_positions.append(position)
                    texts.append(_doc_text(row["title"], row["abstract"]))
                    input_hashes.append(current_input)
            if not positions:
                continue
            if texts:
                if model is None:
                    if encoder_backend == 'onnx':
                        from services.astar_onnx_encoder import OnnxBgeEncoder
                        model = OnnxBgeEncoder(onnx_model, tokenizer_dir, threads)
                    else:
                        import torch
                        from sentence_transformers import SentenceTransformer
                        torch.set_num_threads(threads)
                        torch.set_num_interop_threads(1 if safe_native_cpu else 2)
                        if safe_native_cpu:
                            torch.backends.mkldnn.enabled = False
                        model = SentenceTransformer(MODEL_NAME, device="cpu", local_files_only=True,
                                                    model_kwargs={"attn_implementation": "eager"} if safe_native_cpu else {})
                    LOG.info("Loaded offline %s model on CPU; threads=%s batch_size=%s", encoder_backend, threads, batch_size)
                if encoder_backend == 'onnx':
                    output = model.encode(texts, batch_size=batch_size)
                else:
                    output = model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                                          show_progress_bar=False).astype("float32")
                if output.shape != (len(texts), 384) or not np.isfinite(output).all():
                    raise ValueError("model returned invalid vector rows")
                for position, vector, actual_input in zip(encode_positions, output, input_hashes):
                    mat[position] = vector
                    fingerprints[position] = actual_input
            # Flush vectors before checkpoint flags, so interruption can safely
            # recompute an unfinished chunk rather than trust partial writes.
            mat.flush()
            title_only.flush()
            fingerprints.flush()
            done[positions] = 1
            done.flush()
            copied_total += copied
            encoded_total += len(texts)
            state.execute("INSERT INTO batches(first_position,last_position,copied_rows,encoded_rows,committed_at) VALUES (?,?,?,?,?)",
                          (first, last, copied, len(texts), utc_now()))
            state.commit()
            if (first // 256) % 20 == 0:
                LOG.info("Complete=%s/%s copied=%s encoded=%s", int(done.sum()), len(ids), copied_total, encoded_total)
        np.save(pack_dir / "astar_emb_titleonly_ids.npy", np.asarray(ids[np.asarray(title_only, dtype=bool)], dtype=np.int64))
        meta = {"model": MODEL_NAME, "dim": 384, "count": len(ids),
                "built_at": datetime.now().isoformat(), "title_only_count": int(title_only.sum()),
                "generation": "history-2010-staged", "local_model_only": True,
                "encoder_backend": encoder_backend, "backend_validation": validation}
        meta.update(input_fingerprint_schema=INPUT_HASH_SCHEMA,
                    input_fingerprint_known_count=int(np.any(fingerprints, axis=1).sum()))
        if (pack_dir / "astar_emb_meta.json").exists():
            raise ValueError("completed pack metadata exists; use verification instead of rebuilding it")
        write_new_json(pack_dir / "astar_emb_meta.json", meta)
        details = {"target_count": len(ids), "copied_this_pass": copied_total, "encoded_this_pass": encoded_total,
                   "completed_rows": int(done.sum()), "encoder_backend": encoder_backend,
                   "packages": {name: importlib.metadata.version(name) for name in
                       (("onnxruntime", "tokenizers", "numpy") if encoder_backend == 'onnx' else ("torch", "sentence-transformers", "transformers", "numpy"))}}
        state.execute("UPDATE runs SET finished_at=?,status='COMPLETE',details=? WHERE id=?",
                      (utc_now(), json.dumps(details), run_id))
        state.commit()
        return details
    except BaseException as exc:
        state.execute("UPDATE runs SET finished_at=?,status='INTERRUPTED',details=? WHERE id=?",
                      (utc_now(), json.dumps({"error_type": type(exc).__name__, "message": str(exc)[:250]}), run_id))
        state.commit()
        raise
    finally:
        db.close()
        state.close()


def verify(pack_dir):
    import numpy as np
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    ids = np.load(pack_dir / "astar_emb_ids.npy", mmap_mode="r")
    mat = np.load(pack_dir / "astar_emb.npy", mmap_mode="r")
    done = np.load(pack_dir / "completed.npy", mmap_mode="r")
    fingerprint_path = pack_dir / 'astar_emb_input_hashes.npy'
    fingerprints = np.load(fingerprint_path, mmap_mode='r') if fingerprint_path.exists() else None
    if fingerprints is not None and (fingerprints.shape != (len(ids), 32) or fingerprints.dtype != np.uint8):
        raise ValueError('Invalid encoded-input fingerprint layout')
    invalid = 0
    min_norm, max_norm = 2.0, 0.0
    for first in range(0, len(ids), 4096):
        chunk = np.asarray(mat[first:first + 4096])
        norms = np.linalg.norm(chunk, axis=1)
        invalid += int((~np.isfinite(chunk)).any(axis=1).sum())
        invalid += int((np.abs(norms - 1) > 1e-3).sum())
        min_norm, max_norm = min(min_norm, float(norms.min())), max(max_norm, float(norms.max()))
    db = connect(manifest["db_path"], readonly=True)
    try:
        live_ids = {row["id"] for row in db.execute("SELECT id FROM astar_articles WHERE is_duplicate=0 AND title IS NOT NULL")}
        id_set = set(int(value) for value in ids)
        sample_2010 = [row["id"] for row in db.execute("SELECT id FROM astar_articles WHERE is_duplicate=0 AND publication_year=2010 ORDER BY id LIMIT 10")]
        sidecar_path = pack_dir / 'astar_emb_titleonly_ids.npy'
        title_only_ids = np.load(sidecar_path, mmap_mode='r') if sidecar_path.exists() else ids[np.load(pack_dir / 'title_only_mask.npy', mmap_mode='r').astype(bool)]
        stale_title_only = 0
        for first in range(0, len(title_only_ids), 800):
            keys = [int(value) for value in title_only_ids[first:first + 800]]
            stale_title_only += db.execute(
                "SELECT COUNT(*) FROM astar_articles WHERE is_duplicate=0 AND trim(COALESCE(abstract,''))<>'' "
                "AND id IN (%s)" % ','.join('?' for _ in keys), keys).fetchone()[0]
        unknown_inputs = stale_inputs = 0
        if fingerprints is None:
            unknown_inputs = len(ids)
        else:
            for first in range(0, len(ids), 800):
                keys = [int(value) for value in ids[first:first + 800]]
                rows = {row['id']: row for row in db.execute('SELECT id,title,abstract FROM astar_articles WHERE id IN (' +
                    ','.join('?' for _ in keys) + ')', keys)}
                for position, key in enumerate(keys, first):
                    if not fingerprint_known(fingerprints[position]):
                        unknown_inputs += 1
                    elif key in rows and not seed_input_matches(fingerprints[position], input_fingerprint(rows[key]['title'], rows[key]['abstract'])):
                        stale_inputs += 1
    finally:
        db.close()
    result = {"created_at": utc_now(), "pack_dir": str(pack_dir), "shape": list(mat.shape),
              "completed_rows": int(done.sum()), "frozen_target_count": manifest["target_count"],
              "duplicate_ids": len(ids) - len(id_set), "invalid_or_unnormalized_rows": invalid,
              "min_norm": min_norm, "max_norm": max_norm,
              "frozen_ids_missing_from_live_database": len(id_set - live_ids),
              "live_ids_not_yet_in_pack": len(live_ids - id_set),
              "title_only_vectors_with_new_abstract": stale_title_only,
              'input_fingerprints_missing_or_unknown': unknown_inputs,
              'input_fingerprints_changed': stale_inputs,
              "sample_2010_ids_covered": all(identifier in id_set for identifier in sample_2010),
              "live_assets_replaced": False}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    write_new_json(pack_dir / ("verification_" + stamp + ".json"), result)
    return result


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--pack-dir", type=Path)
    parser.add_argument("--seed-dir", type=Path,
                        help="reuse a completed verified pack for an incremental generation")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--safe-native-cpu", action="store_true",
                        help="disable optimized CPU attention/oneDNN after an evidenced native-library crash")
    parser.add_argument('--encoder-backend', choices=['pytorch', 'onnx'], default='pytorch')
    parser.add_argument('--onnx-model', type=Path)
    parser.add_argument('--tokenizer-dir', type=Path)
    parser.add_argument('--backend-validation', type=Path)
    parser.add_argument('--force-input-ids', type=Path, help='audited input-drift IDs that require re-encoding')
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 128 or not 1 <= args.threads <= 8:
        parser.error("batch size must be 1–128 and CPU threads 1–8")
    run_dir = args.run_dir.resolve()
    pack_dir = (args.pack_dir or run_dir / "semantic_pack").resolve()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = build(run_dir, pack_dir, args.batch_size, args.threads, args.safe_native_cpu, args.seed_dir,
                   args.encoder_backend, args.onnx_model, args.tokenizer_dir, args.backend_validation,
                   args.force_input_ids) if args.action == "build" else verify(pack_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
