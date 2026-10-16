# -*- coding: utf-8 -*-
"""A* 语义搜索：本地 embedding(BAAI/bge-small-en-v1.5, 384维) + 余弦检索。

- 构建：scripts/build_astar_embeddings.py 批量编码 title+abstract → data/astar_emb.npy
  (float32 已归一化) + data/astar_emb_ids.npy。增量：已有向量不重算。
- 检索：懒加载模型和矩阵；query 编码后点积即余弦。支持按期刊聚合(投稿匹配)。
- 依赖 sentence-transformers 可选：缺失时接口返回 available=False，不影响其他功能。
"""
import json
from contextlib import closing
import logging
import os
import sqlite3
import threading
from datetime import datetime

log = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_ROOT, 'pboc_data.db')
DATA_DIR = os.path.join(_ROOT, 'data')
EMB_PATH = os.path.join(DATA_DIR, 'astar_emb.npy')
IDS_PATH = os.path.join(DATA_DIR, 'astar_emb_ids.npy')
META_PATH = os.path.join(DATA_DIR, 'astar_emb_meta.json')
MODEL_NAME = 'BAAI/bge-small-en-v1.5'

_LOCK = threading.Lock()
_STATE = {'model': None, 'emb': None, 'ids': None, 'id2idx': None, 'asset_signature': None}

os.environ.setdefault('USE_TF', '0')          # 机器上有 Keras3，强制走 PyTorch
os.environ.setdefault('TRANSFORMERS_NO_TF', '1')

# 研究画像(英文侧写，与 bge-small-en 匹配；每条一个侧面，取各侧面余弦的最大值)。
# 与 abdc_astar_research_service.RESEARCH_PROFILE(中文)语义对应，改动请同步。
PROFILE_ASPECTS = [
    'remote work, work from home, hybrid work arrangements and return-to-office mandates',
    'artificial intelligence in organizations and algorithmic management of workers',
    'digital trace data, text mining and natural language processing in organizational research',
    'employee burnout, emotional exhaustion, withdrawal, turnover and exit-voice-loyalty-neglect responses',
    'job demands-resources theory and workplace wellbeing',
    'electronic monitoring, workplace surveillance, worker autonomy and control',
    'work-family boundary management and remote collaboration',
    'platform work, gig economy labor and delivery or logistics workers',
    'research using public data such as Glassdoor, Indeed, O*NET, BLS, social media or online reviews',
]


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _load_model():
    # Accepted ONNX generations use the numerically verified offline backend.
    if os.path.exists(META_PATH):
        with open(META_PATH, encoding='utf-8') as stream:
            metadata = json.load(stream)
        if metadata.get('encoder_backend') == 'onnx':
            from services.astar_semantic_backend import load_verified_model
            return load_verified_model(DATA_DIR, threads=2)
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME, device='cpu')


def _doc_text(title, abstract):
    t = (title or '').strip()
    a = (abstract or '').strip()
    return (t + '. ' + a[:1500]) if a else t


TITLEONLY_PATH = os.path.join(DATA_DIR, 'astar_emb_titleonly_ids.npy')


def _init_titleonly(conn, done_ids, meta_built_at):
    """sidecar 缺失时初始化"仅标题编码"集合：
    当前无摘要的 + 构建之后才补上摘要的(它们编码时也没摘要)。"""
    missing = {r[0] for r in conn.execute(
        "SELECT id FROM astar_articles WHERE is_duplicate=0 AND (abstract IS NULL OR abstract='')")}
    late_filled = set()
    if meta_built_at:
        late_filled = {r[0] for r in conn.execute(
            "SELECT id FROM astar_articles WHERE is_duplicate=0 AND abstract_status='available' AND updated_at > ?",
            (meta_built_at,))}
    return (missing | late_filled) & done_ids


