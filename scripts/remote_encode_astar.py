# -*- coding: utf-8 -*-
"""在 GPU 机上编码 A* 文本(与本地 services/astar_semantic_service._doc_text 完全一致)。"""
import gzip, json, os, sys, time

os.environ.setdefault('HF_HOME', '/home/simurghnobackup/zcui/hf_cache')
os.environ.setdefault('USE_TF', '0')

import numpy as np
from sentence_transformers import SentenceTransformer


def doc_text(title, abstract):
    t = (title or '').strip()
    a = (abstract or '').strip()
    return (t + '. ' + a[:1500]) if a else t


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else 'astar_texts.jsonl.gz'
    rows = [json.loads(l) for l in gzip.open(src, 'rt', encoding='utf-8')]
    texts = [doc_text(r.get('title'), r.get('abstract')) for r in rows]
    ids = np.array([r['id'] for r in rows], dtype='int64')
    print(f'texts: {len(texts)}', flush=True)
    model = SentenceTransformer('BAAI/bge-small-en-v1.5', device='cuda')
    t0 = time.time()
    emb = model.encode(texts, batch_size=256, normalize_embeddings=True,
                       show_progress_bar=True).astype('float32')
    print(f'encode 用时 {time.time()-t0:.0f}s  shape={emb.shape}', flush=True)
    np.save('astar_emb.npy', emb)
    np.save('astar_emb_ids.npy', ids)
    print('saved.', flush=True)


if __name__ == '__main__':
    main()
