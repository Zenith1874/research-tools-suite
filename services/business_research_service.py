# -*- coding: utf-8 -*-
"""Shared Business Research model and API payload builders.

The existing project is a Python HTTPServer application rather than a typed
frontend framework.  This module therefore provides the server-side equivalent
of the shared Paper/Theory/Construct/Method/Topic model described in the Phase
2 specification.

Important data boundaries:
* Papers come from the existing ``astar_articles`` cache and its classification
  table.  The service never invents a paper, DOI, author, journal, rank, or
  citation count.
* The theory/construct/method catalog is an explicitly labelled scaffold.  It
  is useful for navigation and planning, but is not a publication-ready review.
* Theory and method links come from the existing classification tags.  A tag is
  either *precise* (it denotes this entity) or *broad* (an umbrella tag that
  covers this entity and others).  The two are counted and reported separately
  so a narrow method never presents its parent tag's volume as its own.
* Construct links are keyword-inferred and labelled as such in the payload.
* User state is written to a separate small SQLite database so notes and
  reading status do not mutate the large A* metadata database.
"""

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / 'data' / 'research_catalog.json'
DEFAULT_ARTICLE_DB_PATH = ROOT / 'pboc_data.db'
DEFAULT_STATE_DB_PATH = Path(os.environ.get(
    'BUSINESS_RESEARCH_STATE_DB_PATH',
    str(ROOT / 'data' / 'business_research_state.db'),
))
SOURCE_TEXT_CHAPTER_MAP_PATH = (
    ROOT / 'data' / 'research_source_text' /
    'management-organization-60-book-scan' / 'chapter_map.json'
)
SOURCE_EVIDENCE_QUEUE_PATH = (
    ROOT / 'data' / 'research_evidence' /
    'management-organization-60_evidence_queue.json'
)

DISCIPLINES = (
    'Information Systems',
    'Management / Strategy',
    'Marketing',
    'OB / HR',
    'Operations Management',
    'Supply Chain Management',
    'Decision Sciences',
    'Finance',
    'Accounting',
    'Entrepreneurship',
    'International Business',
    'Business Analytics / Operations Research',
    'Economics',
    'Computational Social Science',
)
READING_STATUSES = ('unread', 'reading', 'read')
NOTE_TAGS = ('Theory', 'Method', 'Citation', 'Idea', 'Limitation', 'Future Research')
METHOD_CATEGORIES = ('quantitative', 'experimental', 'computational', 'qualitative')

KIND_SINGULAR = {'theories': 'theory', 'constructs': 'construct', 'methods': 'method'}

PRECISE_BASIS = 'precise_classification_tag'
BROAD_BASIS = 'broad_classification_tag'
KEYWORD_BASIS = 'title_abstract_keyword_inference'

# A landscape built on a handful of papers cannot support a statement about what
# the literature under-studies.  Below this many analyzed papers the payload
# still reports distributions, but suppresses the underexplored-combination
# section and says why.
MIN_PAPERS_FOR_UNDEREXPLORED = 40

TOPIC_LABELS = {
    'AI_in_organizations': 'AI in Organizations',
    'algorithmic_management': 'Algorithmic Management',
    'remote_work': 'Remote Work',
    'return_to_office': 'Return-to-Office',
    'hybrid_work': 'Hybrid Work',
    'employee_wellbeing': 'Employee Wellbeing',
    'employee_engagement': 'Employee Engagement',
    'surveillance_monitoring': 'Surveillance / Monitoring',
    'labor_market': 'Labor Market',
    'leadership': 'Leadership',
    'collaboration': 'Collaboration',
    'turnover': 'Turnover',
    'voice': 'Employee Voice',
    'burnout': 'Burnout',
    'strategy_innovation': 'Strategy / Innovation',
    'inequality': 'Inequality',
    'logistics_delivery': 'Logistics / Delivery',
}

OUTCOME_CONSTRUCTS = {
    'employee-engagement', 'burnout', 'employee-voice', 'turnover-intention',
    'job-satisfaction', 'trust', 'technology-adoption-intention',
}

STOPWORDS = {
    'and', 'the', 'for', 'with', 'from', 'into', 'about', 'this', 'that',
    'employee', 'employees', 'work', 'research', 'study', 'using', 'use',
    'to', 'of', 'on', 'in', 'an', 'a', 'is', 'are', 'its',
}


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _json_list(value):
    if isinstance(value, list):
        return value
    if value is None or value == '':
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _as_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _slug(value):
    value = re.sub(r'[^a-z0-9]+', '-', str(value or '').strip().lower())
    return value.strip('-')


# ── catalog ──────────────────────────────────────────────────────────────────

_CATALOG_CACHE = {'mtime': None, 'data': None}
_CATALOG_LOCK = threading.Lock()
_SOURCE_TEXT_CACHE = {'mtime': None, 'data': None}
_SOURCE_TEXT_LOCK = threading.Lock()
_SOURCE_EVIDENCE_CACHE = {'mtime': None, 'data': None}
_SOURCE_EVIDENCE_LOCK = threading.Lock()