def build_embeddings(batch_size=4, progress_every=20):
    """Apply a bounded, fingerprint-aware ONNX delta with immutable backups.

    Initial or unverified packs require the separate reviewed staging workflow.
    The historical batch/progress arguments remain accepted for CLI compatibility.
    """
    from services.astar_safe_semantic_update import update_embeddings
    result = update_embeddings(DB_PATH, DATA_DIR, batch_size=min(4, max(1, int(batch_size))))
    if result.get('applied'):
        with _LOCK:
            _STATE['emb'] = None
            _STATE['asset_signature'] = None
    return result


def _ensure_loaded():
    import numpy as np
    with _LOCK:
        signature = ((os.stat(META_PATH).st_mtime_ns, os.stat(META_PATH).st_size)
                     if os.path.exists(META_PATH) else None)
        if _STATE['emb'] is None or signature != _STATE.get('asset_signature'):
            if not (os.path.exists(EMB_PATH) and os.path.exists(IDS_PATH)):
                return False
            try:
                meta = {}
                if os.path.exists(META_PATH):
                    with open(META_PATH, encoding='utf-8') as meta_file:
                        meta = json.load(meta_file)
                emb = np.load(EMB_PATH)
                ids = np.load(IDS_PATH)
                if emb.ndim != 2 or len(ids) != len(emb) or (meta.get('count') is not None and int(meta['count']) != len(ids)):
                    raise ValueError('embedding generation and ID mapping do not agree')
            except (OSError, ValueError, json.JSONDecodeError):
                # Keep the previously loaded generation readable during a
                # metadata-last file activation; incomplete files are not used.
                return _STATE['emb'] is not None
            _STATE['emb'], _STATE['ids'] = emb, ids
            _STATE['id2idx'] = {int(a): i for i, a in enumerate(ids)}
            _STATE['asset_signature'] = signature
        if _STATE['model'] is None:
            _STATE['model'] = _load_model()
    return True


def _hydrate_articles(id_list, sim_map):
    """按 id 列表取文章元数据+分类，保持 id_list 顺序，附相似度。"""
    if not id_list:
        return []
    with closing(_connect()) as conn:
        marks = ','.join('?' * len(id_list))
        rows = {r['id']: dict(r) for r in conn.execute(f"""
            SELECT a.id, a.title, a.abstract, a.journal_title, a.publication_date,
                   a.publication_year, a.publication_month, a.doi, a.url,
                   a.cited_by_count, a.authors_json, c.relevance_score, c.broad_area
            FROM astar_articles a
            LEFT JOIN astar_article_classifications c ON c.article_id=a.id
            WHERE a.id IN ({marks})""", id_list)}
        from services.astar_archive_year_service import attach_years
        attach_years(conn, list(rows.values()))
    arts = []
    for aid in id_list:
        r = rows.get(aid)
        if not r:
            continue
        try:
            authors = [x.get('name') if isinstance(x, dict) else x
                       for x in json.loads(r.get('authors_json') or '[]')
                       if isinstance(x, (dict, str))][:5]
        except Exception:
            authors = []
        arts.append({'id': aid, 'similarity': round(sim_map[aid], 4), 'title': r['title'],
                     'journal_title': r['journal_title'], 'publication_date': r['publication_date'],
                     'publication_year': r['publication_year'], 'publication_month': r['publication_month'],
                     'archive_year': r.get('archive_year'), 'archive_year_basis': r.get('archive_year_basis'),
                     'doi': r['doi'], 'url': r['url'], 'authors': authors,
                     'abstract': (r['abstract'] or '')[:400],
                     'relevance_score': r['relevance_score'], 'broad_area': r['broad_area']})
    return arts


