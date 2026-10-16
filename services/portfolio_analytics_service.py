"""Privacy-conscious, local-only analytics for the public portfolio site."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import secrets
import sqlite3
from statistics import mean, median
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_analytics_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio_visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visited_at TEXT NOT NULL,
    visitor_hash TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    ip_prefix TEXT NOT NULL,
    path TEXT NOT NULL,
    page_title TEXT NOT NULL,
    referrer_host TEXT NOT NULL,
    user_agent TEXT NOT NULL,
    language TEXT NOT NULL,
    timezone TEXT NOT NULL,
    screen_width INTEGER,
    screen_height INTEGER,
    country_code TEXT NOT NULL,
    cf_ray TEXT NOT NULL,
    site TEXT NOT NULL DEFAULT 'portfolio',
    ip_address TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    region_code TEXT NOT NULL DEFAULT '',
    postal_code TEXT NOT NULL DEFAULT '',
    geo_timezone TEXT NOT NULL DEFAULT '',
    latitude TEXT NOT NULL DEFAULT '',
    longitude TEXT NOT NULL DEFAULT '',
    is_bot INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_portfolio_visits_time
    ON portfolio_visits(visited_at);
CREATE INDEX IF NOT EXISTS idx_portfolio_visits_visitor
    ON portfolio_visits(visitor_hash, visited_at);
CREATE TABLE IF NOT EXISTS portfolio_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    site TEXT NOT NULL,
    visitor_hash TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    path TEXT NOT NULL,
    event_name TEXT NOT NULL,
    event_target TEXT NOT NULL DEFAULT '',
    dwell_seconds INTEGER,
    country_code TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT 'remote'
);
CREATE INDEX IF NOT EXISTS idx_portfolio_events_time
    ON portfolio_events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_portfolio_events_name
    ON portfolio_events(site, event_name, occurred_at);
"""

# Events are a closed vocabulary: the browser cannot invent new dimensions by
# sending a different string, so the table stays readable without a cleanup pass.
EVENT_NAMES = {
    'portfolio': ('cv_download', 'outbound_click', 'contact_click',
                  'scroll_75', 'session_end', 'scroll_depth', 'engagement',
                  'internal_navigation'),
    'research': ('page_view', 'tab_view', 'data_export', 'outbound_click',
                 'session_end', 'scroll_depth', 'engagement', 'internal_navigation'),
}

# The research platform is used almost entirely by its owner on the loopback.
# Dropping those events, the way page views drop them, left the whole section
# permanently empty, so they are kept and labelled instead of discarded.
# 'automation' is a third kind of traffic, not a third place: a driven browser
# on the loopback would otherwise dominate the owner's own usage counts. One
# agent run produced 16 one-second sessions in 95 seconds against a single page.
EVENT_SCOPES = ('remote', 'local', 'automation')

ANALYTICS_DAYS = ('all', 1, 7, 30, 90, 365, 730, 1095, 1825)
ANALYTICS_SITES = ('all', 'portfolio', 'research')
ANALYTICS_VIEWS = ('visitor', 'diagnostics')

# Judged from the user agent on the server, because a page cannot be trusted to
# report this and `navigator.webdriver` is false in the agent browsers that
# actually generate the traffic. Real examples already in this database:
# AhrefsBot/7.0 and HeadlessChrome/146.0.0.0 both counted as portfolio visitors.
AGENT_MARKERS = (
    'claude/', 'headlesschrome', 'playwright', 'puppeteer', 'selenium',
    'webdriver', 'phantomjs', 'bot', 'crawler', 'spider', 'scrapy',
    'curl/', 'wget/', 'python-requests', 'httpx', 'go-http-client',
)

# A Research HTML request is logged before browser JavaScript runs, so it is a
# request hit rather than proof that a person rendered the page. A nearby
# remote ``page_view`` event confirms a browser; strict multi-prefix bursts are
# separated as suspected automation without rewriting the raw visit table.
BROWSER_CONFIRMATION_SECONDS = 180
BURST_MIN_REQUESTS = 12
BURST_MIN_NETWORK_PREFIXES = 3
BURST_MIN_USER_AGENTS = 6
SELF_REFERRER_HOSTS = {
    'zhengresearch.com', 'www.zhengresearch.com',
    'research.zhengresearch.com',
}


def is_automated_agent(user_agent: str) -> bool:
    """True when the user agent identifies a crawler or a driven browser."""
    lowered = str(user_agent or '').lower()
    return any(marker in lowered for marker in AGENT_MARKERS)


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30)
    try:
        return _prepare(connection)
    except Exception:
        connection.close()
        raise