def load_catalog(catalog_path=None):
    """Load the catalog, re-reading only when the file changes on disk."""
    path = Path(catalog_path or CATALOG_PATH)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    key = (str(path), mtime)
    with _CATALOG_LOCK:
        if _CATALOG_CACHE['mtime'] == key and _CATALOG_CACHE['data'] is not None:
            return _CATALOG_CACHE['data']
    with path.open(encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError('research catalog must be a JSON object')
    data.setdefault('theories', [])
    data.setdefault('constructs', [])
    data.setdefault('methods', [])
    with _CATALOG_LOCK:
        _CATALOG_CACHE['mtime'] = key
        _CATALOG_CACHE['data'] = data
    return data


def _catalog_entity(catalog, kind, entity_id):
    for entity in catalog.get(kind, []):
        if entity.get('id') == entity_id or _slug(entity.get('name')) == entity_id:
            return entity
    return None


def _catalog_map(catalog, kind):
    return {item.get('id'): item for item in catalog.get(kind, [])}


def load_source_text_chapter_map(path=None):
    """Load optional local OCR chapter locators without exposing source text.

    The supplied book and its derived page text are private local reading
    aids.  The API only receives locator/status metadata; it never reads or
    serves the OCR text itself.  This keeps a remote/tunnel client from
    silently becoming a document reader for a copyrighted local scan.
    """
    source_path = Path(path or SOURCE_TEXT_CHAPTER_MAP_PATH)
    try:
        mtime = source_path.stat().st_mtime
    except OSError:
        mtime = None
    key = (str(source_path), mtime)
    with _SOURCE_TEXT_LOCK:
        if (_SOURCE_TEXT_CACHE['mtime'] == key and
                _SOURCE_TEXT_CACHE['data'] is not None):
            return _SOURCE_TEXT_CACHE['data']
    if not source_path.exists():
        data = {}
    else:
        try:
            payload = json.loads(source_path.read_text(encoding='utf-8'))
            data = {
                '__meta__': {
                    'source_pack': payload.get('source_pack'),
                    'pdf_page_count': payload.get('pdf_page_count'),
                    'printed_to_pdf_offset': payload.get('printed_to_pdf_offset'),
                },
            }
            data.update({
                row.get('theory_id'): row for row in payload.get('chapters', [])
                if isinstance(row, dict) and row.get('theory_id')
            })
        except (OSError, json.JSONDecodeError, AttributeError):
            data = {}
    with _SOURCE_TEXT_LOCK:
        _SOURCE_TEXT_CACHE['mtime'] = key
        _SOURCE_TEXT_CACHE['data'] = data
    return data


def load_source_evidence_queue(path=None):
    """Load only queue status/counts; never return human notes through the API."""
    source_path = Path(path or SOURCE_EVIDENCE_QUEUE_PATH)
    try:
        mtime = source_path.stat().st_mtime
    except OSError:
        mtime = None
    key = (str(source_path), mtime)
    with _SOURCE_EVIDENCE_LOCK:
        if (_SOURCE_EVIDENCE_CACHE['mtime'] == key and
                _SOURCE_EVIDENCE_CACHE['data'] is not None):
            return _SOURCE_EVIDENCE_CACHE['data']
    data = {}
    if source_path.exists():
        try:
            payload = json.loads(source_path.read_text(encoding='utf-8'))
            data = {
                '__meta__': {
                    'schema_version': payload.get('schema_version'),
                    'generated_at': payload.get('generated_at'),
                },
            }
            coding_fields = tuple(payload.get('coding_fields') or ())
            for row in payload.get('chapters', []):
                if not isinstance(row, dict) or not row.get('theory_id'):
                    continue
                coding = row.get('coding') or {}
                populated = [field for field in coding_fields
                             if coding.get(field) not in (None, '', [])]
                data[row['theory_id']] = {
                    'status': coding.get('status', 'needs_human_coding'),
                    'evidence_count': len(row.get('evidence') or []),
                    'coded_field_count': len(populated),
                }
        except (OSError, json.JSONDecodeError, AttributeError):
            data = {}
    with _SOURCE_EVIDENCE_LOCK:
        _SOURCE_EVIDENCE_CACHE['mtime'] = key
        _SOURCE_EVIDENCE_CACHE['data'] = data
    return data


def _source_evidence_metadata(entity):
    queue = load_source_evidence_queue()
    row = queue.get(entity.get('id'))
    if not row:
        return {
            'status': 'not_initialized',
            'evidence_count': 0,
            'coded_field_count': 0,
            'human_coding_required': True,
        }
    return dict(row, human_coding_required=row.get('status') != 'verified')


def _source_text_metadata(entity, chapter_map=None):
    """Return safe OCR status and page locators for a book-backed theory."""
    if entity.get('source_pack') != 'management-organization-60':
        return None
    chapter_map = chapter_map if chapter_map is not None else load_source_text_chapter_map()
    row = chapter_map.get(entity.get('id'))
    meta = chapter_map.get('__meta__') or {}
    if not row:
        return {
            'source_id': 'management-organization-60-book-scan',
            'status': 'not_ingested',
            'printed_page_start': entity.get('source_page'),
            'printed_page_end': None,
            'pdf_page_start': None,
            'pdf_page_end': None,
            'human_review_required': True,
            'evidence_queue': _source_evidence_metadata(entity),
            'note': 'The attached scan has a printed chapter locator, but no local OCR manifest has been loaded.',
        }
    return {
        'source_id': 'management-organization-60-book-scan',
        'status': 'ocr_derived_available',
        'chapter_locator_status': row.get('status'),
        'ocr_title_match': row.get('ocr_title_match') or {},
        'printed_page_start': row.get('printed_page_start'),
        'printed_page_end': row.get('printed_page_end'),
        'pdf_page_start': row.get('pdf_page_start'),
        'pdf_page_end': row.get('pdf_page_end'),
        'page_offset': row.get('page_offset'),
        'pdf_page_count': meta.get('pdf_page_count'),
        'human_review_required': True,
        'evidence_queue': _source_evidence_metadata(entity),
        'note': ('OCR text is a derived local reading layer. It supports page '
                 'search and review but does not by itself verify a theory claim, '
                 'construct definition, measure, or citation.'),
    }


def _entity_name(catalog, kind, entity_id):
    entity = _catalog_entity(catalog, kind, entity_id)
    return entity['name'] if entity else entity_id


def _tag_variants(value):
    """Expand one tag into the separator variants classifiers actually emit.

    The cache contains ``event_study``, ``event study``, and
    ``difference-in-differences`` side by side.  Matching one spelling only
    would silently drop papers, so every tag is compared in all three forms.
    """
    value = str(value or '').strip().lower()
    if not value:
        return set()
    variants = {value}
    for source in ('_', '-', ' '):
        for target in ('_', '-', ' '):
            if source != target:
                variants.add(value.replace(source, target))
    return {item for item in variants if item}


def _entity_tags(entity):
    """Precise tags: the classifier tags that denote this entity."""
    values = set(entity.get('tags') or [])
    values.add(entity.get('id') or '')
    values.add(_slug(entity.get('name')))
    values.add((entity.get('name') or '').lower())
    if entity.get('abbreviation'):
        values.add(entity['abbreviation'].lower())
    tags = set()
    for value in values:
        tags |= _tag_variants(value)
    return tags


def _entity_broad_tags(entity):
    """Umbrella tags that cover this entity together with others."""
    tags = set()
    for value in entity.get('broad_tags') or []:
        tags |= _tag_variants(value)
    return tags - _entity_tags(entity)


def _keyword_hit(text, keyword):
    keyword = str(keyword or '').strip().lower()
    if not keyword:
        return False
    if re.match(r'^[a-z0-9][a-z0-9 _/-]*$', keyword):
        return re.search(r'(?<![a-z0-9])' + re.escape(keyword) + r'(?![a-z0-9])', text) is not None
    return keyword in text


def _refs_from_raw(raw_tags, catalog, kind):
    """Map classifier tags onto catalog entities, keeping the basis explicit.

    A precise tag wins; a broad tag still produces a link, but one labelled as
    coming from an umbrella tag so the UI can present it separately.
    """
    raw = set()
    for tag in raw_tags or []:
        raw |= _tag_variants(tag)
    refs = []
    for entity in catalog.get(kind, []):
        if raw & _entity_tags(entity):
            basis = PRECISE_BASIS
        elif raw & _entity_broad_tags(entity):
            basis = BROAD_BASIS
        else:
            continue
        refs.append({
            'id': entity['id'],
            'name': entity['name'],
            'abbreviation': entity.get('abbreviation'),
            'source_status': entity.get('source_status', 'curated_scaffold'),
            'relation_basis': basis,
        })
    return refs


def _infer_construct_refs(text, catalog):
    text = (text or '').lower()
    refs = []
    for entity in catalog.get('constructs', []):
        if any(_keyword_hit(text, keyword) for keyword in entity.get('keywords', [])):
            refs.append({
                'id': entity['id'],
                'name': entity['name'],
                'source_status': entity.get('source_status', 'curated_scaffold'),
                'relation_basis': KEYWORD_BASIS,
            })
    return refs


def _catalog_fingerprint(catalog):
    """Fingerprint the parts of the catalog that determine paper links."""
    payload = []
    for kind in ('theories', 'constructs', 'methods'):
        for entity in catalog.get(kind, []):
            payload.append([
                kind, entity.get('id'),
                sorted(_entity_tags(entity)),
                sorted(_entity_broad_tags(entity)),
                sorted(entity.get('keywords') or []),
            ])
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


# ── database access ──────────────────────────────────────────────────────────

def _article_connect(db_path=None):
    """Open the article database, with a read-only immutable fallback.

    The live project database is occasionally held by a Windows process while
    WSL performs audits.  A normal connection is preferred so current WAL
    state is visible; immutable mode is a safe fallback for read-only payloads.
    """
    path = str(db_path or DEFAULT_ARTICLE_DB_PATH)
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=1)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout=1000')
        conn.execute('SELECT 1 FROM astar_articles LIMIT 1').fetchone()
        return conn
    except sqlite3.Error:
        try:
            if conn is not None:
                conn.close()
        except sqlite3.Error:
            pass
        uri = 'file:' + quote(os.path.abspath(path), safe='/:') + '?immutable=1'
        conn = sqlite3.connect(uri, uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn


def _state_connect_without_ensure(state_db_path=None):
    path = Path(state_db_path or DEFAULT_STATE_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=8000')
    # WAL keeps catalog pages readable while the link index rebuilds.  Under the
    # default rollback journal the rebuild holds an exclusive lock for its whole
    # run and every page in the workspace fails with "database is locked".
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except sqlite3.Error:
        pass
    return conn


def _state_connect(state_db_path=None):
    conn = _state_connect_without_ensure(state_db_path)
    ensure_business_research_tables(conn)
    return conn


def ensure_business_research_tables(conn=None, state_db_path=None):
    own = conn is None
    if own:
        conn = _state_connect_without_ensure(state_db_path)
    conn.execute('''CREATE TABLE IF NOT EXISTS research_library_state (
        paper_id INTEGER PRIMARY KEY,
        reading_status TEXT NOT NULL DEFAULT 'unread',
        favorite INTEGER NOT NULL DEFAULT 0,
        last_opened_at TEXT,
        updated_at TEXT NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS research_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id INTEGER NOT NULL,
        note_text TEXT NOT NULL,
        tags_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_research_notes_paper ON research_notes(paper_id)')
    # Derived paper↔entity links.  Kept in the small state database so the large
    # shared article cache is never written to by this module.
    conn.execute('''CREATE TABLE IF NOT EXISTS research_paper_links (
        paper_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        basis TEXT NOT NULL,
        PRIMARY KEY (paper_id, kind, entity_id)
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_research_links_entity ON research_paper_links(kind, entity_id, basis)')
    conn.execute('''CREATE TABLE IF NOT EXISTS research_index_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    conn.commit()
    if own:
        conn.close()


# ── link index ───────────────────────────────────────────────────────────────

_INDEX_LOCK = threading.Lock()
_INDEX_READY = set()


def _index_meta(conn, key):
    row = conn.execute('SELECT value FROM research_index_meta WHERE key=?', (key,)).fetchone()
    return row['value'] if row else None


def _set_index_meta(conn, key, value):
    conn.execute('''INSERT INTO research_index_meta (key, value) VALUES (?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value''', (key, str(value)))


def _links_for_row(row, catalog):
    """All catalog links implied by one article row."""
    title = row['title'] or ''
    abstract = row['abstract'] or ''
    text = (title + '\n' + abstract).lower()
    links = []
    for ref in _refs_from_raw(_json_list(row['theory_tags_json']), catalog, 'theories'):
        links.append(('theory', ref['id'], ref['relation_basis']))
    for ref in _refs_from_raw(_json_list(row['method_tags_json']), catalog, 'methods'):
        links.append(('method', ref['id'], ref['relation_basis']))
    for ref in _infer_construct_refs(text, catalog):
        links.append(('construct', ref['id'], ref['relation_basis']))
    return links


def rebuild_link_index(db_path=None, state_db_path=None, catalog=None, force=False):
    """Materialize paper↔entity links so catalog pages do not rescan 100k+ rows.

    A full scan with dozens of ``LIKE '%…%'`` predicates took seconds per page
    view.  The links only change when the catalog changes or new articles
    arrive, so they are computed once and refreshed incrementally.
    """
    catalog = catalog or load_catalog()
    fingerprint = _catalog_fingerprint(catalog)
    state = _state_connect(state_db_path)
    try:
        stored = _index_meta(state, 'catalog_fingerprint')
        last_id = _as_int(_index_meta(state, 'max_article_id')) or 0
        full = force or stored != fingerprint

        articles = _article_connect(db_path)
        try:
            max_id = articles.execute(
                'SELECT COALESCE(MAX(id), 0) FROM astar_articles').fetchone()[0] or 0
            if not full and max_id <= last_id:
                return {'rebuilt': False, 'papers_indexed': 0, 'max_article_id': last_id}

            if full:
                state.execute('DELETE FROM research_paper_links')
                since = 0
            else:
                since = last_id

            cursor = articles.execute('''
                SELECT a.id, a.title, a.abstract,
                       c.theory_tags_json, c.method_tags_json
                FROM astar_articles a
                LEFT JOIN astar_article_classifications c ON c.article_id = a.id
                WHERE a.is_duplicate = 0 AND a.id > ?
                ORDER BY a.id''', (since,))

            if full:
                state.commit()   # release the DELETE's lock before the long scan

            indexed = 0
            while True:
                rows = cursor.fetchmany(2000)
                if not rows:
                    break
                batch = []
                for row in rows:
                    indexed += 1
                    for kind, entity_id, basis in _links_for_row(row, catalog):
                        batch.append((row['id'], kind, entity_id, basis))
                if batch:
                    state.executemany(
                        '''INSERT INTO research_paper_links (paper_id, kind, entity_id, basis)
                           VALUES (?,?,?,?)
                           ON CONFLICT(paper_id, kind, entity_id) DO UPDATE SET basis=excluded.basis''',
                        batch)
                # Commit per batch so a multi-minute rebuild never holds one long
                # write lock; readers see a partially rebuilt index rather than an
                # error, and the fingerprint is only written once the scan finishes.
                state.commit()
        finally:
            articles.close()

        _set_index_meta(state, 'catalog_fingerprint', fingerprint)
        _set_index_meta(state, 'max_article_id', max_id)
        _set_index_meta(state, 'built_at', _now())
        state.commit()
        return {'rebuilt': True, 'full': full, 'papers_indexed': indexed, 'max_article_id': max_id}
    finally:
        state.close()


def _ensure_index(db_path=None, state_db_path=None, catalog=None):
    """Build the index on first use per database, then refresh incrementally."""
    key = (str(db_path or DEFAULT_ARTICLE_DB_PATH), str(state_db_path or DEFAULT_STATE_DB_PATH))
    with _INDEX_LOCK:
        first = key not in _INDEX_READY
        _INDEX_READY.add(key)
    try:
        rebuild_link_index(db_path, state_db_path, catalog, force=False)
    except sqlite3.Error:
        # A read-only or locked state database must not take the pages down;
        # callers fall back to counting directly against the article cache.
        if first:
            with _INDEX_LOCK:
                _INDEX_READY.discard(key)
        return False
    return True


def _entity_counts(kind, state_db_path=None):
    """Precise and broad paper counts per entity, from the link index."""
    singular = KIND_SINGULAR[kind]
    conn = _state_connect(state_db_path)
    try:
        rows = conn.execute('''SELECT entity_id, basis, COUNT(*) AS n
                               FROM research_paper_links WHERE kind=?
                               GROUP BY entity_id, basis''', (singular,)).fetchall()
    finally:
        conn.close()
    precise = defaultdict(int)
    broad = defaultdict(int)
    for row in rows:
        if row['basis'] == BROAD_BASIS:
            broad[row['entity_id']] += row['n']
        else:
            precise[row['entity_id']] += row['n']
    return precise, broad


def _entity_paper_ids(kind, entity_id, state_db_path=None, include_broad=False):
    singular = KIND_SINGULAR[kind]
    sql = 'SELECT paper_id FROM research_paper_links WHERE kind=? AND entity_id=?'
    args = [singular, entity_id]
    if not include_broad:
        sql += ' AND basis!=?'
        args.append(BROAD_BASIS)
    conn = _state_connect(state_db_path)
    try:
        return [row['paper_id'] for row in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _links_for_papers(paper_ids, state_db_path=None):
    """Fetch indexed links for a specific set of papers, in id batches."""
    result = defaultdict(lambda: {'theory': [], 'construct': [], 'method': []})
    ids = list(paper_ids)
    if not ids:
        return result
    conn = _state_connect(state_db_path)
    try:
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            rows = conn.execute(
                'SELECT paper_id, kind, entity_id, basis FROM research_paper_links '
                'WHERE paper_id IN (%s)' % ','.join('?' for _ in chunk), chunk).fetchall()
            for row in rows:
                result[row['paper_id']][row['kind']].append(
                    {'id': row['entity_id'], 'basis': row['basis']})
    finally:
        conn.close()
    return result


# ── paper model ──────────────────────────────────────────────────────────────

def _classification_from_row(row):
    return {
        'broad_area': row.get('cls_broad_area'),
        'research_topic': _json_list(row.get('cls_research_topic')),
        'theory_tags': _json_list(row.get('cls_theory_tags')),
        'method_tags': _json_list(row.get('cls_method_tags')),
        'data_type_tags': _json_list(row.get('cls_data_type_tags')),
        'context_tags': _json_list(row.get('cls_context_tags')),
        'relevance_score': row.get('cls_relevance_score'),
        'is_related_to_my_research': row.get('cls_related'),
        'classification_method': row.get('cls_method'),
        'classification_status': row.get('cls_status'),
        'classification_notes': row.get('cls_notes'),
        'sample_context': row.get('cls_sample_context'),
    }


def _author_names(value):
    names = []
    for author in _json_list(value):
        if isinstance(author, str):
            name = author
        elif isinstance(author, dict):
            name = author.get('name') or author.get('display_name') or author.get('author_name')
        else:
            name = None
        if name:
            names.append(str(name))
    return names


def _indexed_refs(links, kind, catalog, catalog_kind):
    """Rebuild display refs from indexed links, without re-reading abstracts."""
    refs = []
    for link in (links or {}).get(kind, []):
        entity = _catalog_entity(catalog, catalog_kind, link['id'])
        if not entity:
            continue
        refs.append({
            'id': entity['id'],
            'name': entity['name'],
            'abbreviation': entity.get('abbreviation'),
            'source_status': entity.get('source_status', 'curated_scaffold'),
            'relation_basis': link['basis'],
        })
    return refs


def _paper_from_row(row, catalog, links=None):
    row = dict(row)
    cls = _classification_from_row(row)
    title = row.get('title') or ''
    abstract = row.get('abstract') or ''
    if links is not None:
        theory_refs = _indexed_refs(links, 'theory', catalog, 'theories')
        method_refs = _indexed_refs(links, 'method', catalog, 'methods')
        construct_refs = _indexed_refs(links, 'construct', catalog, 'constructs')
    else:
        text = (title + '\n' + abstract).lower()
        theory_refs = _refs_from_raw(cls['theory_tags'], catalog, 'theories')
        method_refs = _refs_from_raw(cls['method_tags'], catalog, 'methods')
        construct_refs = _infer_construct_refs(text, catalog)
    year = _as_int(row.get('publication_year'))
    rank = row.get('journal_abdc_rating')
    return {
        'id': str(row.get('id')),
        'title': title,
        'abstract': abstract or None,
        'authors': _author_names(row.get('authors_json')),
        'year': year,
        'publicationDate': row.get('publication_date'),
        'journal': {
            'title': row.get('journal_title'),
            'issn': row.get('journal_issn'),
            'rank': rank,
            'publisher': row.get('publisher'),
        },
        'doi': row.get('doi'),
        'url': row.get('landing_page_url') or row.get('url'),
        'doiUrl': ('https://doi.org/' + str(row['doi'])) if row.get('doi') else None,
        'abdcRank': rank,
        'disciplines': [cls['broad_area']] if cls.get('broad_area') else [],
        'topics': cls['research_topic'],
        'theories': theory_refs,
        'constructs': construct_refs,
        'methods': method_refs,
        'researchQuestion': None,
        'hypotheses': [],
        'sample': cls.get('sample_context'),
        'sampleSize': None,
        'country': None,
        'findings': [],
        'limitations': [],
        'futureResearch': [],
        'notes': None,
        'status': 'unread',
        'favorite': False,
        'citedByCount': row.get('cited_by_count'),
        'sourceName': row.get('source_name'),
        'sourceType': row.get('source_type'),
        'dataStatus': row.get('data_status'),
        'abstractStatus': row.get('abstract_status'),
        'abstractReviewStatus': row.get('abstract_review_status'),
        'classification': cls,
        'relation_basis': {
            'theories': 'existing_astar_classification_tags',
            'methods': 'existing_astar_classification_tags',
            'constructs': KEYWORD_BASIS,
        },
    }


def _paper_reference(paper):
    return {
        'id': paper.get('id'),
        'title': paper.get('title'),
        'journal': (paper.get('journal') or {}).get('title'),
        'year': paper.get('year'),
        'rank': paper.get('abdcRank'),
        'doi': paper.get('doi'),
        'url': paper.get('url'),
        'cited_by_count': paper.get('citedByCount'),
    }


def _search_terms(value):
    raw = re.findall(r'[\w-]{2,}', str(value or '').lower())
    terms = []
    for term in raw:
        if term in STOPWORDS:
            continue
        if term not in terms:
            terms.append(term)
    return terms[:8]


# The landscape aggregates thousands of rows but only needs the fields it
# actually counts.  Pulling every abstract for that is the difference between a
# responsive page and an eight-second one.
PAPER_SELECT_LIGHT = '''SELECT a.id, a.title, a.doi, a.publication_date, a.publication_year,
        a.journal_title, a.journal_issn, a.journal_abdc_rating, a.publisher,
        a.url, a.landing_page_url, a.cited_by_count, a.authors_json,
        a.source_name, a.source_type, a.data_status,
        c.broad_area AS cls_broad_area,
        c.research_topic AS cls_research_topic,
        c.theory_tags_json AS cls_theory_tags,
        c.method_tags_json AS cls_method_tags,
        c.relevance_score AS cls_relevance_score,
        c.sample_context AS cls_sample_context
'''

PAPER_SELECT = '''SELECT a.*,
        c.broad_area AS cls_broad_area,
        c.research_topic AS cls_research_topic,
        c.theory_tags_json AS cls_theory_tags,
        c.method_tags_json AS cls_method_tags,
        c.data_type_tags_json AS cls_data_type_tags,
        c.context_tags_json AS cls_context_tags,
        c.relevance_score AS cls_relevance_score,
        c.is_related_to_my_research AS cls_related,
        c.classification_method AS cls_method,
        c.classification_status AS cls_status,
        c.classification_notes AS cls_notes,
        c.sample_context AS cls_sample_context
'''

SORT_ORDERS = {
    'date_desc': 'a.publication_date DESC, a.id DESC',
    'recent': 'a.publication_date DESC, a.id DESC',
    'date_asc': 'a.publication_date ASC, a.id ASC',
    'relevance_desc': 'COALESCE(c.relevance_score, 0) DESC, a.publication_date DESC',
    'citations_desc': 'COALESCE(a.cited_by_count, 0) DESC, a.publication_date DESC',
}


def _query_papers(params=None, db_path=None, catalog=None, state_db_path=None, light=False):
    """Query the article cache.

    Entity filters (theory / construct / method) are resolved through the link
    index and passed to SQLite as a temporary id table, which keeps the query
    plan indexed instead of scanning every abstract with ``LIKE``.
    """
    params = params or {}
    catalog = catalog or load_catalog()
    conn = _article_connect(db_path)
    try:
        where = ['a.is_duplicate=0']
        args = []
        id_filter_applied = False

        paper_id = params.get('paper_id')
        if paper_id is not None:
            where.append('a.id=?')
            args.append(int(paper_id))

        query = params.get('q') or params.get('topic') or ''
        terms = _search_terms(query)
        match_mode = (params.get('match') or 'all').lower()
        if terms:
            clauses = []
            for term in terms:
                like = '%' + term + '%'
                clauses.append('(' + ' OR '.join([
                    'a.title LIKE ?', 'a.abstract LIKE ?', 'a.journal_title LIKE ?',
                    'c.research_topic LIKE ?', 'c.theory_tags_json LIKE ?',
                    'c.method_tags_json LIKE ?', 'c.context_tags_json LIKE ?',
                ]) + ')')
                args.extend([like] * 7)
            joiner = ' OR ' if match_mode == 'any' else ' AND '
            where.append('(' + joiner.join(clauses) + ')')
        if params.get('discipline'):
            where.append('c.broad_area=?')
            args.append(params['discipline'])
        if params.get('from_year'):
            where.append('a.publication_year>=?')
            args.append(int(params['from_year']))
        if params.get('to_year'):
            where.append('a.publication_year<=?')
            args.append(int(params['to_year']))
        rank = str(params.get('rank') or '').strip()
        if rank and rank not in ('All', 'all'):
            ranks = [item.strip() for item in re.split(r'[,;+]', rank) if item.strip()]
            where.append('a.journal_abdc_rating IN (%s)' % ','.join('?' for _ in ranks))
            args.extend(ranks)

        entity_ids = None
        for kind, key in (('theories', 'theory'), ('methods', 'method'), ('constructs', 'construct')):
            value = params.get(key)
            if not value:
                continue
            entity = _catalog_entity(catalog, kind, value)
            if entity is None:
                entity_ids = set()
                break
            include_broad = bool(params.get('include_broad'))
            found = set(_entity_paper_ids(kind, entity['id'], state_db_path, include_broad))
            entity_ids = found if entity_ids is None else (entity_ids & found)

        if entity_ids is not None:
            conn.execute('CREATE TEMP TABLE IF NOT EXISTS _entity_ids (id INTEGER PRIMARY KEY)')
            conn.execute('DELETE FROM _entity_ids')
            conn.executemany('INSERT OR IGNORE INTO _entity_ids (id) VALUES (?)',
                             [(int(value),) for value in entity_ids])
            where.append('a.id IN (SELECT id FROM _entity_ids)')
            id_filter_applied = True

        base = '''FROM astar_articles a
                  LEFT JOIN astar_article_classifications c ON c.article_id=a.id
                  WHERE %s''' % ' AND '.join(where)
        total = conn.execute('SELECT COUNT(*) ' + base, args).fetchone()[0]
        order = SORT_ORDERS.get(params.get('sort') or 'date_desc', SORT_ORDERS['date_desc'])
        limit = max(0, min(int(params.get('limit', 50)), 5000))
        offset = max(0, int(params.get('offset', 0)))
        rows = []
        if limit:
            select = PAPER_SELECT_LIGHT if light else PAPER_SELECT
            sql = select + base + ' ORDER BY %s LIMIT ? OFFSET ?' % order
            rows = conn.execute(sql, args + [limit, offset]).fetchall()
        if light:
            links = _links_for_papers([row['id'] for row in rows], state_db_path)
            papers = [_paper_from_row(row, catalog, links.get(row['id'])) for row in rows]
        else:
            papers = [_paper_from_row(row, catalog) for row in rows]
        if id_filter_applied:
            conn.execute('DELETE FROM _entity_ids')
        return {'total': total, 'papers': papers,
                'sampled': total > len(papers) + offset,
                'offset': offset, 'limit': limit}
    finally:
        conn.close()


def _data_boundary(catalog, sampled=False, sample_size=None):
    return {
        'catalog': {
            'status': catalog.get('catalog_status', 'demo_catalog'),
            'note': catalog.get('provenance_note'),
        },
        'papers': {
            'status': 'existing_abdc_astar_cache',
            'source': 'astar_articles + astar_article_classifications',
            'note': 'Paper metadata and ABDC rank come from the existing A* radar cache; theory/method links reuse its classification tags.',
        },
        'inference': {
            'constructs': KEYWORD_BASIS,
            'landscape': 'descriptive aggregation of the available cache; not a proof of a research gap',
            'tag_precision': 'A precise tag denotes the entity. A broad tag is an umbrella that also covers other entities; broad counts are reported separately and never merged into the entity count.',
        },
        'sampled': bool(sampled),
        'sample_size': sample_size,
    }


# ── catalog payloads ─────────────────────────────────────────────────────────

def _mapping_status(entity, precise, broad):
    if precise:
        return 'mapped_precise_tag'
    if broad:
        return 'broad_tag_only'
    if _entity_broad_tags(entity):
        return 'no_matching_paper'
    return 'no_classifier_tag_in_cache'


MAPPING_NOTES = {
    'mapped_precise_tag': None,
    'broad_tag_only': 'No paper carries a tag specific to this entity. The count shown is for a broader umbrella tag.',
    'no_matching_paper': 'No paper in the current cache carries a tag for this entity.',
    'no_classifier_tag_in_cache': 'The existing classifier vocabulary has no tag for this entity, so the cache cannot report papers for it. This is a coverage limit of the classifier, not evidence that no such research exists.',
}


def _entity_card(entity, kind, catalog=None, precise=None, broad=None):
    catalog = catalog or load_catalog()
    result = dict(entity)
    result['slug'] = entity['id']
    result['entity_type'] = KIND_SINGULAR[kind]
    result['data_status'] = entity.get('source_status', 'curated_scaffold')
    precise_count = int((precise or {}).get(entity['id'], 0))
    broad_count = int((broad or {}).get(entity['id'], 0))
    result['paper_count'] = precise_count
    result['broad_paper_count'] = broad_count
    result['broad_tags'] = sorted(entity.get('broad_tags') or [])
    result['mapping_status'] = _mapping_status(entity, precise_count, broad_count)
    result['mapping_note'] = MAPPING_NOTES.get(result['mapping_status'])
    result['source_works'] = _seminal_works(entity)
    result['source_text'] = _source_text_metadata(entity)
    if result['source_text'] and result['source_text'].get('status') == 'ocr_derived_available':
        result['source_note'] = (
            'Chapter title and printed starting page were checked against the attached scan. '
            'A separate local OCR text layer is now available for page search; its claims, '
            'measurements, and citations still require human review against the original page.'
        )
    result['source_coverage_status'] = entity.get(
        'source_coverage_status',
        'source_records_loaded' if entity.get('seminal_works') else 'source_search_pending')
    result['source_coverage_note'] = entity.get(
        'source_coverage_note',
        'Source record is a catalog lead until its bibliographic match and primary source are verified.')
    if kind == 'theories':
        result['core_construct_refs'] = _resolve_refs(catalog, 'constructs', entity.get('core_constructs'))
    return result


def _resolve_refs(catalog, kind, ids):
    """Turn a list of catalog ids into {id, name} pairs for display.

    Slugs like ``employee-voice`` were reaching the page verbatim; anything the
    UI renders as a label goes through here first.
    """
    refs = []
    for value in ids or []:
        entity = _catalog_entity(catalog, kind, value)
        if entity:
            refs.append({'id': entity['id'], 'name': entity['name'],
                         'abbreviation': entity.get('abbreviation'), 'resolved': True})
        else:
            refs.append({'id': None, 'name': str(value), 'resolved': False})
    return refs


def _catalog_search(catalog, kind, query='', discipline=None):
    query = (query or '').strip().lower()
    entities = []
    for entity in catalog.get(kind, []):
        parts = [
            entity.get('name') or '', entity.get('abbreviation') or '',
            entity.get('name_zh') or '', entity.get('definition_zh') or '',
            entity.get('description_zh') or '',
            entity.get('definition') or '', entity.get('description') or '',
            ' '.join(entity.get('keywords') or []),
            ' '.join(entity.get('tags') or []),
            entity.get('sub_category') or '', entity.get('category') or '',
        ]
        # A theory should be findable by the constructs it is built from; a
        # search for "autonomy" that misses JD-R is a search bug, not a result.
        # Sibling entity names are deliberately excluded: matching a neighbour's
        # name would return every theory merely related to the one searched for.
        for field in ('core_constructs', 'antecedents', 'outcomes', 'mediators', 'moderators'):
            for ref in entity.get(field) or []:
                parts.append(_entity_name(catalog, 'constructs', ref))
        haystack = ' '.join(parts).lower()
        if query and query not in haystack:
            continue
        if discipline and discipline not in (entity.get('discipline') or []):
            continue
        entities.append(entity)
    return entities


def _catalog_payload(kind, params=None, db_path=None, state_db_path=None, extra=None):
    params = params or {}
    catalog = load_catalog()
    _ensure_index(db_path, state_db_path, catalog)
    entities = _catalog_search(catalog, kind, params.get('q'), params.get('discipline'))
    if kind == 'methods':
        category = (params.get('category') or '').strip().lower()
        if category and category != 'all':
            entities = [item for item in entities if item.get('category') == category]
    precise, broad = _entity_counts(kind, state_db_path)
    payload = {
        'success': True,
        'entities': [_entity_card(entity, kind, catalog, precise, broad) for entity in entities],
        'disciplines': list(DISCIPLINES),
        'total': len(entities),
        'data_boundary': _data_boundary(catalog),
    }
    payload.update(extra or {})
    return payload


def build_theories_payload(params=None, db_path=None, state_db_path=None):
    return _catalog_payload('theories', params, db_path, state_db_path)


def build_constructs_payload(params=None, db_path=None, state_db_path=None):
    return _catalog_payload('constructs', params, db_path, state_db_path)


def build_methods_payload(params=None, db_path=None, state_db_path=None):
    return _catalog_payload('methods', params, db_path, state_db_path,
                            extra={'categories': list(METHOD_CATEGORIES)})


def _conceptual_model(catalog, theory):
    """Resolve the theory's own model, or derive one from its catalog fields.

    Every theory page used to render the same hard-coded Job Demands–Resources
    diagram.  A theory now shows either the pathways recorded for it or a
    generic antecedent→mechanism→outcome view built from its own fields, and
    nothing at all when neither exists.
    """
    model = theory.get('conceptual_model')
    if model and model.get('pathways'):
        return {
            'kind': 'pathways',
            'note': model.get('note'),
            'pathways': [
                {'label': pathway.get('label'),
                 'steps': _resolve_refs(catalog, 'constructs', pathway.get('steps'))}
                for pathway in model['pathways']
            ],
        }
    antecedents = _resolve_refs(catalog, 'constructs', theory.get('antecedents'))
    outcomes = _resolve_refs(catalog, 'constructs', theory.get('outcomes'))
    mechanisms = [{'id': None, 'name': item, 'resolved': False}
                  for item in theory.get('mechanisms') or []]
    if not (antecedents or mechanisms or outcomes):
        return None
    return {
        'kind': 'derived',
        'note': 'Derived from the antecedent, mechanism, and outcome fields recorded for this theory in the catalog. It is a navigation aid, not a tested model.',
        'columns': [
            {'label': 'Antecedents', 'items': antecedents},
            {'label': 'Mechanisms', 'items': mechanisms},
            {'label': 'Outcomes', 'items': outcomes},
        ],
    }



def _seminal_works(entity):
    """Source records with bibliographic and full-text access state explicit.

    A row is verified only after the verification script matched it to a real
    OpenAlex or Crossref record; everything else is presented as a lead to
    check, never as a confirmed citation. ``open_full_text`` means a legal OA
    locator was found; it does not mean the catalog copied or independently
    audited the publisher's version of record.
    """
    access_labels = {
        'not_checked': 'full-text access not checked',
        'open_full_text': 'open full-text locator found',
        'open_landing_page': 'open landing page found',
        'publisher_page': 'publisher/institutional access may be required',
        'metadata_only': 'metadata only; no DOI locator',
        'access_lookup_failed': 'access lookup failed; retry needed',
    }
    works = []
    for work in entity.get('seminal_works') or []:
        verification = work.get('verification')
        verified = verification in {'verified_openalex', 'verified_crossref', 'verified_pubmed'}
        source = work.get('verification_source')
        if not source and verification == 'verified_openalex':
            source = 'OpenAlex'
        if not source and verification == 'verified_crossref':
            source = 'Crossref'
        if not source and verification == 'verified_pubmed':
            source = 'PubMed'
        access_status = work.get('access_status') or 'not_checked'
        source_url = (work.get('full_text_url') or work.get('landing_url') or
                      ('https://doi.org/' + work['doi'] if work.get('doi') else None))
        works.append(dict(
            work,
            verified=verified,
            verification_source=source,
            doi_url=('https://doi.org/' + work['doi']) if work.get('doi') else None,
            source_url=source_url,
            access_status=access_status,
            access_display_status=access_labels.get(access_status, access_status),
            access_is_full_text=(access_status == 'open_full_text'),
            display_status=(('verified against ' + source) if verified and source
                            else 'unverified — check the primary source'),
        ))
    return works


def _source_authors(entity):
    """Return authors transcribed from catalog works, not canonical scholars."""
    rows = []
    for work in entity.get('seminal_works') or []:
        if not work.get('authors'):
            continue
        verification = work.get('verification')
        verified = verification in {'verified_openalex', 'verified_crossref', 'verified_pubmed'}
        source = work.get('verification_source')
        if not source and verification == 'verified_openalex':
            source = 'OpenAlex'
        if not source and verification == 'verified_crossref':
            source = 'Crossref'
        if not source and verification == 'verified_pubmed':
            source = 'PubMed'
        rows.append({
            'authors': work['authors'],
            'work_title': work.get('title'),
            'year': work.get('year'),
            'verification': verification,
            'verified': verified,
            'verification_source': source,
            'display_status': (('verified against ' + source) if verified and source
                               else 'catalog lead — verify primary source'),
        })
    return rows


def build_theory_detail(slug, db_path=None, state_db_path=None):
    catalog = load_catalog()
    entity = _catalog_entity(catalog, 'theories', slug)
    if not entity:
        return {'success': False, 'error': 'theory not found'}
    _ensure_index(db_path, state_db_path, catalog)
    precise, broad = _entity_counts('theories', state_db_path)
    papers = _query_papers({'theory': entity['id'], 'sort': 'date_desc', 'limit': 40},
                           db_path, catalog, state_db_path)
    broad_papers = {'total': 0, 'papers': [], 'sampled': False}
    if entity.get('broad_tags'):
        broad_all = _query_papers({'theory': entity['id'], 'include_broad': True,
                                   'sort': 'date_desc', 'limit': 20},
                                  db_path, catalog, state_db_path)
        precise_ids = {paper['id'] for paper in papers['papers']}
        broad_papers = {
            'total': max(0, broad_all['total'] - papers['total']),
            'papers': [p for p in broad_all['papers'] if p['id'] not in precise_ids],
            'sampled': broad_all['sampled'],
        }
    card = _entity_card(entity, 'theories', catalog, precise, broad)
    return {
        'success': True,
        'theory': dict(card, paper_count=papers['total']),
        'conceptual_model': _conceptual_model(catalog, entity),
        'core_constructs': [
            dict(_catalog_entity(catalog, 'constructs', item), relation_basis='catalog_theory_construct_link')
            for item in entity.get('core_constructs', [])
            if _catalog_entity(catalog, 'constructs', item)
        ],
        'antecedents': _resolve_refs(catalog, 'constructs', entity.get('antecedents')),
        'outcomes': _resolve_refs(catalog, 'constructs', entity.get('outcomes')),
        'moderators': _resolve_refs(catalog, 'constructs', entity.get('moderators')),
        'recent_applications': [_paper_reference(paper) for paper in papers['papers']],
        'broad_tag_applications': {
            'tags': sorted(entity.get('broad_tags') or []),
            'total': broad_papers['total'],
            'papers': [_paper_reference(paper) for paper in broad_papers['papers']],
            'note': 'These papers carry a broader umbrella tag that also covers other entities. They are shown separately because the tag does not establish that this specific theory was used.',
        },
        'seminal_works': _seminal_works(entity),
        'source_works': _seminal_works(entity),
        'seminal_papers_note': 'Author, year, title, venue, and source role begin as catalog candidates. A row is marked verified only after scripts/verify_research_sources.py matches it to OpenAlex or Crossref. A legal open-access locator is a separate status; it does not replace reading and citing the primary source.',
        'key_scholars': entity.get('key_scholars') or [],
        'key_scholars_note': 'No separate canonical key-scholar attribution is loaded. Source-author rows are shown separately from the catalog works and must not be read as a ranked or exhaustive scholar list.',
        'source_authors': _source_authors(entity),
        'related_theories': [
            dict(_catalog_entity(catalog, 'theories', item), relation_basis='catalog_related_theory')
            for item in entity.get('related_theories', [])
            if _catalog_entity(catalog, 'theories', item)
        ],
        'data_boundary': _data_boundary(catalog, papers['sampled'], len(papers['papers'])),
    }


def build_construct_detail(slug, params=None, db_path=None, state_db_path=None):
    catalog = load_catalog()
    entity = _catalog_entity(catalog, 'constructs', slug)
    if not entity:
        return {'success': False, 'error': 'construct not found'}
    params = params or {}
    _ensure_index(db_path, state_db_path, catalog)
    precise, broad = _entity_counts('constructs', state_db_path)
    sort = params.get('sort') or 'relevance_desc'
    if sort not in SORT_ORDERS:
        sort = 'relevance_desc'
    papers = _query_papers({'construct': entity['id'], 'sort': sort, 'limit': 50},
                           db_path, catalog, state_db_path)
    card = _entity_card(entity, 'constructs', catalog, precise, broad)
    network = {
        'antecedents': _resolve_refs(catalog, 'constructs', entity.get('antecedents')),
        'outcomes': _resolve_refs(catalog, 'constructs', entity.get('outcomes')),
        'mediators': _resolve_refs(catalog, 'constructs', entity.get('mediators')),
        'moderators': _resolve_refs(catalog, 'constructs', entity.get('moderators')),
        'note': 'Relationships recorded in the catalog scaffold. A relationship in a specific paper must be read from that paper, not inferred from this diagram.',
    }
    return {
        'success': True,
        'construct': dict(card, paper_count=papers['total']),
        'related_theories': [
            dict(_catalog_entity(catalog, 'theories', item), relation_basis='catalog_construct_theory_link')
            for item in entity.get('related_theories', [])
            if _catalog_entity(catalog, 'theories', item)
        ],
        'network': network,
        'sort': sort,
        'papers': [_paper_reference(paper) for paper in papers['papers']],
        'data_boundary': _data_boundary(catalog, papers['sampled'], len(papers['papers'])),
    }


def build_method_detail(slug, db_path=None, state_db_path=None):
    catalog = load_catalog()
    entity = _catalog_entity(catalog, 'methods', slug)
    if not entity:
        return {'success': False, 'error': 'method not found'}
    _ensure_index(db_path, state_db_path, catalog)
    precise, broad = _entity_counts('methods', state_db_path)
    papers = _query_papers({'method': entity['id'], 'sort': 'relevance_desc', 'limit': 50},
                           db_path, catalog, state_db_path)
    broad_papers = {'total': 0, 'papers': []}
    if entity.get('broad_tags'):
        broad_all = _query_papers({'method': entity['id'], 'include_broad': True,
                                   'sort': 'relevance_desc', 'limit': 20},
                                  db_path, catalog, state_db_path)
        precise_ids = {paper['id'] for paper in papers['papers']}
        broad_papers = {
            'total': max(0, broad_all['total'] - papers['total']),
            'papers': [p for p in broad_all['papers'] if p['id'] not in precise_ids],
        }
    card = _entity_card(entity, 'methods', catalog, precise, broad)
    return {
        'success': True,
        'method': dict(card, paper_count=papers['total']),
        'example_papers': [_paper_reference(paper) for paper in papers['papers']],
        'broad_tag_papers': {
            'tags': sorted(entity.get('broad_tags') or []),
            'total': broad_papers['total'],
            'papers': [_paper_reference(paper) for paper in broad_papers['papers']],
            'note': 'These papers carry a broader umbrella tag such as survey or causal_inference. The tag does not establish that this specific method was used.',
        },
        'related_methods': [
            dict(_catalog_entity(catalog, 'methods', item), relation_basis='catalog_related_method')
            for item in entity.get('related_methods', [])
            if _catalog_entity(catalog, 'methods', item)
        ],
        'data_boundary': _data_boundary(catalog, papers['sampled'], len(papers['papers'])),
    }


# ── overview, search, papers ─────────────────────────────────────────────────

def build_research_overview(db_path=None, state_db_path=None):
    catalog = load_catalog()
    _ensure_index(db_path, state_db_path, catalog)
    counts = {'papers': 0, 'a_star': 0, 'a': 0, 'theories': len(catalog['theories']),
              'constructs': len(catalog['constructs']), 'methods': len(catalog['methods'])}
    conn = _article_connect(db_path)
    try:
        # One grouped scan instead of a separate COUNT(*) pass.
        for row in conn.execute('''SELECT journal_abdc_rating, COUNT(*) AS n
                                   FROM astar_articles WHERE is_duplicate=0
                                   GROUP BY journal_abdc_rating'''):
            counts['papers'] += row['n']
            if row['journal_abdc_rating'] == 'A*':
                counts['a_star'] = row['n']
            elif row['journal_abdc_rating'] == 'A':
                counts['a'] = row['n']
        recent = conn.execute('''SELECT id, title, journal_title, publication_date,
                                        journal_abdc_rating, doi, cited_by_count
                                 FROM astar_articles WHERE is_duplicate=0
                                 ORDER BY publication_date DESC, id DESC LIMIT 8''').fetchall()
    finally:
        conn.close()
    return {
        'success': True,
        'counts': counts,
        'disciplines': list(DISCIPLINES),
        'method_categories': list(METHOD_CATEGORIES),
        'recent_papers': [dict(row) for row in recent],
        'data_boundary': _data_boundary(catalog),
        'links': {
            'journals': '/abdc',
            'radar': '/abdc-astar-research',
            'theories': '/abdc/theories',
            'constructs': '/abdc/constructs',
            'methods': '/abdc/methods',
            'landscape': '/abdc/landscape',
            'library': '/abdc/library',
        },
    }


def build_research_search(params=None, db_path=None, state_db_path=None):
    params = params or {}
    query = (params.get('q') or '').strip()
    catalog = load_catalog()
    _ensure_index(db_path, state_db_path, catalog)
    result = {'success': True, 'query': query}
    for kind in ('theories', 'constructs', 'methods'):
        precise, broad = _entity_counts(kind, state_db_path)
        entities = _catalog_search(catalog, kind, query)[:12]
        result[kind] = [_entity_card(entity, kind, catalog, precise, broad) for entity in entities]
    papers = (_query_papers({'q': query, 'limit': 12}, db_path, catalog, state_db_path)
              if query else {'total': 0, 'papers': [], 'sampled': False})
    result['papers'] = [_paper_reference(paper) for paper in papers['papers']]
    result['paper_total'] = papers['total']
    result['data_boundary'] = _data_boundary(catalog, papers['sampled'], len(papers['papers']))
    return result


def build_papers_payload(params=None, db_path=None, state_db_path=None):
    """Paginated paper list, used by the workspace paper picker."""
    params = dict(params or {})
    catalog = load_catalog()
    _ensure_index(db_path, state_db_path, catalog)
    params.setdefault('limit', 25)
    params.setdefault('sort', 'date_desc')
    result = _query_papers(params, db_path, catalog, state_db_path)
    return {
        'success': True,
        'papers': [_paper_reference(paper) for paper in result['papers']],
        'total': result['total'],
        'offset': result['offset'],
        'limit': result['limit'],
        'data_boundary': _data_boundary(catalog, result['sampled'], len(result['papers'])),
    }


# ── library state and notes ──────────────────────────────────────────────────

def _read_state(paper_id, state_db_path=None):
    conn = _state_connect(state_db_path)
    try:
        row = conn.execute('SELECT * FROM research_library_state WHERE paper_id=?',
                           (int(paper_id),)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else {
        'paper_id': int(paper_id), 'reading_status': 'unread', 'favorite': 0,
        'last_opened_at': None, 'updated_at': None,
    }


def _read_notes(paper_id, state_db_path=None):
    conn = _state_connect(state_db_path)
    try:
        rows = conn.execute('SELECT * FROM research_notes WHERE paper_id=? '
                            'ORDER BY updated_at DESC, id DESC', (int(paper_id),)).fetchall()
    finally:
        conn.close()
    return [dict(row, tags=_json_list(row['tags_json'])) for row in rows]


def build_paper_workspace(paper_id, db_path=None, state_db_path=None):
    catalog = load_catalog()
    result = _query_papers({'paper_id': int(paper_id), 'limit': 1}, db_path, catalog, state_db_path)
    if not result['papers']:
        return {'success': False, 'error': 'paper not found'}
    paper = result['papers'][0]
    state = _read_state(paper_id, state_db_path)
    paper['status'] = state.get('reading_status') or 'unread'
    paper['favorite'] = bool(state.get('favorite'))
    conn = _article_connect(db_path)
    try:
        rows = conn.execute('''SELECT source_name, source_type, source_url, raw_id,
                                      fetched_at, parser_notes
                               FROM astar_article_sources WHERE article_id=?
                               ORDER BY fetched_at DESC''', (int(paper_id),)).fetchall()
        sources = [dict(row) for row in rows]
    except sqlite3.Error:
        sources = []
    finally:
        conn.close()
    return {
        'success': True,
        'paper': paper,
        'notes': _read_notes(paper_id, state_db_path),
        'library_state': state,
        'source_records': sources,
        'note_tags': list(NOTE_TAGS),
        'data_boundary': _data_boundary(catalog),
        'workspace_note': 'Structured research question, hypotheses, findings, limitations, and future research are not present in the current A* metadata cache; empty fields remain explicit rather than inferred as facts.',
    }


def update_library_state(paper_id, payload=None, state_db_path=None):
    """Update reading status and favorite.

    Fields absent from the payload keep their stored value: a request that only
    toggles ``favorite`` must not silently reset a paper from ``read`` back to
    ``unread``.
    """
    payload = payload or {}
    current = _read_state(paper_id, state_db_path)
    if 'reading_status' in payload or 'status' in payload:
        status = payload.get('reading_status') or payload.get('status') or 'unread'
    else:
        status = current.get('reading_status') or 'unread'
    if status not in READING_STATUSES:
        raise ValueError('reading_status must be unread, reading, or read')
    if 'favorite' in payload:
        favorite = 1 if bool(payload.get('favorite')) else 0
    else:
        favorite = 1 if current.get('favorite') else 0
    now = _now()
    last_opened = payload.get('last_opened_at') or now
    conn = _state_connect(state_db_path)
    try:
        conn.execute('''INSERT INTO research_library_state
                        (paper_id, reading_status, favorite, last_opened_at, updated_at)
                        VALUES (?,?,?,?,?)
                        ON CONFLICT(paper_id) DO UPDATE SET
                          reading_status=excluded.reading_status,
                          favorite=excluded.favorite,
                          last_opened_at=COALESCE(excluded.last_opened_at, research_library_state.last_opened_at),
                          updated_at=excluded.updated_at''',
                     (int(paper_id), status, favorite, last_opened, now))
        conn.commit()
        row = conn.execute('SELECT * FROM research_library_state WHERE paper_id=?',
                           (int(paper_id),)).fetchone()
    finally:
        conn.close()
    return {'success': True, 'state': dict(row)}


def save_research_note(paper_id, payload=None, state_db_path=None):
    payload = payload or {}
    text = str(payload.get('note_text') or payload.get('text') or '').strip()
    if not text:
        raise ValueError('note_text is required')
    if len(text) > 20000:
        raise ValueError('note_text is too long')
    tags = [tag for tag in payload.get('tags', []) if tag in NOTE_TAGS]
    now = _now()
    conn = _state_connect(state_db_path)
    try:
        note_id = payload.get('note_id')
        if note_id:
            cur = conn.execute('''UPDATE research_notes SET note_text=?, tags_json=?, updated_at=?
                                  WHERE id=? AND paper_id=?''',
                               (text, json.dumps(tags, ensure_ascii=False), now,
                                int(note_id), int(paper_id)))
            if cur.rowcount == 0:
                raise ValueError('note not found')
        else:
            cur = conn.execute('''INSERT INTO research_notes
                                  (paper_id, note_text, tags_json, created_at, updated_at)
                                  VALUES (?,?,?,?,?)''',
                               (int(paper_id), text, json.dumps(tags, ensure_ascii=False), now, now))
            note_id = cur.lastrowid
        conn.commit()
        row = conn.execute('SELECT * FROM research_notes WHERE id=?', (int(note_id),)).fetchone()
    finally:
        conn.close()
    return {'success': True, 'note': dict(row, tags=_json_list(row['tags_json']))}


def delete_research_note(paper_id, note_id, state_db_path=None):
    conn = _state_connect(state_db_path)
    try:
        cur = conn.execute('DELETE FROM research_notes WHERE id=? AND paper_id=?',
                           (int(note_id), int(paper_id)))
        deleted = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return {'success': bool(deleted), 'deleted': bool(deleted)}


def build_library_payload(db_path=None, state_db_path=None, recent_ids=None):
    """Saved papers plus, optionally, the caller's recently opened papers."""
    conn = _state_connect(state_db_path)
    try:
        states = [dict(row) for row in conn.execute(
            '''SELECT * FROM research_library_state
               WHERE favorite=1 OR reading_status!='unread'
               ORDER BY updated_at DESC''').fetchall()]
        notes = {row['paper_id']: row['n'] for row in conn.execute(
            'SELECT paper_id, COUNT(*) n FROM research_notes GROUP BY paper_id')}
        opened = [dict(row) for row in conn.execute(
            '''SELECT * FROM research_library_state WHERE last_opened_at IS NOT NULL
               ORDER BY last_opened_at DESC LIMIT 12''').fetchall()]
    finally:
        conn.close()
    catalog = load_catalog()

    def reference(paper_id):
        result = _query_papers({'paper_id': paper_id, 'limit': 1}, db_path, catalog, state_db_path)
        return _paper_reference(result['papers'][0]) if result['papers'] else None

    papers = []
    for state in states:
        paper = reference(state['paper_id'])
        if not paper:
            continue
        paper.update({
            'reading_status': state['reading_status'],
            'favorite': bool(state['favorite']),
            'note_count': notes.get(state['paper_id'], 0),
            'updated_at': state['updated_at'],
        })
        papers.append(paper)

    seen = set()
    recent = []
    for paper_id in list(recent_ids or []) + [state['paper_id'] for state in opened]:
        try:
            paper_id = int(paper_id)
        except (TypeError, ValueError):
            continue
        if paper_id in seen:
            continue
        seen.add(paper_id)
        paper = reference(paper_id)
        if paper:
            paper['note_count'] = notes.get(paper_id, 0)
            recent.append(paper)
        if len(recent) >= 12:
            break

    return {'success': True, 'papers': papers, 'recent_papers': recent,
            'note_tags': list(NOTE_TAGS), 'data_boundary': _data_boundary(catalog)}


# ── landscape ────────────────────────────────────────────────────────────────

def _topic_label(value):
    return TOPIC_LABELS.get(value, str(value).replace('_', ' ').title())


def _distribution(counter, total, limit=12, label_fn=None):
    label_fn = label_fn or (lambda value: value)
    return [
        {'id': value, 'label': label_fn(value), 'count': count,
         'share': round(count / total * 100, 1) if total else 0}
        for value, count in counter.most_common(limit)
    ]


def _paper_sort_key(paper):
    cls = paper.get('classification') or {}
    return (
        float(cls.get('relevance_score') or 0),
        int(paper.get('citedByCount') or 0),
        int(paper.get('year') or 0),
    )


LANDSCAPE_SAMPLE_LIMIT = 3000


def build_landscape_payload(params=None, db_path=None, state_db_path=None):
    params = params or {}
    topic = (params.get('topic') or params.get('q') or '').strip()
    catalog = load_catalog()
    if not topic:
        return {
            'success': True, 'requires_topic': True, 'topic': '', 'papers': [],
            'message': 'Enter a topic to build a descriptive landscape from the available A* cache.',
            'data_boundary': _data_boundary(catalog),
        }
    _ensure_index(db_path, state_db_path, catalog)
    query_params = {
        'topic': topic,
        'from_year': params.get('from_year'),
        'to_year': params.get('to_year'),
        'discipline': params.get('discipline'),
        'rank': params.get('rank') or 'A*,A',
        'theory': params.get('theory'),
        'method': params.get('method'),
        'match': params.get('match') or 'all',
        'limit': LANDSCAPE_SAMPLE_LIMIT,
        'sort': 'date_desc',
    }
    result = _query_papers(query_params, db_path, catalog, state_db_path, light=True)
    relaxed = False
    if result['total'] == 0 and len(_search_terms(topic)) > 1 and query_params['match'] != 'any':
        # A multi-word topic entered as a phrase should not silently return an
        # empty landscape when the corpus does contain the individual concepts.
        query_params['match'] = 'any'
        result = _query_papers(query_params, db_path, catalog, state_db_path, light=True)
        relaxed = result['total'] > 0

    papers = result['papers']
    analyzed = len(papers)
    theme_counts = Counter()
    theory_counts = Counter()
    method_counts = Counter()
    construct_counts = Counter()
    outcome_counts = Counter()
    for paper in papers:
        for raw in paper.get('topics') or []:
            theme_counts[raw] += 1
        for ref in paper.get('theories') or []:
            if ref['relation_basis'] != BROAD_BASIS:
                theory_counts[ref['id']] += 1
        for ref in paper.get('methods') or []:
            if ref['relation_basis'] != BROAD_BASIS:
                method_counts[ref['id']] += 1
        for ref in paper.get('constructs') or []:
            construct_counts[ref['id']] += 1
            if ref['id'] in OUTCOME_CONSTRUCTS:
                outcome_counts[ref['id']] += 1

    theory_map = _catalog_map(catalog, 'theories')
    method_map = _catalog_map(catalog, 'methods')
    construct_map = _catalog_map(catalog, 'constructs')
    themes = _distribution(theme_counts, analyzed, label_fn=_topic_label)
    theories = _distribution(theory_counts, analyzed, label_fn=lambda v: theory_map.get(v, {}).get('name', v))
    methods = _distribution(method_counts, analyzed, label_fn=lambda v: method_map.get(v, {}).get('name', v))
    constructs = _distribution(construct_counts, analyzed, label_fn=lambda v: construct_map.get(v, {}).get('name', v))

    top_theories = [item['id'] for item in theories[:6]]
    top_outcomes = [item['id'] for item in _distribution(
        outcome_counts, analyzed, limit=6,
        label_fn=lambda v: construct_map.get(v, {}).get('name', v))]
    theory_papers = defaultdict(set)
    outcome_papers = defaultdict(set)
    by_id = {}
    for paper in papers:
        by_id[paper['id']] = paper
        for ref in paper.get('theories') or []:
            if ref['relation_basis'] != BROAD_BASIS:
                theory_papers[ref['id']].add(paper['id'])
        for ref in paper.get('constructs') or []:
            outcome_papers[ref['id']].add(paper['id'])

    matrix_rows = []
    matrix_cells = []
    for theory_id in top_theories:
        row = {'id': theory_id, 'label': theory_map.get(theory_id, {}).get('name', theory_id), 'cells': []}
        for outcome_id in top_outcomes:
            matching = sorted(theory_papers[theory_id] & outcome_papers[outcome_id])
            cell = {
                'id': theory_id + '::' + outcome_id,
                'theory_id': theory_id,
                'outcome_id': outcome_id,
                'label': (theory_map.get(theory_id, {}).get('name', theory_id) + ' × ' +
                          construct_map.get(outcome_id, {}).get('name', outcome_id)),
                'count': len(matching),
                'papers': [_paper_reference(by_id[pid]) for pid in matching[:12]],
            }
            row['cells'].append(cell)
            matrix_cells.append(cell)
        matrix_rows.append(row)
    matrix_columns = [{'id': item, 'label': construct_map.get(item, {}).get('name', item)}
                      for item in top_outcomes]

    underexplored = []
    underexplored_suppressed = None
    if analyzed < MIN_PAPERS_FOR_UNDEREXPLORED:
        underexplored_suppressed = (
            'Only %d papers matched this query. A combination count drawn from a corpus this '
            'small reflects the search terms and the classifier vocabulary more than the '
            'literature, so this section is withheld. Broaden the topic, year range, or rank '
            'filter to at least %d papers.' % (analyzed, MIN_PAPERS_FOR_UNDEREXPLORED))
    else:
        low_threshold = max(1, round(analyzed * 0.02))
        underexplored = [
            dict(cell, interpretation='relatively less represented in this available corpus')
            for cell in sorted(matrix_cells, key=lambda item: item['count'])
            if 0 < cell['count'] <= low_threshold
        ][:12]
        # A zero cell usually means the classifier never tagged the pair, which is
        # a coverage fact about the cache rather than an observation about the
        # literature.  Those are reported separately and explicitly.
        zero_cells = [dict(cell, interpretation='no paper in this corpus carries both tags; this may reflect classifier coverage rather than the literature')
                      for cell in matrix_cells if cell['count'] == 0][:6]
        underexplored.extend(zero_cells)

    network_nodes = [{'id': item['id'], 'label': item['label'], 'count': item['count']}
                     for item in constructs[:10]]
    node_ids = {node['id'] for node in network_nodes}
    network_edges = Counter()
    for paper in papers:
        ids = sorted({ref['id'] for ref in paper.get('constructs', []) if ref['id'] in node_ids})
        for left_index, left in enumerate(ids):
            for right in ids[left_index + 1:]:
                network_edges[(left, right)] += 1
    max_edge = max(network_edges.values()) if network_edges else 1
    network_links = [
        {'source': left, 'target': right,
         'source_label': construct_map.get(left, {}).get('name', left),
         'target_label': construct_map.get(right, {}).get('name', right),
         'count': count, 'strength': round(count / max_edge, 3)}
        for (left, right), count in network_edges.most_common(16)
    ]

    years = [paper['year'] for paper in papers if paper.get('year')]
    max_year = max(years) if years else None
    emerging = []
    if max_year:
        recent_start = max_year - 2
        prior_start = max_year - 5
        for theme_id in theme_counts:
            recent = sum(1 for paper in papers
                         if (paper.get('year') or 0) >= recent_start
                         and theme_id in (paper.get('topics') or []))
            prior = sum(1 for paper in papers
                        if prior_start <= (paper.get('year') or 0) < recent_start
                        and theme_id in (paper.get('topics') or []))
            if recent < 3:
                continue
            if prior == 0:
                growth = None
                direction = 'new'
            else:
                growth = round((recent - prior) / prior * 100, 1)
                direction = 'up_strong' if growth >= 50 else 'up' if growth > 0 else 'flat' if growth == 0 else 'down'
            emerging.append({'id': theme_id, 'label': _topic_label(theme_id),
                             'recent_count': recent, 'prior_count': prior,
                             'growth_pct': growth, 'direction': direction,
                             'basis': '%d-%d vs %d-%d' % (recent_start, max_year, prior_start, recent_start - 1)})
        emerging.sort(key=lambda item: (item['recent_count'],
                                        item['growth_pct'] if item['growth_pct'] is not None else 0),
                      reverse=True)

    representative = sorted(papers, key=_paper_sort_key, reverse=True)[:12]
    return {
        'success': True,
        'requires_topic': False,
        'topic': topic,
        'match_mode': query_params['match'],
        'relaxed_to_any_term': relaxed,
        'overview': {
            'papers': result['total'],
            'analyzed_papers': analyzed,
            'from_year': min(years) if years else None,
            'to_year': max(years) if years else None,
            'a_star': sum(1 for paper in papers if paper.get('abdcRank') == 'A*'),
            'a': sum(1 for paper in papers if paper.get('abdcRank') == 'A'),
            'sampled': result['sampled'],
            'sample_limit': LANDSCAPE_SAMPLE_LIMIT,
        },
        'themes': themes,
        'theories': theories,
        'methods': methods,
        'constructs': constructs,
        'construct_network': {'nodes': network_nodes, 'links': network_links},
        'matrix': {'rows': matrix_rows, 'columns': matrix_columns},
        'underexplored_combinations': underexplored,
        'underexplored_suppressed': underexplored_suppressed,
        'underexplored_minimum': MIN_PAPERS_FOR_UNDEREXPLORED,
        'underexplored_disclaimer': 'These patterns indicate relatively less-studied combinations in the available literature. They do not by themselves establish a theoretical research gap.',
        'emerging_topics': emerging[:12],
        'representative_papers': [_paper_reference(paper) for paper in representative],
        'selection_notes': 'Counts and links are descriptive observations from the available A* / A cache. Theory and method links reuse precise classification tags; construct links are title/abstract keyword inferences.',
        'data_boundary': _data_boundary(catalog, result['sampled'], analyzed),
    }
