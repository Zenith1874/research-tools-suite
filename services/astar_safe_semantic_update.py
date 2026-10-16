"""Bounded ONNX deltas, streamed candidate files, backups and new-only scores.

Source articles and existing classification values are never rewritten here.
An interrupted activation journal stops later automatic runs for explicit review.
"""

from array import array
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

import numpy as np

from services.astar_semantic_backend import load_verified_model, require_encoder_headroom
from services.astar_semantic_service import PROFILE_ASPECTS, _doc_text

LOG = logging.getLogger(__name__)
NAMES = ('astar_emb.npy', 'astar_emb_ids.npy', 'astar_emb_titleonly_ids.npy',
         'astar_emb_input_hashes.npy', 'astar_emb_meta.json')
SCHEMA = 'sha256-doc-text-utf8-v1'
CHUNK_ROWS = 4096


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)


def copy_new(source, target):
    with Path(source).open('rb') as inp, Path(target).open('xb') as out:
        shutil.copyfileobj(inp, out, 1024 * 1024)


def signature(conn):
    return {'max_article_id': str(conn.execute('SELECT max(id) FROM astar_articles').fetchone()[0]),
            'article_revision_watermark': str(conn.execute('SELECT max(updated_at) FROM astar_articles').fetchone()[0])
            + ' | ' + str(conn.execute('SELECT max(created_at) FROM astar_articles').fetchone()[0]),
            'classification_revision_watermark': str(conn.execute(
                'SELECT max(classified_at) FROM astar_article_classifications').fetchone()[0])}


def fingerprint(title, abstract):
    return hashlib.sha256(_doc_text(title, abstract).encode('utf-8')).digest()


def asset_stats(data_dir):
    return {name: (Path(data_dir, name).stat().st_size, Path(data_dir, name).stat().st_mtime_ns)
            for name in NAMES}


