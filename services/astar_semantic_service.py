# -*- coding: utf-8 -*-
"""A* 语义搜索：本地 embedding(BAAI/bge-small-en-v1.5, 384维) + 余弦检索。

- 构建：scripts/build_astar_embeddings.py 批量编码 title+abstract → data/astar_emb.npy
  (float32 已归一化) + data/astar_emb_ids.npy。增量：已有向量不重算。
- 检索：懒加载模型和矩阵；query 编码后点积即余弦。支持按期刊聚合(投稿匹配)。
- 依赖 sentence-transformers 可选：缺失时接口返回 available=False，不影响其他功能。
"""
import json
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
_STATE = {'model': None, 'emb': None, 'ids': None, 'id2idx': None}

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
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME, device='cpu')


def _doc_text(title, abstract):
    t = (title or '').strip()
    a = (abstract or '').strip()
    return (t + '. ' + a[:1500]) if a else t


def build_embeddings(batch_size=256, progress_every=20):
    """全量/增量构建向量库。已有向量的文章跳过；新文章追加。"""
    import numpy as np
    os.makedirs(DATA_DIR, exist_ok=True)
    old_ids, old_emb = [], None
    if os.path.exists(EMB_PATH) and os.path.exists(IDS_PATH):
        old_emb = np.load(EMB_PATH)
        old_ids = np.load(IDS_PATH).tolist()
    done = set(old_ids)
    with _connect() as conn:
        rows = conn.execute("""SELECT id, title, abstract FROM astar_articles
                               WHERE is_duplicate=0 AND title IS NOT NULL""").fetchall()
    todo = [r for r in rows if r['id'] not in done]
    log.info(f'embedding 构建：库内 {len(rows)}，已有 {len(done)}，待编码 {len(todo)}')
    if not todo:
        return {'success': True, 'total': len(old_ids), 'encoded': 0}
    model = _load_model()
    new_vecs, new_ids = [], []
    for i in range(0, len(todo), batch_size):
        chunk = todo[i:i + batch_size]
        texts = [_doc_text(r['title'], r['abstract']) for r in chunk]
        vecs = model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                            show_progress_bar=False)
        new_vecs.append(vecs.astype('float32'))
        new_ids.extend(r['id'] for r in chunk)
        if (i // batch_size) % progress_every == 0:
            print(f'  {i + len(chunk)}/{len(todo)}  {datetime.now().strftime("%H:%M:%S")}', flush=True)
    new_mat = np.vstack(new_vecs)
    emb = np.vstack([old_emb, new_mat]) if old_emb is not None and len(old_ids) else new_mat
    ids = (old_ids + new_ids) if old_ids else new_ids
    np.save(EMB_PATH, emb)
    np.save(IDS_PATH, np.array(ids, dtype='int64'))
    with open(META_PATH, 'w', encoding='utf-8') as f:
        json.dump({'model': MODEL_NAME, 'dim': int(emb.shape[1]), 'count': len(ids),
                   'built_at': datetime.now().isoformat()}, f, ensure_ascii=False)
    with _LOCK:                    # 让服务端下次搜索时重新加载
        _STATE['emb'] = None
    return {'success': True, 'total': len(ids), 'encoded': len(new_ids)}


def _ensure_loaded():
    import numpy as np
    with _LOCK:
        if _STATE['emb'] is None:
            if not (os.path.exists(EMB_PATH) and os.path.exists(IDS_PATH)):
                return False
            _STATE['emb'] = np.load(EMB_PATH)
            _STATE['ids'] = np.load(IDS_PATH)
            _STATE['id2idx'] = {int(a): i for i, a in enumerate(_STATE['ids'])}
        if _STATE['model'] is None:
            _STATE['model'] = _load_model()
    return True


def _hydrate_articles(id_list, sim_map):
    """按 id 列表取文章元数据+分类，保持 id_list 顺序，附相似度。"""
    if not id_list:
        return []
    with _connect() as conn:
        marks = ','.join('?' * len(id_list))
        rows = {r['id']: dict(r) for r in conn.execute(f"""
            SELECT a.id, a.title, a.abstract, a.journal_title, a.publication_date, a.doi, a.url,
                   a.cited_by_count, a.authors_json, c.relevance_score, c.broad_area
            FROM astar_articles a
            LEFT JOIN astar_article_classifications c ON c.article_id=a.id
            WHERE a.id IN ({marks})""", id_list)}
    arts = []
    for aid in id_list:
        r = rows.get(aid)
        if not r:
            continue
        try:
            authors = [x.get('name') for x in json.loads(r.get('authors_json') or '[]')
                       if isinstance(x, dict)][:5]
        except Exception:
            authors = []
        arts.append({'id': aid, 'similarity': round(sim_map[aid], 4), 'title': r['title'],
                     'journal_title': r['journal_title'], 'publication_date': r['publication_date'],
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
