#!/usr/bin/env python3
"""
研究工具集成服务  v3.0
  - PBOC 金融统计数据（央行爬取 + SQLite）
  - ABDC 期刊质量列表查询
"""

import sqlite3, json, re, threading, time, logging, os, mimetypes, socket, sys
import html as html_lib
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, urljoin, quote
import urllib.request
from services.financial_data_service import (
    ensure_financial_tables,
    build_api_payload,
    sync_observations,
    build_debug_payload,
)
from services.fiscal_debt_service import (
    ensure_fiscal_tables,
    build_fiscal_debt_payload,
    build_fiscal_debt_debug_payload,
    update_fiscal_debt,
    build_projection_payload,
    run_projection,
)
from services.pboc_balance_sheet_service import (
    ensure_pboc_balance_sheet_tables,
    build_pboc_balance_sheet_payload,
    build_pboc_balance_sheet_debug,
    update_pboc_balance_sheet,
)
from services.pboc_gov_bond_omo_service import (
    ensure_pboc_gov_bond_omo_tables,
    build_pboc_gov_bond_omo_payload,
    build_pboc_gov_bond_omo_debug,
    update_pboc_gov_bond_omo,
)
from services.pboc_buyout_reverse_repo_service import (
    ensure_pboc_buyout_reverse_repo_tables,
    build_pboc_buyout_reverse_repo_payload,
    build_pboc_buyout_reverse_repo_debug,
    update_pboc_buyout_reverse_repo,
)
from services.mof_treasury_bond_service import (
    ensure_mof_treasury_bond_tables,
    build_mof_treasury_bond_payload,
    build_mof_treasury_bond_debug,
    update_mof_treasury_bonds,
)
from services.fiscal_monitor_service import (
    build_fiscal_monitor_payload,
    build_fiscal_monitor_debug,
    run_fiscal_module_update,
    run_all_fiscal_updates,
)
from services.abdc_astar_research_service import (
    ensure_astar_tables,
    load_astar_journals_from_abdc,
    update_astar_recent_articles,
    backfill_astar_articles,
    deduplicate_articles,
    reclassify_all,
    save_article,
    build_astar_journals_payload,
    build_astar_articles_payload,
    build_astar_article_detail,
    build_astar_recent_payload,
    build_astar_digest_payload,
    build_astar_debug_payload,
    build_saved_articles_payload,
    build_astar_trends_payload,
    enrich_with_semantic_scholar,
    load_journal_prestige_lists,
    build_prestige_lists_payload,
    ensure_prestige_extra_journals,
    cleanup_journal_doi_pollution,
    dedup_article_sources,
    run_journal_health_check,
    build_journal_health_payload,
    llm_classify_articles,
)

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)

PORT       = 5001
_ROOT      = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(_ROOT, 'pboc_data.db')
STATIC_DIR = os.path.join(_ROOT, 'static')
ABDC_PATH  = os.path.join(_ROOT, 'data', 'abdc_data.json')
BASE    = 'https://www.pbc.gov.cn'
INDEX_URL = BASE + '/goutongjiaoliu/113456/113469/index.html'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Connection': 'keep-alive',
}

# ── 历史底仓（来源：中国人民银行历年金融统计数据报告，季度级别）────────────
# M2单位：万亿元  M2y/M1y/loany/depy/ibor单位：%
SEED = [
    # ── 2015 ─────────────────────────────────────────────────────────────────
    # 来源：央行2015年各季度金融统计数据报告（已对照原始报文核实）
    # 注：2015-03原始报文M2=127.53万亿，与部分修订版数据集存在差异，以原始报文为准
    {'m':'2015-03','M2':127.53,'M2y':11.6,'M1y':15.9,'loan': 85.91,'loany':14.4},
    {'m':'2015-06','M2':133.34,'M2y':11.8,'M1y':18.3,'loan': 90.00,'loany':13.2},
    {'m':'2015-09','M2':135.98,'M2y':13.1,'M1y':13.0,'loan': 91.64,'loany':15.4,'ibor':2.27},
    {'m':'2015-12','M2':139.23,'M2y':13.3,'M1y':15.2,'loan': 93.95,'loany':14.3,'ibor':2.35},
    # ── 2016 ──────────────────────────────────────────────────────────────
    {'m':'2016-03','M2':144.46,'M2y':13.4,'M1y':22.1,'loan': 99.85,'loany':14.7},
    {'m':'2016-06','M2':149.05,'M2y':11.8,'M1y':24.6,'loan':104.10,'loany':14.3},
    {'m':'2016-09','M2':151.95,'M2y':11.5,'M1y':24.7,'loan':106.13,'loany':13.5,'ibor':2.38},
    {'m':'2016-12','M2':155.01,'M2y':11.3,'M1y':21.4,'loan':106.58,'loany':13.5,'ibor':2.35},
    # ── 2017 ──────────────────────────────────────────────────────────────
    {'m':'2017-03','M2':159.96,'M2y':10.6,'M1y':18.8,'loan':113.03,'loany':13.3},
    {'m':'2017-06','M2':163.13,'M2y': 9.4,'M1y':15.0,'loan':117.76,'loany':12.9},
    {'m':'2017-09','M2':165.58,'M2y': 9.2,'M1y':13.2,'loan':119.65,'loany':13.1,'ibor':2.88},
    {'m':'2017-12','M2':167.68,'M2y': 8.2,'M1y':11.8,'loan':120.13,'loany':12.7,'ibor':3.35},
    # ── 2018 ──────────────────────────────────────────────────────────────
    {'m':'2018-03','M2':173.99,'M2y': 8.2,'M1y': 9.0,'loan':125.64,'loany':12.8},
    {'m':'2018-06','M2':177.02,'M2y': 8.0,'M1y': 6.6,'loan':130.00,'loany':12.7},
    {'m':'2018-09','M2':180.17,'M2y': 8.3,'M1y': 4.0,'loan':133.95,'loany':13.2,'ibor':2.70},
    {'m':'2018-12','M2':181.17,'M2y': 8.1,'M1y': 1.5,'loan':136.30,'loany':13.5,'ibor':2.79},
    # ── 2019 ──────────────────────────────────────────────────────────────
    # 2019-03贷款余额：原始报文142.11，种子保留了当时部分修订值141.83，以报文为准
    {'m':'2019-03','M2':188.94,'M2y': 8.6,'M1y': 4.6,'loan':142.11,'loany':13.7,'dep':188.83,'depy':7.8},
    {'m':'2019-06','M2':192.14,'M2y': 8.5,'M1y': 3.4,'loan':146.12,'loany':13.0,'dep':193.12,'depy':7.9},
    {'m':'2019-09','M2':195.23,'M2y': 8.4,'M1y': 3.4,'loan':149.92,'loany':12.5,'dep':197.45,'depy':7.9,'ibor':2.56},
    {'m':'2019-12','M2':198.65,'M2y': 8.7,'M1y': 4.4,'loan':153.11,'loany':12.3,'dep':198.56,'depy':8.7,'ibor':2.38},
    # ── 2020 ──────────────────────────────────────────────────────────────
    {'m':'2020-03','M2':208.09,'M2y':10.1,'M1y': 5.0,'loan':160.21,'loany':13.0,'dep':208.77,'depy':10.4,'ibor':1.92},
    {'m':'2020-06','M2':213.49,'M2y':11.1,'M1y': 6.5,'loan':166.86,'loany':13.2,'dep':217.58,'depy':11.2,'ibor':1.74},
    {'m':'2020-09','M2':216.41,'M2y':10.9,'M1y': 8.1,'loan':170.71,'loany':13.0,'dep':219.26,'depy':10.7,'ibor':2.23},
    {'m':'2020-12','M2':218.68,'M2y':10.1,'M1y':10.0,'loan':172.75,'loany':12.8,'dep':218.47,'depy': 9.6,'ibor':2.27},
    # ── 2021 ──────────────────────────────────────────────────────────────
    {'m':'2021-03','M2':227.65,'M2y': 9.4,'M1y': 7.1,'loan':180.05,'loany':12.6,'dep':228.55,'depy': 9.5,'ibor':2.27},
    {'m':'2021-06','M2':231.78,'M2y': 8.6,'M1y': 5.5,'loan':184.66,'loany':12.3,'dep':229.45,'depy': 8.5,'ibor':2.19},
    {'m':'2021-09','M2':234.28,'M2y': 8.3,'M1y': 3.7,'loan':189.05,'loany':11.9,'dep':232.65,'depy': 8.3,'ibor':2.27},
    {'m':'2021-12','M2':238.29,'M2y': 9.0,'M1y': 3.5,'loan':192.69,'loany':11.6,'dep':235.09,'depy': 7.9,'ibor':2.39},
    # ── 2022 ──────────────────────────────────────────────────────────────
    {'m':'2022-03','M2':249.97,'M2y': 9.7,'M1y': 4.7,'loan':200.43,'loany':11.4,'dep':248.75,'depy': 9.5,'ibor':2.03},
    {'m':'2022-06','M2':258.15,'M2y':11.4,'M1y': 5.8,'loan':206.35,'loany':11.2,'dep':258.24,'depy':10.7,'ibor':1.87},
    {'m':'2022-09','M2':261.29,'M2y':12.1,'M1y': 6.4,'loan':210.76,'loany':11.2,'dep':261.62,'depy':11.3,'ibor':1.89},
    {'m':'2022-12','M2':266.43,'M2y':11.8,'M1y': 3.7,'loan':213.99,'loany':11.1,'dep':265.36,'depy':11.6,'ibor':1.73},
    # ── 2023 ──────────────────────────────────────────────────────────────
    {'m':'2023-03','M2':281.46,'M2y':12.7,'M1y': 5.1,'loan':225.38,'loany':11.8,'dep':279.37,'depy':11.8,'ibor':1.87},
    {'m':'2023-06','M2':287.30,'M2y':11.3,'M1y': 3.1,'loan':231.60,'loany':11.3,'dep':283.21,'depy': 9.0,'ibor':1.84},
    {'m':'2023-09','M2':292.30,'M2y':10.3,'M1y': 2.1,'loan':234.60,'loany':10.9,'dep':285.42,'depy': 9.3,'ibor':1.90},
    {'m':'2023-12','M2':292.27,'M2y': 9.7,'M1y': 1.3,'loan':237.59,'loany':10.6,'dep':284.26,'depy': 9.5,'ibor':1.84},
    # ── 2024（月度，已有更详细数据，保留为底仓避免空洞）─────────────────
    {'m':'2024-05','M2':301.85,'M2y':7.0},
    {'m':'2024-06','M2':305.02,'M2y':6.2},
    {'m':'2024-07','M2':303.31,'M2y':6.3},
    {'m':'2024-08','M2':305.05,'M2y':6.3},
    {'m':'2024-09','M2':309.48,'M2y':6.8},
    {'m':'2024-10','M2':309.71,'M2y':7.5},
    {'m':'2024-11','M2':311.96,'M2y':7.1,'M1y':-3.7,'M0y':12.7,'loan':254.68,'loany':7.7,'dep':303.65,'depy':6.9,'ibor':1.55,'repo':1.57},
    {'m':'2024-12','M2':313.53,'M2y':7.3,'M1y':-1.4,'M0y':13.0,'loan':255.68,'loany':7.6,'dep':302.25,'depy':6.3,'ibor':1.57,'repo':1.60},
    # ── 2025-01 起新口径 M1 ───────────────────────────────────────────────
    {'m':'2025-01','M2':318.52,'M2y':7.0,'M1':112.45,'M1y':0.4,'M0y':17.2,'dep':306.55,'depy':5.8,'ibor':1.86,'repo':2.16},
    {'m':'2025-02','M2':320.52,'M2y':7.0,'M1':109.44,'M1y':0.1,'M0y':9.7},
    {'m':'2025-03','M2':326.06,'M2y':7.0,'M1':113.49,'M1y':1.6,'M0y':11.5},
    {'m':'2025-04','M2':325.17,'M2y':8.0,'M1':109.14,'M1y':1.5,'M0y':12.0},
    {'m':'2025-05','M2':325.78,'M2y':7.9,'M1':108.91,'M1y':2.3,'M0y':12.1,'ibor':1.55,'repo':1.56},
    {'m':'2025-06','M2':330.29,'M2y':8.3,'M1':113.95,'M1y':4.6,'M0y':12.0,'loan':268.56,'loany':7.1,'dep':320.17,'depy':8.3,'ibor':1.46,'repo':1.50},
    {'m':'2025-07','M2':329.94,'M2y':8.8,'M1':111.06,'M1y':5.6,'M0y':11.8},
    {'m':'2025-08','M2':331.98,'M2y':8.8,'M1':111.23,'M1y':6.0,'M0y':11.7,'loan':269.10,'loany':6.8,'dep':322.73,'depy':8.6,'ibor':1.40,'repo':1.41},
    {'m':'2025-09','M2':335.38,'M2y':8.4,'M1':113.15,'M1y':7.2,'M0y':11.5,'SF':437.08,'SFy':8.7,'loan':270.39,'loany':6.6,'dep':324.94,'depy':8.0,'ibor':1.45,'repo':1.46},
    {'m':'2025-10','M2':335.13,'M2y':8.2,'M1':112.00,'M1y':6.2,'M0y':10.6,'SF':437.72,'SFy':8.5,'loan':270.61,'loany':6.5,'dep':325.55,'depy':8.0,'ibor':1.39,'repo':1.40},
    {'m':'2025-11','M2':336.99,'M2y':8.0,'M1':112.89,'M1y':4.9,'M0y':10.6,'SF':440.07,'SFy':8.5,'dep':326.96,'depy':7.7,'ibor':1.42,'repo':1.44},
    {'m':'2025-12','M2':340.29,'M2y':8.5,'M1':115.51,'M1y':3.8,'M0y':10.2,'SF':442.12,'SFy':8.3,'dep':328.64,'depy':8.7,'ibor':1.36,'repo':1.40},
    # 2026-01~04 余额来源：央行《金融机构信贷收支统计》（人民币，亿元→万亿元）
    {'m':'2026-01','M2':347.19,'M2y':9.0,'M1':117.97,'M1y':4.9,'M0y':2.7,'SF':449.11,'SFy':8.2,'dep':336.77,'depy':9.9,'ibor':1.40,'repo':1.43,
     'loan_hh_bal':83.727932,'loan_hh_st_bal':20.506090,'loan_hh_lt_bal':63.221842,'loan_hh_lt_cons_bal':48.819476,
     'loan_corp_bal':189.610437,'loan_corp_st_bal':49.268919,'loan_corp_lt_bal':121.247951,'loan_bill_bal':15.506432,'loan_nbfi_bal':0.762997},
    {'m':'2026-02','M2':349.22,'M2y':9.0,'M1':115.93,'M1y':5.9,'M0y':14.1,'SF':451.40,'SFy':8.2,'dep':337.94,'depy':8.7,'ibor':1.40,'repo':1.44,
     'loan_hh_bal':83.077239,'loan_hh_st_bal':20.036820,'loan_hh_lt_bal':63.040420,'loan_hh_lt_cons_bal':48.600276,
     'loan_corp_bal':191.106044,'loan_corp_st_bal':49.870318,'loan_corp_lt_bal':122.143710,'loan_bill_bal':15.471504,'loan_nbfi_bal':0.752544},
    {'m':'2026-03','M2':353.86,'M2y':8.5,'M1':119.32,'M1y':5.1,'M0y':12.5,'SF':456.46,'SFy':7.9,'loan':280.51,'loany':5.7,'dep':342.41,'depy':8.6,'ibor':1.38,'repo':1.40,
     'loan_hh_bal':83.568133,'loan_hh_st_bal':20.232407,'loan_hh_lt_bal':63.335725,'loan_hh_lt_cons_bal':48.666229,
     'loan_corp_bal':193.766811,'loan_corp_st_bal':51.349156,'loan_corp_lt_bal':123.493981,'loan_bill_bal':15.283120,'loan_nbfi_bal':0.583197},
    # 2026-04 来源：央行2026年4月金融统计数据报告（人工核实）
    # 贷款分部门数据为前四个月YTD累计；余额来自《金融机构信贷收支统计》
    {'m':'2026-04','M2':353.04,'M2y':8.6,'M1':114.58,'M1y':5.0,'M0y':12.2,
     'SF':456.89,'SFy':7.8,'loan':280.50,'loany':5.6,'dep':342.68,'depy':8.9,
     'ibor':1.29,'repo':1.31,
     # 贷款分部门 YTD（前四月累计，万亿元，负值=净减少）
     'loan_ytd':8.59,
     'loan_hh_ytd':-0.4902, 'loan_hh_st_ytd':-0.6102, 'loan_hh_lt_ytd':0.1199,
     'loan_corp_ytd':8.99,  'loan_corp_st_ytd':3.67,   'loan_corp_lt_ytd':5.01,
     'loan_bill_ytd':0.1429,'loan_nbfi_ytd':-0.1935,
     # 余额（万亿元）
     'loan_hh_bal':82.781162,'loan_hh_st_bal':19.786268,'loan_hh_lt_bal':62.994895,'loan_hh_lt_cons_bal':48.366427,
     'loan_corp_bal':194.154866,'loan_corp_st_bal':50.891515,'loan_corp_lt_bal':123.085193,'loan_bill_bal':16.523217,'loan_nbfi_bal':0.757763,
     # 外币存款（亿美元）：余额=时点值，同比=%, ytd=前四月增加量
     'fx_dep':11500.0, 'fx_dep_y':19.9, 'fx_dep_ytd':891.0},
]