def matrix_header(path):
    with Path(path).open('rb') as stream:
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
        elif version == (2, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_2_0(stream)
        else:
            raise ValueError('Unsupported semantic matrix NPY version')
        if fortran or dtype != np.dtype('float32') or len(shape) != 2 or shape[1] != 384:
            raise ValueError('Semantic matrix must be C-order FP32 with 384 columns')
        if Path(path).stat().st_size != stream.tell() + shape[0] * 384 * 4:
            raise ValueError('Semantic matrix file size differs from its header')
        return stream.tell(), shape


@contextmanager
def update_lock(data_dir):
    """Serialize safe semantic writers across processes; keep the lock file."""
    path = Path(data_dir) / 'astar_semantic_update.lock'
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def check_unfinished(run_root):
    if not run_root.exists():
        return
    for run in run_root.iterdir():
        if run.is_dir() and (run / 'activation_intent.json').exists():
            if not (run / 'complete.json').exists() and not (run / 'rolled_back.json').exists():
                raise RuntimeError(f'Unfinished semantic activation needs review: {run}')


def verify_accepted_seed(metadata, data_dir, actual_hashes):
    """Do not promote an altered but numerically valid matrix to an accepted seed."""
    if metadata.get('safe_update_receipt'):
        receipt = json.loads(Path(metadata['safe_update_receipt']).read_text(encoding='utf-8'))
        expected = receipt.get('active_asset_hashes') if receipt.get('success') else None
    else:
        # Preserve the existing recovery receipts; match by the active generation
        # marker instead of assuming a particular PID or article maximum.
        recovery = (Path(data_dir).parent / 'backups/abdc_A_extension_20261006'
                    / 'recovery_20261009T024300Z')
        expected = None
        for path in recovery.glob('semantic_*/guarded_activation_postcheck.json'):
            receipt = json.loads(path.read_text(encoding='utf-8'))
            hashes = receipt.get('live_asset_hashes') or {}
            if receipt.get('passed') and hashes.get('astar_emb_meta.json') == actual_hashes['astar_emb_meta.json']:
                expected = hashes
                break
    if not expected or actual_hashes != expected:
        raise ValueError('Accepted semantic seed asset hash mismatch; reviewed recovery is required')


def plan_update(db_path, data_dir, max_delta_rows=2000):
    data_dir = Path(data_dir)
    before = asset_stats(data_dir)
    metadata = json.loads((data_dir / 'astar_emb_meta.json').read_text(encoding='utf-8'))
    if metadata.get('input_fingerprint_schema') != SCHEMA or metadata.get('encoder_backend') != 'onnx':
        raise ValueError('A verified ONNX pack with known input fingerprints is required')
    ids = np.load(data_dir / 'astar_emb_ids.npy', allow_pickle=False)
    hashes = np.load(data_dir / 'astar_emb_input_hashes.npy', allow_pickle=False)
    title_only = np.load(data_dir / 'astar_emb_titleonly_ids.npy', allow_pickle=False)
    offset, shape = matrix_header(data_dir / 'astar_emb.npy')
    if (ids.ndim != 1 or ids.dtype != np.int64 or not len(ids) or len(ids) != metadata.get('count')
            or shape != (len(ids), 384) or not np.all(ids[1:] > ids[:-1])
            or hashes.shape != (len(ids), 32) or hashes.dtype != np.uint8
            or not np.all(np.any(hashes, axis=1))):
        raise ValueError('The accepted ID/fingerprint/matrix layout is invalid or unknown')
    if (title_only.ndim != 1 or len(title_only) != metadata.get('title_only_count')
            or not np.all(title_only[1:] > title_only[:-1])
            or not np.isin(title_only, ids).all()):
        raise ValueError('The accepted title-only sidecar is invalid')
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    version = conn.execute('PRAGMA data_version').fetchone()[0]
    conn.execute('BEGIN')
    target_ids, target_title_only = array('q'), array('q')
    target_hashes = bytearray()
    delta, position = [], 0
    try:
        rows = conn.execute('SELECT id,title,abstract FROM astar_articles '
                            'WHERE is_duplicate=0 AND title IS NOT NULL ORDER BY id')
        for row in rows:
            identifier = int(row['id'])
            if position < len(ids) and int(ids[position]) < identifier:
                raise ValueError('A previously encoded record became ineligible; reviewed recovery is required')
            is_new = position == len(ids) or int(ids[position]) != identifier
            if is_new and position < len(ids):
                raise ValueError('An uncovered historical ID requires reviewed recovery')
            actual = fingerprint(row['title'], row['abstract'])
            changed = is_new or hashes[position].tobytes() != actual
            # Preserve an already accepted empty-input vector; do not infer that
            # a newly empty/new record is suitable for automatic encoding.
            if changed and not _doc_text(row['title'], row['abstract']):
                raise ValueError(f'Article {identifier} has no encodable text')
            if changed:
                delta.append({'id': identifier, 'title': row['title'], 'abstract': row['abstract'],
                              'fingerprint': actual.hex(), 'new': is_new,
                              'base_position': None if is_new else position})
                if len(delta) > max_delta_rows:
                    raise ValueError(f'Delta exceeds the automatic {max_delta_rows}-row limit; no full re-encoding is started')
            target_ids.append(identifier)
            target_hashes.extend(actual)
            if not (row['abstract'] or '').strip():
                target_title_only.append(identifier)
            if not is_new:
                position += 1
        if position != len(ids):
            raise ValueError('Previously encoded records are no longer eligible; reviewed recovery is required')
        if before != asset_stats(data_dir):
            raise RuntimeError('Active semantic files changed during planning')
        return {'conn': conn, 'data_version': version, 'source_signature': signature(conn),
                'metadata': metadata, 'base_ids': ids, 'base_hashes': hashes,
                'base_stats': before, 'base_offset': offset, 'delta': delta,
                'ids': np.frombuffer(target_ids, dtype=np.int64),
                'hashes': np.frombuffer(target_hashes, dtype=np.uint8).reshape(-1, 32),
                'title_only': np.frombuffer(target_title_only, dtype=np.int64)}
    except BaseException:
        conn.close()
        raise


def summary(plan):
    new = sum(row['new'] for row in plan['delta'])
    return {'success': True, 'total': len(plan['ids']), 'base_rows': len(plan['base_ids']),
            'new_rows': new, 'changed_text_rows': len(plan['delta']) - new,
            'delta_rows': len(plan['delta']), 'source_signature': plan['source_signature'],
            'encoder_backend': 'verified-offline-onnx', 'full_corpus_reembedded': False}


def check_vectors(values):
    if values.ndim != 2 or values.shape[1] != 384 or values.dtype != np.float32:
        raise ValueError('Invalid delta/candidate vector layout')
    norms = np.linalg.norm(values, axis=1)
    if not np.isfinite(values).all() or (np.abs(norms - 1) > 1e-3).any():
        raise ValueError('Invalid or unnormalized semantic vectors')
    return norms


def stage_pack(plan, data_dir, candidate, vectors, encoder, run):
    """Write the matrix with small file buffers, never a full output mapping."""
    candidate.mkdir()
    replacements = {row['base_position']: index for index, row in enumerate(plan['delta']) if not row['new']}
    new_positions = [index for index, row in enumerate(plan['delta']) if row['new']]
    with (Path(data_dir) / 'astar_emb.npy').open('rb') as inp, (candidate / 'astar_emb.npy').open('xb') as out:
        inp.seek(plan['base_offset'])
        np.lib.format.write_array_header_1_0(out, {'descr': np.dtype('float32').str,
            'fortran_order': False, 'shape': (len(plan['ids']), 384)})
        for first in range(0, len(plan['base_ids']), CHUNK_ROWS):
            last = min(first + CHUNK_ROWS, len(plan['base_ids']))
            raw = inp.read((last - first) * 384 * 4)
            if len(raw) != (last - first) * 384 * 4:
                raise ValueError('The accepted vector matrix was truncated')
            block = np.frombuffer(raw, dtype=np.float32).reshape(-1, 384).copy()
            for position in range(first, last):
                if position in replacements:
                    block[position - first] = vectors[replacements[position]]
            check_vectors(block)
            out.write(block.tobytes())
        if new_positions:
            out.write(vectors[new_positions].tobytes())
        out.flush()
        os.fsync(out.fileno())
    for name, values in [('astar_emb_ids.npy', plan['ids']),
                         ('astar_emb_input_hashes.npy', plan['hashes']),
                         ('astar_emb_titleonly_ids.npy', plan['title_only'])]:
        with (candidate / name).open('xb') as stream:
            np.save(stream, values, allow_pickle=False)
    metadata = dict(plan['metadata'])
    metadata.update(count=len(plan['ids']), built_at=datetime.now().isoformat(),
                    title_only_count=len(plan['title_only']), input_fingerprint_known_count=len(plan['ids']),
                    generation='safe-onnx-incremental-' + run.name, source_signature=plan['source_signature'],
                    safe_update_receipt=str(run / 'complete.json'))
    if getattr(encoder, 'validation', None):
        metadata['backend_validation'] = encoder.validation
    if getattr(encoder, 'runtime_paths', None):
        metadata['onnx_runtime'] = encoder.runtime_paths
    write_json(candidate / 'astar_emb_meta.json', metadata)
    verify_staged_rows(plan, data_dir, candidate, vectors)


def verify_staged_rows(plan, data_dir, candidate, vectors):
    """Independently compare unchanged rows and every staged replacement."""
    offset, shape = matrix_header(candidate / 'astar_emb.npy')
    if shape != (len(plan['ids']), 384):
        raise ValueError('Candidate vector shape differs from its accepted scope')
    replacements = {row['base_position']: index for index, row in enumerate(plan['delta']) if not row['new']}
    new_positions = [index for index, row in enumerate(plan['delta']) if row['new']]
    with (Path(data_dir) / 'astar_emb.npy').open('rb') as old, (candidate / 'astar_emb.npy').open('rb') as staged:
        old.seek(plan['base_offset'])
        staged.seek(offset)
        for first in range(0, len(plan['base_ids']), CHUNK_ROWS):
            last = min(first + CHUNK_ROWS, len(plan['base_ids']))
            expected = np.frombuffer(old.read((last - first) * 1536), dtype=np.float32).reshape(-1, 384).copy()
            actual = np.frombuffer(staged.read((last - first) * 1536), dtype=np.float32).reshape(-1, 384)
            for position in range(first, last):
                if position in replacements:
                    expected[position - first] = vectors[replacements[position]]
            if not np.array_equal(expected, actual):
                raise ValueError('Unchanged vectors or staged replacement rows differ')
        if new_positions:
            appended = np.frombuffer(staged.read(len(new_positions) * 1536), dtype=np.float32).reshape(-1, 384)
            if not np.array_equal(appended, vectors[new_positions]):
                raise ValueError('Appended vectors differ from the encoded delta')
        if staged.read(1):
            raise ValueError('Candidate contains extra vector data')
    for name, expected in [('astar_emb_ids.npy', plan['ids']), ('astar_emb_input_hashes.npy', plan['hashes']),
                           ('astar_emb_titleonly_ids.npy', plan['title_only'])]:
        if not np.array_equal(np.load(candidate / name, allow_pickle=False), expected):
            raise ValueError(f'Candidate {name} differs from accepted inputs')


def verify_delta_inputs(conn, delta):
    for first in range(0, len(delta), 400):
        part = delta[first:first + 400]
        expected = {row['id']: row for row in part}
        marks = ','.join('?' for _ in part)
        actual = conn.execute('SELECT id,title,abstract,is_duplicate FROM astar_articles WHERE id IN (' + marks + ')',
                              list(expected)).fetchall()
        if len(actual) != len(part) or any(row['is_duplicate'] or row['title'] is None or
                fingerprint(row['title'], row['abstract']).hex() != expected[row['id']]['fingerprint'] for row in actual):
            raise RuntimeError('Encoded inputs changed before activation')


def restore_assets(before, data_dir, expected):
    for name in NAMES:
        temporary = Path(data_dir) / (name + '.rollback_' + uuid.uuid4().hex + '.tmp')
        copy_new(before / name, temporary)
        os.replace(temporary, Path(data_dir) / name)
    actual = {name: digest(Path(data_dir) / name) for name in NAMES}
    if actual != expected:
        raise RuntimeError('Semantic rollback hash verification failed; manual review is required')
    return actual


def activate_and_score(plan, db_path, data_dir, candidate, run, vectors, scores,
                       stage_hashes, base_hashes, backup_root=None):
    before = (Path(backup_root) / run.name / 'before') if backup_root else (run / 'before')
    before.mkdir(parents=True)
    for name in NAMES:
        copy_new(Path(data_dir) / name, before / name)
        if digest(before / name) != base_hashes[name]:
            raise RuntimeError('Active files changed before immutable backup was completed')
    plan['conn'].rollback()
    if plan['conn'].execute('PRAGMA data_version').fetchone()[0] != plan['data_version']:
        raise RuntimeError('Source database changed during isolated staging')
    writer = sqlite3.connect(str(db_path), timeout=30)
    writer.row_factory = sqlite3.Row
    writer.execute('PRAGMA busy_timeout=30000')
    touched = committed = False
    try:
        writer.execute('BEGIN IMMEDIATE')
        if (signature(writer) != plan['source_signature'] or
                plan['conn'].execute('PRAGMA data_version').fetchone()[0] != plan['data_version']):
            raise RuntimeError('Source changed before the final writer guard')
        verify_delta_inputs(writer, plan['delta'])
        if asset_stats(data_dir) != plan['base_stats']:
            raise RuntimeError('Active files changed before semantic activation')
        write_json(run / 'activation_intent.json', {'at_utc': now(), 'base_hashes': base_hashes,
            'candidate_hashes': stage_hashes, 'source_signature': plan['source_signature'],
            'before_directory': str(before), 'new_scores': scores, 'baseline_max_id': int(plan['base_ids'][-1])})
        touched = True
        for name in NAMES:
            os.replace(candidate / name, Path(data_dir) / name)
        if {name: digest(Path(data_dir) / name) for name in NAMES} != stage_hashes:
            raise RuntimeError('Live semantic hashes do not match the verified candidate')
        scored = preserved = 0
        for identifier, score in scores.items():
            prior = writer.execute('SELECT semantic_relevance FROM astar_article_classifications WHERE article_id=?',
                                   (identifier,)).fetchone()
            if prior is None:
                raise RuntimeError(f'New classification row is missing for {identifier}')
            if prior['semantic_relevance'] is not None:
                preserved += 1
                continue
            changed = writer.execute('UPDATE astar_article_classifications SET semantic_relevance=? '
                'WHERE article_id=? AND article_id>? AND semantic_relevance IS NULL',
                (score, identifier, int(plan['base_ids'][-1])))
            if changed.rowcount != 1:
                raise RuntimeError('New-only score writer did not affect exactly one null row')
            readback = writer.execute('SELECT semantic_relevance FROM astar_article_classifications WHERE article_id=?',
                                      (identifier,)).fetchone()[0]
            if abs(float(readback) - score) > 1e-9:
                raise RuntimeError('New-only semantic score readback failed')
            scored += 1
        writer.commit()
        committed = True
        result = {'at_utc': now(), 'success': True, 'source_signature': plan['source_signature'],
                  'active_asset_hashes': stage_hashes, 'baseline_rows_touched': 0,
                  'existing_score_values_overwritten': 0, 'scored_new': scored,
                  'existing_new_scores_preserved': preserved, 'backup_dir': str(before)}
        write_json(run / 'complete.json', result)
        return result
    except BaseException as error:
        if not committed:
            writer.rollback()
            if touched:
                restored = restore_assets(before, data_dir, base_hashes)
                write_json(run / 'rolled_back.json', {'at_utc': now(), 'error': str(error),
                           'active_asset_hashes': restored, 'database_transaction_rolled_back': True})
        raise
    finally:
        writer.close()


def _update(db_path, data_dir, apply, run_root, max_delta_rows, encoder_factory,
            batch_size, backup_root=None):
    check_unfinished(run_root)
    plan = plan_update(db_path, data_dir, max_delta_rows=max_delta_rows)
    run = None
    try:
        report = summary(plan)
        if not apply or not plan['delta']:
            return {**report, 'applied': False, 'encoded': 0, 'refreshed': 0, 'scored_new': 0,
                    'model_loaded': False, 'active_assets_written': False, 'database_written': False}
        require_encoder_headroom()
        assets_bytes = sum(Path(data_dir, name).stat().st_size for name in NAMES)
        if shutil.disk_usage(data_dir).free < 2 * assets_bytes + 4 * 2**30:
            raise OSError('Need candidate + immutable backup space and a 4 GiB free-space margin')
        run_root.mkdir(parents=True, exist_ok=True)
        run = run_root / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '_' + uuid.uuid4().hex)
        run.mkdir()
        base_hashes = {name: digest(Path(data_dir) / name) for name in NAMES}
        verify_accepted_seed(plan['metadata'], data_dir, base_hashes)
        write_json(run / 'plan.json', {**report, 'at_utc': now(), 'base_hashes': base_hashes,
                                     'delta_inputs': plan['delta'], 'batch_size': batch_size, 'threads': 2})
        encoder = encoder_factory(plan['metadata'], data_dir) if encoder_factory else load_verified_model(data_dir, threads=2)
        vectors = encoder.encode([_doc_text(row['title'], row['abstract']) for row in plan['delta']],
                                 batch_size=batch_size, normalize_embeddings=True)
        vectors = np.asarray(vectors)
        check_vectors(vectors)
        if len(vectors) != len(plan['delta']):
            raise ValueError('ONNX delta count differs from planned inputs')
        scores = {}
        new_positions = [index for index, row in enumerate(plan['delta']) if row['new']]
        if new_positions:
            aspect_vectors = np.asarray(encoder.encode(PROFILE_ASPECTS, batch_size=batch_size,
                                                        normalize_embeddings=True))
            check_vectors(aspect_vectors)
            values = np.round(np.clip((vectors[new_positions] @ aspect_vectors.T).max(axis=1), 0, 1) * 100, 1)
            scores = {plan['delta'][index]['id']: float(score) for index, score in zip(new_positions, values)}
        candidate = run / 'candidate'
        stage_pack(plan, data_dir, candidate, vectors, encoder, run)
        stage_hashes = {name: digest(candidate / name) for name in NAMES}
        write_json(run / 'candidate_verification.json', {**report, 'at_utc': now(), 'passed': True,
                   'all_unchanged_vectors_exact': True, 'all_delta_vectors_exact': True,
                   'all_vectors_finite_and_normalized': True, 'candidate_hashes': stage_hashes})
        result = activate_and_score(plan, db_path, data_dir, candidate, run, vectors, scores,
                                    stage_hashes, base_hashes, backup_root=backup_root)
        return {**report, **result, 'encoded': report['new_rows'], 'refreshed': report['changed_text_rows'],
                'applied': True, 'run_dir': str(run), 'active_assets_written': True, 'database_written': bool(result['scored_new'])}
    except BaseException as error:
        if run is not None and not (run / 'failure.json').exists():
            write_json(run / 'failure.json', {'at_utc': now(), 'error_type': type(error).__name__, 'error': str(error)})
        raise
    finally:
        plan['conn'].close()


def update_embeddings(db_path, data_dir, apply=True, run_root=None, max_delta_rows=2000,
                      encoder_factory=None, batch_size=4, backup_root=None):
    """Automatic inference is bounded to a reviewed seed plus at most 2,000 rows."""
    db_path, data_dir = Path(db_path), Path(data_dir)
    run_root = Path(run_root) if run_root else data_dir / 'astar_semantic_updates'
    if backup_root is not None:
        backup_root = Path(backup_root).expanduser().resolve()
        data_dir_resolved = data_dir.resolve()
        try:
            backup_root.relative_to(data_dir_resolved)
        except ValueError:
            pass
        else:
            raise ValueError('External backup root must be outside the active data directory')
    batch_size = min(4, max(1, int(batch_size)))
    if not apply:
        return _update(db_path, data_dir, False, run_root, max_delta_rows,
                       encoder_factory, batch_size, backup_root=backup_root)
    with update_lock(data_dir):
        return _update(db_path, data_dir, True, run_root, max_delta_rows,
                       encoder_factory, batch_size, backup_root=backup_root)
