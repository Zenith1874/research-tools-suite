#!/usr/bin/env python3
"""Resume a private embedding pack only when system commit headroom is adequate."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.system_memory_gate import memory_headroom


def run(run_dir, pack_dir, output_dir, encoder_backend='pytorch', onnx_model=None,
        tokenizer_dir=None, backend_validation=None, force_input_ids=None,
        threads=None, batch_size=4):
    if encoder_backend == 'onnx' and not all((onnx_model, tokenizer_dir, backend_validation)):
        raise ValueError('ONNX wrapper requires its complete verified artifact bundle')
    commit_threshold = 1.75 if encoder_backend == 'onnx' else 5
    physical_threshold = 2 if encoder_backend == 'onnx' else 3
    threads = threads if threads is not None else (2 if encoder_backend == 'onnx' else 1)
    if not 1 <= threads <= 8 or batch_size not in (1, 2, 4, 8, 16):
        raise ValueError('Unsupported CPU thread or batch-size profile')
    child_environment = os.environ.copy()
    controlled_threads = {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                          'TOKENIZERS_PARALLELISM': 'false'}
    child_environment.update(controlled_threads)
    output_dir.mkdir(parents=True, exist_ok=False)
    with (output_dir / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump({"created_at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
                   "run_dir": str(run_dir), "pack_dir": str(pack_dir), "start_commit_threshold_gib": commit_threshold,
                   "start_physical_threshold_gib": physical_threshold, "batch_size": batch_size, "threads": threads,
                   "encoder_backend": encoder_backend, "controlled_child_threads": controlled_threads,
                   'force_input_ids': str(force_input_ids) if force_input_ids else None,
                   "live_assets_replaced": False}, stream, indent=2)
    attempt = 0
    while True:
        status = memory_headroom()
        if status and (status["commit_available"] < commit_threshold * 2**30 or status["physical_available"] < physical_threshold * 2**30):
            print(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "state": "WAITING_MEMORY",
                              "headroom": status}), flush=True)
            time.sleep(30)
            continue
        attempt += 1
        stdout = output_dir / ("attempt_%02d.stdout.log" % attempt)
        stderr = output_dir / ("attempt_%02d.stderr.log" % attempt)
        args = [sys.executable, "-u", str(ROOT / "scripts/stage_astar_history_embeddings.py"), "build",
                "--run-dir", str(run_dir), "--pack-dir", str(pack_dir), "--batch-size", str(batch_size), "--threads", str(threads), "--safe-native-cpu"]
        if encoder_backend == 'onnx':
            args += ['--encoder-backend', 'onnx', '--onnx-model', str(onnx_model), '--tokenizer-dir', str(tokenizer_dir),
                     '--backend-validation', str(backend_validation)]
        if force_input_ids is not None:
            args += ['--force-input-ids', str(force_input_ids)]
        with stdout.open("xb") as out, stderr.open("xb") as err:
            process = subprocess.Popen(args, cwd=ROOT, stdout=out, stderr=err,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                       env=child_environment)
            receipt = {"at": datetime.now(timezone.utc).isoformat(), "child_pid": process.pid,
                       "arguments": args, "headroom_at_start": status}
            with (output_dir / ("attempt_%02d.launch.json" % attempt)).open("x", encoding="utf-8") as stream:
                json.dump(receipt, stream, indent=2)
            print(json.dumps({"state": "BUILDING", "child_pid": process.pid, "attempt": attempt}), flush=True)
            code = process.wait()
        if code == 0:
            return {"finished_at": datetime.now(timezone.utc).isoformat(), "state": "COMPLETE", "attempts": attempt}
        conn = sqlite3.connect((pack_dir / "checkpoint.sqlite3").as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        latest = dict(conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone());conn.close()
        details = json.loads(latest.get("details") or "{}")
        if latest["status"] == "INTERRUPTED" and details.get("error_type") == "MemoryError":
            print(json.dumps({"state": "WAITING_MEMORY_AFTER_CHECKPOINT", "attempt": attempt}), flush=True)
            time.sleep(30)
            continue
        with (output_dir / "attention_required.json").open("x", encoding="utf-8") as stream:
            json.dump({"exit_code": code, "latest_run": latest, "state": "REVIEW_REQUIRED"}, stream, indent=2)
        raise RuntimeError("Embedding child stopped for an unclassified reason; inspect its retained checkpoint/log")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument('--encoder-backend', choices=['pytorch', 'onnx'], default='pytorch')
    parser.add_argument('--onnx-model', type=Path)
    parser.add_argument('--tokenizer-dir', type=Path)
    parser.add_argument('--backend-validation', type=Path)
    parser.add_argument('--force-input-ids', type=Path)
    parser.add_argument('--threads', type=int, choices=range(1, 9))
    parser.add_argument('--batch-size', type=int, choices=[1, 2, 4, 8, 16], default=4)
    args = parser.parse_args()
    print(json.dumps(run(args.run_dir.resolve(), args.pack_dir.resolve(), args.output_dir.resolve(),
                         args.encoder_backend, args.onnx_model, args.tokenizer_dir, args.backend_validation,
                         args.force_input_ids, args.threads, args.batch_size), indent=2))


if __name__ == "__main__":
    main()
