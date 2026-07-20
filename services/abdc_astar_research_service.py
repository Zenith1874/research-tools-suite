"""
ABDC A* 研究动态（A* Research Radar）服务

定位：基于现有 ABDC 期刊列表筛出最新版本 A* 期刊，用 ISSN 经 OpenAlex / Crossref
持续追踪这些顶刊最近发表的文章，做主题/理论/方法/数据类型分类，并按个人研究方向
（WFH/RTO、AI in orgs、algorithmic management、digital trace/NLP、burnout/EVLN、
JD-R、OB-IS 交叉等）打相关性分。

数据纪律（参考此前金融页面教训）：
  - API 失败不造 mock；没有数据就空状态。
  - 只有 title 没有 abstract 时 abstract_status='missing'，绝不伪造摘要。
  - 元数据不足不强行分类（classification_status='insufficient_metadata'）。
  - 只追踪当前 ABDC 版本评级为 A* 的期刊（除非显式切换版本）。
  - 全部走公开 scholarly metadata API，不抓全文、不绕付费墙。
"""

import os, re, json, time, sqlite3, logging
from datetime import datetime, timedelta, date

import requests

from services.journal_lists import FT50, UTD24, match_norm

log = logging.getLogger(__name__)

_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH   = os.path.join(_ROOT, 'pboc_data.db')
ABDC_PATH = os.path.join(_ROOT, 'data', 'abdc_data.json')

# OpenAlex / Crossref polite pool 联系邮箱：本地用环境变量 ASTAR_MAILTO 设置真实邮箱
MAILTO = os.environ.get('ASTAR_MAILTO', 'research-radar@example.com')
OPENALEX_BASE = 'https://api.openalex.org/works'
CROSSREF_BASE = 'https://api.crossref.org/journals'
S2_BATCH_URL  = 'https://api.semanticscholar.org/graph/v1/paper/batch'
HTTP_TIMEOUT  = 25
POLITE_DELAY  = 0.15                       # 每次外部请求之间的间隔（秒）

# ── ANZSRC FoR 代码 → 学科 / broad_area ─────────────────────────────────────
FOR_DISCIPLINE = {
    '3501': ('Accounting', 'Accounting'),
    '3502': ('Banking, Finance & Investment', 'Finance'),
    '3503': ('Business Systems in Context', 'Management / Strategy'),
    '3504': ('Commercial Services', 'Management / Strategy'),
    '3505': ('Human Resources & Industrial Relations', 'OB / HR'),
    '3506': ('Marketing', 'Marketing'),
    '3507': ('Strategy, Management & Organisational Behaviour', 'OB / HR'),
    '3508': ('Tourism', 'Management / Strategy'),
    '3509': ('Transportation, Logistics & Supply Chains', 'Operations / Supply Chain'),
    '3599': ('Other Commerce/Management', 'Management / Strategy'),
    '3801': ('Applied Economics', 'Economics'),
    '3802': ('Econometrics', 'Economics'),
    '3803': ('Economic Theory', 'Economics'),
    '3804': ('Economics (other)', 'Economics'),
    '4609': ('Information Systems', 'Information Systems'),
    '4602': ('Artificial Intelligence', 'Information Systems'),
    '3505 ': ('Human Resources & Industrial Relations', 'OB / HR'),
    '4801': ('Law', 'Law'),
    '4905': ('Statistics & Probability', 'Statistics / Methods'),
}
# IS 期刊在 ABDC 里有时 FoR=46xx，有时仍在 35xx；用期刊名兜底（见下）
IS_JOURNAL_HINTS = [
    'information systems', 'mis quarterly', 'information technology',
    'electronic commerce', 'information management', 'jmis',
]


# ════════════════════════════════════════════════════════════════════════════
#  建表
# ════════════════════════════════════════════════════════════════════════════
DDL = [
    """CREATE TABLE IF NOT EXISTS abdc_astar_journals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        abdc_journal_id TEXT,
        journal_title TEXT,
        journal_title_normalized TEXT,
        issn_print TEXT,
        issn_online TEXT,
        issn_l TEXT,
        abdc_rating TEXT,
        abdc_version TEXT,
        field_of_research TEXT,
        discipline TEXT,
        publisher TEXT,
        is_active INTEGER DEFAULT 1,
        source_table TEXT,
        created_at TEXT,
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS astar_articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doi TEXT UNIQUE,
        openalex_id TEXT,
        semantic_scholar_id TEXT,
        title TEXT,
        title_normalized TEXT,
        abstract TEXT,
        abstract_status TEXT,
        publication_date TEXT,
        publication_year INTEGER,
        publication_month TEXT,
        journal_title TEXT,
        journal_issn TEXT,
        journal_abdc_rating TEXT,
        journal_abdc_version TEXT,
        publisher TEXT,
        authors_json TEXT,
        author_count INTEGER,
        concepts_json TEXT,
        keywords_json TEXT,
        url TEXT,
        landing_page_url TEXT,
        open_access_status TEXT,
        cited_by_count INTEGER,
        source_name TEXT,
        source_type TEXT,
        source_url TEXT,
        data_status TEXT,
        is_duplicate INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS astar_article_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER,
        source_name TEXT,
        source_type TEXT,
        source_url TEXT,
        raw_id TEXT,
        raw_json TEXT,
        fetched_at TEXT,
        parser_notes TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS astar_article_classifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER UNIQUE,
        broad_area TEXT,
        research_topic TEXT,
        theory_tags_json TEXT,
        method_tags_json TEXT,
        data_type_tags_json TEXT,
        context_tags_json TEXT,
        geo_context TEXT,
        sample_context TEXT,
        ai_related_score REAL,
        work_related_score REAL,
        wfh_rto_related_score REAL,
        ob_hr_related_score REAL,
        is_related_to_my_research INTEGER,
        relevance_score REAL,
        classification_method TEXT,
        classification_status TEXT,
        classification_notes TEXT,
        classified_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS astar_update_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT,
        finished_at TEXT,
        success INTEGER,
        update_mode TEXT,
        abdc_version TEXT,
        journals_checked INTEGER,
        journals_with_issn INTEGER,
        journals_missing_issn INTEGER,
        articles_found INTEGER,
        articles_inserted INTEGER,
        articles_updated INTEGER,
        duplicates_skipped INTEGER,
        failed_journals INTEGER,
        failed_sources TEXT,
        warnings TEXT,
        error_message TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS astar_saved_articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER UNIQUE,
        saved_at TEXT,
        user_note TEXT,
        reading_status TEXT,
        project_tag TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS journal_prestige_lists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        journal_title TEXT,
        journal_title_normalized TEXT,
        issn_print TEXT,
        issn_online TEXT,
        abdc_rating TEXT,
        is_utd24 INTEGER DEFAULT 0,
        is_ft50 INTEGER DEFAULT 0,
        in_astar_tracked INTEGER DEFAULT 0,
        matched_abdc INTEGER DEFAULT 0,
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS astar_journal_health (
        journal_id INTEGER PRIMARY KEY,
        journal_title TEXT,
        abdc_rating TEXT,
        issn TEXT,
        db_count INTEGER,
        db_recent2y INTEGER,
        db_latest TEXT,
        oa_works_count INTEGER,
        oa_recent2y INTEGER,
        oa_latest_year INTEGER,
        status TEXT,
        note TEXT,
        checked_at TEXT
    )""",
]

# FT50/UTD24 标题 → ABDC 主表标题的别名（少数命名差异）
PRESTIGE_TITLE_ALIASES = {
    'human resource management': 'human resource management (us)',
}

# ABDC 清单中过期/错误的刊号修正（normalize_title → (issn_print, issn_online)）
# Environment and Planning B 2017 改名为 Urban Analytics and City Science，新刊号 2399-808x
ISSN_OVERRIDES = {
    'environment and planning b urban analytics and city science': ('2399-8083', '2399-8091'),
    # ABDC 录入刊号 0002-0515 有误，JEL 正确刊号为 0022-0515 / eISSN 2328-8175
    'journal of economic literature': ('0022-0515', '2328-8175'),
}

# 已知 OpenAlex 把会议论文错并入期刊 ISSN 的情况：要求 DOI 含指定子串才视为该刊正刊文章。
# JAIS (1536-9323) 被混入大量 AIS eLibrary 会议论文（无 DOI），正刊 DOI 为 10.17705/1jais.*
JOURNAL_DOI_FILTER = {
    '1536-9323': '1jais',
    '1558-3457': '1jais',
}

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_astar_pubdate ON astar_articles(publication_date)",
    "CREATE INDEX IF NOT EXISTS idx_astar_journal ON astar_articles(journal_issn)",
    "CREATE INDEX IF NOT EXISTS idx_astar_titlenorm ON astar_articles(title_normalized)",
    "CREATE INDEX IF NOT EXISTS idx_astar_cls_article ON astar_article_classifications(article_id)",
    "CREATE INDEX IF NOT EXISTS idx_prestige_issnp ON journal_prestige_lists(issn_print)",
    "CREATE INDEX IF NOT EXISTS idx_prestige_issno ON journal_prestige_lists(issn_online)",
    # 注：来源表去重的唯一索引在 dedup_article_sources() 里去重后再建（避免脏数据导致建索引失败）
]


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=8000')
    return conn


def ensure_astar_tables(conn=None):
    own = conn is None
    if own:
        conn = get_db()
    for sql in DDL:
        conn.execute(sql)
    for sql in INDEXES:
        conn.execute(sql)
    conn.commit()
    if own:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
#  归一化
# ════════════════════════════════════════════════════════════════════════════
def normalize_title(s):
    if not s:
        return ''
    s = s.lower()
    s = re.sub(r'<[^>]+>', ' ', s)          # 去 HTML/JATS 标签
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def normalize_issn(s):
    if not s:
        return ''
    s = str(s).strip().upper().replace(' ', '')
    s = s.replace('\t', '')
    m = re.match(r'^(\d{4})-?(\d{3}[\dX])$', s)
    if m:
        return f'{m.group(1)}-{m.group(2)}'
    return s if s else ''


# ════════════════════════════════════════════════════════════════════════════
#  从现有 ABDC 列表加载 A* 期刊
# ════════════════════════════════════════════════════════════════════════════
def _latest_version(data):
    # 年份字符串里取最大
    return sorted(data.keys(), key=lambda v: int(v), reverse=True)[0]


def discipline_for(journal):
    code = str(journal.get('for', '')).strip()
    title_l = (journal.get('title') or '').lower()
    if any(h in title_l for h in IS_JOURNAL_HINTS):
        return 'Information Systems', 'Information Systems'
    disc, area = FOR_DISCIPLINE.get(code, ('Other', 'Other'))
    return disc, area