def _prepare(connection: sqlite3.Connection) -> sqlite3.Connection:
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    columns = {
        row['name'] for row in connection.execute('PRAGMA table_info(portfolio_visits)')
    }
    if 'site' not in columns:
        connection.execute(
            "ALTER TABLE portfolio_visits ADD COLUMN site TEXT NOT NULL DEFAULT 'portfolio'"
        )
    geo_columns = {
        'ip_address': "TEXT NOT NULL DEFAULT ''",
        'city': "TEXT NOT NULL DEFAULT ''",
        'region': "TEXT NOT NULL DEFAULT ''",
        'region_code': "TEXT NOT NULL DEFAULT ''",
        'postal_code': "TEXT NOT NULL DEFAULT ''",
        'geo_timezone': "TEXT NOT NULL DEFAULT ''",
        'latitude': "TEXT NOT NULL DEFAULT ''",
        'longitude': "TEXT NOT NULL DEFAULT ''",
        'is_bot': 'INTEGER NOT NULL DEFAULT 0',
    }
    for name, definition in geo_columns.items():
        if name not in columns:
            connection.execute(
                f'ALTER TABLE portfolio_visits ADD COLUMN {name} {definition}'
            )
    if 'is_bot' not in columns:
        # The user agent was stored all along, so history can be classified
        # rather than guessed at: rows already collected keep their real nature.
        connection.executemany(
            'UPDATE portfolio_visits SET is_bot=1 WHERE id=?',
            [(row['id'],) for row in connection.execute(
                'SELECT id, user_agent FROM portfolio_visits')
             if is_automated_agent(row['user_agent'])],
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_portfolio_visits_site_time "
        "ON portfolio_visits(site, visited_at)"
    )
    event_columns = {
        row['name'] for row in connection.execute('PRAGMA table_info(portfolio_events)')
    }
    if 'scope' not in event_columns:
        connection.execute(
            "ALTER TABLE portfolio_events ADD COLUMN scope TEXT NOT NULL DEFAULT 'remote'"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_portfolio_events_scope "
        "ON portfolio_events(scope, occurred_at)"
    )
    connection.commit()
    return connection


def _database_salt(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT value FROM portfolio_analytics_meta WHERE key='visitor_salt'"
    ).fetchone()
    if row:
        return row['value']
    salt = secrets.token_hex(32)
    connection.execute(
        "INSERT INTO portfolio_analytics_meta(key, value) VALUES('visitor_salt', ?)",
        (salt,),
    )
    return salt


def _bounded_text(value, limit: int) -> str:
    return str(value or '').strip()[:limit]


def _ip_prefix(client_ip: str) -> str:
    try:
        address = ipaddress.ip_address(str(client_ip).split('%', 1)[0])
        if isinstance(address, ipaddress.IPv4Address):
            return str(ipaddress.ip_network(f'{address}/24', strict=False))
        return str(ipaddress.ip_network(f'{address}/48', strict=False))
    except ValueError:
        return 'unknown'


def _referrer_host(value) -> str:
    try:
        return _bounded_text(urlparse(str(value or '')).hostname or '', 255)
    except ValueError:
        return ''


def _outbound_target(value: str) -> str:
    """Reduce an outbound URL to host + path, dropping query and fragment."""
    try:
        parsed = urlparse(value if '//' in value else f'//{value}')
    except ValueError:
        return ''
    host = _bounded_text(parsed.hostname or '', 255)
    if not host:
        return ''
    return _bounded_text(host + (parsed.path or '').rstrip('/'), 255)


def _hash(salt: str, value: str) -> str:
    return hashlib.sha256(f'{salt}:{value}'.encode('utf-8')).hexdigest()[:24]