ALL_FIELDS = [
    'M2','M2y','M1','M1y','M0y','SF','SFy','loan','loany','dep','depy','ibor','repo',
    # 贷款分部门 YTD 累计净增（万亿元，可负）
    'loan_ytd',
    'loan_hh_ytd','loan_hh_st_ytd','loan_hh_lt_ytd',
    'loan_corp_ytd','loan_corp_st_ytd','loan_corp_lt_ytd','loan_bill_ytd',
    'loan_nbfi_ytd',
    # 贷款分部门余额（万亿元，来自信贷收支统计表格，月末时点值）
    'loan_hh_bal','loan_hh_st_bal','loan_hh_lt_bal','loan_hh_lt_cons_bal',
    'loan_corp_bal','loan_corp_st_bal','loan_corp_lt_bal',
    'loan_bill_bal','loan_nbfi_bal',
    # 外币存款（亿美元）
    'fx_dep','fx_dep_y','fx_dep_ytd',
]

# YTD 累计流量字段（需要对前一个月做差分才得到当月净增）
YTD_FLOW_FIELDS = [
    'loan_ytd',
    'loan_hh_ytd','loan_hh_st_ytd','loan_hh_lt_ytd',
    'loan_corp_ytd','loan_corp_st_ytd','loan_corp_lt_ytd','loan_bill_ytd',
    'loan_nbfi_ytd',
    'fx_dep_ytd',
]

# ── 数据库 ────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')    # 允许并发读写
    conn.execute('PRAGMA busy_timeout=30000')  # 写锁最多等 30s 再放弃，避免 "database is locked"
    return conn


# ── 后台任务运行器 + 全局写锁 ───────────────────────────────────────────────────
# 所有"重活/写库"更新都经此运行：① 立即返回不卡 HTTP 线程 ② 全局串行(只允许一个
# 写任务，杜绝并发写撞 database is locked) ③ 状态可经 /api/jobs 轮询。
_JOBS = {}                          # name -> {status,started,finished,result,error}
_JOBS_LOCK = threading.Lock()       # 保护 _JOBS 字典
_UPDATE_LOCK = threading.Lock()     # 全局写任务串行锁(同一时刻只跑一个更新)

def _run_update_job(name, fn, blocking=False):
    """在后台守护线程里跑 fn()，串行(共享 _UPDATE_LOCK)。
    blocking=False(HTTP 触发)：锁被占则直接返回 already_running，不排队。
    blocking=True(调度器触发)：在当前线程内等锁并同步执行(调度器本就是后台线程)。"""
    def _exec():
        with _JOBS_LOCK:
            _JOBS[name] = {'status': 'running', 'started': datetime.now().isoformat(),
                           'finished': None, 'result': None, 'error': None}
        try:
            res = fn()
            safe = res if isinstance(res, (dict, list, str, int, float, bool, type(None))) else str(res)
            with _JOBS_LOCK:
                _JOBS[name].update(status='done', finished=datetime.now().isoformat(), result=safe)
            return safe
        except Exception as e:
            log.exception(f'后台任务 {name} 失败')
            with _JOBS_LOCK:
                _JOBS[name].update(status='error', finished=datetime.now().isoformat(), error=str(e))
            return {'status': 'error', 'error': str(e)}

    if blocking:
        with _UPDATE_LOCK:
            return _exec()

    if not _UPDATE_LOCK.acquire(blocking=False):
        with _JOBS_LOCK:
            cur = _JOBS.get(name) or {}
        return {'status': 'already_running', 'message': '已有更新任务在后台运行，请稍后用 /api/jobs 查看进度',
                'running': [k for k, v in _JOBS.items() if v.get('status') == 'running']}
    def _wrap():
        try:
            _exec()
        finally:
            _UPDATE_LOCK.release()
    threading.Thread(target=_wrap, daemon=True).start()
    return {'status': 'started', 'job': name,
            'message': f'{name} 已在后台运行，可轮询 /api/jobs 查看进度'}