def load_astar_journals_from_abdc(version='latest'):
    """读取指定（默认最新）ABDC 版本的 A* 期刊，写入 abdc_astar_journals。
    返回统计 dict。不修改原 abdc_data.json。"""
    with open(ABDC_PATH, encoding='utf-8') as f:
        data = json.load(f)
    if version in ('latest', None, ''):
        version = _latest_version(data)
    if version not in data:
        raise ValueError(f'ABDC 版本不存在: {version}')

    astar = [j for j in data[version] if (j.get('rating') or '').strip() == 'A*']
    now = datetime.now().isoformat(timespec='seconds')

    conn = get_db()
    ensure_astar_tables(conn)
    # 重新生成该版本的 A* 期刊集合（只清 A* 行，保留 prestige_extra 等非 A* 追踪刊）
    conn.execute("DELETE FROM abdc_astar_journals WHERE abdc_version=? AND abdc_rating='A*'", (version,))

    with_issn = missing_issn = 0
    for j in astar:
        title = (j.get('title') or '').strip()
        issn_p = normalize_issn(j.get('issn'))
        issn_o = normalize_issn(j.get('issnOnline'))
        ov = ISSN_OVERRIDES.get(normalize_title(title))   # 修正 ABDC 过期/错误刊号
        if ov:
            issn_p, issn_o = ov
        disc, _area = discipline_for(j)
        has_issn = bool(issn_p or issn_o)
        if has_issn:
            with_issn += 1
        else:
            missing_issn += 1
        conn.execute("""
            INSERT INTO abdc_astar_journals
              (abdc_journal_id, journal_title, journal_title_normalized,
               issn_print, issn_online, issn_l, abdc_rating, abdc_version,
               field_of_research, discipline, publisher, is_active,
               source_table, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (None, title, normalize_title(title), issn_p, issn_o,
             issn_p or issn_o, 'A*', version, str(j.get('for', '')).strip(),
             disc, (j.get('publisher') or '').strip(), 1,
             'abdc_data.json', now, now))
    conn.commit()
    conn.close()
    return {'abdc_version': version, 'astar_journal_count': len(astar),
            'with_issn_count': with_issn, 'missing_issn_count': missing_issn}


def load_journal_prestige_lists():
    """从 FT50 / UTD24 标题清单解析 ISSN（匹配 ABDC 主表）并写入 journal_prestige_lists。
    标记每刊是否 UTD24 / FT50、ABDC 评级、是否在当前 A* 追踪集中。返回匹配报告。"""
    with open(ABDC_PATH, encoding='utf-8') as f:
        data = json.load(f)
    # ABDC 主表：normalized title → (issn, issnOnline, rating, title)（取所有版本并集，优先最新）
    master = {}
    for ver in sorted(data.keys(), key=lambda v: int(v), reverse=True):
        for j in data[ver]:
            k = match_norm(j.get('title', ''))
            if k and k not in master:
                master[k] = (normalize_issn(j.get('issn')), normalize_issn(j.get('issnOnline')),
                             (j.get('rating') or '').strip(), (j.get('title') or '').strip())

    # 合并 FT50 + UTD24 → {normalized_title: {title, is_ft50, is_utd24}}
    merged = {}
    for t in FT50:
        merged.setdefault(match_norm(t), {'title': t, 'is_ft50': 0, 'is_utd24': 0})['is_ft50'] = 1
    for t in UTD24:
        merged.setdefault(match_norm(t), {'title': t, 'is_ft50': 0, 'is_utd24': 0})['is_utd24'] = 1

    conn = get_db()
    ensure_astar_tables(conn)
    # A* 追踪集的 ISSN 全集（判断该刊是否已被雷达抓取）
    tracked_issns = set()
    for r in conn.execute("SELECT issn_print, issn_online FROM abdc_astar_journals"):
        if r['issn_print']:
            tracked_issns.add(r['issn_print'])
        if r['issn_online']:
            tracked_issns.add(r['issn_online'])

    conn.execute('DELETE FROM journal_prestige_lists')
    now = datetime.now().isoformat(timespec='seconds')
    matched = notfound = tracked = 0
    not_found_titles, not_tracked = [], []
    for k, info in merged.items():
        mk = match_norm(PRESTIGE_TITLE_ALIASES.get(k, k))
        m = master.get(mk)
        issn_p = m[0] if m else ''
        issn_o = m[1] if m else ''
        rating = m[2] if m else ''
        is_matched = 1 if m else 0
        if m:
            matched += 1
        else:
            notfound += 1
            not_found_titles.append(info['title'])
        in_tracked = 1 if (issn_p in tracked_issns or issn_o in tracked_issns) else 0
        if in_tracked:
            tracked += 1
        elif m:
            not_tracked.append(f"{info['title']} (ABDC {rating or '?'})")
        conn.execute("""INSERT INTO journal_prestige_lists
            (journal_title, journal_title_normalized, issn_print, issn_online, abdc_rating,
             is_utd24, is_ft50, in_astar_tracked, matched_abdc, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (info['title'], k, issn_p, issn_o, rating,
             info['is_utd24'], info['is_ft50'], in_tracked, is_matched, now))
    conn.commit()
    conn.close()
    return {'ft50_count': len(FT50), 'utd24_count': len(UTD24),
            'unique_journals': len(merged), 'matched_abdc': matched,
            'not_found_in_abdc': notfound, 'not_found_titles': not_found_titles,
            'in_astar_tracked': tracked, 'not_tracked_in_astar': not_tracked}


def ensure_prestige_extra_journals(version='latest'):
    """把 FT50/UTD24 中匹配到 ABDC 但评级非 A*（因此不在 A* 集合）的期刊，
    作为 source_table='prestige_extra' 持久写入 abdc_astar_journals，使雷达也抓取它们。
    需要 journal_prestige_lists 已载入。返回新增/已有计数。"""
    with open(ABDC_PATH, encoding='utf-8') as f:
        data = json.load(f)
    if version in ('latest', None, ''):
        version = _latest_version(data)
    # ABDC 主表 normalized title -> 完整记录（用于取 FoR/discipline）
    master = {}
    for ver in sorted(data.keys(), key=lambda v: int(v), reverse=True):
        for j in data[ver]:
            k = match_norm(j.get('title', ''))
            if k and k not in master:
                master[k] = j

    conn = get_db()
    ensure_astar_tables(conn)
    if conn.execute('SELECT COUNT(*) FROM journal_prestige_lists').fetchone()[0] == 0:
        conn.close()
        load_journal_prestige_lists()
        conn = get_db()

    extras = conn.execute(
        'SELECT * FROM journal_prestige_lists WHERE matched_abdc=1 AND in_astar_tracked=0').fetchall()
    now = datetime.now().isoformat(timespec='seconds')
    added = existed = 0
    for p in extras:
        issn_p, issn_o = p['issn_print'], p['issn_online']
        # 已在集合（任一 ISSN 命中）则跳过
        exists = conn.execute(
            "SELECT 1 FROM abdc_astar_journals WHERE issn_print=? OR issn_online=? OR "
            "(issn_print=? AND issn_print!='') LIMIT 1",
            (issn_p, issn_p, issn_o)).fetchone()
        if exists:
            existed += 1
            continue
        rec = master.get(p['journal_title_normalized']) or \
              master.get(match_norm(PRESTIGE_TITLE_ALIASES.get(p['journal_title_normalized'],
                                                               p['journal_title_normalized'])))
        disc, _area = discipline_for(rec) if rec else ('Other', 'Other')
        conn.execute("""INSERT INTO abdc_astar_journals
            (abdc_journal_id, journal_title, journal_title_normalized, issn_print, issn_online,
             issn_l, abdc_rating, abdc_version, field_of_research, discipline, publisher,
             is_active, source_table, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (None, (rec.get('title').strip() if rec else p['journal_title']),
             p['journal_title_normalized'], issn_p, issn_o, issn_p or issn_o,
             p['abdc_rating'] or 'A', version, str(rec.get('for', '')).strip() if rec else '',
             disc, (rec.get('publisher') or '').strip() if rec else '', 1,
             'prestige_extra', now, now))
        added += 1
    conn.commit()
    conn.close()
    return {'added': added, 'already_present': existed}


def backfill_prestige_extra(from_date='2020-01-01', to_date=None):
    """对 prestige_extra（FT50/UTD24 非 A*）期刊做定向回填。"""
    ensure_prestige_extra_journals('latest')
    return _run_update('backfill_prestige_extra', 0, 'latest', per_journal_cap=1500,
                       from_date=from_date, to_date=to_date or date.today().isoformat(),
                       source_filter='prestige_extra')


def refetch_truncated_journals(threshold=1490, from_date='2020-01-01', cap=8000):
    """找出当前库内文章数 >= threshold（疑似被旧的每窗口上限截断）的期刊，
    用更高 cap 分页重抓 from_date 至今，补齐被截断的旧文章。返回统计。"""
    conn = get_db()
    ensure_astar_tables(conn)
    rows = conn.execute("""
        SELECT j.*, COUNT(a.id) n FROM abdc_astar_journals j
        LEFT JOIN astar_articles a
          ON (a.journal_issn=j.issn_print OR a.journal_issn=j.issn_online) AND a.is_duplicate=0
        GROUP BY j.id HAVING n >= ? ORDER BY n DESC""", (threshold,)).fetchall()
    to_date = date.today().isoformat()
    targets = [dict(r) for r in rows]
    started = datetime.now().isoformat(timespec='seconds')
    inserted = updated = found = 0
    per_journal = []
    for j in targets:
        j['_area'] = _area_from_discipline(j.get('discipline'))
        arts, src, err = fetch_recent_articles_for_journal(j, from_date, to_date, per_journal_cap=cap)
        time.sleep(POLITE_DELAY)
        ins = upd = 0
        for art in arts:
            status, _ = _upsert_article(conn, art, j)
            if status == 'inserted':
                ins += 1
            elif status == 'updated':
                upd += 1
        conn.commit()
        found += len(arts)
        inserted += ins
        updated += upd
        per_journal.append({'journal': j['journal_title'], 'fetched': len(arts), 'inserted': ins})
    conn.execute("""INSERT INTO astar_update_logs
        (started_at,finished_at,success,update_mode,abdc_version,journals_checked,journals_with_issn,
         journals_missing_issn,articles_found,articles_inserted,articles_updated,duplicates_skipped,
         failed_journals,failed_sources,warnings,error_message)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (started, datetime.now().isoformat(timespec='seconds'), 1, 'refetch_truncated', None,
         len(targets), len(targets), 0, found, inserted, updated, 0, 0, '[]',
         json.dumps([p['journal'] for p in per_journal], ensure_ascii=False), None))
    conn.commit()
    conn.close()
    return {'success': True, 'journals_refetched': len(targets), 'articles_found': found,
            'articles_inserted': inserted, 'articles_updated': updated, 'per_journal': per_journal}


# ════════════════════════════════════════════════════════════════════════════
#  文章抓取：OpenAlex（主）+ Crossref（兜底）
# ════════════════════════════════════════════════════════════════════════════
def reconstruct_abstract(inverted_index):
    """OpenAlex 的 abstract_inverted_index → 纯文本。"""
    if not inverted_index:
        return None
    positions = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    if not positions:
        return None
    positions.sort(key=lambda x: x[0])
    text = ' '.join(w for _, w in positions)
    return text.strip() or None


def _http_get_json(url, params=None, headers=None):
    h = {'User-Agent': f'ABDC-AstarRadar/1.0 (mailto:{MAILTO})'}
    if headers:
        h.update(headers)
    r = requests.get(url, params=params, headers=h, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _parse_openalex_work(w, issn):
    abstract = reconstruct_abstract(w.get('abstract_inverted_index'))
    authors = [a.get('author', {}).get('display_name')
               for a in w.get('authorships', []) if a.get('author')]
    authors = [a for a in authors if a]
    concepts = [{'name': c.get('display_name'), 'score': c.get('score'),
                 'level': c.get('level')} for c in w.get('concepts', [])]
    src = (w.get('primary_location') or {}).get('source') or {}
    doi = w.get('doi')
    if doi:
        doi = doi.replace('https://doi.org/', '').lower()
    oa = w.get('open_access') or {}
    return {
        'doi': doi,
        'openalex_id': (w.get('id') or '').replace('https://openalex.org/', ''),
        'title': w.get('title') or w.get('display_name'),
        'abstract': abstract,
        'abstract_status': 'inverted_index_reconstructed' if abstract else 'missing',
        'publication_date': w.get('publication_date'),
        'publication_year': w.get('publication_year'),
        'journal_title': src.get('display_name'),
        'journal_issn': issn,
        'publisher': src.get('host_organization_name'),
        'authors': authors,
        'concepts': concepts,
        'keywords': [k.get('display_name') for k in w.get('keywords', [])] if w.get('keywords') else [],
        'url': w.get('doi') or (w.get('primary_location') or {}).get('landing_page_url'),
        'landing_page_url': (w.get('primary_location') or {}).get('landing_page_url'),
        'open_access_status': oa.get('oa_status'),
        'cited_by_count': w.get('cited_by_count'),
        'source_name': 'OpenAlex',
        'source_type': 'openalex',
        'source_url': w.get('id'),
        'data_status': 'api_metadata' if abstract else 'title_only',
    }


def fetch_openalex(issn, from_date, to_date, max_total=200):
    """用单个 ISSN 查 OpenAlex works，cursor 分页直到取完或达 max_total。
    深度回填时 max_total 调大即可拿到窗口内全部文章（不再只取最近 200）。"""
    flt = (f'primary_location.source.issn:{issn},'
           f'from_publication_date:{from_date},'
           f'to_publication_date:{to_date},'
           f'type:article')
    out, cursor, pages = [], '*', 0
    while cursor and len(out) < max_total:
        params = {'filter': flt, 'per-page': 200, 'cursor': cursor, 'mailto': MAILTO}
        data = _http_get_json(OPENALEX_BASE, params=params)
        for w in data.get('results', []):
            out.append(_parse_openalex_work(w, issn))
        cursor = (data.get('meta') or {}).get('next_cursor')
        pages += 1
        if pages > 1:
            time.sleep(POLITE_DELAY)   # 多页时礼貌停顿
        if not data.get('results'):
            break
    return out[:max_total]


def fetch_crossref(issn, from_date, to_date, rows=100):
    """Crossref 兜底。"""
    url = f'{CROSSREF_BASE}/{issn}/works'
    params = {'filter': f'from-pub-date:{from_date},until-pub-date:{to_date}',
              'sort': 'published', 'order': 'desc',
              'rows': min(rows, 200), 'mailto': MAILTO}
    data = _http_get_json(url, params=params)
    out = []
    for it in data.get('message', {}).get('items', []):
        title = (it.get('title') or [None])[0]
        if not title:
            continue
        parts = (it.get('published') or it.get('published-online')
                 or it.get('published-print') or {}).get('date-parts', [[None]])
        dp = parts[0] if parts else [None]
        y = dp[0] if len(dp) > 0 else None
        mo = dp[1] if len(dp) > 1 else 1
        da = dp[2] if len(dp) > 2 else 1
        pub_date = f'{y}-{mo:02d}-{da:02d}' if y else None
        authors = [' '.join(filter(None, [a.get('given'), a.get('family')]))
                   for a in it.get('author', [])] if it.get('author') else []
        abstract = it.get('abstract')
        if abstract:
            abstract = re.sub(r'<[^>]+>', '', abstract).strip()
        doi = (it.get('DOI') or '').lower() or None
        out.append({
            'doi': doi,
            'openalex_id': None,
            'title': title,
            'abstract': abstract,
            'abstract_status': 'available' if abstract else 'missing',
            'publication_date': pub_date,
            'publication_year': y,
            'journal_title': (it.get('container-title') or [None])[0],
            'journal_issn': issn,
            'publisher': it.get('publisher'),
            'authors': authors,
            'concepts': [],
            'keywords': it.get('subject', []),
            'url': it.get('URL'),
            'landing_page_url': it.get('URL'),
            'open_access_status': None,
            'cited_by_count': it.get('is-referenced-by-count'),
            'source_name': 'Crossref',
            'source_type': 'crossref',
            'source_url': f'https://doi.org/{doi}' if doi else it.get('URL'),
            'data_status': 'api_metadata' if abstract else 'title_only',
        })
    return out


def fetch_recent_articles_for_journal(journal, from_date, to_date, per_journal_cap=200):
    """对一个期刊（dict，含 issn_print/issn_online）抓最近文章。
    OpenAlex 优先，失败或 0 结果再试 Crossref。返回 (articles, source_used, error)。"""
    issns = [i for i in [journal.get('issn_print'), journal.get('issn_online')] if i]
    if not issns:
        return [], None, 'no_issn'
    last_err = None
    # OpenAlex
    for issn in issns:
        try:
            arts = fetch_openalex(issn, from_date, to_date, max_total=per_journal_cap)
            if arts:
                return arts[:per_journal_cap], 'openalex', None
        except Exception as e:
            last_err = f'openalex:{e}'
            time.sleep(POLITE_DELAY)
    # Crossref 兜底
    for issn in issns:
        try:
            arts = fetch_crossref(issn, from_date, to_date, rows=per_journal_cap)
            if arts:
                return arts[:per_journal_cap], 'crossref', None
        except Exception as e:
            last_err = f'crossref:{e}'
            time.sleep(POLITE_DELAY)
    return [], None, last_err


# ════════════════════════════════════════════════════════════════════════════
#  分类（规则法）+ 个人研究相关性评分
# ════════════════════════════════════════════════════════════════════════════
TOPIC_KEYWORDS = {
    'remote_work': ['remote work', 'remote working', 'telework', 'telecommut', 'work from home', 'work-from-home', 'wfh'],
    'hybrid_work': ['hybrid work', 'hybrid working', 'hybrid arrangement'],
    'return_to_office': ['return to office', 'return-to-office', 'rto', 'back to office', 'office return'],
    'AI_in_organizations': ['artificial intelligence', 'machine learning at work', 'ai adoption', 'generative ai', 'large language model', 'chatgpt', 'ai-based', 'ai in the workplace', 'human-ai'],
    'algorithmic_management': ['algorithmic management', 'algorithmic control', 'algorithm manage', 'algorithmic boss'],
    'digital_transformation': ['digital transformation', 'digitalization', 'digitalisation', 'digital technolog'],
    'platform_work': ['platform work', 'platform labor', 'platform economy', 'digital platform'],
    'gig_work': ['gig work', 'gig economy', 'gig worker', 'on-demand work', 'crowdwork', 'crowd work'],
    'logistics_delivery': ['delivery', 'logistics', 'courier', 'last mile', 'last-mile', 'rider', 'driver'],
    'leadership': ['leadership', 'leader', 'supervisor', 'manager behavior'],
    'employee_wellbeing': ['well-being', 'wellbeing', 'mental health', 'work stress'],
    'burnout': ['burnout', 'exhaustion', 'emotional exhaustion'],
    'turnover': ['turnover', 'quitting', 'attrition', 'intention to leave', 'retention'],
    'voice': ['employee voice', 'speaking up', 'voice behavior'],
    'engagement': ['work engagement', 'employee engagement', 'job engagement'],
    'collaboration': ['collaboration', 'teamwork', 'coordination', 'cooperat'],
    'surveillance_monitoring': ['surveillance', 'monitoring', 'electronic monitoring', 'tracking employees', 'workplace monitoring'],
    'autonomy_control': ['autonomy', 'job control', 'discretion', 'control at work'],
    'work_family_boundary': ['work-family', 'work family', 'work-life', 'work life balance', 'boundary management'],
    'social_support': ['social support', 'coworker support', 'supervisor support'],
    'supply_chain_resilience': ['supply chain resilience', 'supply chain disruption', 'supply chain risk'],
    'customer_reviews': ['online review', 'customer review', 'product review', 'user review', 'rating review'],
    'labor_market': ['labor market', 'labour market', 'job posting', 'vacancy', 'hiring', 'wage'],
    'inequality': ['inequality', 'pay gap', 'gender gap', 'discrimination'],
    'organizational_change': ['organizational change', 'organisational change', 'change management', 'restructuring'],
    'strategy_innovation': ['innovation', 'r&d', 'new product', 'strategic renewal'],
}

METHOD_KEYWORDS = {
    'experiment': ['experiment', 'experimental', 'randomized', 'randomised', 'rct', 'treatment group'],
    'field_experiment_data': ['field experiment'],
    'lab_experiment_data': ['lab experiment', 'laboratory experiment'],
    'survey': ['survey', 'questionnaire', 'self-report'],
    'field_study': ['field study', 'field data', 'field setting'],
    'panel_data': ['panel data', 'longitudinal', 'fixed effects', 'random effects'],
    'archival_data': ['archival', 'secondary data', 'administrative records'],
    'text_mining': ['text mining', 'text analysis', 'topic model', 'lda', 'dictionary-based'],
    'NLP': ['natural language processing', 'nlp', 'word embedding', 'bert', 'language model', 'sentiment analysis'],
    'machine_learning': ['machine learning', 'deep learning', 'neural network', 'predictive model', 'classifier', 'random forest'],
    'causal_inference': ['causal', 'instrumental variable', 'regression discontinuity', 'propensity score'],
    'difference_in_differences': ['difference-in-differences', 'difference in differences', 'diff-in-diff', 'did design'],
    'event_study': ['event study'],
    'qualitative_interviews': ['interview', 'qualitative', 'grounded theory'],
    'ethnography': ['ethnograph', 'participant observation'],
    'theory_paper': ['we theorize', 'conceptual model', 'theory development', 'a theory of', 'theoretical framework'],
    'review': ['literature review', 'systematic review', 'review of', 'we review'],
    'meta_analysis': ['meta-analysis', 'meta analytic', 'meta-analytic'],
    'simulation': ['simulation', 'agent-based', 'monte carlo'],
    'analytical_modeling': ['analytical model', 'game-theoretic', 'game theoretic', 'mathematical model'],
}

DATA_TYPE_KEYWORDS = {
    'survey_data': ['survey data', 'questionnaire'],
    'administrative_data': ['administrative data', 'administrative records', 'personnel records'],
    'social_media_text': ['twitter', 'social media', 'tweets', 'facebook', 'reddit', 'weibo'],
    'online_reviews': ['online review', 'customer review', 'product review', 'yelp'],
    'job_postings': ['job posting', 'job ad', 'vacancy posting', 'job advertisement'],
    'Glassdoor': ['glassdoor'],
    'Indeed': ['indeed.com', 'indeed reviews'],
    'LinkedIn': ['linkedin'],
    'O*NET': ['o*net', 'onet', 'occupational information network'],
    'BLS': ['bureau of labor statistics', 'bls data', 'current population survey'],
    'app_store_reviews': ['app store', 'app review', 'mobile app review'],
    'customer_transaction_data': ['transaction data', 'purchase data', 'scanner data'],
    'financial_data': ['stock returns', 'financial statements', 'compustat', 'crsp'],
    'patent_data': ['patent', 'uspto'],
    'email_or_collaboration_logs': ['email metadata', 'communication logs', 'collaboration logs', 'digital trace', 'slack data'],
    'interview_data': ['interview data', 'interview transcript'],
}

THEORY_KEYWORDS = {
    'JD_R': ['job demands-resources', 'job demands resources', 'jd-r', 'jdr model', 'demands and resources'],
    'EVLN': ['exit voice loyalty', 'exit, voice', 'evln'],
    'sensemaking': ['sensemaking', 'sense-making'],
    'institutional_theory': ['institutional theory', 'institutional logic', 'legitimacy'],
    'social_exchange': ['social exchange'],
    'conservation_of_resources': ['conservation of resources', 'cor theory'],
    'job_design': ['job design', 'job characteristics', 'job crafting'],
    'self_determination': ['self-determination', 'self determination theory', 'intrinsic motivation'],
    'signaling': ['signaling theory', 'signalling theory', 'signal '],
    'transaction_cost': ['transaction cost'],
    'resource_based_view': ['resource-based view', 'resource based view', 'rbv'],
    'upper_echelons': ['upper echelons', 'ceo characteristics', 'tmt '],
    'agency_theory': ['agency theory', 'principal-agent', 'principal agent'],
    'behavioral_theory_of_firm': ['behavioral theory of the firm'],
}

BROAD_AREA_KEYWORDS = {
    'OB / HR': ['employee', 'workplace', 'job satisfaction', 'turnover', 'leadership', 'team', 'human resource', 'motivation', 'organizational behavior', 'organisational behaviour'],
    'Information Systems': ['information system', 'it adoption', 'digital platform', 'is research', 'technology use', 'online platform'],
    'Marketing': ['consumer', 'marketing', 'brand', 'advertising', 'customer', 'product review'],
    'Operations / Supply Chain': ['supply chain', 'operations management', 'inventory', 'logistics', 'manufacturing'],
    'Finance': ['stock', 'investor', 'portfolio', 'capital structure', 'asset pricing', 'bank'],
    'Accounting': ['audit', 'earnings', 'financial reporting', 'disclosure', 'accrual'],
    'Economics': ['labor market', 'wage', 'gdp', 'monetary', 'economic growth', 'welfare'],
    'Entrepreneurship': ['entrepreneur', 'startup', 'start-up', 'venture', 'new firm'],
    'International Business': ['multinational', 'foreign market', 'cross-border', 'internationalization', 'mne '],
    'Management / Strategy': ['strategy', 'competitive advantage', 'firm performance', 'corporate', 'governance'],
}

# 个人研究方向加权关键词
RELEVANCE_TOPIC_WEIGHTS = {
    'remote_work': 18, 'hybrid_work': 18, 'return_to_office': 18,
    'AI_in_organizations': 16, 'algorithmic_management': 18,
    'platform_work': 12, 'gig_work': 12, 'logistics_delivery': 8,
    'burnout': 14, 'turnover': 10, 'voice': 12, 'surveillance_monitoring': 14,
    'autonomy_control': 12, 'work_family_boundary': 12, 'social_support': 8,
    'customer_reviews': 6, 'labor_market': 6, 'employee_wellbeing': 8,
    'engagement': 6,
}
RELEVANCE_METHOD_WEIGHTS = {
    'text_mining': 12, 'NLP': 14, 'machine_learning': 10,
    'field_experiment_data': 6, 'experiment': 4, 'causal_inference': 4,
}
RELEVANCE_DATA_WEIGHTS = {
    'job_postings': 12, 'Glassdoor': 14, 'Indeed': 12, 'O*NET': 10, 'BLS': 8,
    'online_reviews': 8, 'social_media_text': 8, 'app_store_reviews': 8,
    'email_or_collaboration_logs': 10, 'LinkedIn': 8,
}
RELEVANCE_AREA_BONUS = {
    'OB / HR': 10, 'Information Systems': 10, 'Management / Strategy': 5,
    'Operations / Supply Chain': 5, 'Marketing': 4,
}


def _match_tags(text, keyword_map):
    hits = []
    for tag, kws in keyword_map.items():
        if any(kw in text for kw in kws):
            hits.append(tag)
    return hits


def classify_article(article):
    """基于 title + abstract + concepts 做规则分类与相关性评分。
    返回 classification dict（不写库）。"""
    title = article.get('title') or ''
    abstract = article.get('abstract') or ''
    concepts = article.get('concepts') or []
    concept_text = ' '.join((c.get('name') or '').lower() for c in concepts)
    text = f'{title}\n{abstract}\n{concept_text}'.lower()

    has_abstract = bool(abstract)
    # 元数据不足：只有很短的标题、没有摘要也没有 concepts
    insufficient = (not has_abstract and len(concepts) == 0 and len(title.split()) < 4)

    topics = _match_tags(text, TOPIC_KEYWORDS)
    methods = _match_tags(text, METHOD_KEYWORDS)
    data_types = _match_tags(text, DATA_TYPE_KEYWORDS)
    theories = _match_tags(text, THEORY_KEYWORDS)

    # broad_area：先按期刊学科，再用关键词增强
    area = article.get('_journal_discipline_area') or 'Other'
    area_hits = _match_tags(text, BROAD_AREA_KEYWORDS)
    # 关键词只在期刊学科本身模糊时用于细化；单一学科期刊（法学/统计/经济/金融/会计）
    # 不因零星商科关键词被改写（如 Biometrika 论文出现 "performance" 不应变 Management）。
    if area_hits and area in ('Other', 'Management / Strategy'):
        area = area_hits[0]

    # geo / sample context（轻量）
    geo = None
    for token, label in [('china', 'China'), ('united states', 'US'), ('u.s.', 'US'),
                         ('europe', 'Europe'), ('india', 'India'), ('germany', 'Germany')]:
        if token in text:
            geo = label
            break

    # ── 相关性评分 ──
    score = 0.0
    notes = []
    for t in topics:
        w = RELEVANCE_TOPIC_WEIGHTS.get(t, 0)
        if w:
            score += w
            notes.append(f'topic:{t}+{w}')
    for m in methods:
        w = RELEVANCE_METHOD_WEIGHTS.get(m, 0)
        if w:
            score += w
            notes.append(f'method:{m}+{w}')
    for d in data_types:
        w = RELEVANCE_DATA_WEIGHTS.get(d, 0)
        if w:
            score += w
            notes.append(f'data:{d}+{w}')
    area_bonus = RELEVANCE_AREA_BONUS.get(area, 0)
    if area_bonus and (topics or methods or data_types):
        score += area_bonus
        notes.append(f'area:{area}+{area_bonus}')

    # 多个核心研究主题共现 → 组合加分（更像"正中我的研究"的文章）
    core_topics = [t for t in topics if RELEVANCE_TOPIC_WEIGHTS.get(t, 0) >= 12]
    if len(core_topics) >= 2:
        score += 15
        notes.append(f'core_combo({len(core_topics)})+15')

    # 子维度分（0-100）
    ai_score = min(100, sum(RELEVANCE_TOPIC_WEIGHTS.get(t, 0) for t in topics
                            if t in ('AI_in_organizations', 'algorithmic_management')) * 4)
    wfh_score = min(100, sum(RELEVANCE_TOPIC_WEIGHTS.get(t, 0) for t in topics
                             if t in ('remote_work', 'hybrid_work', 'return_to_office')) * 4)
    work_score = min(100, sum(RELEVANCE_TOPIC_WEIGHTS.get(t, 0) for t in topics
                              if t in ('platform_work', 'gig_work', 'logistics_delivery',
                                       'labor_market', 'autonomy_control', 'surveillance_monitoring')) * 3)
    ob_score = min(100, (area_bonus if area in ('OB / HR',) else 0) * 4 +
                   sum(RELEVANCE_TOPIC_WEIGHTS.get(t, 0) for t in topics
                       if t in ('burnout', 'turnover', 'voice', 'engagement',
                                'employee_wellbeing', 'social_support')) * 3)

    # 无摘要时降低 confidence（封顶，避免仅凭标题给高分）
    if not has_abstract:
        score = min(score, 55)
        notes.append('no_abstract:cap55')

    score = round(min(score, 100), 1)
    is_related = 1 if score >= 60 else 0

    if insufficient:
        status = 'insufficient_metadata'
    elif (topics or methods or data_types or theories):
        status = 'confident' if has_abstract else 'uncertain'
    else:
        status = 'uncertain'

    return {
        'broad_area': area,
        'research_topic': topics,
        'theory_tags': theories,
        'method_tags': methods,
        'data_type_tags': data_types,
        'context_tags': [],
        'geo_context': geo,
        'sample_context': None,
        'ai_related_score': round(ai_score, 1),
        'work_related_score': round(work_score, 1),
        'wfh_rto_related_score': round(wfh_score, 1),
        'ob_hr_related_score': round(ob_score, 1),
        'is_related_to_my_research': is_related,
        'relevance_score': score,
        'classification_method': 'rules',
        'classification_status': status,
        'classification_notes': '; '.join(notes) if notes else ('no relevance signals' if not insufficient else 'metadata too sparse'),
    }


# ════════════════════════════════════════════════════════════════════════════
#  入库（含去重）+ 分类持久化
# ════════════════════════════════════════════════════════════════════════════
def _find_existing(conn, art):
    """去重：DOI → openalex_id → normalized title+journal+year。返回已存在 id 或 None。"""
    if art.get('doi'):
        r = conn.execute('SELECT id FROM astar_articles WHERE doi=?', (art['doi'],)).fetchone()
        if r:
            return r['id']
    if art.get('openalex_id'):
        r = conn.execute('SELECT id FROM astar_articles WHERE openalex_id=?', (art['openalex_id'],)).fetchone()
        if r:
            return r['id']
    tn = normalize_title(art.get('title'))
    if tn:
        r = conn.execute(
            'SELECT id FROM astar_articles WHERE title_normalized=? AND publication_year IS ?',
            (tn, art.get('publication_year'))).fetchone()
        if r:
            return r['id']
    return None


def _persist_classification(conn, article_id, art):
    art2 = dict(art)
    # 把期刊学科 area 传给分类器（用于 broad_area 兜底）
    cls = classify_article(art2)
    now = datetime.now().isoformat(timespec='seconds')
    conn.execute("""
        INSERT INTO astar_article_classifications
          (article_id, broad_area, research_topic, theory_tags_json, method_tags_json,
           data_type_tags_json, context_tags_json, geo_context, sample_context,
           ai_related_score, work_related_score, wfh_rto_related_score, ob_hr_related_score,
           is_related_to_my_research, relevance_score, classification_method,
           classification_status, classification_notes, classified_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(article_id) DO UPDATE SET
          broad_area=excluded.broad_area, research_topic=excluded.research_topic,
          theory_tags_json=excluded.theory_tags_json, method_tags_json=excluded.method_tags_json,
          data_type_tags_json=excluded.data_type_tags_json, context_tags_json=excluded.context_tags_json,
          geo_context=excluded.geo_context, ai_related_score=excluded.ai_related_score,
          work_related_score=excluded.work_related_score, wfh_rto_related_score=excluded.wfh_rto_related_score,
          ob_hr_related_score=excluded.ob_hr_related_score,
          is_related_to_my_research=excluded.is_related_to_my_research,
          relevance_score=excluded.relevance_score, classification_method=excluded.classification_method,
          classification_status=excluded.classification_status,
          classification_notes=excluded.classification_notes, classified_at=excluded.classified_at""",
        (article_id, cls['broad_area'], json.dumps(cls['research_topic']),
         json.dumps(cls['theory_tags']), json.dumps(cls['method_tags']),
         json.dumps(cls['data_type_tags']), json.dumps(cls['context_tags']),
         cls['geo_context'], cls['sample_context'], cls['ai_related_score'],
         cls['work_related_score'], cls['wfh_rto_related_score'], cls['ob_hr_related_score'],
         cls['is_related_to_my_research'], cls['relevance_score'], cls['classification_method'],
         cls['classification_status'], cls['classification_notes'], now))
    return cls


def _upsert_article(conn, art, journal):
    """插入或更新一篇文章。返回 ('inserted'|'updated'|'duplicate'|'filtered', article_id)。"""
    now = datetime.now().isoformat(timespec='seconds')
    # 已知会议论文污染的刊：DOI 不含指定子串则跳过（如 JAIS 的 AIS 会议论文）
    req = JOURNAL_DOI_FILTER.get(art.get('journal_issn'))
    if req and req not in (art.get('doi') or ''):
        return 'filtered', None
    art['_journal_discipline_area'] = journal.get('_area')
    existing_id = _find_existing(conn, art)

    pub_month = None
    if art.get('publication_date') and len(art['publication_date']) >= 7:
        pub_month = art['publication_date'][:7]

    fields = dict(
        doi=art.get('doi'), openalex_id=art.get('openalex_id'),
        title=art.get('title'), title_normalized=normalize_title(art.get('title')),
        abstract=art.get('abstract'), abstract_status=art.get('abstract_status'),
        publication_date=art.get('publication_date'), publication_year=art.get('publication_year'),
        publication_month=pub_month, journal_title=art.get('journal_title') or journal.get('journal_title'),
        journal_issn=art.get('journal_issn'), journal_abdc_rating=(journal.get('abdc_rating') or 'A*'),
        journal_abdc_version=journal.get('abdc_version'), publisher=art.get('publisher'),
        authors_json=json.dumps(art.get('authors') or [], ensure_ascii=False),
        author_count=len(art.get('authors') or []),
        concepts_json=json.dumps(art.get('concepts') or [], ensure_ascii=False),
        keywords_json=json.dumps(art.get('keywords') or [], ensure_ascii=False),
        url=art.get('url'), landing_page_url=art.get('landing_page_url'),
        open_access_status=art.get('open_access_status'), cited_by_count=art.get('cited_by_count'),
        source_name=art.get('source_name'), source_type=art.get('source_type'),
        source_url=art.get('source_url'), data_status=art.get('data_status'),
        is_duplicate=0, updated_at=now,
    )

    if existing_id:
        # 更新：只在新值非空时覆盖（保护已有 abstract 等）
        sets, vals = [], []
        for k, v in fields.items():
            if v is not None and v != '' and v != [] :
                sets.append(f'{k}=?')
                vals.append(v)
        vals.append(existing_id)
        conn.execute(f'UPDATE astar_articles SET {",".join(sets)} WHERE id=?', vals)
        _persist_classification(conn, existing_id, art)
        _record_source(conn, existing_id, art)
        return 'updated', existing_id

    fields['created_at'] = now
    cols = ','.join(fields.keys())
    ph = ','.join(['?'] * len(fields))
    try:
        cur = conn.execute(f'INSERT INTO astar_articles ({cols}) VALUES ({ph})', list(fields.values()))
        aid = cur.lastrowid
    except sqlite3.IntegrityError:
        # DOI 唯一约束冲突 → 当作 duplicate
        return 'duplicate', None
    _persist_classification(conn, aid, art)
    _record_source(conn, aid, art)
    return 'inserted', aid


def _record_source(conn, article_id, art):
    now = datetime.now().isoformat(timespec='seconds')
    # INSERT OR IGNORE：配合 idx_src_uniq 唯一索引，重抓同一文章不再累积重复来源行
    conn.execute("""
        INSERT OR IGNORE INTO astar_article_sources
          (article_id, source_name, source_type, source_url, raw_id, raw_json, fetched_at, parser_notes)
        VALUES (?,?,?,?,?,?,?,?)""",
        (article_id, art.get('source_name'), art.get('source_type'), art.get('source_url'),
         art.get('openalex_id') or art.get('doi'), None, now,
         f"abstract_status={art.get('abstract_status')}"))


# ════════════════════════════════════════════════════════════════════════════
#  更新编排
# ════════════════════════════════════════════════════════════════════════════
def _date_range(days):
    to_d = date.today()
    from_d = to_d - timedelta(days=days)
    return from_d.isoformat(), to_d.isoformat()


def _run_update(update_mode, days, version='latest', single_journal=None, per_journal_cap=200,
                from_date=None, to_date=None, source_filter=None):
    """统一的抓取主循环。返回 log dict。
    from_date/to_date 显式给定时优先于 days（用于多年回填）。
    source_filter 给定时只抓 source_table=该值的期刊（如 'prestige_extra'）。"""
    started = datetime.now().isoformat(timespec='seconds')
    conn = get_db()
    ensure_astar_tables(conn)

    # 确保期刊集合存在
    jstat = load_astar_journals_from_abdc(version)
    version = jstat['abdc_version']
    ensure_prestige_extra_journals(version)   # 保证 FT50/UTD24 非 A* 追踪刊在集合内

    q = 'SELECT * FROM abdc_astar_journals WHERE abdc_version=? AND is_active=1'
    args = [version]
    if single_journal:
        q += ' AND journal_title LIKE ?'
        args.append(f'%{single_journal}%')
    if source_filter:
        q += ' AND source_table=?'
        args.append(source_filter)
    journals = conn.execute(q, args).fetchall()

    if not (from_date and to_date):
        from_date, to_date = _date_range(days)

    counters = dict(journals_checked=0, journals_with_issn=0, journals_missing_issn=0,
                    articles_found=0, articles_inserted=0, articles_updated=0,
                    duplicates_skipped=0, failed_journals=0)
    failed_sources, warnings = [], []

    for jrow in journals:
        j = dict(jrow)
        disc, area = (j.get('discipline'), None)
        # 重新算 area（discipline_for 不可用这里，简单映射）
        j['_area'] = _area_from_discipline(j.get('discipline'))
        counters['journals_checked'] += 1
        if not (j.get('issn_print') or j.get('issn_online')):
            counters['journals_missing_issn'] += 1
            warnings.append(f"{j['journal_title']}: no ISSN")
            continue
        counters['journals_with_issn'] += 1

        arts, src_used, err = fetch_recent_articles_for_journal(j, from_date, to_date, per_journal_cap)
        time.sleep(POLITE_DELAY)
        if err and not arts:
            if err != 'no_issn':
                counters['failed_journals'] += 1
                failed_sources.append(f"{j['journal_title']}: {err}")
            continue
        counters['articles_found'] += len(arts)
        for art in arts:
            status, _aid = _upsert_article(conn, art, j)
            if status == 'inserted':
                counters['articles_inserted'] += 1
            elif status == 'updated':
                counters['articles_updated'] += 1
            elif status == 'duplicate':
                counters['duplicates_skipped'] += 1
        conn.commit()

    finished = datetime.now().isoformat(timespec='seconds')
    logrow = dict(started_at=started, finished_at=finished, success=1,
                  update_mode=update_mode, abdc_version=version,
                  failed_sources=json.dumps(failed_sources[:50], ensure_ascii=False),
                  warnings=json.dumps(warnings[:50], ensure_ascii=False),
                  error_message=None, **counters)
    conn.execute("""INSERT INTO astar_update_logs
        (started_at,finished_at,success,update_mode,abdc_version,journals_checked,
         journals_with_issn,journals_missing_issn,articles_found,articles_inserted,
         articles_updated,duplicates_skipped,failed_journals,failed_sources,warnings,error_message)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (logrow['started_at'], logrow['finished_at'], 1, update_mode, version,
         counters['journals_checked'], counters['journals_with_issn'], counters['journals_missing_issn'],
         counters['articles_found'], counters['articles_inserted'], counters['articles_updated'],
         counters['duplicates_skipped'], counters['failed_journals'],
         logrow['failed_sources'], logrow['warnings'], None))
    conn.commit()
    conn.close()
    logrow['journal_stats'] = jstat
    return logrow


def _area_from_discipline(disc):
    rev = {
        'Accounting': 'Accounting', 'Banking, Finance & Investment': 'Finance',
        'Marketing': 'Marketing', 'Human Resources & Industrial Relations': 'OB / HR',
        'Strategy, Management & Organisational Behaviour': 'OB / HR',
        'Transportation, Logistics & Supply Chains': 'Operations / Supply Chain',
        'Applied Economics': 'Economics', 'Econometrics': 'Economics',
        'Economic Theory': 'Economics', 'Information Systems': 'Information Systems',
    }
    rev.update({
        'Tourism': 'Management / Strategy', 'Commercial Services': 'Management / Strategy',
        'Other Commerce/Management': 'Management / Strategy', 'Business Systems in Context': 'Management / Strategy',
        'Law': 'Law', 'Statistics & Probability': 'Statistics / Methods',
    })
    return rev.get(disc, 'Other')


def update_astar_recent_articles(days=30, version='latest'):
    return _run_update('recent', days, version)


def backfill_astar_articles(mode, journal=None, year=None, version='latest', since_year=None):
    if mode == 'backfill_90_days':
        return _run_update('backfill_90_days', 90, version)
    if mode == 'backfill_current_year':
        days = (date.today() - date(date.today().year, 1, 1)).days + 1
        return _run_update('backfill_current_year', days, version, per_journal_cap=600)
    if mode == 'backfill_one_journal':
        # 单刊深挖：回填到 since_year（默认 2015）起的全部历史
        sy = since_year or 2015
        return _run_update('manual_single_journal', 0, version, single_journal=journal,
                           per_journal_cap=3000,
                           from_date=f'{sy}-01-01', to_date=date.today().isoformat())
    if mode == 'backfill_one_year':
        y = int(year or date.today().year)
        return _run_update('backfill_one_year', 0, version, per_journal_cap=3000,
                           from_date=f'{y}-01-01', to_date=f'{y}-12-31')
    if mode == 'backfill_since':
        # 多年回填：从 since_year-01-01 到今天（深度建库用）；cap 调高避免高产刊被截断
        sy = int(since_year or (date.today().year - 1))
        return _run_update('backfill_since', 0, version, per_journal_cap=8000,
                           from_date=f'{sy}-01-01', to_date=date.today().isoformat())
    if mode == 'daily_incremental':
        return _run_update('daily_incremental', 14, version)
    if mode == 'weekly_incremental':
        return _run_update('weekly_incremental', 30, version)
    if mode == 'recent':
        return _run_update('recent', 30, version)
    raise ValueError(f'未知 mode: {mode}')


def cleanup_journal_doi_pollution():
    """对 JOURNAL_DOI_FILTER 中的刊，把 DOI 不含指定子串的文章标记 is_duplicate=1（隐藏会议论文污染）。
    返回每刊清理数。可重复运行（幂等）。"""
    conn = get_db()
    ensure_astar_tables(conn)
    result = {}
    for issn, sub in JOURNAL_DOI_FILTER.items():
        cur = conn.execute(
            "UPDATE astar_articles SET is_duplicate=1 "
            "WHERE journal_issn=? AND is_duplicate=0 AND (doi IS NULL OR doi NOT LIKE ?)",
            (issn, f'%{sub}%'))
        if cur.rowcount:
            result[issn] = cur.rowcount
    conn.commit()
    conn.close()
    return {'hidden': result, 'total_hidden': sum(result.values())}


def deduplicate_articles():
    """二次去重：按 normalized title+year 把重复行标记 is_duplicate=1（保留最早 id）。"""
    conn = get_db()
    rows = conn.execute("""
        SELECT id, title_normalized, publication_year FROM astar_articles
        WHERE is_duplicate=0 AND title_normalized != '' ORDER BY id""").fetchall()
    seen = {}
    dups = 0
    for r in rows:
        key = (r['title_normalized'], r['publication_year'])
        if key in seen:
            conn.execute('UPDATE astar_articles SET is_duplicate=1 WHERE id=?', (r['id'],))
            dups += 1
        else:
            seen[key] = r['id']
    conn.commit()
    conn.close()
    return {'duplicates_marked': dups}


def reclassify_all():
    """对库内所有文章重跑分类。"""
    conn = get_db()
    ensure_astar_tables(conn)
    rows = conn.execute('SELECT * FROM astar_articles WHERE is_duplicate=0').fetchall()
    n = 0
    for r in rows:
        art = dict(r)
        art['concepts'] = json.loads(art.get('concepts_json') or '[]')
        art['_journal_discipline_area'] = _journal_area_for_issn(conn, art.get('journal_issn'))
        _persist_classification(conn, art['id'], art)
        n += 1
        if n % 200 == 0:
            conn.commit()
    conn.commit()
    conn.close()
    return {'reclassified': n}


def _journal_area_for_issn(conn, issn):
    if not issn:
        return 'Other'
    r = conn.execute(
        'SELECT discipline, field_of_research FROM abdc_astar_journals WHERE issn_print=? OR issn_online=? LIMIT 1',
        (issn, issn)).fetchone()
    if not r:
        return 'Other'
    # FoR 码优先（最精确：法学 4801 / 统计 4905 等 discipline='Other' 的刊靠它定位），
    # 其次按 discipline 名称，最后 Other。
    foc = (r['field_of_research'] or '').strip()
    if foc in FOR_DISCIPLINE:
        return FOR_DISCIPLINE[foc][1]
    return _area_from_discipline(r['discipline'])


# ════════════════════════════════════════════════════════════════════════════
#  Payload 构建（供 API）
# ════════════════════════════════════════════════════════════════════════════
def _current_version(conn):
    r = conn.execute('SELECT abdc_version FROM abdc_astar_journals ORDER BY abdc_version DESC LIMIT 1').fetchone()
    return r['abdc_version'] if r else None


def build_astar_journals_payload():
    conn = get_db()
    ensure_astar_tables(conn)
    ver = _current_version(conn)
    rows = conn.execute('SELECT * FROM abdc_astar_journals WHERE abdc_version=? ORDER BY journal_title', (ver,)).fetchall()
    journals = [dict(r) for r in rows]
    # 按 ISSN 统计每刊已抓文章数（对全部期刊，而非仅前 40；避免刊名大小写差异导致漏算）
    counts = {}
    for r in conn.execute("""
        SELECT j.id pid, COUNT(a.id) n FROM abdc_astar_journals j
        LEFT JOIN astar_articles a
          ON (a.journal_issn=j.issn_print OR a.journal_issn=j.issn_online) AND a.is_duplicate=0
        WHERE j.abdc_version=? GROUP BY j.id""", (ver,)):
        counts[r['pid']] = r['n']
    for j in journals:
        j['articles_in_db'] = counts.get(j['id'], 0)
    with_issn = sum(1 for j in journals if j['issn_print'] or j['issn_online'])
    with_articles = sum(1 for j in journals if j['articles_in_db'] > 0)
    conn.close()
    return {'success': True, 'abdc_version': ver, 'astar_journal_count': len(journals),
            'with_issn_count': with_issn, 'missing_issn_count': len(journals) - with_issn,
            'with_articles_count': with_articles, 'journals': journals}


def build_prestige_lists_payload():
    """FT50 / UTD24 清单 + 覆盖/缺口报告（哪些清单期刊未被 A* 雷达追踪）。"""
    conn = get_db()
    ensure_astar_tables(conn)
    if conn.execute('SELECT COUNT(*) FROM journal_prestige_lists').fetchone()[0] == 0:
        conn.close()
        load_journal_prestige_lists()
        conn = get_db()
    rows = [dict(r) for r in conn.execute(
        'SELECT * FROM journal_prestige_lists ORDER BY journal_title')]
    # 每个清单期刊已抓到的文章数
    counts = {}
    for r in conn.execute("""
        SELECT p.id pid, COUNT(a.id) n FROM journal_prestige_lists p
        LEFT JOIN astar_articles a
          ON (a.journal_issn=p.issn_print OR a.journal_issn=p.issn_online) AND a.is_duplicate=0
        GROUP BY p.id"""):
        counts[r['pid']] = r['n']
    for r in rows:
        r['articles_in_db'] = counts.get(r['id'], 0)
    conn.close()
    ft50 = [r for r in rows if r['is_ft50']]
    utd24 = [r for r in rows if r['is_utd24']]
    both = [r for r in rows if r['is_ft50'] and r['is_utd24']]
    not_tracked = [r for r in rows if not r['in_astar_tracked']]
    return {'success': True,
            'ft50_count': len(ft50), 'utd24_count': len(utd24),
            'in_both': len(both), 'total_unique': len(rows),
            'not_tracked_count': len(not_tracked),
            'not_tracked': [{'title': r['journal_title'], 'abdc_rating': r['abdc_rating'],
                             'is_ft50': r['is_ft50'], 'is_utd24': r['is_utd24']} for r in not_tracked],
            'journals': rows}


def _article_row_to_dict(r):
    d = dict(r)
    for k in ('authors_json', 'concepts_json', 'keywords_json'):
        try:
            d[k.replace('_json', '')] = json.loads(d.get(k) or '[]')
        except Exception:
            d[k.replace('_json', '')] = []
    return d


def _attach_classification(conn, d):
    c = conn.execute('SELECT * FROM astar_article_classifications WHERE article_id=?', (d['id'],)).fetchone()
    if c:
        cc = dict(c)
        for k in ('research_topic', 'theory_tags_json', 'method_tags_json', 'data_type_tags_json', 'context_tags_json'):
            base = k.replace('_json', '')
            try:
                cc[base] = json.loads(cc.get(k) or cc.get(base) or '[]') if (cc.get(k) or '').startswith('[') else json.loads(cc.get(k) or '[]')
            except Exception:
                cc[base] = []
        d['classification'] = cc
    else:
        d['classification'] = None
    return d


def build_astar_articles_payload(params):
    conn = get_db()
    ensure_astar_tables(conn)
    where = ['a.is_duplicate=0']
    args = []

    q = (params.get('q') or '').strip()
    if q:
        where.append('(a.title LIKE ? OR a.abstract LIKE ? OR a.journal_title LIKE ?)')
        args += [f'%{q}%'] * 3
    if params.get('from_date'):
        where.append('a.publication_date >= ?'); args.append(params['from_date'])
    if params.get('to_date'):
        where.append('a.publication_date <= ?'); args.append(params['to_date'])
    if params.get('journal'):
        where.append('a.journal_title LIKE ?'); args.append(f"%{params['journal']}%")
    if params.get('journal_issns'):
        issns = [x.strip() for x in str(params['journal_issns']).split(',') if x.strip()]
        if issns:
            where.append('a.journal_issn IN (%s)' % ','.join(['?'] * len(issns)))
            args += issns
    if params.get('broad_area'):
        where.append('c.broad_area = ?'); args.append(params['broad_area'])
    if params.get('topic'):
        where.append('c.research_topic LIKE ?'); args.append(f"%{params['topic']}%")
    if params.get('method'):
        where.append('c.method_tags_json LIKE ?'); args.append(f"%{params['method']}%")
    if params.get('data_type'):
        where.append('c.data_type_tags_json LIKE ?'); args.append(f"%{params['data_type']}%")
    if params.get('theory'):
        where.append('c.theory_tags_json LIKE ?'); args.append(f"%{params['theory']}%")
    if str(params.get('related_only', '')).lower() in ('1', 'true', 'yes'):
        where.append('c.is_related_to_my_research = 1')
    if params.get('min_relevance'):
        where.append('c.relevance_score >= ?'); args.append(float(params['min_relevance']))
    lst = (params.get('list') or '').lower()
    if lst == 'ft50':
        where.append('p.is_ft50 = 1')
    elif lst == 'utd24':
        where.append('p.is_utd24 = 1')

    sort = params.get('sort') or 'date_desc'
    order = {'date_desc': 'a.publication_date DESC',
             'date_asc': 'a.publication_date ASC',
             'relevance_desc': 'c.relevance_score DESC, a.publication_date DESC',
             'semantic_desc': 'c.semantic_relevance DESC, a.publication_date DESC',
             'citations_desc': 'a.cited_by_count DESC'}.get(sort, 'a.publication_date DESC')

    limit = min(int(params.get('limit', 50)), 500)
    offset = int(params.get('offset', 0))

    base = f"""FROM astar_articles a
               LEFT JOIN astar_article_classifications c ON c.article_id=a.id
               LEFT JOIN journal_prestige_lists p
                 ON (a.journal_issn=p.issn_print OR a.journal_issn=p.issn_online)
               WHERE {' AND '.join(where)}"""
    total = conn.execute(f'SELECT COUNT(*) {base}', args).fetchone()[0]
    rows = conn.execute(
        f'SELECT a.*, p.is_ft50, p.is_utd24 {base} ORDER BY {order} LIMIT ? OFFSET ?',
        args + [limit, offset]).fetchall()
    arts = []
    for r in rows:
        d = _article_row_to_dict(r)
        d['is_ft50'] = bool(r['is_ft50'])
        d['is_utd24'] = bool(r['is_utd24'])
        _attach_classification(conn, d)
        arts.append(d)

    lastlog = conn.execute('SELECT finished_at FROM astar_update_logs ORDER BY id DESC LIMIT 1').fetchone()
    conn.close()
    return {'success': True, 'total': total, 'articles': arts,
            'metadata': {'data_mode': 'cache', 'last_update': lastlog['finished_at'] if lastlog else None,
                         'warnings': []}}


def build_astar_article_detail(article_id):
    conn = get_db()
    r = conn.execute('SELECT * FROM astar_articles WHERE id=?', (article_id,)).fetchone()
    if not r:
        conn.close()
        return {'success': False, 'error': 'not found'}
    d = _article_row_to_dict(r)
    _attach_classification(conn, d)
    srcs = conn.execute('SELECT * FROM astar_article_sources WHERE article_id=?', (article_id,)).fetchall()
    d['source_records'] = [dict(s) for s in srcs]
    # related：同 journal 或共享 topic 的近期文章
    rel = conn.execute("""SELECT id,title,journal_title,publication_date FROM astar_articles
                          WHERE journal_issn=? AND id!=? AND is_duplicate=0
                          ORDER BY publication_date DESC LIMIT 6""",
                       (d.get('journal_issn'), article_id)).fetchall()
    d['related_articles'] = [dict(x) for x in rel]
    d['doi_url'] = f"https://doi.org/{d['doi']}" if d.get('doi') else None
    d['openalex_url'] = f"https://openalex.org/{d['openalex_id']}" if d.get('openalex_id') else None
    conn.close()
    return {'success': True, 'article': d}


def build_astar_recent_payload(days=7, related_only=False):
    from_date, to_date = _date_range(days)
    params = {'from_date': from_date, 'to_date': to_date, 'sort': 'relevance_desc',
              'limit': 200, 'related_only': related_only}
    return build_astar_articles_payload(params)


def build_astar_digest_payload(period='this_week', related_only=False):
    today = date.today()
    if period == 'this_week':
        start = today - timedelta(days=today.weekday())
    elif period == 'last_week':
        start = today - timedelta(days=today.weekday() + 7)
    elif period == 'this_month':
        start = today.replace(day=1)
    else:
        start = today - timedelta(days=7)
    from_date = start.isoformat()

    conn = get_db()
    ensure_astar_tables(conn)
    rows = conn.execute("""
        SELECT a.*, c.relevance_score, c.is_related_to_my_research, c.broad_area,
               c.research_topic, c.method_tags_json, c.data_type_tags_json,
               c.classification_status, c.classification_notes
        FROM astar_articles a LEFT JOIN astar_article_classifications c ON c.article_id=a.id
        WHERE a.is_duplicate=0 AND a.publication_date >= ?
        ORDER BY c.relevance_score DESC, a.publication_date DESC""", (from_date,)).fetchall()
    arts = [dict(r) for r in rows]

    def has_topic(a, *topics):
        rt = a.get('research_topic') or '[]'
        return any(t in rt for t in topics)

    def to_card(a):
        abstract = a.get('abstract')
        evidence = 'title + abstract' if abstract else 'title only'
        return {
            'id': a['id'], 'title': a['title'], 'journal_title': a['journal_title'],
            'publication_date': a['publication_date'], 'relevance_score': a.get('relevance_score'),
            'why_it_matters': a.get('classification_notes'),
            'abstract_status': a.get('abstract_status'),
            'evidence_basis': evidence, 'doi': a.get('doi'),
            'url': a.get('url'),
        }

    sections = {
        'this_week_in_astar': [to_card(a) for a in arts[:25]],
        'highly_relevant': [to_card(a) for a in arts if (a.get('relevance_score') or 0) >= 60][:25],
        'ai_organization': [to_card(a) for a in arts if has_topic(a, 'AI_in_organizations', 'algorithmic_management')][:20],
        'wfh_rto': [to_card(a) for a in arts if has_topic(a, 'remote_work', 'hybrid_work', 'return_to_office')][:20],
        'digital_trace_nlp': [to_card(a) for a in arts if (a.get('method_tags_json') or '').find('NLP') >= 0 or (a.get('method_tags_json') or '').find('text_mining') >= 0 or (a.get('method_tags_json') or '').find('machine_learning') >= 0][:20],
        'ob_hr_mechanisms': [to_card(a) for a in arts if a.get('broad_area') == 'OB / HR'][:20],
        'cross_field': [to_card(a) for a in arts if a.get('broad_area') in ('Information Systems', 'Operations / Supply Chain') and (a.get('relevance_score') or 0) >= 40][:20],
        'interesting_titles_no_abstract': [to_card(a) for a in arts if not a.get('abstract') and (a.get('relevance_score') or 0) >= 30][:15],
    }
    conn.close()
    return {'success': True, 'period': period, 'from_date': from_date,
            'total_new': len(arts),
            'highly_relevant_count': len(sections['highly_relevant']),
            'sections': sections,
            'note': '本 digest 仅基于 title / abstract / 公开元数据生成；无摘要的文章已标注 evidence_basis=title only，未编造内容。'}


def build_astar_debug_payload():
    conn = get_db()
    ensure_astar_tables(conn)
    ver = _current_version(conn)
    jcount = conn.execute('SELECT COUNT(*) FROM abdc_astar_journals WHERE abdc_version=?', (ver,)).fetchone()[0]
    with_issn = conn.execute("SELECT COUNT(*) FROM abdc_astar_journals WHERE abdc_version=? AND (issn_print!='' OR issn_online!='')", (ver,)).fetchone()[0]
    total_art = conn.execute('SELECT COUNT(*) FROM astar_articles WHERE is_duplicate=0').fetchone()[0]
    no_doi = conn.execute("SELECT COUNT(*) FROM astar_articles WHERE (doi IS NULL OR doi='') AND is_duplicate=0").fetchone()[0]
    no_abs = conn.execute("SELECT COUNT(*) FROM astar_articles WHERE abstract_status='missing' AND is_duplicate=0").fetchone()[0]
    # 缺摘要拆分:已查过 Semantic Scholar 仍无摘要 = 免费元数据确实没有(多为 Elsevier 等
    # 不向 OpenAlex/Crossref/S2 提供摘要的出版商,政策性缺失,非抓取遗漏);其余为可重试。
    no_abs_confirmed = conn.execute(
        "SELECT COUNT(*) FROM astar_articles WHERE abstract_status='missing' AND is_duplicate=0 "
        "AND semantic_scholar_id IS NOT NULL").fetchone()[0]
    no_abs_top_journals = [dict(r) for r in conn.execute("""
        SELECT journal_title, COUNT(*) n FROM astar_articles
        WHERE abstract_status='missing' AND is_duplicate=0
        GROUP BY journal_title ORDER BY n DESC LIMIT 8""")]
    dups = conn.execute('SELECT COUNT(*) FROM astar_articles WHERE is_duplicate=1').fetchone()[0]

    cls_dist = {r['classification_status']: r['n'] for r in conn.execute(
        'SELECT classification_status, COUNT(*) n FROM astar_article_classifications GROUP BY classification_status')}
    src_cov = {r['source_type']: r['n'] for r in conn.execute(
        'SELECT source_type, COUNT(*) n FROM astar_articles WHERE is_duplicate=0 GROUP BY source_type')}
    per_journal = [dict(r) for r in conn.execute("""
        SELECT journal_title, COUNT(*) n FROM astar_articles WHERE is_duplicate=0
        GROUP BY journal_title ORDER BY n DESC LIMIT 40""")]
    logs = [dict(r) for r in conn.execute('SELECT * FROM astar_update_logs ORDER BY id DESC LIMIT 10')]
    failed = []
    if logs and logs[0].get('failed_sources'):
        try:
            failed = json.loads(logs[0]['failed_sources'])
        except Exception:
            failed = []
    conn.close()
    return {'success': True, 'abdc_version': ver,
            'astar_journal_count': jcount, 'with_issn_count': with_issn,
            'missing_issn_count': jcount - with_issn,
            'articles_total': total_art, 'articles_without_doi': no_doi,
            'articles_without_abstract': no_abs,
            'articles_without_abstract_confirmed_unavailable': no_abs_confirmed,
            'articles_without_abstract_top_journals': no_abs_top_journals,
            'duplicates': dups,
            'classification_status_distribution': cls_dist,
            'source_coverage': src_cov, 'articles_per_journal_top40': per_journal,
            'failed_journals_last_run': failed, 'last_update_logs': logs}


def save_article(article_id, note=None, reading_status='to_read', project_tag=None):
    conn = get_db()
    ensure_astar_tables(conn)
    now = datetime.now().isoformat(timespec='seconds')
    conn.execute("""INSERT INTO astar_saved_articles (article_id, saved_at, user_note, reading_status, project_tag)
        VALUES (?,?,?,?,?)
        ON CONFLICT(article_id) DO UPDATE SET user_note=excluded.user_note,
          reading_status=excluded.reading_status, project_tag=excluded.project_tag""",
        (article_id, now, note, reading_status, project_tag))
    conn.commit()
    conn.close()
    return {'success': True, 'article_id': article_id}


def build_saved_articles_payload():
    conn = get_db()
    ensure_astar_tables(conn)
    rows = conn.execute("""
        SELECT s.*, a.title, a.journal_title, a.publication_date, a.doi
        FROM astar_saved_articles s JOIN astar_articles a ON a.id=s.article_id
        ORDER BY s.saved_at DESC""").fetchall()
    conn.close()
    return {'success': True, 'saved': [dict(r) for r in rows]}


# ════════════════════════════════════════════════════════════════════════════
#  Semantic Scholar 补全（补摘要 / 引用数 / fieldsOfStudy）
# ════════════════════════════════════════════════════════════════════════════
def _s2_batch(dois, fields='abstract,fieldsOfStudy,citationCount,influentialCitationCount,externalIds'):
    """批量查 Semantic Scholar，返回 {doi_lower: record}。失败抛异常。"""
    ids = [f'DOI:{d}' for d in dois]
    r = requests.post(S2_BATCH_URL, params={'fields': fields}, json={'ids': ids}, timeout=40)
    r.raise_for_status()
    out = {}
    for d, rec in zip(dois, r.json()):
        if rec:
            out[d.lower()] = rec
    return out


def enrich_with_semantic_scholar(limit=None, batch_size=100):
    """对缺摘要且有 DOI 的文章批量查 Semantic Scholar。
    - 仅当 S2 提供真实 abstract 时才回填（abstract_status='available'）。
    - 同时回填 citationCount、fieldsOfStudy（并入 keywords，作为分类信号）、semantic_scholar_id。
    - 回填后重跑分类。返回统计 dict。不伪造摘要。"""
    started = datetime.now().isoformat(timespec='seconds')
    conn = get_db()
    ensure_astar_tables(conn)
    q = """SELECT id, doi, keywords_json, concepts_json, journal_issn, title
           FROM astar_articles
           WHERE abstract_status='missing' AND doi IS NOT NULL AND doi!='' AND is_duplicate=0
           ORDER BY publication_date DESC"""
    rows = conn.execute(q).fetchall()
    if limit:
        rows = rows[:limit]

    checked = abstracts_filled = citations_filled = fos_filled = failed_batches = 0
    now = datetime.now().isoformat(timespec='seconds')

    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        dois = [r['doi'] for r in chunk]
        try:
            res = _s2_batch(dois)
        except Exception as e:
            failed_batches += 1
            log.warning(f's2 batch failed [{i}:{i+batch_size}]: {e}')
            time.sleep(3)
            continue
        for r in chunk:
            checked += 1
            rec = res.get((r['doi'] or '').lower())
            if not rec:
                continue
            updates, vals = [], []
            s2id = (rec.get('externalIds') or {}).get('CorpusId')
            if s2id:
                updates.append('semantic_scholar_id=?'); vals.append(str(s2id))
            if rec.get('citationCount') is not None:
                updates.append('cited_by_count=COALESCE(cited_by_count,?)'); vals.append(rec['citationCount'])
                citations_filled += 1
            fos = rec.get('fieldsOfStudy') or []
            if fos:
                try:
                    kw = json.loads(r['keywords_json'] or '[]')
                except Exception:
                    kw = []
                merged = list(dict.fromkeys(kw + fos))
                updates.append('keywords_json=?'); vals.append(json.dumps(merged, ensure_ascii=False))
                fos_filled += 1
            abstract = rec.get('abstract')
            if abstract and abstract.strip():
                updates.append('abstract=?'); vals.append(abstract.strip())
                updates.append('abstract_status=?'); vals.append('available')
                updates.append('data_status=?'); vals.append('api_metadata')
                abstracts_filled += 1
            if not updates:
                continue
            updates.append('updated_at=?'); vals.append(now)
            vals.append(r['id'])
            conn.execute(f"UPDATE astar_articles SET {','.join(updates)} WHERE id=?", vals)
            conn.execute("""INSERT OR IGNORE INTO astar_article_sources
                (article_id, source_name, source_type, source_url, raw_id, raw_json, fetched_at, parser_notes)
                VALUES (?,?,?,?,?,?,?,?)""",
                (r['id'], 'Semantic Scholar', 'semantic_scholar',
                 f'https://www.semanticscholar.org/paper/{s2id}' if s2id else None,
                 str(s2id) if s2id else r['doi'], None, now,
                 f"abstract={'filled' if abstract else 'none'}, fos={len(fos)}"))
            art = {'title': r['title'], 'abstract': abstract,
                   'concepts': json.loads(r['concepts_json'] or '[]'),
                   '_journal_discipline_area': _journal_area_for_issn(conn, r['journal_issn'])}
            _persist_classification(conn, r['id'], art)
        conn.commit()
        time.sleep(1.0)   # S2 未授权速率较严，批间停顿

    finished = datetime.now().isoformat(timespec='seconds')
    conn.execute("""INSERT INTO astar_update_logs
        (started_at,finished_at,success,update_mode,abdc_version,journals_checked,
         journals_with_issn,journals_missing_issn,articles_found,articles_inserted,
         articles_updated,duplicates_skipped,failed_journals,failed_sources,warnings,error_message)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (started, finished, 1, 'enrich_semantic_scholar', None, 0, 0, 0,
         checked, 0, abstracts_filled, 0, failed_batches,
         '[]', json.dumps([f'citations_filled={citations_filled}', f'fos_filled={fos_filled}']), None))
    conn.commit()
    conn.close()
    return {'success': True, 'checked': checked, 'abstracts_filled': abstracts_filled,
            'citations_filled': citations_filled, 'fields_of_study_filled': fos_filled,
            'failed_batches': failed_batches}


# ════════════════════════════════════════════════════════════════════════════
#  趋势地图：研究主题 / 方法 / 领域 随时间（按月）变化
# ════════════════════════════════════════════════════════════════════════════
def build_astar_trends_payload(months=18, related_only=False):
    """按 publication_month 聚合 topic / method / broad_area 计数，供趋势图使用。"""
    conn = get_db()
    ensure_astar_tables(conn)
    where = ['a.is_duplicate=0', 'a.publication_month IS NOT NULL']
    if related_only:
        where.append('c.is_related_to_my_research=1')
    rows = conn.execute(f"""
        SELECT a.publication_month m, c.research_topic, c.method_tags_json, c.broad_area
        FROM astar_articles a LEFT JOIN astar_article_classifications c ON c.article_id=a.id
        WHERE {' AND '.join(where)}""").fetchall()
    conn.close()

    all_months = sorted({r['m'] for r in rows if r['m']})
    keep = all_months[-months:] if len(all_months) > months else all_months
    keep_set = set(keep)

    topic_by_month, method_by_month, area_by_month = {}, {}, {}
    month_totals = {m: 0 for m in keep}
    for r in rows:
        m = r['m']
        if m not in keep_set:
            continue
        month_totals[m] += 1
        try:
            topics = json.loads(r['research_topic'] or '[]')
        except Exception:
            topics = []
        try:
            methods = json.loads(r['method_tags_json'] or '[]')
        except Exception:
            methods = []
        for t in topics:
            topic_by_month.setdefault(t, {mm: 0 for mm in keep})[m] += 1
        for mt in methods:
            method_by_month.setdefault(mt, {mm: 0 for mm in keep})[m] += 1
        area = r['broad_area'] or 'Other'
        area_by_month.setdefault(area, {mm: 0 for mm in keep})[m] += 1

    def top_series(d, n):
        ranked = sorted(d.items(), key=lambda kv: sum(kv[1].values()), reverse=True)[:n]
        return [{'label': k, 'total': sum(v.values()), 'series': [v[m] for m in keep]} for k, v in ranked]

    return {'success': True, 'months': keep,
            'month_totals': [month_totals[m] for m in keep],
            'topics': top_series(topic_by_month, 12),
            'methods': top_series(method_by_month, 10),
            'areas': top_series(area_by_month, 10)}


# ════════════════════════════════════════════════════════════════════════════
#  来源记录去重（一次性 + 建唯一索引防再生）
# ════════════════════════════════════════════════════════════════════════════
def dedup_article_sources():
    """删除 astar_article_sources 中 (article_id, source_type, raw_id) 重复的行（保留最小 id），
    并建唯一索引，使之后的重抓不再累积重复来源行。返回删除数。"""
    conn = get_db()
    ensure_astar_tables(conn)
    before = conn.execute('SELECT COUNT(*) FROM astar_article_sources').fetchone()[0]
    conn.execute("""DELETE FROM astar_article_sources WHERE id NOT IN (
        SELECT MIN(id) FROM astar_article_sources GROUP BY article_id, source_type, raw_id)""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_src_uniq "
                 "ON astar_article_sources(article_id, source_type, raw_id)")
    conn.commit()
    after = conn.execute('SELECT COUNT(*) FROM astar_article_sources').fetchone()[0]
    conn.close()
    return {'before': before, 'after': after, 'removed': before - after}


# ════════════════════════════════════════════════════════════════════════════
#  期刊健康检查：逐刊比对 OpenAlex 覆盖，自动分类健康/可救/无解
# ════════════════════════════════════════════════════════════════════════════
def _openalex_source_stats(issn):
    """查 OpenAlex source（按 ISSN），返回 (works_count, latest_year_with_works, recent2y_count, display_name)。
    无对应 source 返回 None。"""
    try:
        r = requests.get(f'https://api.openalex.org/sources/issn:{issn}',
                         headers={'User-Agent': f'ABDC-AstarRadar/1.0 (mailto:{MAILTO})'},
                         timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        d = r.json()
        cby = {x['year']: x['works_count'] for x in (d.get('counts_by_year') or [])}
        latest = max([y for y, n in cby.items() if n > 0], default=None)
        this_year = date.today().year
        recent2y = cby.get(this_year, 0) + cby.get(this_year - 1, 0)
        return d.get('works_count'), latest, recent2y, d.get('display_name')
    except Exception:
        return None


def run_journal_health_check():
    """对每个追踪期刊：取我们库内文章数/最新年，与 OpenAlex source 的近两年活跃度比对，分类：
      healthy        我们有且 OpenAlex 也活跃
      refetch_needed OpenAlex 近两年有不少，但我们库里近两年明显偏少 → 该重抓
      check_issn     OpenAlex 没有该 ISSN 的 source（疑似刊号错/改名）
      source_inactive OpenAlex 该刊近两年≈0（源头无近期数据，多为法学/实务刊，通常无解）
    结果写入 astar_journal_health。返回各状态计数。"""
    conn = get_db()
    ensure_astar_tables(conn)
    journals = conn.execute('SELECT * FROM abdc_astar_journals WHERE is_active=1').fetchall()
    this_year = date.today().year
    now = datetime.now().isoformat(timespec='seconds')
    counts = {}
    conn.execute('DELETE FROM astar_journal_health')
    for jr in journals:
        j = dict(jr)
        issn = j.get('issn_print') or j.get('issn_online')
        # 库内统计
        row = conn.execute("""SELECT COUNT(*) c, MAX(publication_date) latest,
            SUM(CASE WHEN publication_year>=? THEN 1 ELSE 0 END) r2
            FROM astar_articles WHERE (journal_issn=? OR journal_issn=?) AND is_duplicate=0""",
            (this_year - 1, j.get('issn_print'), j.get('issn_online'))).fetchone()
        db_count, db_latest, db_r2 = row['c'], row['latest'], row['r2'] or 0
        # OpenAlex：print 刊号无 source 时回退到 eISSN（避免误判 check_issn）
        oa = _openalex_source_stats(j.get('issn_print')) if j.get('issn_print') else None
        if oa is None and j.get('issn_online'):
            oa = _openalex_source_stats(j.get('issn_online'))
        time.sleep(POLITE_DELAY)
        if oa is None:
            oa_wc = oa_latest = oa_r2 = None
            status, note = 'check_issn', 'OpenAlex 无此 ISSN 的 source（疑似刊号错/改名）'
        else:
            oa_wc, oa_latest, oa_r2, _name = oa
            if (oa_latest or 0) <= this_year - 2 or (oa_r2 or 0) == 0:
                status = 'source_inactive'
                note = f'OpenAlex 近两年≈0（最新 {oa_latest}），源头无近期数据'
            elif db_r2 < (oa_r2 or 0) * 0.5:
                status = 'refetch_needed'
                note = f'OpenAlex 近两年 {oa_r2}，库内仅 {db_r2} → 建议重抓'
            else:
                status = 'healthy'
                note = ''
        counts[status] = counts.get(status, 0) + 1
        conn.execute("""INSERT INTO astar_journal_health
            (journal_id, journal_title, abdc_rating, issn, db_count, db_recent2y, db_latest,
             oa_works_count, oa_recent2y, oa_latest_year, status, note, checked_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (j['id'], j['journal_title'], j['abdc_rating'], issn, db_count, db_r2, db_latest,
             oa_wc, oa_r2, oa_latest, status, note, now))
        conn.commit()
    conn.close()
    return {'success': True, 'checked': len(journals), 'by_status': counts, 'checked_at': now}


def build_journal_health_payload():
    conn = get_db()
    ensure_astar_tables(conn)
    rows = [dict(r) for r in conn.execute(
        'SELECT * FROM astar_journal_health ORDER BY '
        "CASE status WHEN 'refetch_needed' THEN 0 WHEN 'check_issn' THEN 1 "
        "WHEN 'source_inactive' THEN 2 ELSE 3 END, journal_title")]
    last = conn.execute('SELECT MAX(checked_at) FROM astar_journal_health').fetchone()[0]
    conn.close()
    by = {}
    for r in rows:
        by[r['status']] = by.get(r['status'], 0) + 1
    return {'success': True, 'checked_at': last, 'by_status': by, 'journals': rows}


# ════════════════════════════════════════════════════════════════════════════
#  LLM 辅助分类（可选，需 ANTHROPIC_API_KEY）：给规则法判不准的文章重判
# ════════════════════════════════════════════════════════════════════════════
ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'
ANTHROPIC_MODEL_DEFAULT = 'claude-haiku-4-5-20251001'
DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'
DEEPSEEK_MODEL_DEFAULT = 'deepseek-v4-flash'   # 旧名 deepseek-chat 2026-07-24 弃用
LLM_MODEL_DEFAULT = ANTHROPIC_MODEL_DEFAULT   # 兼容旧引用

# 用户核心 OB/IS/管理期刊 ISSN（用于只扫这些刊里被规则低估的漏判候选）
CORE_JOURNAL_ISSNS = [
    '0001-4273', '1948-0989', '0001-8392', '1047-7039', '1526-5455',  # AMJ ASQ OrgSci
    '1047-7047', '1526-5536', '0276-7783', '2162-9730',               # ISR MISQ
    '0021-9010', '1939-1854', '0149-2063', '1557-1211',               # JAP J Mgmt
    '0894-3796', '1099-1379', '0018-7267', '1741-282X',               # JOB Human Relations
    '1071-5797', '1532-7043',                                          # (extra HR-ish placeholders ok)
]

RESEARCH_PROFILE = (
    'WFH/混合办公/RTO；AI in organizations 与算法管理(algorithmic management)；'
    '数字痕迹/文本挖掘/NLP 在组织研究中的应用；员工 burnout/withdrawal/EVLN(exit-voice-loyalty-neglect)；'
    'JD-R 理论；OB-IS 交叉；远程协作/监控/自主性/工作-家庭边界；平台/零工/物流配送劳动；'
    'Glassdoor/Indeed/O*NET/BLS/社媒/在线评论等公开数据研究。')

_LLM_SYS = (
    '你是学术文献分类助手。基于给定文章的标题/摘要/概念，对照用户研究方向做分类与相关性打分。'
    '只依据给出的证据，不要臆测；没有摘要时基于标题保守判断。'
    f'用户研究方向：{RESEARCH_PROFILE}\n'
    '严格只输出一个 JSON 对象，字段：broad_area(字符串，如 "OB / HR"/"Information Systems"/"Marketing"/'
    '"Operations / Supply Chain"/"Finance"/"Accounting"/"Economics"/"Law"/"Statistics / Methods"/'
    '"Management / Strategy"/"Other")、'
    'research_topic(字符串数组)、method_tags(字符串数组)、data_type_tags(字符串数组)、theory_tags(字符串数组)、'
    'relevance_score(0-100 整数，越贴近用户方向越高)、reason(一句中文说明)。不要输出 JSON 以外的任何内容。')


def _llm_provider():
    """优先 DeepSeek（更便宜），其次 Anthropic。返回 (provider, model) 或 (None, None)。"""
    if os.environ.get('DEEPSEEK_API_KEY'):
        return 'deepseek', os.environ.get('LLM_MODEL', DEEPSEEK_MODEL_DEFAULT)
    if os.environ.get('ANTHROPIC_API_KEY'):
        return 'anthropic', os.environ.get('LLM_MODEL', ANTHROPIC_MODEL_DEFAULT)
    return None, None


def _user_msg(title, abstract, concepts):
    return (f'标题：{title}\n摘要：{abstract or "(无公开摘要)"}\n'
            f'OpenAlex概念：{", ".join([c for c in concepts if c])}\n\n只输出 JSON。')


def _anthropic_classify(title, abstract, concepts, model):
    body = {'model': model, 'max_tokens': 700, 'system': _LLM_SYS,
            'messages': [{'role': 'user', 'content': _user_msg(title, abstract, concepts)}]}
    r = requests.post(ANTHROPIC_URL, headers={
        'x-api-key': os.environ['ANTHROPIC_API_KEY'], 'anthropic-version': '2023-06-01',
        'content-type': 'application/json'}, json=body, timeout=45)
    r.raise_for_status()
    text = ''.join(b.get('text', '') for b in r.json().get('content', []))
    m = re.search(r'\{.*\}', text, re.DOTALL)
    return json.loads(m.group(0)) if m else None


def _deepseek_classify(title, abstract, concepts, model):
    # OpenAI 兼容接口；response_format=json_object 保证只返回 JSON。
    # v4-flash 关思考模式(等价旧 deepseek-chat：快、无 reasoning 开销)。
    body = {'model': model, 'max_tokens': 700, 'temperature': 0.2,
            'thinking': {'type': 'disabled'},
            'response_format': {'type': 'json_object'},
            'messages': [{'role': 'system', 'content': _LLM_SYS},
                         {'role': 'user', 'content': _user_msg(title, abstract, concepts)}]}
    r = requests.post(DEEPSEEK_URL, headers={
        'Authorization': f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
        'Content-Type': 'application/json'}, json=body, timeout=60)
    r.raise_for_status()
    text = r.json()['choices'][0]['message']['content']
    m = re.search(r'\{.*\}', text, re.DOTALL)
    return json.loads(m.group(0)) if m else None


def _llm_classify_one(title, abstract, concepts, provider, model):
    if provider == 'deepseek':
        return _deepseek_classify(title, abstract, concepts, model)
    return _anthropic_classify(title, abstract, concepts, model)


def _classification_candidates(conn, limit, only_status='uncertain', require_abstract=True,
                               max_relevance=None, core_journals_only=False):
    """选出待重判的候选行（id/title/journal/abstract/concepts/rules_score）。"""
    where = ['a.is_duplicate=0', "c.classification_method!='llm'"]
    args = []
    if only_status:
        where.append('c.classification_status=?'); args.append(only_status)
    if require_abstract:
        where.append("a.abstract IS NOT NULL AND a.abstract!=''")
    if max_relevance is not None:
        where.append('c.relevance_score < ?'); args.append(float(max_relevance))
    if core_journals_only:
        ph = ','.join(['?'] * len(CORE_JOURNAL_ISSNS))
        where.append(f'a.journal_issn IN ({ph})'); args += CORE_JOURNAL_ISSNS
    order = 'a.publication_date DESC' if max_relevance is not None else 'c.relevance_score DESC'
    return conn.execute(f"""SELECT a.id, a.title, a.journal_title, a.abstract, a.concepts_json,
        c.relevance_score FROM astar_articles a JOIN astar_article_classifications c ON c.article_id=a.id
        WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?""", args + [int(limit)]).fetchall()


# ── "通过 Claude 会话判定" 的口子：导出候选 / 导入结果 ────────────────────────
def export_classification_batch(out_path=None, limit=40, only_status='uncertain',
                                require_abstract=True, max_relevance=None, core_journals_only=False):
    """导出一批待分类候选到 JSON，供 Claude 会话人工判定（不花 API 钱）。返回 {path, count}。"""
    conn = get_db(); ensure_astar_tables(conn)
    rows = _classification_candidates(conn, limit, only_status, require_abstract,
                                      max_relevance, core_journals_only)
    conn.close()
    cands = [{'id': r['id'], 'title': r['title'], 'journal': r['journal_title'],
              'rules_score': r['relevance_score'],
              'concepts': [x.get('name') for x in json.loads(r['concepts_json'] or '[]')][:8],
              'abstract': (r['abstract'] or '')[:750]} for r in rows]
    out_path = out_path or os.path.join(_ROOT, 'data', 'classify_batch.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'schema': '结果数组每条: {id, broad_area, research_topic[], method_tags[], '
                   'data_type_tags[], theory_tags[], relevance_score(0-100整数), reason(中文一句)}',
                   'research_profile': RESEARCH_PROFILE, 'count': len(cands),
                   'candidates': cands}, f, ensure_ascii=False, indent=1)
    return {'path': out_path, 'count': len(cands)}


def apply_classification_results(results, source='Claude会话'):
    """把分类结果(list[dict] 或 JSON 文件路径)写回库；每条需 id + 分类字段。返回 {applied}。"""
    if isinstance(results, str):
        with open(results, encoding='utf-8') as f:
            results = json.load(f)
    if isinstance(results, dict):
        results = results.get('results') or results.get('candidates') or []
    conn = get_db(); ensure_astar_tables(conn)
    now = datetime.now().isoformat(timespec='seconds')
    applied = 0
    for res in results:
        aid = res.get('id')
        if not aid:
            continue
        score = float(res.get('relevance_score', 0) or 0)
        conn.execute("""UPDATE astar_article_classifications SET broad_area=?, research_topic=?,
            method_tags_json=?, data_type_tags_json=?, theory_tags_json=?, relevance_score=?,
            is_related_to_my_research=?, classification_method='llm', classification_status='confident',
            classification_notes=?, classified_at=? WHERE article_id=?""",
            (res.get('broad_area'), json.dumps(res.get('research_topic', []), ensure_ascii=False),
             json.dumps(res.get('method_tags', []), ensure_ascii=False),
             json.dumps(res.get('data_type_tags', []), ensure_ascii=False),
             json.dumps(res.get('theory_tags', []), ensure_ascii=False),
             round(score, 1), 1 if score >= 60 else 0,
             f'LLM({source}): ' + (res.get('reason', '') or ''), now, aid))
        applied += 1
    conn.commit(); conn.close()
    return {'applied': applied}


def llm_classify_articles(limit=100, only_status='uncertain', require_abstract=True,
                          model=None, max_relevance=None, core_journals_only=False):
    """对规则法判不准的文章用 LLM 重判并打相关性分。自动选 provider：
    有 DEEPSEEK_API_KEY 走 DeepSeek（便宜），否则走 Anthropic。
    max_relevance：只处理规则分 < 该值的（找漏判用，如 35）；不传则按分从高到低（清误报用）。
    core_journals_only：只扫用户核心 OB/IS 期刊（漏判最可能藏在这里）。"""
    provider, mdl = _llm_provider()
    if not provider:
        return {'success': False, 'error': '未设置 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY，无法调用 LLM。'}
    if model:
        mdl = model
    conn = get_db()
    ensure_astar_tables(conn)
    rows = _classification_candidates(conn, limit, only_status, require_abstract,
                                      max_relevance, core_journals_only)

    done = fail = 0
    now = datetime.now().isoformat(timespec='seconds')
    for r in rows:
        try:
            concepts = [x.get('name') for x in json.loads(r['concepts_json'] or '[]')][:8]
            res = _llm_classify_one(r['title'], r['abstract'], concepts, provider, mdl)
            if not res:
                fail += 1
                continue
            score = float(res.get('relevance_score', 0) or 0)
            conn.execute("""UPDATE astar_article_classifications SET
                broad_area=?, research_topic=?, method_tags_json=?, data_type_tags_json=?,
                theory_tags_json=?, relevance_score=?, is_related_to_my_research=?,
                classification_method='llm', classification_status='confident',
                classification_notes=?, classified_at=? WHERE article_id=?""",
                (res.get('broad_area'), json.dumps(res.get('research_topic', []), ensure_ascii=False),
                 json.dumps(res.get('method_tags', []), ensure_ascii=False),
                 json.dumps(res.get('data_type_tags', []), ensure_ascii=False),
                 json.dumps(res.get('theory_tags', []), ensure_ascii=False),
                 round(score, 1), 1 if score >= 60 else 0,
                 f'LLM({provider}): ' + (res.get('reason', '') or ''), now, r['id']))
            done += 1
            if done % 20 == 0:
                conn.commit()
        except Exception as e:
            fail += 1
            log.debug(f'llm classify 失败 article {r["id"]}: {e}')
    conn.commit()
    conn.close()
    return {'success': True, 'provider': provider, 'model': mdl,
            'classified': done, 'failed': fail, 'candidates_in_scope': len(rows)}
