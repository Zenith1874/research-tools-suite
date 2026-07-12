# -*- coding: utf-8 -*-
"""A* 研究兴趣多维匹配 —— 派生数据层。

设计原则(项目数据纪律):
- 原始库 pboc_data.db 只读；所有模型产物写独立 data/astar_interest.db。
- 论文基础标签(aim_paper_labels)与画像无关，每篇只抽一次；
  论文×画像的多维分(aim_profile_scores)与画像有关，新增/改画像只重算这个。
- 每条模型输出带 provenance：model、prompt_version、prompt_hash、input_hash、run_at。
- 不造数据：LLM 未给的字段留空/missing，不填 0。
"""
import glob
import hashlib
import json
import os
import sqlite3
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_DB = os.path.join(_ROOT, 'pboc_data.db')
AIM_DB = os.path.join(_ROOT, 'data', 'astar_interest.db')
PROFILE_DIR = os.path.join(_ROOT, 'profiles')

DIMENSIONS = ['topic', 'theory', 'method', 'data', 'setting', 'opportunity']


def connect(db_path=AIM_DB):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS aim_profiles (
        profile_id TEXT PRIMARY KEY, name TEXT, description TEXT,
        aspects_json TEXT, weights_json TEXT, my_methods_json TEXT,
        enabled INTEGER DEFAULT 1, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS aim_paper_labels (
        article_id INTEGER PRIMARY KEY,
        research_topics_json TEXT, constructs_json TEXT, theories_json TEXT,
        methods_json TEXT, data_sources_json TEXT, settings_json TEXT,
        analysis_levels_json TEXT, country TEXT, time_range TEXT,
        research_question TEXT, key_findings TEXT, evidence_spans_json TEXT,
        uncertainty INTEGER DEFAULT 0,
        model TEXT, prompt_version TEXT, prompt_hash TEXT, input_hash TEXT, run_at TEXT
    );
    CREATE TABLE IF NOT EXISTS aim_profile_scores (
        article_id INTEGER, profile_id TEXT,
        topic_match REAL, theory_match REAL, method_match REAL,
        data_match REAL, setting_match REAL, opportunity REAL, overall REAL,
        rationale TEXT, model TEXT, run_at TEXT,
        PRIMARY KEY (article_id, profile_id)
    );
    CREATE TABLE IF NOT EXISTS aim_runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage TEXT, profile_ids TEXT, model TEXT, prompt_version TEXT,
        n_input INTEGER, n_output INTEGER, started TEXT, finished TEXT, notes TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_aim_scores_profile ON aim_profile_scores(profile_id, overall);
    """)
    conn.commit()


# ── 画像 ──────────────────────────────────────────────────────────────────────
def load_profile_files():
    """读 profiles/*.json(忽略 _schema)。"""
    out = []
    for p in sorted(glob.glob(os.path.join(PROFILE_DIR, '*.json'))):
        try:
            out.append(json.load(open(p, encoding='utf-8')))
        except Exception:
            pass
    return out


def sync_profiles_to_db():
    profs = load_profile_files()
    with connect() as conn:
        ensure_tables(conn)
        now = datetime.now().isoformat()
        for p in profs:
            conn.execute("""INSERT INTO aim_profiles
                (profile_id,name,description,aspects_json,weights_json,my_methods_json,enabled,updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(profile_id) DO UPDATE SET
                  name=excluded.name, description=excluded.description, aspects_json=excluded.aspects_json,
                  weights_json=excluded.weights_json, my_methods_json=excluded.my_methods_json,
                  enabled=excluded.enabled, updated_at=excluded.updated_at""",
                (p['profile_id'], p.get('name'), p.get('description'),
                 json.dumps(p.get('aspects', {}), ensure_ascii=False),
                 json.dumps(p.get('weights', {}), ensure_ascii=False),
                 json.dumps(p.get('my_methods_used', []), ensure_ascii=False),
                 1 if p.get('enabled', True) else 0, now))
        conn.commit()
    return len(profs)


# ── 工具 ──────────────────────────────────────────────────────────────────────
def input_hash(title, abstract):
    return hashlib.sha256(((title or '') + '\n' + (abstract or '')).encode('utf-8')).hexdigest()[:16]


def overall_from_dims(dim_scores, weights):
    """加权归一(0-100)。dim_scores/weights 键为 DIMENSIONS 子集。"""
    num = den = 0.0
    for d in DIMENSIONS:
        w = float(weights.get(d, 0) or 0)
        v = dim_scores.get(d)
        if v is not None and w:
            num += w * float(v)
            den += w
    return round(num / den, 1) if den else None


def fetch_articles(article_ids):
    """从主库只读取标题/摘要/期刊。"""
    if not article_ids:
        return []
    conn = sqlite3.connect(MAIN_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    marks = ','.join('?' * len(article_ids))
    rows = conn.execute(f"""SELECT id, title, abstract, journal_title, publication_date
                            FROM astar_articles WHERE id IN ({marks})""", article_ids).fetchall()
    conn.close()
    by_id = {r['id']: dict(r) for r in rows}
    return [by_id[i] for i in article_ids if i in by_id]


def save_labels(conn, article_id, labels, meta):
    L = lambda k: json.dumps(labels.get(k, []), ensure_ascii=False)
    conn.execute("""INSERT INTO aim_paper_labels
        (article_id,research_topics_json,constructs_json,theories_json,methods_json,
         data_sources_json,settings_json,analysis_levels_json,country,time_range,
         research_question,key_findings,evidence_spans_json,uncertainty,
         model,prompt_version,prompt_hash,input_hash,run_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(article_id) DO UPDATE SET
          research_topics_json=excluded.research_topics_json, constructs_json=excluded.constructs_json,
          theories_json=excluded.theories_json, methods_json=excluded.methods_json,
          data_sources_json=excluded.data_sources_json, settings_json=excluded.settings_json,
          analysis_levels_json=excluded.analysis_levels_json, country=excluded.country,
          time_range=excluded.time_range, research_question=excluded.research_question,
          key_findings=excluded.key_findings, evidence_spans_json=excluded.evidence_spans_json,
          uncertainty=excluded.uncertainty, model=excluded.model, prompt_version=excluded.prompt_version,
          prompt_hash=excluded.prompt_hash, input_hash=excluded.input_hash, run_at=excluded.run_at""",
        (article_id, L('research_topics'), L('constructs'), L('theories'), L('methods'),
         L('data_sources'), L('settings'), L('analysis_levels'),
         labels.get('country'), labels.get('time_range'),
         labels.get('research_question'), labels.get('key_findings'),
         L('evidence_spans'), 1 if labels.get('uncertainty') else 0,
         meta['model'], meta['prompt_version'], meta['prompt_hash'], meta['input_hash'], meta['run_at']))


def save_scores(conn, article_id, profile_id, dims, overall, rationale, model, run_at):
    conn.execute("""INSERT INTO aim_profile_scores
        (article_id,profile_id,topic_match,theory_match,method_match,data_match,setting_match,
         opportunity,overall,rationale,model,run_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(article_id,profile_id) DO UPDATE SET
          topic_match=excluded.topic_match, theory_match=excluded.theory_match,
          method_match=excluded.method_match, data_match=excluded.data_match,
          setting_match=excluded.setting_match, opportunity=excluded.opportunity,
          overall=excluded.overall, rationale=excluded.rationale, model=excluded.model, run_at=excluded.run_at""",
        (article_id, profile_id, dims.get('topic'), dims.get('theory'), dims.get('method'),
         dims.get('data'), dims.get('setting'), dims.get('opportunity'), overall, rationale, model, run_at))