def record_portfolio_visit(db_path: str, payload: dict, client_ip: str,
                           user_agent: str = '', country_code: str = '',
                           cf_ray: str = '', site: str = 'portfolio',
                           geo: dict | None = None) -> dict:
    """Validate and store one page view, deduplicated for thirty minutes."""
    if not isinstance(payload, dict):
        raise ValueError('request body must be a JSON object')
    site = _bounded_text(site, 32).lower()
    if site not in {'portfolio', 'research'}:
        raise ValueError('invalid analytics site')
    geo = geo if isinstance(geo, dict) else {}
    path = _bounded_text(payload.get('path') or '/', 512)
    if not path.startswith('/') or path.startswith('//'):
        raise ValueError('invalid page path')
    session_id = _bounded_text(payload.get('session_id'), 128)
    if not session_id:
        raise ValueError('session_id is required')

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=30)).isoformat(timespec='seconds')
    with closing(_connect(db_path)) as connection:
        salt = _database_salt(connection)
        visitor_hash = _hash(salt, str(client_ip))
        session_hash = _hash(salt, session_id)
        duplicate = connection.execute(
            """SELECT 1 FROM portfolio_visits
               WHERE site=? AND visitor_hash=? AND session_hash=? AND path=? AND visited_at>=?
               LIMIT 1""",
            (site, visitor_hash, session_hash, path, cutoff),
        ).fetchone()
        if duplicate:
            return {'accepted': True, 'recorded': False, 'reason': 'deduplicated'}

        try:
            width = max(0, min(20000, int(payload.get('screen_width') or 0))) or None
            height = max(0, min(20000, int(payload.get('screen_height') or 0))) or None
        except (TypeError, ValueError):
            width = height = None
        connection.execute(
            """INSERT INTO portfolio_visits(
                   visited_at, visitor_hash, session_hash, ip_prefix, path,
                   page_title, referrer_host, user_agent, language, timezone,
                   screen_width, screen_height, country_code, cf_ray, site,
                   ip_address, city, region, region_code, postal_code,
                   geo_timezone, latitude, longitude, is_bot)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now.isoformat(timespec='seconds'), visitor_hash, session_hash,
                _ip_prefix(client_ip), path,
                _bounded_text(payload.get('title'), 255),
                _referrer_host(payload.get('referrer')),
                _bounded_text(user_agent, 768),
                _bounded_text(payload.get('language'), 64),
                _bounded_text(payload.get('timezone'), 128),
                width, height,
                _bounded_text(country_code, 2).upper(),
                _bounded_text(cf_ray, 128),
                site,
                _bounded_text(client_ip, 64),
                _bounded_text(geo.get('city'), 128),
                _bounded_text(geo.get('region'), 128),
                _bounded_text(geo.get('region_code'), 32),
                _bounded_text(geo.get('postal_code'), 32),
                _bounded_text(geo.get('timezone'), 128),
                _bounded_text(geo.get('latitude'), 32),
                _bounded_text(geo.get('longitude'), 32),
                1 if is_automated_agent(user_agent) else 0,
            ),
        )
        connection.commit()
    return {'accepted': True, 'recorded': True}


def record_portfolio_event(db_path: str, payload: dict, client_ip: str,
                           country_code: str = '', site: str = 'portfolio',
                           scope: str = 'remote') -> dict:
    """Validate and store one whitelisted interaction event.

    Events deliberately carry no IP, user agent or coordinates. They are linked
    to their page view through ``session_hash``, so the behavioural trail does
    not duplicate the identifying fields already held by ``portfolio_visits``.
    """
    if not isinstance(payload, dict):
        raise ValueError('request body must be a JSON object')
    site = _bounded_text(site, 32).lower()
    if site not in EVENT_NAMES:
        raise ValueError('invalid analytics site')
    scope = _bounded_text(scope, 16).lower()
    if scope not in EVENT_SCOPES:
        raise ValueError('invalid analytics scope')
    event_name = _bounded_text(payload.get('event'), 64)
    if event_name not in EVENT_NAMES[site]:
        raise ValueError('unknown event name')
    session_id = _bounded_text(payload.get('session_id'), 128)
    if not session_id:
        raise ValueError('session_id is required')
    path = _bounded_text(payload.get('path') or '/', 512)
    if not path.startswith('/') or path.startswith('//'):
        raise ValueError('invalid page path')

    target = _bounded_text(payload.get('target'), 255)
    if event_name == 'outbound_click':
        # Host plus path: enough to tell which project was opened, without the
        # query string, which is the part that carries identifiers.
        target = _outbound_target(target)
    elif event_name == 'scroll_depth':
        if target not in {'25', '50', '75', '90'}:
            raise ValueError('invalid scroll depth')
    elif event_name == 'internal_navigation':
        target = target.split('?', 1)[0].split('#', 1)[0]
        if not target.startswith('/') or target.startswith('//') or '\\' in target:
            raise ValueError('invalid navigation target')
    dwell = None
    if event_name in {'session_end', 'engagement'}:
        try:
            dwell = max(0, min(86400, int(payload.get('dwell_seconds') or 0)))
        except (TypeError, ValueError, OverflowError):
            dwell = None
    if event_name == 'engagement':
        page_id = str(payload.get('page_id') or '')
        if not re.fullmatch(r'[a-zA-Z0-9-]{8,80}', page_id) or not dwell:
            raise ValueError('engagement requires a page id and positive visible seconds')

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=30)).isoformat(timespec='seconds')
    with closing(_connect(db_path)) as connection:
        salt = _database_salt(connection)
        visitor_hash = _hash(salt, str(client_ip))
        session_hash = _hash(salt, session_id)
        if event_name == 'engagement':
            # Append cumulative checkpoints. Never overwrite previous raw rows.
            # This per-load random key is not a persistent user identifier and
            # is omitted from the filtered API and dashboard.
            target = 'foreground-v1:' + _hash(salt, page_id)
        duplicate = connection.execute(
            """SELECT 1 FROM portfolio_events
               WHERE site=? AND visitor_hash=? AND session_hash=? AND scope=?
                 AND path=? AND event_name=? AND event_target=?
                 AND (? <> 'engagement' OR dwell_seconds >= ?)
                 AND occurred_at>=?
               LIMIT 1""",
            (site, visitor_hash, session_hash, scope, path, event_name, target,
             event_name, dwell, cutoff),
        ).fetchone()
        if duplicate:
            return {'accepted': True, 'recorded': False, 'reason': 'deduplicated'}

        connection.execute(
            """INSERT INTO portfolio_events(
                   occurred_at, site, visitor_hash, session_hash, path,
                   event_name, event_target, dwell_seconds, country_code, scope)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now.isoformat(timespec='seconds'), site, visitor_hash,
                session_hash, path, event_name, target, dwell,
                _bounded_text(country_code, 2).upper(), scope,
            ),
        )
        connection.commit()
    return {'accepted': True, 'recorded': True}


def _count(connection, where='1=1', parameters=()):
    return connection.execute(
        f"SELECT COUNT(*) AS views, COUNT(DISTINCT visitor_hash) AS visitors "
        f"FROM portfolio_visits WHERE is_bot=0 AND ({where})", parameters
    ).fetchone()


