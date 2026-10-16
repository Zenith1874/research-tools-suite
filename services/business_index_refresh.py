"""Single-flight background refresh of derived research links.

Large refreshes build in a separate SQLite file. Only completed derived tables
are activated; article data, reading state, and user notes are never replaced.
"""

import logging
import threading
import time
import uuid
from pathlib import Path

LOG = logging.getLogger(__name__)
_LOCK = threading.RLock()
_JOBS = {}
_LAST_CHECK = {}
_STATES = {}


def key_for(module, db_path, state_path):
    return (str(Path(db_path or module.DEFAULT_ARTICLE_DB_PATH).resolve()),
            str(Path(state_path or module.DEFAULT_STATE_DB_PATH).resolve()))


def signature(module, db_path, catalog):
    conn = module._article_connect(db_path)
    try:
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(astar_articles)')}
        article_revision = ' | '.join(str(conn.execute(
            "SELECT COALESCE(MAX(%s),'') FROM astar_articles" % field).fetchone()[0] or '')
            for field in ('updated_at', 'created_at') if field in columns)
        cls_columns = {row['name'] for row in conn.execute('PRAGMA table_info(astar_article_classifications)')}
        classification_revision = str(conn.execute(
            "SELECT COALESCE(MAX(classified_at),'') FROM astar_article_classifications").fetchone()[0] or '') if 'classified_at' in cls_columns else ''
        return {'catalog_fingerprint': module._catalog_fingerprint(catalog),
                'pipeline_version': module.ASSERTION_PIPELINE_VERSION,
                'max_article_id': str(conn.execute('SELECT COALESCE(MAX(id),0) FROM astar_articles').fetchone()[0]),
                'article_revision_watermark': article_revision,
                'classification_revision_watermark': classification_revision}
    finally:
        conn.close()


def is_current(module, key, expected):
    conn = module._state_connect(key[1])
    try:
        return all(module._index_meta(conn, name) == value for name, value in expected.items())
    finally:
        conn.close()


def activate(module, target, staged):
    """A failed staging build cannot clear the currently served index."""
    conn = module._state_connect(target)
    try:
        conn.execute('ATTACH DATABASE ? AS completed_index', (str(staged),))
        conn.execute('BEGIN IMMEDIATE')
        protected = conn.execute("SELECT count(*) FROM research_entity_assertions "
                                 "WHERE verification_status<>'CANDIDATE' OR reviewed_at IS NOT NULL").fetchone()[0]
        if protected:
            raise RuntimeError('A full index replacement would affect reviewed assertions; preserve the served index')
        for table in ('research_paper_links', 'research_entity_assertions'):
            conn.execute('DELETE FROM ' + table)
            conn.execute('INSERT INTO ' + table + ' SELECT * FROM completed_index.' + table)
        for row in conn.execute('SELECT key,value FROM completed_index.research_index_meta').fetchall():
            module._set_index_meta(conn, row['key'], row['value'])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def refresh(module, key, catalog):
    if all(hasattr(module, name) for name in ('_links_for_row', '_assertions_for_row', '_catalog_fingerprint')):
        from services.business_index_incremental import NeedsFullIndex, update_index
        try:
            result = update_index(module, key[0], key[1], catalog=catalog, apply=True)
            with _LOCK:
                _STATES[key] = 'current' if is_current(module, key, signature(module, key[0], catalog)) else 'stale'
                _LAST_CHECK[key] = time.monotonic()
            LOG.info('research incremental index: mode=%s affected=%s', result['mode'], result['affected_papers'])
            return result
        except NeedsFullIndex:
            # Initial or changed catalogs need the preserved staged full builder.
            LOG.info('research index requires a different catalog/pipeline baseline')
        except Exception:
            with _LOCK:
                _STATES[key] = 'error'
                _LAST_CHECK[key] = time.monotonic()
            LOG.exception('research incremental refresh held; served state retained')
            return None
    generation_dir = Path(key[1]).parent / 'business_research_index_generations'
    generation_dir.mkdir(parents=True, exist_ok=True)
    staged = generation_dir / ('generation_' + uuid.uuid4().hex + '.db')
    try:
        before = signature(module, key[0], catalog) if hasattr(module, '_article_connect') else None
        module.rebuild_link_index(key[0], staged, catalog, force=True)
        if before is not None and signature(module, key[0], catalog) != before:
            raise RuntimeError('Source moved during the full staging build; preserve the served index')
        activate(module, key[1], staged)
        expected = signature(module, key[0], catalog)
        current = is_current(module, key, expected)
        with _LOCK:
            _STATES[key] = 'current' if current else 'stale'
            _LAST_CHECK[key] = time.monotonic()
        LOG.info('research link generation activated: %s current=%s', staged.name, current)
    except Exception:
        with _LOCK:
            _STATES[key] = 'error'
            _LAST_CHECK[key] = time.monotonic()
        LOG.exception('research link refresh failed; served index was retained')


def ensure(module, db_path=None, state_path=None, catalog=None):
    catalog = catalog or module.load_catalog()
    key = key_for(module, db_path, state_path)
    with _LOCK:
        job = _JOBS.get(key)
        if job is not None and job.is_alive():
            return False
        if time.monotonic() - _LAST_CHECK.get(key, 0) < 30:
            return _STATES.get(key) == 'current'
    expected = signature(module, key[0], catalog)
    if is_current(module, key, expected):
        with _LOCK:
            _STATES[key] = 'current'
            _LAST_CHECK[key] = time.monotonic()
        return True
    if int(expected['max_article_id']) <= 5000:
        # Small isolated fixtures and new small projects finish immediately.
        refresh(module, key, catalog)
        return is_current(module, key, expected)
    with _LOCK:
        job = _JOBS.get(key)
        if job is not None and job.is_alive():
            return False
        _STATES[key] = 'refreshing'
        _LAST_CHECK[key] = time.monotonic()
        job = threading.Thread(target=refresh, args=(module, key, catalog),
                               name='research-link-index-refresh', daemon=True)
        _JOBS[key] = job
        job.start()
    return False


def status():
    with _LOCK:
        states = list(_STATES.values())
        active = any(job.is_alive() for job in _JOBS.values())
    return {'refreshing': active, 'status': 'refreshing' if active else
            'error' if 'error' in states else 'stale' if 'stale' in states else
            'current' if states else 'not_checked'}
