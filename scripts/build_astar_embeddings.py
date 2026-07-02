# -*- coding: utf-8 -*-
"""构建/增量更新 A* 语义搜索向量库(bge-small-en-v1.5, CPU 可跑)。

    python scripts/build_astar_embeddings.py            # 增量(已有的跳过)
首次全量 13 万篇在 CPU 上约 20-60 分钟；之后每日增量只有几百篇，秒级。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('USE_TF', '0')
os.environ.setdefault('TRANSFORMERS_NO_TF', '1')

from services.astar_semantic_service import build_embeddings   # noqa: E402

if __name__ == '__main__':
    t0 = time.time()
    r = build_embeddings()
    print(f'完成: {r}  用时 {time.time() - t0:.0f}s')