def _group(connection, field: str, limit=10):
    rows = connection.execute(
        f"""SELECT {field} AS label, COUNT(*) AS views,
                   COUNT(DISTINCT visitor_hash) AS visitors
            FROM portfolio_visits WHERE is_bot=0
            GROUP BY {field}
            ORDER BY views DESC, label ASC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _bot_summary(connection, limit=10):
    """Crawlers are kept and shown, just never counted as visitors."""
    rows = connection.execute(
        """SELECT user_agent AS label, site, COUNT(*) AS views,
                  MAX(visited_at) AS last_seen
           FROM portfolio_visits WHERE is_bot=1
           GROUP BY user_agent, site
           ORDER BY views DESC, label ASC LIMIT ?""",
        (limit,),
    ).fetchall()
    total = connection.execute(
        'SELECT COUNT(*) AS views FROM portfolio_visits WHERE is_bot=1').fetchone()
    return {'total': dict(total), 'agents': [dict(row) for row in rows]}


def _event_group(connection, field: str, limit=15, where='1=1', parameters=()):
    rows = connection.execute(
        f"""SELECT {field} AS label, COUNT(*) AS events,
                   COUNT(DISTINCT visitor_hash) AS visitors
            FROM portfolio_events WHERE {where}
            GROUP BY {field}
            ORDER BY events DESC, label ASC LIMIT ?""",
        (*parameters, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _dwell_summary(connection):
    """Median plus mean, because a single long read skews the mean on low traffic."""
    return _filtered_dwell(connection, '1=1', ())


def _build_legacy_analytics(db_path: str) -> dict:
    """Return the pre-filter payload for callers that still use the old API."""
    now = datetime.now(timezone.utc)
    with closing(_connect(db_path)) as connection:
        total = _count(connection)
        today = _count(connection, 'visited_at >= ?', (
            now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),))
        last_7d = _count(connection, 'visited_at >= ?', (
            (now - timedelta(days=7)).isoformat(timespec='seconds'),))
        last_30d = _count(connection, 'visited_at >= ?', (
            (now - timedelta(days=30)).isoformat(timespec='seconds'),))
        daily = [dict(row) for row in connection.execute(
            """SELECT substr(visited_at, 1, 10) AS date, COUNT(*) AS views,
                      COUNT(DISTINCT visitor_hash) AS visitors
               FROM portfolio_visits WHERE is_bot=0
               GROUP BY substr(visited_at, 1, 10)
               ORDER BY date DESC LIMIT 30"""
        ).fetchall()]
        events_total = connection.execute(
            """SELECT COUNT(*) AS events, COUNT(DISTINCT visitor_hash) AS visitors
               FROM portfolio_events"""
        ).fetchone()
        recent_events = [dict(row) for row in connection.execute(
            """SELECT occurred_at, site, scope, visitor_hash, path, event_name,
                      event_target, dwell_seconds, country_code
               FROM portfolio_events ORDER BY id DESC LIMIT 50"""
        ).fetchall()]
        recent = [dict(row) for row in connection.execute(
            """SELECT visited_at, site, visitor_hash, ip_address, ip_prefix,
                      path, referrer_host, country_code, city, region,
                      region_code, postal_code, geo_timezone, latitude,
                      longitude, language, timezone, screen_width,
                      screen_height, user_agent, is_bot
               FROM portfolio_visits ORDER BY id DESC LIMIT 100"""
        ).fetchall()]
        return {
            'generated_at': now.isoformat(timespec='seconds'),
            'retention_days': None,
            'retention_policy': 'permanent',
            'overview': {
                'total': dict(total), 'today': dict(today),
                'last_7d': dict(last_7d), 'last_30d': dict(last_30d),
            },
            'daily': daily,
            'sites': _group(connection, 'site'),
            'pages': _group(connection, "site || ': ' || path"),
            'referrers': _group(connection, 'referrer_host'),
            'countries': _group(connection, 'country_code'),
            'bots': _bot_summary(connection),
            'recent': recent,
            'events': {
                'total': dict(events_total),
                'by_scope': _event_group(connection, 'scope'),
                'by_name': _event_group(
                    connection, "scope || ' · ' || site || ': ' || event_name", 20),
                'targets': _event_group(
                    connection, "event_name || ' · ' || event_target", 20,
                    where="event_target <> ''"),
                'dwell': _dwell_summary(connection),
                'recent': recent_events,
            },
        }


def validate_analytics_filters(days=30, site='all', view='visitor', tz=None) -> dict:
    """Validate the dashboard filter contract before any SQL is assembled."""
    if isinstance(days, str) and days.strip().lower() == 'all':
        days = 'all'
    else:
        if isinstance(days, bool):
            raise ValueError('days must be 1, 7, 30, 90, 365, 730, 1095, 1825, or all')
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise ValueError(
                'days must be 1, 7, 30, 90, 365, 730, 1095, 1825, or all') from None
    if days not in ANALYTICS_DAYS:
        raise ValueError('days must be 1, 7, 30, 90, 365, 730, 1095, 1825, or all')
    site = str(site or '').strip().lower()
    if site not in ANALYTICS_SITES:
        raise ValueError('site must be all, portfolio, or research')
    view = str(view or '').strip().lower()
    if view not in ANALYTICS_VIEWS:
        raise ValueError('view must be visitor or diagnostics')
    filters = {'days': days, 'site': site, 'view': view}
    if tz is not None:
        tz = str(tz).strip()
        try:
            if not tz or len(tz) > 128:
                raise ValueError
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('tz must be a valid IANA timezone, such as America/Denver') from None
        filters['tz'] = tz
    return filters


def _analytics_start(now, days, reporting_tz):
    """Use calendar days in the reporting zone, including the current day."""
    if days == 'all':
        return None
    midnight = now.astimezone(reporting_tz).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=days - 1)


def _filter_clause(column, now, days, site, extra=(), reporting_tz=timezone.utc):
    # Stored collection timestamps are UTC. Compare UTC strings on both sides
    # so local midnight and daylight-saving transitions use the time index.
    conditions = [f'{column} <= ?']
    parameters = [now.astimezone(timezone.utc).isoformat(timespec='seconds')]
    if days != 'all':
        conditions.append(f'{column} >= ?')
        cutoff = _analytics_start(now, days, reporting_tz)
        parameters.append(cutoff.astimezone(timezone.utc).isoformat(timespec='seconds'))
    if site != 'all':
        conditions.append('site = ?')
        parameters.append(site)
    conditions.extend(extra)
    return ' AND '.join(conditions) or '1=1', tuple(parameters)


def _safe_user_agent_summary(user_agent, is_bot=False):
    """Keep only a coarse diagnostic label; never return the raw UA string."""
    value = str(user_agent or '')
    lowered = value.lower()
    if is_bot or is_automated_agent(value):
        browser = '自动化/爬虫'
    elif 'edg/' in lowered:
        browser = 'Edge'
    elif 'chrome/' in lowered:
        browser = 'Chrome'
    elif 'firefox/' in lowered:
        browser = 'Firefox'
    elif 'safari/' in lowered:
        browser = 'Safari'
    elif 'opera' in lowered or 'opr/' in lowered:
        browser = 'Opera'
    else:
        browser = '其他浏览器'
    if any(token in lowered for token in ('mobile', 'iphone', 'android')):
        device = '移动设备'
    elif 'ipad' in lowered or 'tablet' in lowered:
        device = '平板设备'
    elif value:
        device = '桌面设备'
    else:
        device = '未知设备'
    return f'{browser} · {device}'


def _safe_coordinate_summary(latitude, longitude):
    """Return a deliberately coarse diagnostic-only coordinate label.

    IP geolocation is not GPS. Rounding to one decimal place keeps the roughly
    0.1-degree location useful for diagnostics without returning raw coordinates.
    """
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return ''
    if (not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        return ''
    return f'{lat:.1f}, {lon:.1f}（约 0.1°）'


def _safe_visit_row(row, diagnostics=False):
    result = {
        'visited_at': row['visited_at'],
        'site': row['site'],
        'path': row['path'],
        'referrer_host': row['referrer_host'] or '',
        'country_code': row['country_code'] or '',
        'city': row['city'] or '',
        'region': row['region_code'] or row['region'] or '',
        'is_bot': bool(row['is_bot']),
        'automation': bool(row['is_bot']),
        'traffic_class': row.get(
            'traffic_class', 'known_bot' if row['is_bot'] else 'unknown_request'),
        'classification_reasons': row.get('classification_reasons', []),
    }
    if diagnostics:
        result.update({
            'ip_prefix': row['ip_prefix'] or 'unknown',
            'user_agent_summary': _safe_user_agent_summary(
                row['user_agent'], row['is_bot']),
            'language': row['language'] or '',
            'timezone': row['timezone'] or '',
            'coordinates_approx': _safe_coordinate_summary(
                row['latitude'], row['longitude']),
        })
    return result


def _parse_analytics_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _classify_filtered_visits(connection, where, parameters):
    """Classify request hits without mutating permanently retained rows."""
    rows = [dict(row) for row in connection.execute(
        f"""SELECT id, visited_at, site, visitor_hash, path, referrer_host,
                   country_code, city, region, region_code, is_bot, ip_prefix,
                   user_agent, language, timezone, screen_width, screen_height,
                   latitude, longitude, cf_ray
            FROM portfolio_visits WHERE {where}
            ORDER BY id DESC""", parameters).fetchall()]

    confirmations = defaultdict(list)
    for event in connection.execute(
            """SELECT visitor_hash, path, occurred_at
               FROM portfolio_events
               WHERE site='research' AND scope='remote' AND event_name='page_view'"""):
        occurred_at = _parse_analytics_time(event['occurred_at'])
        if occurred_at is not None:
            confirmations[(event['visitor_hash'], event['path'])].append(occurred_at)

    pending_groups = defaultdict(list)
    for row in rows:
        reasons = []
        if row['is_bot']:
            row['traffic_class'] = 'known_bot'
            reasons.append('recognized_user_agent')
        elif row['site'] == 'portfolio':
            row['traffic_class'] = 'confirmed_browser'
            reasons.append('browser_collector_request')
        else:
            visited_at = _parse_analytics_time(row['visited_at'])
            matched = False
            if visited_at is not None:
                matched = any(
                    abs((occurred_at - visited_at).total_seconds())
                    <= BROWSER_CONFIRMATION_SECONDS
                    for occurred_at in confirmations.get(
                        (row['visitor_hash'], row['path']), ())
                )
            if matched:
                row['traffic_class'] = 'confirmed_browser'
                reasons.append('nearby_client_page_view')
            else:
                row['traffic_class'] = 'unknown_request'
                reasons.append('no_client_page_view')
                minute = str(row['visited_at'])[:16]
                key = (minute, row['site'], row['path'], row['referrer_host'] or '')
                pending_groups[key].append(row)
        row['classification_reasons'] = reasons

    suspected_clusters = []
    for key, grouped_rows in pending_groups.items():
        prefixes = {row['ip_prefix'] for row in grouped_rows if row['ip_prefix']}
        user_agents = {row['user_agent'] for row in grouped_rows if row['user_agent']}
        missing_signals = sum(
            not row['screen_width'] and not row['screen_height'] and not row['timezone']
            for row in grouped_rows
        )
        if not (
            len(grouped_rows) >= BURST_MIN_REQUESTS
            and len(prefixes) >= BURST_MIN_NETWORK_PREFIXES
            and len(user_agents) >= BURST_MIN_USER_AGENTS
            and missing_signals / len(grouped_rows) >= .8
        ):
            continue
        for row in grouped_rows:
            row['traffic_class'] = 'suspected_automation'
            row['classification_reasons'] = [
                'distributed_minute_burst', 'no_client_page_view',
                'missing_browser_signals', 'rotating_user_agents',
            ]
        minute, grouped_site, path, referrer = key
        suspected_clusters.append({
            'minute': minute,
            'site': grouped_site,
            'path': path,
            'referrer_host': referrer,
            'requests': len(grouped_rows),
            'network_prefixes': len(prefixes),
            'user_agents': len(user_agents),
            'reason': 'distributed_minute_burst',
        })
    suspected_clusters.sort(
        key=lambda item: (item['minute'], item['requests']), reverse=True)
    return rows, suspected_clusters[:25]


def _visit_count_from_rows(rows):
    return {
        'views': len(rows),
        'visitors': len({row['visitor_hash'] for row in rows}),
    }


def _visit_groups_from_rows(rows):
    expressions = {
        'sites': lambda row: row['site'],
        'pages': lambda row: f"{row['site']}: {row['path']}",
        'referrers': lambda row: (
            'Direct / Unknown' if not row['referrer_host'] else
            'Internal / Self' if row['referrer_host'].lower() in SELF_REFERRER_HOSTS else
            row['referrer_host']),
        'countries': lambda row: row['country_code'] or 'Unknown',
    }
    result = {}
    for name, label_for in expressions.items():
        grouped = defaultdict(lambda: {'views': 0, 'visitors': set()})
        for row in rows:
            label = label_for(row)
            grouped[label]['views'] += 1
            grouped[label]['visitors'].add(row['visitor_hash'])
        result[name] = sorted(({
            'label': label,
            'views': values['views'],
            'visitors': len(values['visitors']),
        } for label, values in grouped.items()),
            key=lambda item: (-item['views'], item['label']))[:15]
    return result


def _traffic_quality(rows):
    result = {}
    for traffic_class in (
            'confirmed_browser', 'suspected_automation', 'known_bot', 'unknown_request'):
        result[traffic_class] = _visit_count_from_rows([
            row for row in rows if row['traffic_class'] == traffic_class])
    result['raw_requests'] = _visit_count_from_rows(rows)
    return result


def _filtered_daily_from_rows(connection, rows, event_where, event_parameters,
                              reporting_tz, start, now):
    daily = {}

    def bucket_for(timestamp):
        parsed = _parse_analytics_time(timestamp)
        if parsed is None:
            return None
        day = parsed.astimezone(reporting_tz).date().isoformat()
        return daily.setdefault(day, {
            'date': day, 'views': 0, '_visitors': set(), 'events': 0})

    for row in rows:
        bucket = bucket_for(row['visited_at'])
        if bucket is not None:
            bucket['views'] += 1
            bucket['_visitors'].add(row['visitor_hash'])
    for row in connection.execute(
            f'SELECT occurred_at FROM portfolio_events WHERE {event_where}',
            event_parameters):
        bucket = bucket_for(row['occurred_at'])
        if bucket is not None:
            bucket['events'] += 1
    for bucket in daily.values():
        bucket['visitors'] = len(bucket.pop('_visitors'))
    first = start.date() if start is not None else (
        datetime.fromisoformat(min(daily)).date() if daily else None)
    if first is None:
        return []
    last = now.astimezone(reporting_tz).date()
    # A missing date means no collected records, not proof of zero actual
    # visitors or continuous collection availability. The UI states this.
    return [daily.get(day.isoformat(), {
        'date': day.isoformat(), 'views': 0, 'visitors': 0, 'events': 0})
        for day in (first + timedelta(days=offset)
                    for offset in range((last - first).days + 1))]


def _safe_event_row(row, diagnostics=False):
    result = {
        'occurred_at': row['occurred_at'],
        'site': row['site'],
        'scope': row['scope'],
        'path': row['path'],
        'event_name': row['event_name'],
        'event_target': ('' if row['event_name'] == 'engagement'
                         else row['event_target'] or ''),
        'dwell_seconds': row['dwell_seconds'],
        'country_code': row['country_code'] or '',
    }
    if diagnostics:
        result['scope_label'] = {
            'remote': '外部', 'local': '本机', 'automation': '自动化'
        }.get(row['scope'], row['scope'])
    return result


def _filtered_visit_count(connection, where, parameters):
    row = connection.execute(
        f"SELECT COUNT(*) AS views, COUNT(DISTINCT visitor_hash) AS visitors "
        f"FROM portfolio_visits WHERE {where}", parameters).fetchone()
    return dict(row)


def _filtered_event_count(connection, where, parameters):
    row = connection.execute(
        f"SELECT COUNT(*) AS events, COUNT(DISTINCT visitor_hash) AS visitors "
        f"FROM portfolio_events WHERE {where}", parameters).fetchone()
    return dict(row)


def _filtered_visit_groups(connection, where, parameters):
    groups = {
        'sites': 'site',
        'pages': "site || ': ' || path",
        'referrers': "CASE WHEN referrer_host = '' THEN 'Direct / Unknown' ELSE referrer_host END",
        'countries': "CASE WHEN country_code = '' THEN 'Unknown' ELSE country_code END",
    }
    result = {}
    for name, expression in groups.items():
        rows = connection.execute(
            f"""SELECT {expression} AS label, COUNT(*) AS views,
                       COUNT(DISTINCT visitor_hash) AS visitors
                FROM portfolio_visits WHERE {where}
                GROUP BY {expression}
                ORDER BY views DESC, label ASC LIMIT 15""",
            parameters).fetchall()
        result[name] = [dict(row) for row in rows]
    return result


def _filtered_event_groups(connection, where, parameters):
    by_scope = connection.execute(
        f"""SELECT scope AS label, COUNT(*) AS events,
                   COUNT(DISTINCT visitor_hash) AS visitors
            FROM portfolio_events WHERE {where}
            GROUP BY scope ORDER BY events DESC, label ASC""",
        parameters).fetchall()
    by_name = connection.execute(
        f"""SELECT scope || ' · ' || site || ': ' || event_name AS label,
                   COUNT(*) AS events, COUNT(DISTINCT visitor_hash) AS visitors
            FROM portfolio_events WHERE {where}
            GROUP BY scope, site, event_name
            ORDER BY events DESC, label ASC LIMIT 20""",
        parameters).fetchall()
    targets = connection.execute(
        f"""SELECT event_name || ' · ' || event_target AS label,
                   COUNT(*) AS events, COUNT(DISTINCT visitor_hash) AS visitors
            FROM portfolio_events WHERE {where} AND event_target <> ''
                AND event_name <> 'engagement'
            GROUP BY event_name, event_target
            ORDER BY events DESC, label ASC LIMIT 20""",
        parameters).fetchall()
    return {
        'by_scope': [dict(row) for row in by_scope],
        'by_name': [dict(row) for row in by_name],
        'targets': [dict(row) for row in targets],
    }


def _filtered_dwell(connection, where, parameters):
    dwell_where = f"{where} AND event_name='session_end' AND dwell_seconds IS NOT NULL"
    row = connection.execute(
        f"SELECT COUNT(*) AS sessions, AVG(dwell_seconds) AS mean_seconds "
        f"FROM portfolio_events WHERE {dwell_where}", parameters).fetchone()
    sessions = row['sessions'] or 0
    median = None
    if sessions:
        middle_rows = connection.execute(
            f"SELECT dwell_seconds FROM portfolio_events WHERE {dwell_where} "
            "ORDER BY dwell_seconds LIMIT ? OFFSET ?",
            (*parameters, 2 if sessions % 2 == 0 else 1,
             (sessions - 1) // 2)).fetchall()
        median = sum(item['dwell_seconds'] for item in middle_rows) / len(middle_rows)
    mean = row['mean_seconds']
    return {
        'sessions': sessions,
        'mean_seconds': round(mean, 1) if mean is not None else None,
        'median_seconds': median,
    }


def _filtered_behavior(connection, where, parameters):
    """Keep new visible-time samples separate from legacy first-hide dwell.

    Each selected page-load sample contributes its largest cumulative report,
    not the sum of its checkpoints. A selected time window includes reports
    received within that window, not a proration of time spent on each day.
    """
    samples = [row['seconds'] for row in connection.execute(
        f"""SELECT MAX(dwell_seconds) AS seconds FROM portfolio_events
            WHERE {where} AND event_name='engagement'
                AND event_target LIKE 'foreground-v1:%'
            GROUP BY site, visitor_hash, session_hash, scope, path, event_target""",
        parameters).fetchall() if row['seconds'] is not None]
    depths = [dict(row) for row in connection.execute(
        f"""SELECT event_target AS label, COUNT(*) AS events,
                   COUNT(DISTINCT visitor_hash) AS visitors
            FROM portfolio_events WHERE {where} AND event_name='scroll_depth'
            GROUP BY event_target ORDER BY CAST(event_target AS INTEGER)""",
        parameters).fetchall()]
    navigation = _event_group(
        connection, "path || ' → ' || event_target", limit=10,
        where=f"{where} AND event_name='internal_navigation'", parameters=parameters)
    return {
        'foreground': {
            'samples': len(samples),
            'mean_seconds': round(mean(samples), 1) if samples else None,
            'median_seconds': median(samples) if samples else None,
            'over_30_seconds': sum(value >= 30 for value in samples),
        },
        'scroll_depth': depths,
        'navigation': navigation,
        'basis': 'visible_time_cumulative_max_per_page_load; reports_in_selected_range',
    }


def _filtered_daily(connection, visit_where, visit_parameters, event_where,
                    event_parameters):
    rows = connection.execute(
        f"""SELECT substr(visited_at, 1, 10) AS date, COUNT(*) AS views,
                   COUNT(DISTINCT visitor_hash) AS visitors
            FROM portfolio_visits WHERE {visit_where}
            GROUP BY substr(visited_at, 1, 10) ORDER BY date ASC""",
        visit_parameters).fetchall()
    daily = {row['date']: dict(row) for row in rows}
    event_rows = connection.execute(
        f"""SELECT substr(occurred_at, 1, 10) AS date, COUNT(*) AS events
            FROM portfolio_events WHERE {event_where}
            GROUP BY substr(occurred_at, 1, 10)""",
        event_parameters).fetchall()
    for row in event_rows:
        daily.setdefault(row['date'], {'date': row['date'], 'views': 0,
                                       'visitors': 0})['events'] = row['events']
    # The selected range still controls inclusion; the chart itself remains a
    # readable simple 30-day trend even when the operator selects 90/365 days.
    return [daily[key] for key in sorted(daily)[-30:]]


def _filtered_bot_summary(connection, where, parameters):
    rows = connection.execute(
        f"""SELECT site, COUNT(*) AS views, MAX(visited_at) AS last_seen,
                   user_agent, ip_prefix
            FROM portfolio_visits WHERE {where} AND is_bot=1
            GROUP BY site, user_agent, ip_prefix
            ORDER BY views DESC, last_seen DESC LIMIT 15""",
        parameters).fetchall()
    total = connection.execute(
        f"SELECT COUNT(*) AS views FROM portfolio_visits WHERE {where} AND is_bot=1",
        parameters).fetchone()
    return {
        'total': dict(total),
        'agents': [{
            'site': row['site'], 'views': row['views'],
            'last_seen': row['last_seen'], 'ip_prefix': row['ip_prefix'],
            'user_agent_summary': _safe_user_agent_summary(row['user_agent'], True),
        } for row in rows],
    }


def _build_filtered_analytics(db_path: str, filters: dict) -> dict:
    now = datetime.now(timezone.utc)
    days, site, view = filters['days'], filters['site'], filters['view']
    timezone_name = filters.get('tz', 'UTC')
    reporting_tz = ZoneInfo(timezone_name)
    start = _analytics_start(now, days, reporting_tz)
    diagnostic_visit_where, diagnostic_visit_params = _filter_clause(
        'visited_at', now, days, site, reporting_tz=reporting_tz)
    if view == 'visitor':
        event_where, event_params = _filter_clause(
            'occurred_at', now, days, site, ("scope='remote'",), reporting_tz)
        diagnostic = False
    else:
        event_where, event_params = _filter_clause(
            'occurred_at', now, days, site, reporting_tz=reporting_tz)
        diagnostic = True

    with closing(_connect(db_path)) as connection:
        all_visit_rows, suspected_clusters = _classify_filtered_visits(
            connection, diagnostic_visit_where, diagnostic_visit_params)
        traffic_quality = _traffic_quality(all_visit_rows)
        displayed_visit_rows = (all_visit_rows if diagnostic else [
            row for row in all_visit_rows
            if row['traffic_class'] == 'confirmed_browser'
        ])
        page_views = _visit_count_from_rows(displayed_visit_rows)
        external = _filtered_event_count(connection, event_where, event_params)
        groups = _visit_groups_from_rows(displayed_visit_rows)
        event_groups = _filtered_event_groups(connection, event_where, event_params)
        daily = _filtered_daily_from_rows(
            connection, displayed_visit_rows, event_where, event_params,
            reporting_tz, start, now)
        recent_visits = [
            _safe_visit_row(row, diagnostics=diagnostic)
            for row in displayed_visit_rows[:100]
        ]
        recent_events = [
            _safe_event_row(row, diagnostics=diagnostic) for row in connection.execute(
                f"""SELECT occurred_at, site, scope, path, event_name,
                           event_target, dwell_seconds, country_code
                    FROM portfolio_events WHERE {event_where}
                    ORDER BY id DESC LIMIT 50""", event_params).fetchall()
        ]
        top_page = groups['pages'][0] if groups['pages'] else None
        top_referrer = groups['referrers'][0] if groups['referrers'] else None
        trend_days = sum(bool(row['views'] or row['events']) for row in daily)
        trend = {
            'window_days': len(daily),
            'sample_days': trend_days,
            'status': 'ok' if trend_days else 'empty',
            'message': '' if trend_days else '所选期间暂无采集记录',
        }
        if diagnostic:
            overview = {
                'page_views': page_views,
                'total': page_views,
                'events': external,
                'bots': _filtered_bot_summary(
                    connection, diagnostic_visit_where, diagnostic_visit_params),
                'local_events': next((row['events'] for row in event_groups['by_scope']
                                      if row['label'] == 'local'), 0),
                'automation_events': next((row['events'] for row in event_groups['by_scope']
                                           if row['label'] == 'automation'), 0),
                'remote_events': next((row['events'] for row in event_groups['by_scope']
                                       if row['label'] == 'remote'), 0),
                'traffic_quality': traffic_quality,
            }
        else:
            overview = {
                'page_views': page_views,
                'external_interactions': external,
                'top_page': top_page,
                'top_referrer': top_referrer,
                # Keep the old names as harmless aliases for small local scripts.
                'total': page_views,
                'traffic_quality': traffic_quality,
            }
        dwell = _filtered_dwell(connection, event_where, event_params)
        return {
            'generated_at': now.isoformat(timespec='seconds'),
            'retention_days': None,
            'retention_policy': 'permanent',
            'filters': filters,
            'time_range': {
                'timezone': timezone_name,
                'start': start.isoformat(timespec='seconds') if start else None,
                'end': now.astimezone(reporting_tz).isoformat(timespec='seconds'),
                'basis': 'calendar_days_including_today',
            },
            'view': view,
            'privacy': {
                'redacted': True,
                'omitted_fields': ['ip_address', 'latitude', 'longitude',
                                   'postal_code', 'user_agent', 'visitor_hash',
                                   'session_hash'],
            },
            'overview': overview,
            'daily': daily,
            'trend': trend,
            'sites': groups['sites'],
            'pages': groups['pages'],
            'referrers': groups['referrers'],
            'countries': groups['countries'],
            'events': {
                'total': external,
                **event_groups,
                'dwell': dwell,
                'behavior': _filtered_behavior(connection, event_where, event_params),
                'recent': recent_events,
            },
            'recent': recent_visits,
            'recent_visits': recent_visits,
            'diagnostics': {
                'bots': _filtered_bot_summary(
                    connection, diagnostic_visit_where, diagnostic_visit_params)
                if diagnostic else None,
                'recent_events': recent_events if diagnostic else [],
                'traffic_quality': traffic_quality,
                'suspected_clusters': suspected_clusters if diagnostic else [],
            },
        }


def build_portfolio_analytics(db_path: str, days=None, site=None, view=None, tz=None) -> dict:
    """Build analytics with optional validated filters.

    No-argument calls retain the historical payload for compatibility. New API
    callers must pass explicit filters and receive the privacy-minimized payload.
    """
    if days is None and site is None and view is None and tz is None:
        return _build_legacy_analytics(db_path)
    return _build_filtered_analytics(
        db_path, validate_analytics_filters(
            30 if days is None else days,
            'all' if site is None else site,
            'visitor' if view is None else view, tz))


def export_portfolio_analytics_json(db_path: str) -> str:
    return json.dumps(build_portfolio_analytics(db_path), ensure_ascii=False, indent=2)
