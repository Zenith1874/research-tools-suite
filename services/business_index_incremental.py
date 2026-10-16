"""Audit-backed input fingerprints and candidate-only entity-index deltas.

Only the derived state database is written. Source fields, human state and
reviewed assertions are protected. Every input is streamed so untracked
duplicate flags, deletions and backdated edits are detected when checked.
"""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import uuid

SCHEMA = 'sha256-business-entity-input-v1'
FIELDS = ('id', 'title', 'abstract', 'is_duplicate', 'theory_tags_json',
          'method_tags_json', 'classification_method')
CONTENT = ('matched_text', 'matched_field', 'classifier_name', 'classifier_version',
           'confidence', 'evidence_level', 'verification_status', 'review_reason', 'reviewed_at')
META_SOURCE = ('max_article_id', 'article_revision_watermark', 'classification_revision_watermark')


class NeedsFullIndex(RuntimeError):
    """A different catalog/pipeline or a missing baseline needs separate staging."""


class NeedsReview(RuntimeError):
    """Preserve live state when provenance, inputs or a reviewed assertion moved."""


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(row):
    return hashlib.sha256(canonical({name: row[name] for name in FIELDS}).encode('utf-8')).digest()


def checksum_add(value, identifier, encoded):
    if len(encoded) != 32:
        raise NeedsReview('An input fingerprint has an unknown size')
    value.update(struct.pack('<q', int(identifier)))
    value.update(encoded)


def connect_ro(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    connection.execute('PRAGMA cache_size=-8192')
    connection.execute('BEGIN')
    return connection


def source_signature(connection):
    columns = {row['name'] for row in connection.execute('PRAGMA table_info(astar_articles)')}
    revisions = [str(connection.execute('SELECT coalesce(max(' + name + "),'') FROM astar_articles").fetchone()[0])
                 for name in ('updated_at', 'created_at') if name in columns]
    classification = {row['name'] for row in connection.execute('PRAGMA table_info(astar_article_classifications)')}
    return {'max_article_id': str(connection.execute('SELECT coalesce(max(id),0) FROM astar_articles').fetchone()[0]),
            'article_revision_watermark': ' | '.join(revisions),
            'classification_revision_watermark': str(connection.execute(
                "SELECT coalesce(max(classified_at),'') FROM astar_article_classifications").fetchone()[0])
                if 'classified_at' in classification else ''}


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)


@contextmanager
def writer_lock(state_path):
    path = Path(state_path).with_name('business_research_incremental.lock')
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


def table_rows(connection, table, identifiers):
    rows = []
    for first in range(0, len(identifiers), 400):
        part = identifiers[first:first + 400]
        marks = ','.join('?' for _ in part)
        rows.extend(dict(row) for row in connection.execute(
            'SELECT * FROM ' + table + ' WHERE paper_id IN (' + marks + ')', part))
    return rows


def assertion_key(row):
    return (row['paper_id'], row['entity_kind'], row['entity_id'], row['assertion_type'], row['rule_id'])