def _do_financial_update():
    """央行月度观测同步(原 _api_financial_update 的同步逻辑，抽成可后台运行的函数)。"""
    started = datetime.now().isoformat()
    try:
        sync = sync_observations(DB_PATH)
        payload = build_api_payload(DB_PATH)
        return {
            'success': True, 'updated_at': datetime.now().isoformat(),
            'pboc_latest_period': payload['pboc_monthly']['latest_period'],
            'market_latest_date': None,
            'new_records': sync.get('new_records', 0),
            'updated_records': sync.get('updated_records', 0),
            'failed_sources': [],
            'warnings': sync.get('warnings', []) + ['市场数据源未配置，状态为 missing。'],
        }
    except Exception as e:
        with get_db() as conn:
            ensure_financial_tables(conn)
            conn.execute('''INSERT INTO financial_update_logs
                (source_name,source_type,started_at,finished_at,success,new_records,updated_records,error_message,warnings)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                ('中国人民银行', 'pboc_monthly', started, datetime.now().isoformat(), 0, 0, 0, str(e), '[]'))
            conn.commit()
        raise

def init_db():
    with get_db() as conn:
        # 建主表
        conn.execute('''CREATE TABLE IF NOT EXISTS monthly_data (
            month      TEXT PRIMARY KEY,
            M2   REAL, M2y  REAL,
            M1   REAL, M1y  REAL, M0y REAL,
            SF   REAL, SFy  REAL,
            loan REAL, loany REAL,
            dep  REAL, depy  REAL,
            ibor REAL, repo  REAL,
            -- 贷款分部门 YTD 累计净增（万亿元，可负，来自报告"前N月"段落）
            loan_ytd        REAL,
            loan_hh_ytd     REAL,  loan_hh_st_ytd  REAL,  loan_hh_lt_ytd  REAL,
            loan_corp_ytd   REAL,  loan_corp_st_ytd REAL,  loan_corp_lt_ytd REAL,
            loan_bill_ytd   REAL,  loan_nbfi_ytd   REAL,
            -- 贷款分部门余额（万亿元，月末时点值，来自信贷收支统计表格）
            loan_hh_bal      REAL, loan_hh_st_bal  REAL,
            loan_hh_lt_bal   REAL, loan_hh_lt_cons_bal REAL,
            loan_corp_bal    REAL, loan_corp_st_bal REAL,
            loan_corp_lt_bal REAL, loan_bill_bal    REAL, loan_nbfi_bal REAL,
            -- 外币存款（亿美元）
            fx_dep  REAL, fx_dep_y REAL, fx_dep_ytd REAL,
            scraped_at TEXT, source_url TEXT
        )''')
        # 迁移：兼容旧版 schema，逐一添加缺失列
        _new_cols = [
            ('raw_html',             'TEXT'),
            ('loan_ytd',             'REAL'), ('loan_hh_ytd',        'REAL'),
            ('loan_hh_st_ytd',       'REAL'), ('loan_hh_lt_ytd',     'REAL'),
            ('loan_corp_ytd',        'REAL'), ('loan_corp_st_ytd',   'REAL'),
            ('loan_corp_lt_ytd',     'REAL'), ('loan_bill_ytd',      'REAL'),
            ('loan_nbfi_ytd',        'REAL'),
            # 余额字段（月末时点值，万亿元）
            ('loan_hh_bal',          'REAL'), ('loan_hh_st_bal',     'REAL'),
            ('loan_hh_lt_bal',       'REAL'), ('loan_hh_lt_cons_bal','REAL'),
            ('loan_corp_bal',        'REAL'), ('loan_corp_st_bal',   'REAL'),
            ('loan_corp_lt_bal',     'REAL'), ('loan_bill_bal',      'REAL'),
            ('loan_nbfi_bal',        'REAL'),
            ('fx_dep',               'REAL'), ('fx_dep_y',           'REAL'),
            ('fx_dep_ytd',           'REAL'),
        ]
        added = []
        for col, typ in _new_cols:
            try:
                conn.execute(f'ALTER TABLE monthly_data ADD COLUMN {col} {typ}')
                added.append(col)
            except Exception:
                pass
        if added:
            log.info(f'DB 迁移：已添加列 {added}')

        # 爬取日志表
        conn.execute('''CREATE TABLE IF NOT EXISTS scrape_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scraped_at TEXT, status TEXT, message TEXT, new_months TEXT
        )''')
        # 原始页面存档表（按 URL 去重）
        conn.execute('''CREATE TABLE IF NOT EXISTS raw_pages (
            url        TEXT PRIMARY KEY,
            fetched_at TEXT,
            http_code  INTEGER,
            html       TEXT,
            byte_size  INTEGER
        )''')
        ensure_financial_tables(conn)
        ensure_fiscal_tables(conn)
        ensure_pboc_balance_sheet_tables(conn)
        ensure_pboc_gov_bond_omo_tables(conn)
        ensure_pboc_buyout_reverse_repo_tables(conn)
        ensure_mof_treasury_bond_tables(conn)
        ensure_astar_tables(conn)
        # 不再批量重置爬取来源。来源 URL 是前端判断 cache/seed/live 的关键证据。
        reset_count = 0
        conn.commit()

        # 写入种子数据（动态列，支持新增的贷款分部门字段）
        seeded = 0
        _fixed_tail = ['scraped_at', 'source_url']
        _data_cols = [f for f in ALL_FIELDS if f != 'raw_html']  # 排除 raw_html
        for row in SEED:
            exists = conn.execute('SELECT 1 FROM monthly_data WHERE month=?',(row['m'],)).fetchone()
            if not exists:
                cols = ['month'] + _data_cols + _fixed_tail
                vals = ([row['m']]
                        + [row.get(f) for f in _data_cols]
                        + ['seed', 'seed'])
                ph = ','.join(['?'] * len(cols))
                conn.execute(
                    f"INSERT INTO monthly_data ({','.join(cols)}) VALUES ({ph})", vals
                )
                seeded += 1
            else:
                # 种子数据只作为兜底：不覆盖官网爬取结果，只补已有行的空字段。
                updates = []
                vals = []
                for f in _data_cols:
                    v = row.get(f)
                    if v is not None:
                        updates.append(f'{f}=COALESCE({f}, ?)')
                        vals.append(v)
                if updates:
                    updates.append("source_url=COALESCE(source_url, 'seed')")
                    vals.append(row['m'])
                    conn.execute(
                        f"UPDATE monthly_data SET {','.join(updates)} WHERE month=?", vals
                    )
        conn.commit()

    total = get_db().execute('SELECT COUNT(*) FROM monthly_data').fetchone()[0]
    log.info(f'DB 就绪 — 种子新增 {seeded} 条，库中共 {total} 个月')

# ── HTTP 工具 ─────────────────────────────────────────────────────────────────
def fetch_url(url, timeout=25):
    """带 User-Agent 的 GET，返回 (html_text, http_code)"""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            raw = resp.read()
            return decode_response(raw, resp.headers), code
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception as e:
        log.debug(f'fetch 失败 {url}: {e}')
        return None, 0

def fetch_url_gbk(url, timeout=30):
    """GBK/GB2312 编码的 PBOC 统计表格专用 fetch，返回 (text, http_code)"""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw  = resp.read()
            code = resp.getcode()
            return decode_response(raw, resp.headers), code
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception as e:
        log.debug(f'fetch_gbk 失败 {url}: {e}')
        return None, 0

def save_raw_page(conn, url, html, code):
    """将原始 HTML 存档到 raw_pages 表"""
    try:
        conn.execute('''INSERT INTO raw_pages (url,fetched_at,http_code,html,byte_size)
            VALUES (?,?,?,?,?)
            ON CONFLICT(url) DO UPDATE SET
              fetched_at=excluded.fetched_at,
              html=excluded.html,
              byte_size=excluded.byte_size''',
            (url, datetime.now().isoformat(), code,
             html if html else None,
             len(html.encode('utf-8')) if html else 0))
    except Exception as e:
        log.debug(f'raw_pages 存档失败: {e}')

def decode_response(raw, headers=None):
    """按 HTTP 头、HTML meta、常见中文编码顺序解码页面。"""
    candidates = []
    if headers:
        enc = headers.get_content_charset()
        if enc:
            candidates.append(enc)
    head = raw[:4096].decode('ascii', errors='ignore')
    m = re.search(r'charset=["\']?([A-Za-z0-9_\-]+)', head, re.I)
    if m:
        candidates.append(m.group(1))
    candidates += ['utf-8', 'gb18030', 'gbk', 'gb2312']

    tried = set()
    for enc in candidates:
        enc = (enc or '').strip().lower()
        if not enc or enc in tried:
            continue
        tried.add(enc)
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode('utf-8', errors='replace')

def normalize_text(html):
    """HTML 转纯文本并合并空白，供标题和正文解析共用。"""
    if not html:
        return ''
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.I | re.S)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = html_lib.unescape(text).replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', text).strip()

def clean_title(s):
    return normalize_text(s).strip(' \t\r\n-—_')

def compact_cjk_spaces(s):
    return re.sub(r'(?<=[\u4e00-\u9fff0-9])\s+(?=[\u4e00-\u9fff0-9])', '', s or '')

def is_stats_report_title(title):
    """只保留真正的金融统计数据报告，避免会议、解读稿等文章混入。"""
    title = compact_cjk_spaces(clean_title(title))
    if not title:
        return False
    bad = ['新闻发布会', '答记者问', '解读', '图解', '专栏', '调查统计司负责人']
    if any(x in title for x in bad):
        return False
    return bool(re.search(
        r'\d{4}年(?:\d{1,2}月份?|一季度|二季度|三季度|上半年|前三季度|全年)?'
        r'(?:金融统计数据报告|货币金融统计数据报告)',
        title
    ))

# 金融统计数据报告关键词（标题含此词才处理）
STATS_KEYWORDS = ['金融统计数据', '货币金融统计', '货币供应量']

# ── 已知历史报告 URL（由人工核实，直接入库）──────────────────────────────────
# 来源：央行于2025-09-22 批量上传历史报告；包含季度/半年/全年报告
# 注：这些 URL 不在首页索引中，需直接处理
KNOWN_HISTORY_URLS = [
    # 格式: (url, title)
    (BASE+'/goutongjiaoliu/113456/113469/2025092212540228028/index.html', '2015年一季度金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212540724530/index.html', '2015年上半年金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212541182148/index.html', '2015年前三季度金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212541621527/index.html', '2015年金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212542067461/index.html', '2016年一季度金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212542506609/index.html', '2016年上半年金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212542954785/index.html', '2016年前三季度金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212543402183/index.html', '2016年金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212543835780/index.html', '2017年一季度金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212544288040/index.html', '2017年上半年金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212544742490/index.html', '2017年前三季度金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212545175726/index.html', '2017年金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212545792129/index.html', '2019年一季度金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212553128690/index.html', '2023年一季度金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/2025092212553684550/index.html', '2023年金融统计数据报告'),
    (BASE+'/goutongjiaoliu/113456/113469/5868082/index.html',             '2025年前三季度金融统计数据报告'),
]

def discover_pbc_history_links(start_year=2010, end_year=None):
    """用央行站内搜索发现历史金融统计数据报告链接。"""
    if end_year is None:
        end_year = datetime.now().year
    found = {}
    # 用 chr 拼接，避免部分 Windows 控制台/脚本编码破坏中文查询词。
    nian = chr(24180)
    phrase = ''.join(map(chr, [37329,34701,32479,35745,25968,25454,25253,21578]))
    suffixes = [
        '',
        ''.join(map(chr, [19968,23395,24230])),
        ''.join(map(chr, [19978,21322,24180])),
        ''.join(map(chr, [21069,19977,23395,24230])),
    ]
    search_url = 'https://wzdig.pbc.gov.cn/search/pcRender'
    for year in range(start_year, end_year + 1):
        for suffix in suffixes:
            q = f'{year}{nian}{suffix}{phrase}'
            url = f'{search_url}?pageId=c177a85bd02b4114bebebd210809f691&sr=score%20desc&q={quote(q)}'
            html, code = fetch_url(url, timeout=12)
            if not html or code != 200:
                continue
            for m in re.finditer(
                r'href="(https://www\.pbc\.gov\.cn/[^"]+/index\.html)"[^>]*>(.*?)</a>',
                html, re.I | re.S
            ):
                title = clean_title(m.group(2))
                if not is_stats_report_title(title):
                    continue
                month = parse_month_from_text(m.group(1), title)
                if not month:
                    continue
                # 优先使用新闻发布栏目；同一月份可能也在调查统计司栏目重复出现。
                old = found.get(month)
                new = (m.group(1), title)
                if old is None or '/goutongjiaoliu/' in new[0]:
                    found[month] = new
            time.sleep(0.1)
    return list(found.values())

# ── 信贷收支统计年度页面 ID（格式: /diaochatongjisi/116219/116319/{id}/jrjgxdsztj/index.html）
CREDIT_TABLE_YEAR_IDS = {
    2015: '2161324', 2016: '3013637', 2017: '3245697', 2018: '3471721',
    2019: '3750274', 2020: '3959050', 2021: '4184109', 2022: '4458449',
    2023: '4780803', 2024: '5225358', 2025: '5570903', 2026: '2026ntjsj',
}

# ── 爬虫：获取所有金融统计报告链接 ─────────────────────────────────────────
def get_all_report_links():
    """
    翻页爬取央行索引，同时尝试多种翻页 URL 格式（PBOC 不同时期用不同格式）。
    过滤标题，只保留金融统计数据报告类文章。
    合并已知历史 URL，返回 [(url, title), ...] 按时间从旧到新排序。
    """
    all_links = []   # [(url, title)]
    seen_reports = set()
    fetched_pages = set()
    queued_pages = []

    def enqueue_page(url):
        url = url.split('#', 1)[0]
        if url not in fetched_pages and url not in queued_pages:
            queued_pages.append(url)

    def iter_anchors(html):
        pattern = re.compile(
            r'<a\b([^>]*)href=["\']([^"\']+)["\']([^>]*)>(.*?)</a>',
            re.I | re.S
        )
        for m in pattern.finditer(html or ''):
            attrs = f'{m.group(1)} {m.group(3)}'
            href = html_lib.unescape(m.group(2).strip())
            title_attr = re.search(r'title=["\']([^"\']+)["\']', attrs, re.I | re.S)
            title = title_attr.group(1) if title_attr else m.group(4)
            yield href, clean_title(title)

    def parse_index_page(page_url, html):
        """从索引页提取报告链接和分页链接。"""
        found = []
        for href, title in iter_anchors(html):
            full = urljoin(page_url, href)
            path = urlparse(full).path
            if re.search(r'/goutongjiaoliu/113456/113469/\d+/index\.html$', path):
                if full in seen_reports:
                    continue
                seen_reports.add(full)
                if is_stats_report_title(title):
                    found.append((full, title))
                    log.info(f'  [索引发现] {title}')
            elif re.search(r'/goutongjiaoliu/113456/113469/(?:index(?:_\d+|\d+)?|11040-\d+)\.html$', path):
                enqueue_page(full)
        return found

    # 页面发现优先使用索引内分页链接；再用历史格式兜底，避免固定 80 页漏抓或空跑。
    enqueue_page(INDEX_URL)
    misses = 0
    while queued_pages and len(fetched_pages) < 220:
        page_url = queued_pages.pop(0)
        if page_url in fetched_pages:
            continue
        fetched_pages.add(page_url)
        html, code = fetch_url(page_url, timeout=10)
        if not html or code != 200:
            misses += 1
            if misses >= 30 and all_links:
                break
            continue
        misses = 0
        found = parse_index_page(page_url, html)
        all_links.extend(found)
        log.info(f'索引页 {os.path.basename(urlparse(page_url).path)}: 找到 {len(found)} 篇，累计 {len(all_links)}')
        time.sleep(0.2)

    PAGE_FORMATS = [
        lambda n: BASE + f'/goutongjiaoliu/113456/113469/index_{n}.html',
    ]
    fallback_misses = 0
    for n in range(2, 121):
        got_page = False
        for fmt in PAGE_FORMATS:
            page_url = fmt(n)
            if page_url in fetched_pages:
                continue
            fetched_pages.add(page_url)
            html, code = fetch_url(page_url, timeout=2)
            if not html or code != 200:
                continue
            found = parse_index_page(page_url, html)
            all_links.extend(found)
            log.info(f'兜底索引第{n}页 {os.path.basename(urlparse(page_url).path)}: 找到 {len(found)} 篇，累计 {len(all_links)}')
            time.sleep(0.2)
            got_page = True
            break
        if got_page:
            fallback_misses = 0
        else:
            fallback_misses += 1
            if fallback_misses >= 3:
                break

    # 合并已知历史 URL（这些不在当前索引但确认存在）
    hist_added = 0
    for url, title in KNOWN_HISTORY_URLS:
        if url not in seen_reports:
            seen_reports.add(url)
            all_links.append((url, title))
            hist_added += 1
    if hist_added:
        log.info(f'加入 {hist_added} 条已知历史报告 URL')

    discovered_added = 0
    try:
        for url, title in discover_pbc_history_links(2010, datetime.now().year):
            if url not in seen_reports:
                seen_reports.add(url)
                all_links.append((url, title))
                discovered_added += 1
    except Exception as e:
        log.warning(f'央行站内搜索历史报告失败: {e}')
    if discovered_added:
        log.info(f'站内搜索加入 {discovered_added} 条历史报告 URL')

    # 复用 raw_pages 中已经归档过的报告链接。PBOC 新闻栏目历史分页不可稳定遍历，
    # 本地归档能避免下一次“全量爬取”反而只处理首页和少量硬编码 URL。
    archived_added = 0
    try:
        with get_db() as conn:
            for row in conn.execute('SELECT url, html FROM raw_pages'):
                url = row['url']
                if url in seen_reports:
                    continue
                text = normalize_text(row['html'] or '')
                month = parse_month_from_text(url, text)
                if not month:
                    continue
                year, mo = month.split('-')
                seen_reports.add(url)
                all_links.append((url, f'{year}年{int(mo)}月金融统计数据报告'))
                archived_added += 1
    except Exception as e:
        log.debug(f'读取 raw_pages 历史归档失败: {e}')
    if archived_added:
        log.info(f'加入 {archived_added} 条本地归档报告 URL')

    # 按数据月份排序；识别失败时再按 URL 排序。
    def sort_key(pair):
        month = parse_month_from_text(pair[0], pair[1])
        return (month or '9999-99', pair[0])

    all_links.sort(key=sort_key)
    log.info(f'共获取 {len(all_links)} 篇金融统计报告链接（含历史）')
    return all_links

# ── 爬虫：解析单篇报告 ──────────────────────────────────────────────────────
def parse_month_from_text(url, text):
    """
    从报告文本或 URL 推断数据对应的自然月（不是发布月）。

    央行报告标题格式（数据月 → 覆盖时间）：
      "YYYY年X月金融统计数据报告"         → YYYY-MM（月度，直接用）
      "YYYY年一季度金融统计数据报告"       → YYYY-03
      "YYYY年上半年金融统计数据报告"       → YYYY-06
      "YYYY年前三季度金融统计数据报告"     → YYYY-09
      "YYYY年金融统计数据报告"（全年）     → YYYY-12

    核心字段（M2余额、贷款余额等）全部是时点/余额数据，无论报告覆盖几个月，
    文中都明确写 "X月末余额…" 的时点值，不需要对累计流量做拆解。
    """
    text = compact_cjk_spaces(text)
    # 1. 标准月度标题
    m = re.search(r'(\d{4})年(\d{1,2})月份?(?:金融统计|货币金融)', text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"

    # 2. 季度 / 半年 / 三季度 → 映射到对应季末月
    QUARTER_MAP = {
        '一季度':   '03',
        '上半年':   '06',
        '二季度':   '06',   # 极少用，同上半年
        '前三季度': '09',
        '三季度':   '09',
        '前两季度': '06',
    }
    m = re.search(
        r'(\d{4})年(一季度|上半年|二季度|前三季度|三季度|前两季度)'
        r'(?:金融统计|货币金融)',
        text
    )
    if m:
        return f"{m.group(1)}-{QUARTER_MAP[m.group(2)]}"

    # 3. 全年报告（"YYYY年金融统计数据报告"，无月份/季度词）→ 12月
    m = re.search(r'(\d{4})年(?:全年)?金融统计数据报告', text)
    if m:
        return f"{m.group(1)}-12"

    # 4. URL 时间戳兜底（发布时间 - 1 个月 ≈ 数据月，但准确性较低，仅用于无法识别标题时）
    m = re.search(r'/(\d{4})(\d{2})\d{6,}/', url)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        mo -= 1
        if mo == 0: y -= 1; mo = 12
        return f"{y}-{mo:02d}"

    return None

def _n(s):
    try: return float(s)
    except: return None

def _to_wan_yi(val, unit):
    """将亿元/万亿元统一换算为万亿元"""
    v = float(val)
    if '万亿' in unit: return v
    if '亿' in unit:   return round(v / 10000.0, 6)
    return v

def _signed(direction, val):
    """'减少'方向 → 取负，'增加'方向 → 取正"""
    return -val if '减少' in direction else val

def parse_loan_breakdown(body):
    """
    解析报告正文中的"分部门看"段落，提取贷款 YTD 累计净增数据。
    单位统一为万亿元（负值 = 净减少）。

    央行报告格式示例（2026-04）：
      "前四个月人民币贷款增加8.59万亿元。分部门看，
       住户贷款减少4902亿元，其中，短期贷款减少6102亿元，中长期贷款增加1199亿元；
       企（事）业单位贷款增加8.99万亿元，其中，短期贷款增加3.67万亿元，
         中长期贷款增加5.01万亿元，票据融资增加1429亿元；
       非银行业金融机构贷款减少1935亿元。"
    """
    d = {}
    # ── 总量YTD ───────────────────────────────────────────────────────────────
    m = re.search(
        r'前[一二三四五六七八九十百\d]+月人民币贷款(增加|减少)(\d+\.?\d*)(万亿|亿)元',
        body
    )
    if m:
        d['loan_ytd'] = _signed(m.group(1), _to_wan_yi(m.group(2), m.group(3)))

    # ── 找到"分部门看"段落 ────────────────────────────────────────────────────
    sec = re.search(r'分部门看[，,]?(.*?)(?:二、|三、|注：|$)', body, re.DOTALL)
    if not sec:
        return d
    seg = sec.group(1)

    # 按中文分号"；"拆分三个子段（住户 / 企业 / 非银）
    parts = re.split(r'[；;]', seg)

    for part in parts:
        part = part.strip()
        if '住户' in part:
            # 住户贷款总量
            m = re.search(r'住户贷款(增加|减少)(\d+\.?\d*)(万亿|亿)元', part)
            if m: d['loan_hh_ytd'] = _signed(m.group(1), _to_wan_yi(m.group(2), m.group(3)))
            # 短期（住户）
            m = re.search(r'短期贷款(增加|减少)(\d+\.?\d*)(万亿|亿)元', part)
            if m: d['loan_hh_st_ytd'] = _signed(m.group(1), _to_wan_yi(m.group(2), m.group(3)))
            # 中长期（住户）
            m = re.search(r'中长期贷款(增加|减少)(\d+\.?\d*)(万亿|亿)元', part)
            if m: d['loan_hh_lt_ytd'] = _signed(m.group(1), _to_wan_yi(m.group(2), m.group(3)))

        elif ('企' in part and '业单位' in part) or ('企业' in part and '贷款' in part):
            # 企(事)业单位贷款总量
            m = re.search(r'企[（(]?事[）)]?业单位贷款(增加|减少)(\d+\.?\d*)(万亿|亿)元', part)
            if not m:
                m = re.search(r'企业贷款(增加|减少)(\d+\.?\d*)(万亿|亿)元', part)
            if m: d['loan_corp_ytd'] = _signed(m.group(1), _to_wan_yi(m.group(2), m.group(3)))
            # 短期（企业）
            m = re.search(r'短期贷款(增加|减少)(\d+\.?\d*)(万亿|亿)元', part)
            if m: d['loan_corp_st_ytd'] = _signed(m.group(1), _to_wan_yi(m.group(2), m.group(3)))
            # 中长期（企业）
            m = re.search(r'中长期贷款(增加|减少)(\d+\.?\d*)(万亿|亿)元', part)
            if m: d['loan_corp_lt_ytd'] = _signed(m.group(1), _to_wan_yi(m.group(2), m.group(3)))
            # 票据融资
            m = re.search(r'票据融资(增加|减少)(\d+\.?\d*)(万亿|亿)元', part)
            if m: d['loan_bill_ytd'] = _signed(m.group(1), _to_wan_yi(m.group(2), m.group(3)))

        elif '非银行' in part:
            m = re.search(r'非银行业?金融机构贷款(增加|减少)(\d+\.?\d*)(万亿|亿)元', part)
            if m: d['loan_nbfi_ytd'] = _signed(m.group(1), _to_wan_yi(m.group(2), m.group(3)))

    found = [k for k,v in d.items() if v is not None]
    if found:
        log.info(f'    贷款分部门: {found}')
    return d

def parse_credit_table_text(text, year):
    """
    解析 GBK 信贷收支 HTML 表格（去标签后纯文本），提取分部门贷款余额。
    返回 {month_str -> {field -> val_wan_yi}} 例如 {'2026-01': {'loan_hh_bal': 83.73, ...}}

    表格行顺序（固定）：
      住户贷款 → 短期(住户) → 消费(住户短) → 经营(住户短)
      → 中长期(住户) → 消费(住户中长/房贷) → 经营(住户中长)
      → 企(事)业单位贷款 → 短期(企业) → 中长期(企业) → 票据融资
      → 非银行业金融机构贷款
    """
    text = html_lib.unescape(text).replace('\xa0', ' ')
    text = re.sub(r'\s+', ' ', text)

    # 标签序列：(field, search_str_list, skip?)
    # skip=True 表示找到位置但不保存值（消除重复的"消费贷款"/"经营贷款"）
    ROW_DEFS = [
        ('loan_hh_bal',          ['住户贷款'],                                  False),
        ('loan_hh_st_bal',       ['短期贷款'],                                  False),
        (None,                   ['消费贷款'],                                  True ),  # 住户短期消费
        (None,                   ['经营贷款'],                                  True ),  # 住户短期经营
        ('loan_hh_lt_bal',       ['中长期贷款'],                                False),
        ('loan_hh_lt_cons_bal',  ['消费贷款'],                                  False),  # 住户中长期消费（房贷）
        (None,                   ['经营贷款'],                                  True ),  # 住户中长期经营
        ('loan_corp_bal',        ['企（事）业单位贷款','企(事)业单位贷款','企业贷款'], False),
        ('loan_corp_st_bal',     ['短期贷款'],                                  False),
        ('loan_corp_lt_bal',     ['中长期贷款'],                                False),
        ('loan_bill_bal',        ['票据融资'],                                  False),
        ('loan_nbfi_bal',        ['非银行业金融机构贷款','非银行金融机构贷款'],   False),
    ]

    # 顺序查找每个标签位置
    search_from = 0
    found_labels = []   # [(field, char_pos, skip)]
    for field, patterns, skip in ROW_DEFS:
        best = -1
        for pat in patterns:
            pos = text.find(pat, search_from)
            if pos >= 0 and (best < 0 or pos < best):
                best = pos
        if best >= 0:
            found_labels.append((field, best, skip))
            search_from = best + 2   # 从找到的位置往后继续，保证顺序
        else:
            found_labels.append((field, -1, skip))

    # 提取每个有效行的数值（label_pos ~ next_label_pos 段落内）
    def extract_nums(seg):
        """提取 > 500 亿的数字（跳过年份 2000-2030 和月份 1-12）"""
        vals = []
        for s in re.findall(r'\b(\d{4,9}\.?\d*)\b', seg):
            v = float(s)
            if 2000 <= v <= 2030:   # 年份
                continue
            if v < 500:             # 太小（不是有效余额）
                continue
            vals.append(v)
        return vals

    results_by_field = {}
    for i, (field, pos, skip) in enumerate(found_labels):
        if pos < 0 or skip or field is None:
            continue
        # 段落结束 = 下一个有效标签（pos>0）
        end = len(text)
        for j in range(i + 1, len(found_labels)):
            nxt_pos = found_labels[j][1]
            if nxt_pos > pos:
                end = nxt_pos
                break
        nums = extract_nums(text[pos:end])
        if nums:
            results_by_field[field] = nums

    if not results_by_field:
        return {}

    # 月数取各目标行共同具备的最短长度，防止某一行串到后续表格后写出未来月份。
    max_len = min(min(len(v) for v in results_by_field.values()), 12)
    if max_len <= 0:
        return {}
    months  = [f"{year}-{mo:02d}" for mo in range(1, max_len + 1)]

    out = {}
    for idx, month in enumerate(months):
        row = {}
        for field, vals in results_by_field.items():
            if idx < len(vals):
                row[field] = round(vals[idx] / 10000.0, 6)   # 亿元 → 万亿元
        if row:
            out[month] = row
    return out


def get_credit_htm_url(year):
    """
    获取某年《金融机构人民币信贷收支统计》HTM 文件 URL。
    统计表附件在 /attachDir/ 路径下，后缀为 .htm（非 .html）。
    第5个 .htm 附件 = 人民币月度汇总表（含12列月度余额）。
    返回 URL 字符串，失败返回 None。
    """
    year_id = CREDIT_TABLE_YEAR_IDS.get(year)
    if not year_id:
        return None
    index_url = f'{BASE}/diaochatongjisi/116219/116319/{year_id}/jrjgxdsztj/index.html'
    html, code = fetch_url_gbk(index_url)
    if not html or code != 200:
        log.debug(f'信贷统计索引页失败 {year}: HTTP {code}')
        return None
    links = []
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+\.htm)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        href = html_lib.unescape(m.group(1).strip())
        full = urljoin(index_url, href)
        start = max(0, m.start() - 300)
        end = min(len(html), m.end() + 300)
        context = clean_title(html[start:end])
        links.append((full, context))
    if not links:
        log.debug(f'信贷统计索引页无 .htm 附件链接: {year}')
        return None

    def score_link(item):
        url, context = item
        score = 0
        if '人民币' in context: score += 5
        if '信贷收支' in context: score += 5
        if '金融机构' in context: score += 2
        if '本外币' in context: score -= 4
        if '外汇' in context or '外币' in context: score -= 3
        return score

    scored = sorted(links, key=score_link, reverse=True)
    if score_link(scored[0]) > 0:
        return scored[0][0]

    # 央行 Excel 导出的索引锚文本常常只有 "htm"，历史页面里第 5 个通常是人民币月度汇总表。
    return links[min(4, len(links) - 1)][0]


def scrape_credit_tables():
    """
    爬取所有年份的《金融机构信贷收支统计》HTML 表格，写入分部门贷款余额字段。
    只写入 NULL 的字段（保护已有数据；种子/人工核实数据优先）。
    """
    log.info('开始爬取信贷收支统计余额数据…')
    total_written = 0
    current_year = datetime.now().year

    with get_db() as conn:
        for year in range(2015, current_year + 1):
            try:
                htm_url = get_credit_htm_url(year)
                if not htm_url:
                    continue
                log.info(f'  信贷表格 {year}: {htm_url}')
                time.sleep(1.0)
                html, code = fetch_url_gbk(htm_url)
                if not html or code != 200:
                    log.debug(f'  信贷表格 {year} 下载失败: HTTP {code}')
                    continue
                # 去标签，合并空白
                text = normalize_text(html)
                month_data = parse_credit_table_text(text, year)
                if not month_data:
                    log.warning(f'  信贷表格 {year}: 解析无结果')
                    continue

                bal_fields = [
                    'loan_hh_bal','loan_hh_st_bal','loan_hh_lt_bal','loan_hh_lt_cons_bal',
                    'loan_corp_bal','loan_corp_st_bal','loan_corp_lt_bal',
                    'loan_bill_bal','loan_nbfi_bal',
                ]
                written_months = []
                for month, row in month_data.items():
                    if not row:
                        continue
                    # 检查该月是否已有余额数据（非NULL）
                    existing = conn.execute(
                        "SELECT source_url FROM monthly_data WHERE month=?", (month,)
                    ).fetchone()
                    if existing and existing['source_url'] == 'manual':
                        # 人工核实数据优先，爬虫不覆盖
                        continue

                    # UPSERT：只写入余额字段，不动其他字段；非人工来源允许用新解析覆盖旧脏值。
                    set_parts = []
                    vals = []
                    for f in bal_fields:
                        v = row.get(f)
                        if v is not None:
                            set_parts.append(f'{f}=?')
                            vals.append(v)
                    if not set_parts:
                        continue
                    # 先确保该 month 行存在
                    conn.execute(
                        "INSERT OR IGNORE INTO monthly_data (month, source_url) VALUES (?, 'credit_table')",
                        (month,)
                    )
                    vals.append(month)
                    conn.execute(
                        f"UPDATE monthly_data SET {', '.join(set_parts)} WHERE month=?", vals
                    )
                    written_months.append(month)
                    total_written += 1

                if written_months:
                    conn.commit()
                    log.info(f'  信贷表格 {year}: 写入 {len(written_months)} 个月 {written_months[:4]}…')
                else:
                    log.info(f'  信贷表格 {year}: 解析 {len(month_data)} 个月，无需更新（已有数据）')

            except Exception as e:
                log.warning(f'  信贷表格 {year} 处理异常: {e}')
                continue

    log.info(f'信贷余额爬取完成，共写入/更新 {total_written} 条月份记录')
    return total_written


PATTERNS = {
    # M2 余额（时点值）——月度/季度报告均写 "广义货币（M2）余额XXX万亿元"
    'M2_b': r'广义货币(?:供应量)?\s*[（(]?M2[）)]?[^，。]*?余额[为是]?\s*(\d+\.?\d*)\s*万亿元',
    # M2 同比增速
    'M2_y': r'广义货币(?:供应量)?\s*[（(]?M2[）)]?[^。；;]*?同比增长\s*(\d+\.?\d*)\s*%',
    # M1 余额（时点值）
    'M1_b': r'狭义货币(?:供应量)?\s*[（(]?M1[）)]?[^，。]*?余额[为是]?\s*(\d+\.?\d*)\s*万亿元',
    # M1 同比（可能增长/下降）
    'M1_y': r'狭义货币(?:供应量)?\s*[（(]?M1[）)]?[^。；;]*?同比(增长|下降)\s*(\d+\.?\d*)\s*%',
    # M0 同比
    'M0_y': r'流通中货币[（(]?M0[）)]?[^。；;]*?同比(增长|下降)\s*(\d+\.?\d*)\s*%',
    # 贷款余额（时点值，"月末人民币贷款余额XXX万亿元"）
    # 注意：区分"月末人民币贷款余额"（时点）与"前X月贷款增加"（累计流量，不提取）
    'loan_b': r'(?<!发放的)(?:月末)?(?:金融机构)?\s*人民币(?:各项)?贷款余额[为是]?\s*(\d+\.?\d*)\s*万亿元',
    # 贷款同比增速
    'loan_y': r'(?<!发放的)(?:月末)?(?:金融机构)?\s*人民币(?:各项)?贷款余额[为是]?\s*\d+\.?\d*\s*万亿元[^。；;]*?同比增长\s*(\d+\.?\d*)\s*%',
    # 社融存量（时点值）——注意区分"存量"和"增量"，只提取"存量"
    'SF_b': r'社会融资规模存量为?(\d+\.?\d*)万亿元',
    # 社融存量同比
    'SF_y': r'社会融资规模存量[^。；;]*?同比增长(\d+\.?\d*)%',
    # 存款余额（时点值，"月末人民币存款余额XXX万亿元"）
    'dep_b': r'(?:月末)?(?:金融机构)?人民币(?:各项)?存款余额[为是]?\s*(\d+\.?\d*)\s*万亿元',
    # 存款同比增速
    'dep_y': r'(?:月末)?(?:金融机构)?人民币(?:各项)?存款余额[为是]?\s*\d+\.?\d*\s*万亿元[^。；;]*?同比增长\s*(\d+\.?\d*)\s*%',
    # 同业拆借利率（月加权平均）
    'ibor': r'同业拆借(?:月)?加权平均利率为\s*(\d+\.?\d*)\s*%',
    # 回购利率
    'repo': r'质押式(?:债券)?回购(?:月)?加权平均利率为\s*(\d+\.?\d*)\s*%',
    # 外币存款余额（亿美元；"1.15万亿美元"→11500亿美元，直接写亿美元的也要匹配）
    'fx_dep_b':  r'外币存款余额(\d+\.?\d*)(万亿|亿)美元',
    # 外币存款同比
    'fx_dep_y':  r'外币存款余额.{0,60}同比(增长|下降)(\d+\.?\d*)%',
    # 前N月外币存款增加（亿美元）
    'fx_dep_ytd': r'前[一二三四五六七八九十百\d]+月外币存款增加(\d+\.?\d*)(万亿|亿)美元',
}

def parse_report(url):
    """抓取并解析一篇央行月报，返回 (month, data_dict, raw_html)"""
    html, code = fetch_url(url)
    if not html:
        return None, {}, None

    # 提取纯文本
    text = normalize_text(html)

    month = parse_month_from_text(url, text)
    if not month:
        log.warning(f'无法识别月份: {url}')
        return None, {}, html

    d = {}
    # ── 先去掉页面头部导航/注释干扰，只保留报告正文 ──────────────────────
    # 找到报告标题后的正文（标题是报告名称，正文从"一、"或"关键词"开始）
    body_start = re.search(r'(?:一、|广义货币|社会融资规模)', text)
    body = text[body_start.start():] if body_start else text

    m = re.search(PATTERNS['M2_b'], body)
    if m: d['M2'] = _n(m.group(1))
    m = re.search(PATTERNS['M2_y'], body)
    if m: d['M2y'] = _n(m.group(1))

    m = re.search(PATTERNS['M1_b'], body)
    if m: d['M1'] = _n(m.group(1))
    m = re.search(PATTERNS['M1_y'], body)
    if m: d['M1y'] = _n(m.group(2)) * (-1 if '下降' in m.group(1) else 1)

    m = re.search(PATTERNS['M0_y'], body)
    if m: d['M0y'] = _n(m.group(2)) * (-1 if '下降' in m.group(1) else 1)

    m = re.search(PATTERNS['loan_b'], body)
    if m: d['loan'] = _n(m.group(1))
    m = re.search(PATTERNS['loan_y'], body)
    if m: d['loany'] = _n(m.group(1))

    m = re.search(PATTERNS['SF_b'], body)
    if m: d['SF'] = _n(m.group(1))
    m = re.search(PATTERNS['SF_y'], body)
    if m: d['SFy'] = _n(m.group(1))

    m = re.search(PATTERNS['dep_b'], body)
    if m: d['dep'] = _n(m.group(1))
    m = re.search(PATTERNS['dep_y'], body)
    if m: d['depy'] = _n(m.group(1))

    m = re.search(PATTERNS['ibor'], body)
    if m: d['ibor'] = _n(m.group(1))
    m = re.search(PATTERNS['repo'], body)
    if m: d['repo'] = _n(m.group(1))

    # ── 外币存款 ──────────────────────────────────────────────────────────────
    m = re.search(PATTERNS['fx_dep_b'], body)
    if m:
        # 统一转为亿美元存储（1万亿=10000亿）
        v = float(m.group(1))
        d['fx_dep'] = v * 10000 if '万亿' in m.group(2) else v
    m = re.search(PATTERNS['fx_dep_y'], body)
    if m: d['fx_dep_y'] = _n(m.group(2)) * (-1 if '下降' in m.group(1) else 1)
    m = re.search(PATTERNS['fx_dep_ytd'], body)
    if m:
        v = float(m.group(1))
        d['fx_dep_ytd'] = v * 10000 if '万亿' in m.group(2) else v

    # ── 贷款分部门 YTD ────────────────────────────────────────────────────────
    bd = parse_loan_breakdown(body)
    d.update(bd)

    found_fields = [k for k,v in d.items() if v is not None]
    log.info(f'  ✓ {month} | {len(found_fields)} 字段: {found_fields}')
    return month, d, html

# ── 主爬取任务 ────────────────────────────────────────────────────────────────
def scrape_and_update():
    log.info('━' * 50)
    log.info('开始全量爬取 PBOC 历史数据…')
    new_months, updated = [], []

    try:
        link_pairs = get_all_report_links()   # [(url, title), ...]
        with get_db() as conn:
            for url, title in link_pairs:
                # 优先从标题推断月份（比 URL 时间戳更准确）
                # 用一个临时文本只包含标题做快速判断
                quick = parse_month_from_text(url, title)
                if quick:
                    row_info = conn.execute(
                        "SELECT M2, source_url FROM monthly_data WHERE month=?",
                        (quick,)
                    ).fetchone()
                    if row_info:
                        if (row_info['M2'] is not None
                                and row_info['source_url'] not in ('seed', 'manual', None)):
                            log.debug(f'跳过已有爬取数据: {quick} [{title}]')
                            continue

                log.info(f'处理: [{title}]')
                time.sleep(1.5)
                month, data, raw_html = parse_report(url)
                if not month:
                    continue

                # 存原始 HTML
                save_raw_page(conn, url, raw_html, 200)

                if not data:
                    log.warning(f'跳过无有效字段的报告: {month} {url}')
                    continue

                ex = conn.execute('SELECT source_url FROM monthly_data WHERE month=?', (month,)).fetchone()

                # 动态构建 UPSERT（所有 ALL_FIELDS + raw_html + scraped_at + source_url）
                _upsert_cols = ['month'] + ALL_FIELDS + ['raw_html', 'scraped_at', 'source_url']
                _upsert_vals = (
                    [month]
                    + [data.get(f) for f in ALL_FIELDS]
                    + [raw_html, datetime.now().isoformat(), url]
                )
                _ph = ','.join(['?'] * len(_upsert_cols))
                # ON CONFLICT: 用 COALESCE 只在 DB 为 NULL 时才用新值（保护已有数据）
                _upd_parts = []
                for f in ALL_FIELDS:
                    _upd_parts.append(f'{f}=COALESCE(excluded.{f},{f})')
                _upd_parts += [
                    'raw_html=COALESCE(excluded.raw_html,raw_html)',
                    'scraped_at=excluded.scraped_at',
                    'source_url=excluded.source_url',
                ]
                conn.execute(
                    f"INSERT INTO monthly_data ({','.join(_upsert_cols)}) VALUES ({_ph})"
                    f" ON CONFLICT(month) DO UPDATE SET {','.join(_upd_parts)}",
                    _upsert_vals
                )
                if ex and ex['source_url'] in ('manual','seed'):
                    updated.append(month)
                else:
                    new_months.append(month)

            conn.execute(
                'INSERT INTO scrape_log (scraped_at,status,message,new_months) VALUES (?,?,?,?)',
                (datetime.now().isoformat(), 'ok',
                 f'新增{len(new_months)}个月，更新种子{len(updated)}个月',
                 json.dumps(sorted(new_months+updated)))
            )
            conn.commit()

        # ── 额外爬取信贷收支统计表格（余额数据）────────────────────────────
        try:
            scrape_credit_tables()
        except Exception as e:
            log.warning(f'信贷余额爬取出错（不影响主流程）: {e}')

        with get_db() as c2:
            total   = c2.execute('SELECT COUNT(*) FROM monthly_data').fetchone()[0]
            raw_cnt = c2.execute('SELECT COUNT(*) FROM raw_pages').fetchone()[0]
        log.info(f'爬取完成 — 新增:{new_months}  更新:{updated}')
        log.info(f'数据库: {total} 个月  原始页面存档: {raw_cnt} 篇')
        return {'status':'ok','new':new_months,'updated':updated,'total':total}

    except Exception as e:
        log.error(f'爬取失败: {e}', exc_info=True)
        try:
            with get_db() as conn:
                conn.execute('INSERT INTO scrape_log (scraped_at,status,message) VALUES (?,?,?)',
                    (datetime.now().isoformat(),'error',str(e)))
                conn.commit()
        except: pass
        return {'status':'error','message':str(e)}

# ── HTTP API ──────────────────────────────────────────────────────────────────
def cors_headers():
    return {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Content-Type': 'application/json; charset=utf-8',
    }

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        try:
            self.send_response(code)
            for k,v in cors_headers().items(): self.send_header(k,v)
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # 客户端在响应写完前断开(刷新/离开/等不及)——正常现象，静默丢弃，
            # 不让异常冒泡到 socketserver 刷屏日志、也不影响其它线程。
            pass

    def send_file(self, file_path):
        try:
            with open(file_path, 'rb') as f:
                body = f.read()
            mime, _ = mimetypes.guess_type(file_path)
            self.send_response(200)
            self.send_header('Content-Type', mime or 'application/octet-stream')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_json({'error': 'not found'}, 404)

    def _serve_static(self, url_path):
        # 把 URL 路径映射到 STATIC_DIR 下的文件，防止目录穿越
        rel = url_path.lstrip('/').replace('/', os.sep)
        target = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not target.startswith(STATIC_DIR) or not os.path.isfile(target):
            self.send_json({'error': 'not found'}, 404)
            return
        self.send_file(target)

    def do_OPTIONS(self):
        self.send_response(204)
        for k,v in cors_headers().items(): self.send_header(k,v)
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            # API routes
            if   path == '/api/data':       self._api_data()
            elif path == '/api/status':     self._api_status()
            elif path == '/api/health':     self.send_json({'status':'ok','time':datetime.now().isoformat()})
            elif path == '/api/jobs':
                with _JOBS_LOCK:
                    jobs = dict(_JOBS)
                self.send_json({'update_lock_busy': _UPDATE_LOCK.locked(), 'jobs': jobs})
            elif path == '/api/abdc/data':  self._api_abdc_data()
            elif path == '/api/financial/debug': self._api_financial_debug()
            elif path == '/api/fiscal-debt/data': self._api_fiscal_debt_data()
            elif path == '/api/fiscal-debt/debug': self._api_fiscal_debt_debug()
            elif path == '/api/fiscal-debt/projection': self._api_fiscal_debt_projection()
            elif path == '/api/fiscal-debt/pboc-balance-sheet': self._api_pboc_balance_sheet()
            elif path == '/api/fiscal-debt/pboc-gov-bond-omo': self._api_pboc_gov_bond_omo()
            elif path == '/api/fiscal-debt/pboc-buyout-reverse-repo': self._api_pboc_buyout_reverse_repo()
            elif path == '/api/fiscal-debt/mof-treasury-bonds': self._api_mof_treasury_bonds()
            # ABDC A* Research Radar API
            elif path == '/api/abdc/astar/journals': self.send_json(build_astar_journals_payload())
            elif path == '/api/abdc/astar/articles': self._api_astar_articles()
            elif re.match(r'^/api/abdc/astar/articles/\d+$', path):
                self.send_json(build_astar_article_detail(int(path.rsplit('/', 1)[1])))
            elif path == '/api/abdc/astar/recent': self._api_astar_recent()
            elif path == '/api/abdc/astar/digest': self._api_astar_digest()
            elif path == '/api/abdc/astar/saved': self.send_json(build_saved_articles_payload())
            elif path == '/api/abdc/astar/trends': self._api_astar_trends()
            elif path == '/api/abdc/astar/lists': self.send_json(build_prestige_lists_payload())
            elif path == '/api/abdc/astar/health': self.send_json(build_journal_health_payload())
            elif path == '/api/abdc/astar/debug': self.send_json(build_astar_debug_payload())
            # Static page routes
            elif path in ('/', ''):         self.send_file(os.path.join(STATIC_DIR, 'index.html'))
            elif path in ('/dashboard', '/dashboard.html'):
                self.send_file(os.path.join(STATIC_DIR, 'dashboard.html'))
            elif path in ('/financial/debug', '/financial/debug.html'):
                self.send_file(os.path.join(STATIC_DIR, 'financial_debug.html'))
            elif path in ('/fiscal-debt/debug', '/fiscal-debt/debug.html'):
                self.send_file(os.path.join(STATIC_DIR, 'fiscal_debt_debug.html'))
            elif path in ('/fiscal-debt', '/fiscal-debt/'):
                self.send_file(os.path.join(STATIC_DIR, 'fiscal_debt.html'))
            elif path in ('/abdc', '/abdc/', '/abdc/index.html'):
                self.send_file(os.path.join(STATIC_DIR, 'abdc', 'index.html'))
            elif path in ('/abdc-astar-research', '/abdc-astar-research/'):
                self.send_file(os.path.join(STATIC_DIR, 'abdc_astar_research.html'))
            else:
                # 通用静态文件（/vendor/*.js 等），带目录穿越保护
                self._serve_static(path)
        except Exception as e:
            self.send_json({'error':str(e)},500)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/scrape':
            self.send_json(_run_update_job('pboc_scrape', scrape_and_update))
        elif path == '/api/financial/update':
            self._api_financial_update()
        elif path == '/api/fiscal-debt/update':
            self._api_fiscal_debt_update()
        elif path == '/api/fiscal-debt/local-government-debt/update':
            self.send_json(_run_update_job('local_government_debt', lambda: run_fiscal_module_update(DB_PATH, 'local_government_debt')))
        elif path == '/api/fiscal-debt/central-government-debt/update':
            self.send_json(_run_update_job('central_government_debt', lambda: run_fiscal_module_update(DB_PATH, 'central_government_debt')))
        elif path == '/api/fiscal-debt/pboc-balance-sheet/update':
            self._api_pboc_balance_sheet_update()
        elif path == '/api/fiscal-debt/pboc-gov-bond-omo/update':
            self._api_pboc_gov_bond_omo_update()
        elif path == '/api/fiscal-debt/pboc-buyout-reverse-repo/update':
            self._api_pboc_buyout_reverse_repo_update()
        elif path == '/api/fiscal-debt/mof-treasury-bonds/update':
            self._api_mof_treasury_bonds_update()
        elif path == '/api/fiscal-debt/projection/run':
            self._api_fiscal_debt_projection_run()
        elif path == '/api/abdc/astar/update':
            self._api_astar_update()
        elif path == '/api/abdc/astar/classify':
            threading.Thread(target=reclassify_all, daemon=True).start()
            self.send_json({'status': 'started', 'message': '重新分类已在后台启动'})
        elif path == '/api/abdc/astar/health/run':
            threading.Thread(target=run_journal_health_check, daemon=True).start()
            self.send_json({'status': 'started', 'message': '期刊健康检查已启动（223 刊逐个查 OpenAlex，约 1-2 分钟），完成后看 /api/abdc/astar/health'})
        elif path == '/api/abdc/astar/llm-classify':
            body = self._read_json_body()
            if not (os.environ.get('DEEPSEEK_API_KEY') or os.environ.get('ANTHROPIC_API_KEY')):
                self.send_json({'success': False, 'error': '未设置 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY'}, 400)
            else:
                limit = int(body.get('limit', 100))
                kw = dict(limit=limit, max_relevance=body.get('max_relevance'),
                          core_journals_only=bool(body.get('core_journals_only')))
                threading.Thread(target=lambda: llm_classify_articles(**kw), daemon=True).start()
                self.send_json({'status': 'started', 'message': f'LLM 重新分类已启动（最多 {limit} 篇）'})
        elif path == '/api/abdc/astar/save':
            self._api_astar_save()
        elif path == '/api/abdc/astar/enrich':
            body = self._read_json_body()
            limit = body.get('limit')
            threading.Thread(target=lambda: enrich_with_semantic_scholar(limit=limit), daemon=True).start()
            self.send_json({'status': 'started',
                            'message': 'Semantic Scholar 补全已启动（补摘要/引用/学科，按批进行，可在 Debug 看进度）'})
        else:
            self.send_json({'error':'not found'},404)

    def _api_data(self):
        self.send_json(build_api_payload(DB_PATH))

    def _api_financial_update(self):
        self.send_json(_run_update_job('financial', _do_financial_update))

    def _api_financial_debug(self):
        self.send_json(build_debug_payload(DB_PATH))

    def _api_fiscal_debt_data(self):
        self.send_json(build_fiscal_monitor_payload(DB_PATH))

    def _api_fiscal_debt_debug(self):
        self.send_json(build_fiscal_monitor_debug(DB_PATH))

    def _api_pboc_balance_sheet(self):
        self.send_json(build_pboc_balance_sheet_payload(DB_PATH))

    def _api_pboc_balance_sheet_update(self):
        self.send_json(_run_update_job('pboc_balance_sheet', lambda: run_fiscal_module_update(DB_PATH, 'pboc_balance_sheet')))

    def _api_pboc_gov_bond_omo(self):
        self.send_json(build_pboc_gov_bond_omo_payload(DB_PATH))

    def _api_pboc_gov_bond_omo_update(self):
        self.send_json(_run_update_job('pboc_gov_bond_omo', lambda: run_fiscal_module_update(DB_PATH, 'pboc_gov_bond_omo')))

    def _api_pboc_buyout_reverse_repo(self):
        self.send_json(build_pboc_buyout_reverse_repo_payload(DB_PATH))

    def _api_pboc_buyout_reverse_repo_update(self):
        self.send_json(_run_update_job('pboc_buyout_reverse_repo', lambda: run_fiscal_module_update(DB_PATH, 'pboc_buyout_reverse_repo')))

    def _api_mof_treasury_bonds(self):
        self.send_json(build_mof_treasury_bond_payload(DB_PATH))

    def _api_mof_treasury_bonds_update(self):
        self.send_json(_run_update_job('treasury_issuance', lambda: run_fiscal_module_update(DB_PATH, 'treasury_issuance')))

    def _api_fiscal_debt_update(self):
        body = self._read_json_body()
        module_code = body.get('module_code')
        if module_code:
            self.send_json(_run_update_job(module_code, lambda: run_fiscal_module_update(DB_PATH, module_code)))
        else:
            self.send_json(_run_update_job('fiscal_all', lambda: run_all_fiscal_updates(DB_PATH)))

    def _api_fiscal_debt_projection(self):
        self.send_json(build_projection_payload(DB_PATH))

    def _api_fiscal_debt_projection_run(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length).decode('utf-8') if length else '{}'
            payload = json.loads(body or '{}')
            self.send_json(run_projection(DB_PATH, payload))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json({'success': False, 'data_status': 'scenario', 'error': str(exc)}, 400)

    def _api_status(self):
        with get_db() as conn:
            total   = conn.execute('SELECT COUNT(*) FROM monthly_data').fetchone()[0]
            raw_cnt = conn.execute('SELECT COUNT(*) FROM raw_pages').fetchone()[0]
            latest  = conn.execute('SELECT month,scraped_at,source_url FROM monthly_data ORDER BY month DESC LIMIT 1').fetchone()
            oldest  = conn.execute('SELECT month FROM monthly_data ORDER BY month LIMIT 1').fetchone()
            logs    = conn.execute('SELECT scraped_at,status,message,new_months FROM scrape_log ORDER BY id DESC LIMIT 10').fetchall()
        self.send_json({
            'months_in_db': total,
            'raw_pages_stored': raw_cnt,
            'latest_month': latest['month'] if latest else None,
            'oldest_month': oldest['month'] if oldest else None,
            'latest_source': latest['source_url'] if latest else None,
            'recent_logs': [dict(r) for r in logs],
        })

    def _api_abdc_data(self):
        try:
            with open(ABDC_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.send_json(data)
        except FileNotFoundError:
            self.send_json({'error': 'ABDC data file not found'}, 404)

    # ── ABDC A* Research Radar ──────────────────────────────────────────────
    def _query_params(self):
        from urllib.parse import parse_qs
        qs = urlparse(self.path).query
        return {k: v[0] for k, v in parse_qs(qs).items()}

    def _read_json_body(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length).decode('utf-8') if length else '{}'
            return json.loads(body or '{}')
        except Exception:
            return {}

    def _api_astar_articles(self):
        self.send_json(build_astar_articles_payload(self._query_params()))

    def _api_astar_recent(self):
        p = self._query_params()
        days = int(p.get('days', 7))
        related = str(p.get('related_only', '')).lower() in ('1', 'true', 'yes')
        self.send_json(build_astar_recent_payload(days, related))

    def _api_astar_digest(self):
        p = self._query_params()
        related = str(p.get('related_only', '')).lower() in ('1', 'true', 'yes')
        self.send_json(build_astar_digest_payload(p.get('period', 'this_week'), related))

    def _api_astar_trends(self):
        p = self._query_params()
        months = int(p.get('months', 18))
        related = str(p.get('related_only', '')).lower() in ('1', 'true', 'yes')
        self.send_json(build_astar_trends_payload(months, related))

    def _api_astar_update(self):
        body = self._read_json_body()
        mode = body.get('mode', 'recent')
        days = int(body.get('days', 30))
        version = body.get('abdc_version', 'latest')

        def _run():
            try:
                if mode == 'recent':
                    update_astar_recent_articles(days=days, version=version)
                else:
                    backfill_astar_articles(mode, journal=body.get('journal'), version=version,
                                            year=body.get('year'), since_year=body.get('since_year'))
                deduplicate_articles()
            except Exception as e:
                log.error(f'astar update 失败: {e}', exc_info=True)

        threading.Thread(target=_run, daemon=True).start()
        self.send_json({'status': 'started',
                        'message': f'A* 文章更新已启动 (mode={mode}, days={days})；'
                                   f'219 个 A* 期刊抓取约需数分钟，可轮询 /api/abdc/astar/debug 看进度'})

    def _api_astar_save(self):
        body = self._read_json_body()
        if not body.get('article_id'):
            self.send_json({'success': False, 'error': 'article_id required'}, 400)
            return
        self.send_json(save_article(
            body['article_id'], note=body.get('user_note'),
            reading_status=body.get('reading_status', 'to_read'),
            project_tag=body.get('project_tag')))

# ── 定时调度 ──────────────────────────────────────────────────────────────────
def scheduler_thread():
    SCHEDULE = ['09:00','14:00']
    log.info(f'调度器启动，每日 {" / ".join(SCHEDULE)} 自动爬取')
    while True:
        if datetime.now().strftime('%H:%M') in SCHEDULE:
            _run_update_job('pboc_scrape', scrape_and_update, blocking=True)
            time.sleep(61)
        time.sleep(30)


def astar_scheduler_thread(interval_hours=24):
    """A* 研究雷达持续更新：启动后等待 10 分钟，之后每 interval_hours 抓最近 14 天增量。
    顶刊发文较慢，每天一次足够（抓 14 天窗口留出漏跑余量，去重处理重复）。"""
    log.info(f'A* 雷达调度器启动，每 {interval_hours}h 增量抓取最近 14 天')
    time.sleep(600)   # 启动后先让位给首页/财政模块，10 分钟后再开始
    while True:
        try:
            r = update_astar_recent_articles(days=14)
            deduplicate_articles()
            log.info(f"A* 增量完成：新增 {r.get('articles_inserted')}，更新 {r.get('articles_updated')}")
        except Exception as e:
            log.warning(f'A* 增量抓取失败（稍后重试）: {e}')
        time.sleep(interval_hours * 3600)


def fiscal_scheduler_thread(interval_hours=168):
    """每周检查已接入的财政债务和央行相关官方来源；失败只写日志，不清空旧数据。"""
    log.info(f'财政债务监控调度器启动，每 {interval_hours}h 检查官方来源')
    time.sleep(1800)
    while True:
        try:
            result = _run_update_job('fiscal_all', lambda: run_all_fiscal_updates(DB_PATH), blocking=True)
            log.info(f"财政债务更新完成：status={result.get('status')}")
        except Exception as e:
            log.warning(f'财政债务更新失败（旧数据保留）: {e}')
        time.sleep(interval_hours * 3600)

# ── 入口 ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print('''
╔══════════════════════════════════════════════════════╗
║   研究工具集成服务  v3.0                             ║
║   http://localhost:5001                              ║
╠══════════════════════════════════════════════════════╣
║  GET  /              首页导航                        ║
║  GET  /dashboard     央行金融统计仪表板              ║
║  GET  /abdc          ABDC 期刊查询                   ║
╠══════════════════════════════════════════════════════╣
║  GET  /api/data      全量月度数据 JSON               ║
║  POST /api/scrape    触发全量历史爬取                 ║
║  GET  /api/status    状态 + 爬取日志                 ║
║  GET  /api/abdc/data ABDC 期刊数据 JSON              ║
╚══════════════════════════════════════════════════════╝
''')
    # 启动前检测端口：已有实例在跑就退出，避免 Windows 下多实例叠加导致路由错乱
    _probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _probe.settimeout(1)
    if _probe.connect_ex(('127.0.0.1', PORT)) == 0:
        _probe.close()
        print(f'\n⚠️  端口 {PORT} 已被占用 —— 服务可能已在运行。')
        print(f'   请先关闭已有窗口，或直接访问 http://localhost:{PORT}\n')
        sys.exit(1)
    _probe.close()

    init_db()
    _run_update_job('pboc_scrape', scrape_and_update)   # 后台启动，串行+不卡 HTTP
    threading.Thread(target=scheduler_thread, daemon=True).start()
    if os.environ.get('ASTAR_AUTO', '1') != '0':
        threading.Thread(target=astar_scheduler_thread, daemon=True).start()
    if os.environ.get('FISCAL_AUTO', '1') != '0':
        threading.Thread(target=fiscal_scheduler_thread, daemon=True).start()
    try:
        load_journal_prestige_lists()       # 填充 FT50 / UTD24 清单（轻量）
        ensure_prestige_extra_journals()    # 把非 A* 的 FT50/UTD24 刊持久并入追踪集
        load_journal_prestige_lists()       # 重算 in_astar_tracked
        cleanup_journal_doi_pollution()     # 隐藏 JAIS 等被混入的会议论文
        dedup_article_sources()             # 来源表去重 + 建唯一索引（幂等）
    except Exception as e:
        log.warning(f'prestige lists 载入失败: {e}')
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    log.info(f'服务启动 → http://localhost:{PORT}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info('服务已停止')