def find_similar(article_id, topk=10):
    """给定文章 id，返回向量空间里最近的 topk 篇(不含自身)。"""
    import numpy as np
    try:
        ok = _ensure_loaded()
    except Exception as e:
        return {'available': False, 'error': f'加载失败: {e}'}
    if not ok:
        return {'available': False, 'error': '向量库未构建。'}
    idx = _STATE['id2idx'].get(int(article_id))
    if idx is None:
        return {'available': True, 'error': '该文章尚未编码(新文章等每日增量)。', 'articles': []}
    sims = _STATE['emb'] @ _STATE['emb'][idx]
    order = np.argsort(-sims)
    id_list, sim_map = [], {}
    for i in order[:topk + 1]:
        aid = int(_STATE['ids'][i])
        if aid == int(article_id):
            continue
        id_list.append(aid)
        sim_map[aid] = float(sims[i])
        if len(id_list) >= topk:
            break
    return {'available': True, 'source_id': int(article_id),
            'articles': _hydrate_articles(id_list, sim_map)}


def compute_semantic_relevance(only_missing=True, batch=5000):
    """研究画像(多侧面) × 全库向量 → semantic_relevance(0-100，=最大余弦×100)存分类表。
    只需向量矩阵+一次编码画像句，CPU 秒级；only_missing 时只补未打分的(日增量用)。"""
    import numpy as np
    if not _ensure_loaded():
        return {'success': False, 'error': '向量库未构建'}
    aspects = _STATE['model'].encode(PROFILE_ASPECTS, normalize_embeddings=True).astype('float32')
    sims = _STATE['emb'] @ aspects.T            # (N, 侧面数)
    best = sims.max(axis=1)                     # 每篇取最贴近的侧面
    scores = np.round(np.clip(best, 0, 1) * 100, 1)
    ids = _STATE['ids']
    with _connect() as conn:
        try:
            conn.execute('ALTER TABLE astar_article_classifications ADD COLUMN semantic_relevance REAL')
        except sqlite3.OperationalError:
            pass    # 列已存在
        todo = None
        if only_missing:
            todo = {r[0] for r in conn.execute(
                'SELECT article_id FROM astar_article_classifications WHERE semantic_relevance IS NULL')}
        pairs = [(float(s), int(a)) for s, a in zip(scores, ids)
                 if todo is None or int(a) in todo]
        for i in range(0, len(pairs), batch):
            conn.executemany(
                'UPDATE astar_article_classifications SET semantic_relevance=? WHERE article_id=?',
                pairs[i:i + batch])
        conn.commit()
    return {'success': True, 'scored': len(pairs), 'aspects': len(PROFILE_ASPECTS)}


def semantic_status():
    meta = None
    if os.path.exists(META_PATH):
        try:
            meta = json.load(open(META_PATH, encoding='utf-8'))
        except Exception:
            pass
    return {'available': os.path.exists(EMB_PATH), 'meta': meta}


def semantic_search(query, topk=30):
    """query -> topk 文章(带相似度和分类) + 期刊聚合(投稿匹配)。"""
    import numpy as np
    try:
        ok = _ensure_loaded()
    except Exception as e:
        return {'available': False, 'error': f'加载失败: {e}'}
    if not ok:
        return {'available': False,
                'error': '向量库未构建。运行: python scripts/build_astar_embeddings.py'}
    q = _STATE['model'].encode([f'Represent this sentence for searching relevant passages: {query}'],
                               normalize_embeddings=True)[0].astype('float32')
    sims = _STATE['emb'] @ q
    top_idx = np.argsort(-sims)[:max(topk, 100)]     # 多取一些供期刊聚合
    id_list = [int(_STATE['ids'][i]) for i in top_idx]
    sim_map = {int(_STATE['ids'][i]): float(sims[i]) for i in top_idx}
    arts = _hydrate_articles(id_list, sim_map)
    # 期刊聚合：每刊取相似度前3篇的均值(既看强度也防单篇偶合)
    by_j = {}
    for a in arts:
        by_j.setdefault(a['journal_title'], []).append(a['similarity'])
    journals = [{'journal': j, 'score': round(sum(sorted(s, reverse=True)[:3]) / min(len(s), 3), 4),
                 'hits': len(s)} for j, s in by_j.items()]
    journals.sort(key=lambda x: -x['score'])
    return {'available': True, 'query': query,
            'articles': arts[:topk], 'journal_match': journals[:12],
            'meta': semantic_status()['meta']}