def prepare(module, source, state, catalog, stage, max_changed):
    previous = dict(state.execute('SELECT key,value FROM research_index_meta'))
    signature = source_signature(source)
    version = source.execute('PRAGMA data_version').fetchone()[0]
    catalog_hash = module._catalog_fingerprint(catalog)
    projection_hash = file_digest(Path(module.__file__))
    if (previous.get('catalog_fingerprint') != catalog_hash or
            previous.get('pipeline_version') != module.ASSERTION_PIPELINE_VERSION):
        raise NeedsFullIndex('The accepted catalog/pipeline baseline is absent or different')
    tables = {row[0] for row in state.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    initialized = 'research_index_inputs' in tables
    if not initialized and any(previous.get(name) != value for name, value in signature.items()):
        raise NeedsFullIndex('An input cache can only start from a current accepted entity index')
    if initialized:
        if previous.get('input_fingerprint_schema') != SCHEMA:
            raise NeedsReview('Unknown entity-input cache schema')
        if previous.get('input_projection_sha256') != projection_hash:
            raise NeedsReview('The entity projection code changed; preserve the accepted cache for review')
        receipt = Path(previous['input_receipt'])
        if not receipt.exists():
            raise NeedsReview('An input-cache commit has an incomplete external receipt')
        accepted = json.loads(receipt.read_text(encoding='utf-8'))
        if (not accepted.get('success') or accepted.get('input_checksum') != previous.get('input_checksum') or
                accepted.get('projection_sha256') != projection_hash or
                any(accepted['source_signature'].get(name) != previous.get(name) for name in META_SOURCE)):
            raise NeedsReview('The source/index changed outside the accepted input-cache generation')
    old_cursor = iter(state.execute('SELECT paper_id,input_hash FROM research_index_inputs ORDER BY paper_id')) if initialized else iter(())
    old = next(old_cursor, None)
    old_digest, current_digest = hashlib.sha256(), hashlib.sha256()
    changed, removed, current_count, old_count, last_id = [], [], 0, 0, -1
    input_batch = []
    catalog_index = module._build_assertion_catalog_index(catalog)

    def changed_input(identifier, row, encoded):
        changed.append(int(identifier))
        if len(changed) > max_changed:
            raise NeedsReview('Entity delta exceeds the ' + str(max_changed) + '-paper limit')
        if stage is None:
            return
        if row is None:
            stage.execute('INSERT INTO removals VALUES (?)', (identifier,))
            return
        stage.execute('INSERT INTO inputs VALUES (?,?)', (identifier, encoded))
        if row['is_duplicate']:
            return
        for kind, entity_id, basis in module._links_for_row(row, catalog, catalog_index):
            stage.execute('INSERT OR REPLACE INTO links VALUES (?,?,?,?)', (identifier, kind, entity_id, basis))
        for assertion in module._assertions_for_row(row, catalog, catalog_index):
            if assertion['verification_status'] != 'CANDIDATE' or assertion.get('reviewed_at') is not None:
                raise NeedsReview('The candidate generator emitted a reviewed assertion')
            stage.execute('INSERT INTO assertions VALUES (?,?)', (identifier, canonical(assertion)))

    rows = source.execute('SELECT a.id,a.title,a.abstract,a.is_duplicate,c.theory_tags_json,'
        'c.method_tags_json,c.classification_method FROM astar_articles a LEFT JOIN '
        'astar_article_classifications c ON c.article_id=a.id ORDER BY a.id')
    for row in rows:
        identifier = int(row['id'])
        if identifier <= last_id:
            raise NeedsReview('Source article IDs are not unique and increasing')
        last_id = identifier
        encoded = fingerprint(row)
        checksum_add(current_digest, identifier, encoded)
        current_count += 1
        while old is not None and old['paper_id'] < identifier:
            checksum_add(old_digest, old['paper_id'], old['input_hash'])
            old_count += 1
            removed.append(old['paper_id'])
            changed_input(old['paper_id'], None, None)
            old = next(old_cursor, None)
        if not initialized:
            if stage is not None:
                input_batch.append((identifier, encoded))
                if len(input_batch) >= 2000:
                    stage.executemany('INSERT INTO inputs VALUES (?,?)', input_batch)
                    input_batch.clear()
        elif old is None or old['paper_id'] != identifier:
            changed_input(identifier, row, encoded)
        else:
            checksum_add(old_digest, old['paper_id'], old['input_hash'])
            old_count += 1
            if bytes(old['input_hash']) != encoded:
                changed_input(identifier, row, encoded)
            old = next(old_cursor, None)
    while old is not None:
        checksum_add(old_digest, old['paper_id'], old['input_hash'])
        old_count += 1
        removed.append(old['paper_id'])
        changed_input(old['paper_id'], None, None)
        old = next(old_cursor, None)
    if input_batch:
        stage.executemany('INSERT INTO inputs VALUES (?,?)', input_batch)
    if initialized and (old_digest.hexdigest() != previous['input_checksum'] or
                        old_count != int(previous['input_count'])):
        raise NeedsReview('The accepted input cache was modified or truncated')
    previous_links = table_rows(state, 'research_paper_links', changed)
    previous_assertions = table_rows(state, 'research_entity_assertions', changed)
    if any(row['verification_status'] != 'CANDIDATE' or row['reviewed_at'] is not None for row in previous_assertions):
        raise NeedsReview('An affected assertion is reviewed; preserve it for author review')
    if stage is not None:
        stage.executemany('INSERT INTO before_links VALUES (?,?)',
                          [(row['paper_id'], canonical(row)) for row in previous_links])
        stage.executemany('INSERT INTO before_assertions VALUES (?,?)',
                          [(row['paper_id'], canonical(row)) for row in previous_assertions])
        stage.commit()
    return {'success': True, 'mode': 'delta' if initialized else 'initialize_input_cache',
            'previous_meta': previous, 'source_signature': signature, 'data_version': version,
            'catalog_fingerprint': catalog_hash, 'input_checksum': current_digest.hexdigest(),
            'projection_sha256': projection_hash,
            'input_count': current_count, 'affected_ids': sorted(changed), 'removed_inputs': len(removed),
            'previous_links': len(previous_links), 'previous_assertions': len(previous_assertions),
            'source_read_only': True, 'full_entity_rebuild': False}


def _apply(module, source, state, source_path, state_path, catalog, plan, stage_path, run):
    # Keep a complete migration snapshot once; subsequent runs retain exact deltas.
    if plan['mode'] == 'initialize_input_cache':
        with closing(sqlite3.connect(run / 'state_before.sqlite3')) as snapshot:
            state.backup(snapshot, pages=256)
    source.rollback()
    if source.execute('PRAGMA data_version').fetchone()[0] != plan['data_version']:
        raise NeedsReview('Source changed during isolated entity staging')
    state.rollback()
    writer = sqlite3.connect(state_path, timeout=30)
    writer.row_factory = sqlite3.Row
    guard = sqlite3.connect(source_path, timeout=30)
    guard.row_factory = sqlite3.Row
    committed = False
    try:
        # Reserve the source writer without changing any source record.
        guard.execute('BEGIN IMMEDIATE')
        if (source_signature(guard) != plan['source_signature'] or
                source.execute('PRAGMA data_version').fetchone()[0] != plan['data_version'] or
                module._catalog_fingerprint(module.load_catalog() if catalog is None else catalog) != plan['catalog_fingerprint'] or
                file_digest(Path(module.__file__)) != plan['projection_sha256']):
            raise NeedsReview('Source/catalog changed before the final entity writer guard')
        writer.execute('ATTACH DATABASE ? AS candidate_delta', (str(stage_path),))
        writer.execute('BEGIN IMMEDIATE')
        if file_digest(stage_path) != plan['candidate_sha256']:
            raise NeedsReview('The staged entity candidate changed after verification')
        if dict(writer.execute('SELECT key,value FROM research_index_meta')) != plan['previous_meta']:
            raise NeedsReview('The served entity generation changed during staging')
        identifiers = plan['affected_ids']
        current_links = table_rows(writer, 'research_paper_links', identifiers)
        current_assertions = table_rows(writer, 'research_entity_assertions', identifiers)
        for table, rows in (('before_links', current_links), ('before_assertions', current_assertions)):
            expected = sorted(row[0] for row in writer.execute('SELECT payload FROM candidate_delta.' + table))
            if sorted(canonical(row) for row in rows) != expected:
                raise NeedsReview('An affected before-image changed; preserve the current rows')
        if any(row['verification_status'] != 'CANDIDATE' or row['reviewed_at'] is not None for row in current_assertions):
            raise NeedsReview('A reviewed assertion appeared during staging')
        write_json(run / 'activation_intent.json', {'at_utc': now(), 'previous_meta': plan['previous_meta'],
            'source_signature': plan['source_signature'], 'affected_ids': identifiers,
            'candidate_sha256': file_digest(stage_path), 'input_checksum': plan['input_checksum']})
        writer.execute('CREATE TABLE IF NOT EXISTS research_index_inputs '
                       '(paper_id INTEGER PRIMARY KEY,input_hash BLOB NOT NULL CHECK(length(input_hash)=32))')
        for row in writer.execute('SELECT paper_id FROM candidate_delta.removals').fetchall():
            writer.execute('DELETE FROM research_index_inputs WHERE paper_id=?', (row['paper_id'],))
        writer.execute('INSERT OR REPLACE INTO research_index_inputs '
                       'SELECT paper_id,input_hash FROM candidate_delta.inputs')
        desired = {assertion_key(json.loads(row[0])): json.loads(row[0])
                   for row in writer.execute('SELECT payload FROM candidate_delta.assertions')}
        affected_set = set(identifiers)
        if any(row['paper_id'] not in affected_set or row['verification_status'] != 'CANDIDATE'
               or row.get('reviewed_at') is not None for row in desired.values()):
            raise NeedsReview('The staged assertion scope or review status is unsupported')
        old_by_key = {assertion_key(row): row for row in current_assertions}
        inserted = updated = deleted = preserved = 0
        for identifier, old in old_by_key.items():
            expected = desired.get(identifier)
            if expected is None:
                writer.execute('DELETE FROM research_entity_assertions WHERE id=?', (old['id'],))
                deleted += 1
            elif any(old.get(field) != expected.get(field) for field in CONTENT):
                fields = CONTENT + ('updated_at',)
                writer.execute('UPDATE research_entity_assertions SET ' + ','.join(field + '=?' for field in fields)
                               + ' WHERE id=?', [expected.get(field) for field in fields] + [old['id']])
                updated += 1
            else:
                preserved += 1
        for identifier, expected in desired.items():
            if identifier not in old_by_key:
                fields = tuple(expected)
                writer.execute('INSERT INTO research_entity_assertions (' + ','.join(fields) + ') VALUES ('
                               + ','.join('?' for _ in fields) + ')', [expected[field] for field in fields])
                inserted += 1
        for first in range(0, len(identifiers), 400):
            part = identifiers[first:first + 400]
            writer.execute('DELETE FROM research_paper_links WHERE paper_id IN (' + ','.join('?' for _ in part) + ')', part)
        writer.execute('INSERT INTO research_paper_links SELECT * FROM candidate_delta.links')
        actual_links = {tuple(row[name] for name in ('paper_id', 'kind', 'entity_id', 'basis'))
                        for row in table_rows(writer, 'research_paper_links', identifiers)}
        expected_links = {tuple(row) for row in writer.execute('SELECT * FROM candidate_delta.links')}
        actual_assertions = {assertion_key(row): row for row in table_rows(writer, 'research_entity_assertions', identifiers)}
        if actual_links != expected_links or set(actual_assertions) != set(desired):
            raise NeedsReview('Entity candidate readback differs; rollback')
        for identifier, expected in desired.items():
            actual = actual_assertions[identifier]
            if any(actual.get(field) != expected.get(field) for field in CONTENT):
                raise NeedsReview('Entity assertion content readback differs; rollback')
            prior = old_by_key.get(identifier)
            if prior and (actual['id'] != prior['id'] or actual['created_at'] != prior['created_at']):
                raise NeedsReview('Existing assertion identity changed; rollback')
            if prior and all(prior.get(field) == expected.get(field) for field in CONTENT) and actual != prior:
                raise NeedsReview('An unchanged assertion row changed; rollback')
        checked = hashlib.sha256()
        count = 0
        for row in writer.execute('SELECT paper_id,input_hash FROM research_index_inputs ORDER BY paper_id'):
            checksum_add(checked, row['paper_id'], row['input_hash'])
            count += 1
        if checked.hexdigest() != plan['input_checksum'] or count != plan['input_count']:
            raise NeedsReview('The live input-cache checksum differs; rollback')
        updates = {**plan['source_signature'], 'input_fingerprint_schema': SCHEMA,
                   'input_checksum': plan['input_checksum'], 'input_count': count,
                   'input_projection_sha256': plan['projection_sha256'],
                   'input_receipt': str(run / 'complete.json')}
        if identifiers or any(plan['previous_meta'].get(name) != value for name, value in plan['source_signature'].items()):
            stamp = module._now()
            updates.update(index_generation=module.ASSERTION_PIPELINE_VERSION + ':' + stamp, built_at=stamp)
        for name, value in updates.items():
            module._set_index_meta(writer, name, value)
        writer.commit()
        committed = True
        result = {'success': True, 'applied': True, 'mode': plan['mode'], 'at_utc': now(),
                  'source_signature': plan['source_signature'], 'input_checksum': plan['input_checksum'],
                  'projection_sha256': plan['projection_sha256'],
                  'input_count': count, 'affected_papers': len(identifiers), 'inserted_assertions': inserted,
                  'updated_assertions': updated, 'deleted_assertions': deleted,
                  'unchanged_assertions_preserved': preserved, 'full_entity_rebuild': False,
                  'source_records_written': 0, 'human_state_written': 0, 'reviewed_assertions_written': 0,
                  'run_dir': str(run)}
        write_json(run / 'complete.json', result)
        return result
    except BaseException as error:
        if not committed:
            writer.rollback()
            if (run / 'activation_intent.json').exists():
                write_json(run / 'rolled_back.json', {'at_utc': now(), 'error': str(error), 'database_rolled_back': True})
        raise
    finally:
        writer.close()
        guard.rollback()
        guard.close()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def update_index(module, source_path, state_path, catalog=None, apply=False, max_changed=20000, run_root=None):
    source_path, state_path = Path(source_path), Path(state_path)
    if apply:
        with writer_lock(state_path):
            return _update(module, source_path, state_path, catalog, True, max_changed, run_root)
    return _update(module, source_path, state_path, catalog, False, max_changed, run_root)


def _update(module, source_path, state_path, catalog, apply, max_changed, run_root):
    source = state = stage = run = None
    supplied_catalog = catalog
    try:
        source, state = connect_ro(source_path), connect_ro(state_path)
        catalog = catalog or module.load_catalog()
        if apply:
            if shutil.disk_usage(state_path.parent).free < state_path.stat().st_size + 2 * 2**30:
                raise OSError('Need a migration snapshot and a 2 GiB free-space margin')
            run_root = Path(run_root) if run_root else state_path.parent / 'business_research_index_updates'
            run_root.mkdir(exist_ok=True, parents=True)
            run = run_root / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '_' + uuid.uuid4().hex)
            run.mkdir()
            stage = sqlite3.connect(run / 'candidate.sqlite3')
            stage.executescript('''
                CREATE TABLE inputs(paper_id INTEGER PRIMARY KEY,input_hash BLOB NOT NULL);
                CREATE TABLE removals(paper_id INTEGER PRIMARY KEY);
                CREATE TABLE links(paper_id INTEGER,kind TEXT,entity_id TEXT,basis TEXT,
                    PRIMARY KEY(paper_id,kind,entity_id));
                CREATE TABLE assertions(paper_id INTEGER,payload TEXT);
                CREATE TABLE before_links(paper_id INTEGER,payload TEXT);
                CREATE TABLE before_assertions(paper_id INTEGER,payload TEXT);
            ''')
        plan = prepare(module, source, state, catalog, stage, max_changed)
        summary = {name: value for name, value in plan.items() if name not in ('affected_ids', 'previous_meta', 'data_version')}
        summary['affected_papers'] = len(plan['affected_ids'])
        if not apply:
            return {**summary, 'applied': False, 'database_written': False}
        stage.close()
        stage = None
        plan['candidate_sha256'] = file_digest(run / 'candidate.sqlite3')
        write_json(run / 'plan.json', {**plan, 'at_utc': now()})
        write_json(run / 'candidate_verification.json', {'passed': True, 'at_utc': now(),
            'candidate_sha256': plan['candidate_sha256'], 'input_checksum': plan['input_checksum'],
            'affected_papers': len(plan['affected_ids']), 'reviewed_assertions_in_scope': 0,
            'source_fingerprint_rows': plan['input_count'], 'full_entity_rebuild': False})
        if plan['mode'] == 'delta' and not plan['affected_ids'] and all(
                plan['previous_meta'].get(name) == value for name, value in plan['source_signature'].items()):
            result = {**summary, 'applied': False, 'database_written': False, 'run_dir': str(run)}
            write_json(run / 'complete.json', result)
            return result
        return _apply(module, source, state, source_path, state_path, supplied_catalog, plan,
                      run / 'candidate.sqlite3', run)
    except BaseException as error:
        if run is not None:
            write_json(run / 'failure.json', {'at_utc': now(), 'error_type': type(error).__name__, 'error': str(error)})
        raise
    finally:
        if stage is not None:
            stage.close()
        if source is not None:
            source.close()
        if state is not None:
            state.close()
