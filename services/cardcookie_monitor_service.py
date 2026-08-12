"""On-demand CardCookie availability monitor with local, auditable history.

The runtime is deliberately *off* after every server start.  A user must start
it from the local page before scheduled checks or email notifications can run.
The first successful observation for a retailer becomes a baseline and never
sends mail.  Fetch or parser failures are recorded separately and never replace
the last valid state.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import smtplib
import sqlite3
import ssl
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import requests
from bs4 import BeautifulSoup


log = logging.getLogger(__name__)

TARGETS = {
    "walmart": {
        "slug": "walmart",
        "brand": "Walmart",
        "url": "https://cardcookie.com/buy-gift-cards/walmart",
    },
    "best-buy": {
        "slug": "best-buy",
        "brand": "Best Buy",
        "url": "https://cardcookie.com/buy-gift-cards/best-buy",
    },
}

DEFAULT_INTERVAL_SECONDS = 600
MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 86_400
BLOCKED_BACKOFF_SECONDS = 900
FAILURE_ALERT_THRESHOLD = 3
REQUEST_TIMEOUT_SECONDS = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
    "ResearchToolsSuite/1.0"
)


class CardCookieMonitorError(RuntimeError):
    """A safe, user-facing monitor or configuration error."""

    def __init__(self, message: str, *, code: str = "monitor_error",
                 http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _utc_now()).replace(microsecond=0).isoformat()


def _number(raw: str, *, percent: bool = False) -> float:
    text = (raw or "").replace(",", "").replace("，", "").strip()
    pattern = r"-?\d+(?:\.\d+)?"
    match = re.search(pattern, text)
    if not match:
        kind = "折扣" if percent else "金额"
        raise CardCookieMonitorError(f"无法识别{kind}：{raw!r}", code="parse_error")
    return round(float(match.group(0)), 4)


def _brand_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _canonical_offers(raw_offers: list[dict]) -> list[dict]:
    """Aggregate identical rows so row order changes do not create false alerts."""
    counts = Counter(
        (
            round(float(item["value"]), 2),
            round(float(item["discount_pct"]), 4),
            round(float(item["price"]), 2),
        )
        for item in raw_offers
    )
    offers = [
        {
            "value": value,
            "discount_pct": discount,
            "price": price,
            "quantity": quantity,
        }
        for (value, discount, price), quantity in counts.items()
    ]
    return sorted(
        offers,
        key=lambda item: (-item["discount_pct"], item["value"], item["price"]),
    )


def _fingerprint(availability: str, offers: list[dict]) -> str:
    payload = json.dumps(
        {"availability": availability, "offers": offers},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_cardcookie_html(html: str, *, brand: str, source_url: str) -> dict:
    """Parse one retailer page without treating a failed page as out of stock."""
    soup = BeautifulSoup(html or "", "html.parser")
    page_text = " ".join(soup.get_text(" ", strip=True).split())
    low_text = page_text.casefold()
    low_html = (html or "").casefold()

    verification_markers = (
        "verify you are human",
        "verification required",
        "captcha",
        "cf-chl-",
        "access denied",
        "antibot",
    )
    if any(marker in low_text or marker in low_html for marker in verification_markers):
        raise CardCookieMonitorError(
            "CardCookie 返回了验证或访问限制页面，本次已跳过",
            code="blocked",
        )

    target_key = _brand_key(brand)
    raw_offers: list[dict] = []
    recognized_table = False
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [
            " ".join(cell.get_text(" ", strip=True).split()).casefold()
            for cell in rows[0].find_all(["th", "td"])
        ]
        if not ({"value", "discount", "price"} <= set(headers)):
            continue
        recognized_table = True
        value_idx = headers.index("value")
        discount_idx = headers.index("discount")
        price_idx = headers.index("price")
        brand_idx = headers.index("gift card") if "gift card" in headers else 0
        required_idx = max(value_idx, discount_idx, price_idx, brand_idx)
        for row in rows[1:]:
            cells = [" ".join(cell.get_text(" ", strip=True).split())
                     for cell in row.find_all(["th", "td"])]
            if len(cells) <= required_idx:
                continue
            if target_key not in _brand_key(cells[brand_idx]):
                continue
            try:
                raw_offers.append({
                    "value": _number(cells[value_idx]),
                    "discount_pct": _number(cells[discount_idx], percent=True),
                    "price": _number(cells[price_idx]),
                })
            except CardCookieMonitorError:
                # A malformed retailer row must not invalidate other valid rows.
                continue

    offers = _canonical_offers(raw_offers)
    if offers:
        availability = "in_stock"
    else:
        out_of_stock_markers = (
            "out of stock",
            "currently unavailable",
            "no gift cards available",
            "gift cards are unavailable",
        )
        if any(marker in low_text for marker in out_of_stock_markers):
            availability = "out_of_stock"
        elif recognized_table:
            raise CardCookieMonitorError(
                f"找到商品表，但没有识别到 {brand} 的有效卡片；本次不覆盖旧状态",
                code="parse_error",
            )
        else:
            raise CardCookieMonitorError(
                "页面没有可识别的卡片表或明确缺货说明；本次不覆盖旧状态",
                code="parse_error",
            )

    inventory_units = sum(int(item["quantity"]) for item in offers)
    max_discount = max((float(item["discount_pct"]) for item in offers), default=None)
    result = {
        "availability": availability,
        "offers": offers,
        "offer_count": len(offers),
        "inventory_units": inventory_units,
        "max_discount_pct": max_discount,
        "source_url": source_url,
    }
    result["fingerprint"] = _fingerprint(availability, offers)
    return result


def _mask_email(address: str) -> str:
    address = (address or "").strip()
    if "@" not in address:
        return "未设置"
    local, domain = address.rsplit("@", 1)
    shown = local[:2] if len(local) > 2 else local[:1]
    return f"{shown}***@{domain}"


def _split_recipients(raw: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;]", raw or "") if part.strip()]


def email_configuration(env=None) -> dict:
    """Return only safe email metadata; the password never enters the payload."""
    source = env if env is not None else os.environ
    prefixed_names = (
        "CARDCOOKIE_SMTP_HOST", "CARDCOOKIE_SMTP_PORT", "CARDCOOKIE_SMTP_USER",
        "CARDCOOKIE_SMTP_PASS", "CARDCOOKIE_SMTP_FROM", "CARDCOOKIE_NOTIFY_TO",
        "CARDCOOKIE_SMTP_USE_SSL", "CARDCOOKIE_SMTP_STARTTLS",
    )
    use_prefixed = any(str(source.get(name) or "").strip() for name in prefixed_names)

    def setting(prefixed, generic, default=""):
        if use_prefixed:
            return source.get(prefixed, default)
        return source.get(generic, default)

    host = str(setting("CARDCOOKIE_SMTP_HOST", "SMTP_HOST") or "").strip()
    user = str(setting("CARDCOOKIE_SMTP_USER", "SMTP_USER") or "").strip()
    password = str(setting("CARDCOOKIE_SMTP_PASS", "SMTP_PASS") or "")
    recipients = _split_recipients(
        str(setting("CARDCOOKIE_NOTIFY_TO", "NOTIFY_TO") or ""))
    sender = str(setting("CARDCOOKIE_SMTP_FROM", "SMTP_FROM", user) or user).strip()
    missing = []
    missing_names = {
        "host": "CARDCOOKIE_SMTP_HOST" if use_prefixed else "SMTP_HOST",
        "user": "CARDCOOKIE_SMTP_USER" if use_prefixed else "SMTP_USER",
        "password": "CARDCOOKIE_SMTP_PASS" if use_prefixed else "SMTP_PASS",
        "recipients": "CARDCOOKIE_NOTIFY_TO" if use_prefixed else "NOTIFY_TO",
        "port": "CARDCOOKIE_SMTP_PORT" if use_prefixed else "SMTP_PORT",
    }
    if not host:
        missing.append(missing_names["host"])
    if not user:
        missing.append(missing_names["user"])
    if not password:
        missing.append(missing_names["password"])
    if not recipients:
        missing.append(missing_names["recipients"])
    try:
        port = int(setting("CARDCOOKIE_SMTP_PORT", "SMTP_PORT", 587) or 587)
    except (TypeError, ValueError):
        port = 587
        missing.append(missing_names["port"])
    use_ssl = str(setting("CARDCOOKIE_SMTP_USE_SSL", "SMTP_USE_SSL") or "").strip().casefold() in {
        "1", "true", "yes", "on",
    } or port == 465
    starttls = str(setting("CARDCOOKIE_SMTP_STARTTLS", "SMTP_STARTTLS", "1") or "1").strip().casefold() not in {
        "0", "false", "no", "off",
    }
    return {
        "configured": not missing,
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "sender": sender,
        "recipients": recipients,
        "use_ssl": use_ssl,
        "starttls": starttls,
        "missing": sorted(set(missing)),
        "sender_masked": _mask_email(sender),
        "recipients_masked": [_mask_email(item) for item in recipients],
        "namespace": "cardcookie" if use_prefixed else "generic",
    }


def _safe_email_payload(config: dict) -> dict:
    return {
        "configured": bool(config.get("configured")),
        "sender_masked": config.get("sender_masked") or "未设置",
        "recipients_masked": list(config.get("recipients_masked") or []),
        "missing": list(config.get("missing") or []),
        "namespace": config.get("namespace") or "generic",
    }


def discover_legacy_email_settings(directory) -> dict:
    """Read only non-secret SMTP fields from the old notebooks.

    ``email_pass`` is intentionally detected but never returned or copied.
    """
    root = Path(directory)
    notebooks = sorted(root.glob("*.ipynb"))
    values = {name: set() for name in (
        "smtp_server", "smtp_port", "email_user", "to_email")}
    password_ignored = False
    starttls_seen = False
    ssl_seen = False
    parsed_count = 0
    for notebook in notebooks:
        try:
            payload = json.loads(notebook.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        parsed_count += 1
        for cell in payload.get("cells") or []:
            if cell.get("cell_type") != "code":
                continue
            source = "".join(cell.get("source") or [])
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    function = node.func
                    name = (function.attr if isinstance(function, ast.Attribute)
                            else function.id if isinstance(function, ast.Name) else "")
                    starttls_seen = starttls_seen or name == "starttls"
                    ssl_seen = ssl_seen or name == "SMTP_SSL"
                if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                    continue
                for target in node.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id == "email_pass":
                        password_ignored = True
                    elif target.id in values:
                        values[target.id].add(node.value.value)

    def single(name):
        items = values[name]
        if len(items) != 1:
            raise CardCookieMonitorError(
                f"旧笔记本中的 {name} 缺失或不一致，未自动导入",
                code="legacy_email_ambiguous",
            )
        return next(iter(items))

    if not parsed_count:
        raise CardCookieMonitorError("没有找到可读取的旧 Cardcookie 笔记本",
                                     code="legacy_email_missing")
    host = str(single("smtp_server")).strip()
    user = str(single("email_user")).strip()
    recipient = str(single("to_email")).strip()
    try:
        port = int(single("smtp_port"))
    except (TypeError, ValueError) as exc:
        raise CardCookieMonitorError("旧笔记本中的 SMTP 端口无效",
                                     code="legacy_email_ambiguous") from exc
    return {
        "host": host,
        "port": port,
        "use_ssl": bool(ssl_seen and not starttls_seen),
        "starttls": bool(starttls_seen),
        "user": user,
        "sender": user,
        "recipients": [recipient],
        "notebooks_scanned": parsed_count,
        "legacy_password_ignored": password_ignored,
    }


def _write_secrets_updates(path, updates: dict[str, str]) -> None:
    """Atomically update selected keys while preserving unrelated local secrets."""
    secrets_path = Path(path)
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    original = secrets_path.read_text(encoding="utf-8") if secrets_path.exists() else ""
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines()
    output = []
    written = set()
    key_pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
    for line in lines:
        match = key_pattern.match(line)
        key = match.group(1) if match else ""
        if key in updates:
            if key not in written:
                output.append(f"{key}={updates[key]}")
                written.add(key)
            continue
        output.append(line)
    missing = [key for key in updates if key not in written]
    if missing:
        if output and output[-1].strip():
            output.append("")
        if not any("CardCookie monitor email" in line for line in output):
            output.append("# CardCookie monitor email (local only; never commit)")
        output.extend(f"{key}={updates[key]}" for key in missing)
    content = newline.join(output).rstrip("\r\n") + newline
    temporary = secrets_path.with_name(secrets_path.name + ".cardcookie.tmp")
    temporary.write_text(content, encoding="utf-8", newline="")
    os.replace(temporary, secrets_path)
    try:
        os.chmod(secrets_path, 0o600)
    except OSError:
        pass


def _read_secret_value(path, key: str) -> str:
    """Read one exact key without expanding, logging, or returning other secrets."""
    secrets_path = Path(path)
    if not secrets_path.exists():
        return ""
    try:
        lines = secrets_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=(.*)$")
    for line in reversed(lines):
        match = pattern.match(line)
        if match:
            return match.group(1).strip()
    return ""


def _format_offer_lines(state: dict | None) -> str:
    if not state:
        return "无历史基线"
    if state.get("availability") == "out_of_stock":
        return "明确缺货"
    offers = state.get("offers") or []
    if not offers:
        return "没有可展示的卡片"
    return "\n".join(
        f"- 面值 ${item['value']:.2f}；折扣 {item['discount_pct']:g}%；"
        f"售价 ${item['price']:.2f}；数量 {item['quantity']}"
        for item in offers
    )


def _send_smtp_email(config: dict, *, target: dict, event_type: str,
                     summary: str, previous: dict | None, current: dict | None,
                     checked_at: str) -> None:
    if not config.get("configured"):
        raise CardCookieMonitorError("邮件参数尚未配置", code="email_not_configured")
    labels = {
        "stock_in": "恢复有货",
        "stock_out": "转为缺货",
        "offers_changed": "库存或价格变化",
        "fetch_failure": "连续检查失败",
        "recovered": "检查恢复正常",
    }
    message = EmailMessage()
    message["Subject"] = f"[CardCookie] {target['brand']}：{labels.get(event_type, event_type)}"
    message["From"] = config["sender"]
    message["To"] = ", ".join(config["recipients"])
    message.set_content(
        f"{summary}\n\n"
        f"检查时间：{checked_at}\n"
        f"来源：{target['url']}\n\n"
        f"此前状态：\n{_format_offer_lines(previous)}\n\n"
        f"当前状态：\n{_format_offer_lines(current)}\n\n"
        "这是你在研究工具中手动开启的 CardCookie 监控通知。"
    )
    context = ssl.create_default_context()
    if config.get("use_ssl"):
        with smtplib.SMTP_SSL(
                config["host"], config["port"], timeout=20, context=context) as smtp:
            smtp.login(config["user"], config["password"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(config["host"], config["port"], timeout=20) as smtp:
            smtp.ehlo()
            if config.get("starttls"):
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(config["user"], config["password"])
            smtp.send_message(message)


class CardCookieMonitorManager:
    """Owns the local database and the explicitly-started polling thread."""

    def __init__(self, db_path, *, http_get=None, email_sender=None, env=None,
                 secrets_path=None):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._secrets_path = str(secrets_path) if secrets_path is not None else None
        self._http_get = http_get or requests.get
        self._email_sender = email_sender or _send_smtp_email
        self._env = env if env is not None else os.environ
        self._state_lock = threading.RLock()
        self._cycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._checking = False
        self._run_token = 0
        self._interval_seconds = DEFAULT_INTERVAL_SECONDS
        self._effective_wait_seconds = DEFAULT_INTERVAL_SECONDS
        self._backoff_reason: str | None = None
        self._selected_targets = list(TARGETS)
        self._started_at: str | None = None
        self._last_cycle_started_at: str | None = None
        self._last_cycle_finished_at: str | None = None
        self._next_check_at: str | None = None
        self._ensure_schema()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cardcookie_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_slug TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    fetch_status TEXT NOT NULL,
                    availability TEXT,
                    offer_count INTEGER,
                    inventory_units INTEGER,
                    max_discount_pct REAL,
                    fingerprint TEXT,
                    offers_json TEXT,
                    source_url TEXT NOT NULL,
                    http_status INTEGER,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_cardcookie_snapshots_target_time
                    ON cardcookie_snapshots(target_slug, checked_at DESC);

                CREATE TABLE IF NOT EXISTS cardcookie_target_state (
                    target_slug TEXT PRIMARY KEY,
                    brand TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    last_attempt_at TEXT,
                    last_success_at TEXT,
                    availability TEXT,
                    offer_count INTEGER,
                    inventory_units INTEGER,
                    max_discount_pct REAL,
                    fingerprint TEXT,
                    offers_json TEXT NOT NULL DEFAULT '[]',
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    failure_alerted INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    last_http_status INTEGER,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cardcookie_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_slug TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    previous_json TEXT,
                    current_json TEXT,
                    email_status TEXT NOT NULL,
                    email_error TEXT,
                    recipient_masked TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_cardcookie_events_time
                    ON cardcookie_events(created_at DESC);
                """
            )
            now = _iso()
            for target in TARGETS.values():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO cardcookie_target_state
                      (target_slug, brand, source_url, offers_json, updated_at)
                    VALUES (?, ?, ?, '[]', ?)
                    """,
                    (target["slug"], target["brand"], target["url"], now),
                )

    @staticmethod
    def _validate_targets(slugs) -> list[str]:
        values = []
        for slug in slugs or []:
            slug = str(slug).strip().casefold()
            if slug in TARGETS and slug not in values:
                values.append(slug)
        if not values:
            raise CardCookieMonitorError("请至少选择一个要检查的商家", code="no_targets")
        return values

    @staticmethod
    def _validate_interval(value) -> int:
        try:
            seconds = int(value)
        except (TypeError, ValueError) as exc:
            raise CardCookieMonitorError("检查间隔不是有效数字", code="bad_interval") from exc
        if not MIN_INTERVAL_SECONDS <= seconds <= MAX_INTERVAL_SECONDS:
            raise CardCookieMonitorError(
                f"检查间隔须在 {MIN_INTERVAL_SECONDS // 60} 分钟至 24 小时之间",
                code="bad_interval",
            )
        return seconds

    def email_status(self) -> dict:
        return _safe_email_payload(email_configuration(self._env))

    def email_settings(self) -> dict:
        """Return editable non-secret fields for the loopback-only settings page."""
        config = email_configuration(self._env)
        return {
            "provider": "qq" if config["host"].casefold() == "smtp.qq.com" else "custom",
            "host": config["host"],
            "port": config["port"],
            "use_ssl": bool(config["use_ssl"]),
            "starttls": bool(config["starttls"]),
            "user": config["user"],
            "sender": config["sender"],
            "recipients": list(config["recipients"]),
            "password_set": bool(config["password"]),
            "configured": bool(config["configured"]),
            "missing": list(config["missing"]),
            "namespace": config["namespace"],
        }

    @staticmethod
    def _single_line(value, label: str, *, required=True) -> str:
        text = str(value or "").strip()
        if "\r" in text or "\n" in text:
            raise CardCookieMonitorError(
                f"{label} 不能包含换行", code="invalid_email_settings")
        if required and not text:
            raise CardCookieMonitorError(
                f"请填写{label}", code="invalid_email_settings")
        return text

    @classmethod
    def _email_address(cls, value, label: str) -> str:
        address = cls._single_line(value, label)
        if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", address):
            raise CardCookieMonitorError(
                f"{label}格式不正确", code="invalid_email_settings")
        return address

    def save_email_settings(self, settings: dict) -> dict:
        """Persist CardCookie-only SMTP settings without ever echoing the password."""
        if not self._secrets_path:
            raise CardCookieMonitorError(
                "当前运行方式没有可用的本机密钥文件",
                code="email_storage_unavailable",
            )
        if not isinstance(settings, dict):
            raise CardCookieMonitorError(
                "邮件配置格式无效", code="invalid_email_settings")

        provider = self._single_line(
            settings.get("provider") or "custom", "邮件服务商")
        host_default = "smtp.qq.com" if provider == "qq" else ""
        host = self._single_line(settings.get("host") or host_default, "SMTP 服务器")
        if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
            raise CardCookieMonitorError(
                "SMTP 服务器格式不正确", code="invalid_email_settings")
        try:
            port = int(settings.get("port") or (587 if provider == "qq" else 0))
        except (TypeError, ValueError) as exc:
            raise CardCookieMonitorError(
                "SMTP 端口不是有效数字", code="invalid_email_settings") from exc
        if not 1 <= port <= 65535:
            raise CardCookieMonitorError(
                "SMTP 端口须在 1 到 65535 之间", code="invalid_email_settings")

        user = self._email_address(settings.get("user"), "SMTP 登录账号")
        sender = self._email_address(settings.get("sender") or user, "发件邮箱")
        raw_recipients = settings.get("recipients")
        if isinstance(raw_recipients, list):
            recipients = [self._email_address(item, "收件邮箱")
                          for item in raw_recipients if str(item or "").strip()]
        else:
            recipient_text = self._single_line(raw_recipients, "收件邮箱")
            recipients = [self._email_address(item, "收件邮箱")
                          for item in _split_recipients(recipient_text)]
        if not recipients:
            raise CardCookieMonitorError(
                "请至少填写一个收件邮箱", code="invalid_email_settings")

        use_ssl = bool(settings.get("use_ssl"))
        starttls = bool(settings.get("starttls")) and not use_ssl
        password = self._single_line(
            settings.get("password"), "邮箱授权码或应用密码", required=False)
        existing_password = str(
            self._env.get("CARDCOOKIE_SMTP_PASS") or
            _read_secret_value(self._secrets_path, "CARDCOOKIE_SMTP_PASS") or ""
        )
        if password and len(password) < 6:
            raise CardCookieMonitorError(
                "邮箱授权码或应用密码长度异常", code="invalid_email_settings")

        updates = {
            "CARDCOOKIE_SMTP_HOST": host,
            "CARDCOOKIE_SMTP_PORT": str(port),
            "CARDCOOKIE_SMTP_USE_SSL": "1" if use_ssl else "0",
            "CARDCOOKIE_SMTP_STARTTLS": "1" if starttls else "0",
            "CARDCOOKIE_SMTP_USER": user,
            "CARDCOOKIE_SMTP_FROM": sender,
            "CARDCOOKIE_NOTIFY_TO": ",".join(recipients),
        }
        if password:
            updates["CARDCOOKIE_SMTP_PASS"] = password
        _write_secrets_updates(self._secrets_path, updates)
        for key, value in updates.items():
            self._env[key] = value
        if not password and existing_password:
            self._env["CARDCOOKIE_SMTP_PASS"] = existing_password

        return {
            "success": True,
            "message": "邮件配置已保存；本次没有发送邮件",
            "settings": self.email_settings(),
            "email": self.email_status(),
        }

    def import_legacy_nonsecret_settings(self, directory) -> dict:
        """Migrate old notebook addresses/transport only; never migrate passwords."""
        discovered = discover_legacy_email_settings(directory)
        self.save_email_settings({
            "provider": "qq" if discovered["host"].casefold() == "smtp.qq.com" else "custom",
            "host": discovered["host"],
            "port": discovered["port"],
            "use_ssl": discovered["use_ssl"],
            "starttls": discovered["starttls"],
            "user": discovered["user"],
            "sender": discovered["sender"],
            "recipients": discovered["recipients"],
            "password": "",
        })
        return {
            "success": True,
            "message": "旧代码中的非敏感邮件参数已导入；旧授权码未导入",
            "notebooks_scanned": discovered["notebooks_scanned"],
            "legacy_password_ignored": bool(discovered["legacy_password_ignored"]),
            "password_imported": False,
            "email": self.email_status(),
        }

    def _is_run_active(self, token: int | None) -> bool:
        if token is None:
            return False
        with self._state_lock:
            return self._running and token == self._run_token and not self._stop_event.is_set()

    def start(self, *, targets=None, interval_seconds=DEFAULT_INTERVAL_SECONDS,
              confirm_email=False) -> dict:
        selected = self._validate_targets(list(TARGETS) if targets is None else targets)
        interval = self._validate_interval(interval_seconds)
        mail = email_configuration(self._env)
        if mail["configured"] and not confirm_email:
            recipients = "、".join(mail["recipients_masked"])
            raise CardCookieMonitorError(
                f"请先确认：变化通知将自动发送到 {recipients}",
                code="email_confirmation_required",
            )
        with self._state_lock:
            if self._running:
                raise CardCookieMonitorError("监控已经开启", code="already_running")
            if self._checking or (self._thread and self._thread.is_alive()):
                raise CardCookieMonitorError("上一次检查尚未结束，请稍后再开启", code="busy")
            self._run_token += 1
            token = self._run_token
            self._running = True
            self._checking = False
            self._selected_targets = selected
            self._interval_seconds = interval
            self._effective_wait_seconds = interval
            self._backoff_reason = None
            self._started_at = _iso()
            self._next_check_at = self._started_at
            self._stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._monitor_loop,
                args=(token,),
                name="cardcookie-monitor",
                daemon=True,
            )
            self._thread.start()
        return {
            "status": "started",
            "message": "监控已开启，将立即检查一次",
            "email_mode": "notify" if mail["configured"] else "log_only",
            "monitor": self.runtime_status(),
        }

    def stop(self) -> dict:
        with self._state_lock:
            was_running = self._running
            self._running = False
            self._next_check_at = None
            self._effective_wait_seconds = self._interval_seconds
            self._backoff_reason = None
            self._run_token += 1
            self._stop_event.set()
        return {
            "status": "stopped",
            "message": "监控已停止；本地历史和上次有效状态已保留"
                       if was_running else "监控原本就是关闭状态",
            "monitor": self.runtime_status(),
        }

    def check_now(self, *, targets=None) -> dict:
        selected = self._validate_targets(list(TARGETS) if targets is None else targets)
        with self._state_lock:
            if self._running:
                raise CardCookieMonitorError(
                    "监控开启时会按计划检查；如需手动检查，请先停止监控",
                    code="already_running",
                )
            if self._checking or (self._thread and self._thread.is_alive()):
                raise CardCookieMonitorError("已有检查正在进行", code="busy")
            self._checking = True
            self._selected_targets = selected
            self._last_cycle_started_at = _iso()
            self._thread = threading.Thread(
                target=self._manual_cycle,
                args=(selected,),
                name="cardcookie-check-once",
                daemon=True,
            )
            self._thread.start()
        return {
            "status": "started",
            "message": "已开始检查一次；只更新本地记录，不会发邮件",
            "monitor": self.runtime_status(),
        }

    def _manual_cycle(self, selected: list[str]):
        try:
            with self._cycle_lock:
                self._perform_cycle(selected, run_token=None)
        finally:
            with self._state_lock:
                self._checking = False
                self._last_cycle_finished_at = _iso()

    def _monitor_loop(self, token: int):
        try:
            while self._is_run_active(token):
                with self._state_lock:
                    self._checking = True
                    self._last_cycle_started_at = _iso()
                    self._next_check_at = None
                    selected = list(self._selected_targets)
                try:
                    with self._cycle_lock:
                        cycle_result = self._perform_cycle(selected, run_token=token)
                finally:
                    with self._state_lock:
                        self._checking = False
                        self._last_cycle_finished_at = _iso()
                if not self._is_run_active(token):
                    break
                with self._state_lock:
                    wait_seconds, backoff_reason = self._wait_policy(cycle_result)
                    self._effective_wait_seconds = wait_seconds
                    self._backoff_reason = backoff_reason
                    self._next_check_at = _iso(_utc_now() + timedelta(seconds=wait_seconds))
                if self._stop_event.wait(wait_seconds):
                    break
        finally:
            with self._state_lock:
                if token == self._run_token:
                    self._running = False
                    self._checking = False
                    self._next_check_at = None
                    self._effective_wait_seconds = self._interval_seconds
                    self._backoff_reason = None

    def _wait_policy(self, cycle_result: dict | None) -> tuple[int, str | None]:
        if cycle_result and cycle_result.get("blocked"):
            wait_seconds = max(self._interval_seconds, BLOCKED_BACKOFF_SECONDS)
            return wait_seconds, (
                f"检测到验证页或 HTTP 403/429，本轮自动退避 {wait_seconds // 60} 分钟"
            )
        return self._interval_seconds, None

    def _fetch_target(self, target: dict) -> tuple[dict, int]:
        response = self._http_get(
            target["url"],
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            },
        )
        status = int(getattr(response, "status_code", 0) or 0)
        if status in {401, 403, 429}:
            raise CardCookieMonitorError(
                f"CardCookie 返回 HTTP {status}，可能触发访问限制；本次已跳过",
                code="blocked",
                http_status=status,
            )
        if status < 200 or status >= 300:
            raise CardCookieMonitorError(
                f"CardCookie 返回 HTTP {status or '未知'}；本次已跳过",
                code="fetch_error",
            )
        try:
            parsed = parse_cardcookie_html(
                getattr(response, "text", ""),
                brand=target["brand"],
                source_url=target["url"],
            )
        except CardCookieMonitorError as exc:
            if exc.http_status is None:
                exc.http_status = status
            raise
        return parsed, status

    def _perform_cycle(self, selected: list[str], *, run_token: int | None):
        blocked = False
        checked_targets = 0
        for slug in selected:
            if run_token is not None and not self._is_run_active(run_token):
                break
            target = TARGETS[slug]
            checked_at = _iso()
            checked_targets += 1
            try:
                current, http_status = self._fetch_target(target)
                self._record_success(
                    target,
                    current,
                    checked_at=checked_at,
                    http_status=http_status,
                    run_token=run_token,
                )
            except CardCookieMonitorError as exc:
                blocked = blocked or exc.code == "blocked"
                self._record_failure(
                    target,
                    checked_at=checked_at,
                    fetch_status=exc.code,
                    error=str(exc),
                    http_status=exc.http_status,
                    run_token=run_token,
                )
            except requests.RequestException as exc:
                self._record_failure(
                    target,
                    checked_at=checked_at,
                    fetch_status="fetch_error",
                    error=f"网络请求失败：{exc}",
                    http_status=None,
                    run_token=run_token,
                )
            except Exception as exc:  # a single retailer must not stop the loop
                log.exception("CardCookie check failed for %s", slug)
                self._record_failure(
                    target,
                    checked_at=checked_at,
                    fetch_status="unexpected_error",
                    error=f"检查异常：{exc}",
                    http_status=None,
                    run_token=run_token,
                )
        return {"blocked": blocked, "checked_targets": checked_targets}

    @staticmethod
    def _row_state(row) -> dict | None:
        if not row or not row["fingerprint"]:
            return None
        try:
            offers = json.loads(row["offers_json"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            offers = []
        return {
            "availability": row["availability"],
            "offer_count": row["offer_count"] or 0,
            "inventory_units": row["inventory_units"] or 0,
            "max_discount_pct": row["max_discount_pct"],
            "fingerprint": row["fingerprint"],
            "offers": offers,
        }

    @staticmethod
    def _event_type(previous: dict, current: dict) -> str:
        if previous.get("availability") == "out_of_stock" and \
                current.get("availability") == "in_stock":
            return "stock_in"
        if previous.get("availability") == "in_stock" and \
                current.get("availability") == "out_of_stock":
            return "stock_out"
        return "offers_changed"

    @staticmethod
    def _state_summary(target: dict, state: dict) -> str:
        if state.get("availability") == "out_of_stock":
            return f"{target['brand']} 当前明确缺货"
        return (
            f"{target['brand']} 当前有 {state.get('offer_count', 0)} 种价格组合、"
            f"合计 {state.get('inventory_units', 0)} 张卡，"
            f"最高折扣 {state.get('max_discount_pct') or 0:g}%"
        )

    def _record_success(self, target: dict, current: dict, *, checked_at: str,
                        http_status: int, run_token: int | None):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cardcookie_target_state WHERE target_slug=?",
                (target["slug"],),
            ).fetchone()
            previous = self._row_state(row)
            previous_failures = int(row["consecutive_failures"] or 0) if row else 0
            failure_alerted = bool(row["failure_alerted"]) if row else False
            conn.execute(
                """
                INSERT INTO cardcookie_snapshots
                  (target_slug, checked_at, fetch_status, availability, offer_count,
                   inventory_units, max_discount_pct, fingerprint, offers_json,
                   source_url, http_status, error)
                VALUES (?, ?, 'success', ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    target["slug"], checked_at, current["availability"],
                    current["offer_count"], current["inventory_units"],
                    current["max_discount_pct"], current["fingerprint"],
                    json.dumps(current["offers"], ensure_ascii=False),
                    target["url"], http_status,
                ),
            )
            conn.execute(
                """
                UPDATE cardcookie_target_state
                SET last_attempt_at=?, last_success_at=?, availability=?, offer_count=?,
                    inventory_units=?, max_discount_pct=?, fingerprint=?, offers_json=?,
                    consecutive_failures=0, failure_alerted=0, last_error=NULL,
                    last_http_status=?, updated_at=?
                WHERE target_slug=?
                """,
                (
                    checked_at, checked_at, current["availability"], current["offer_count"],
                    current["inventory_units"], current["max_discount_pct"],
                    current["fingerprint"], json.dumps(current["offers"], ensure_ascii=False),
                    http_status, checked_at, target["slug"],
                ),
            )

        if previous is None:
            summary = self._state_summary(target, current) + "；首次成功检查仅建立基线"
            self._insert_event(
                target, "baseline", summary, previous, current,
                email_status="baseline", checked_at=checked_at,
            )
            return

        if previous["fingerprint"] != current["fingerprint"]:
            event_type = self._event_type(previous, current)
            summary = self._state_summary(target, current) + "；与上次有效状态不同"
            self._notify_and_record(
                target, event_type, summary, previous, current,
                checked_at=checked_at, run_token=run_token,
            )
        elif previous_failures and failure_alerted:
            summary = self._state_summary(target, current) + "；连续检查失败后已恢复"
            self._insert_event(
                target, "recovered", summary, previous, current,
                email_status="not_sent", checked_at=checked_at,
            )

    def _record_failure(self, target: dict, *, checked_at: str, fetch_status: str,
                        error: str, http_status: int | None, run_token: int | None):
        error = (error or "未知错误")[:1000]
        should_alert = False
        previous = None
        failures = 1
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cardcookie_target_state WHERE target_slug=?",
                (target["slug"],),
            ).fetchone()
            previous = self._row_state(row)
            failures = int(row["consecutive_failures"] or 0) + 1 if row else 1
            already_alerted = bool(row["failure_alerted"]) if row else False
            should_alert = failures >= FAILURE_ALERT_THRESHOLD and not already_alerted
            conn.execute(
                """
                INSERT INTO cardcookie_snapshots
                  (target_slug, checked_at, fetch_status, source_url, http_status, error)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (target["slug"], checked_at, fetch_status, target["url"], http_status, error),
            )
            conn.execute(
                """
                UPDATE cardcookie_target_state
                SET last_attempt_at=?, consecutive_failures=?, failure_alerted=?,
                    last_error=?, last_http_status=?, updated_at=?
                WHERE target_slug=?
                """,
                (
                    checked_at, failures, int(already_alerted or should_alert), error,
                    http_status, checked_at, target["slug"],
                ),
            )
        if should_alert:
            summary = (
                f"{target['brand']} 已连续 {failures} 次检查失败；"
                "上次有效状态已保留，未将失败误记为缺货"
            )
            self._notify_and_record(
                target, "fetch_failure", summary, previous, None,
                checked_at=checked_at, run_token=run_token,
            )

    def _notify_and_record(self, target: dict, event_type: str, summary: str,
                           previous: dict | None, current: dict | None, *,
                           checked_at: str, run_token: int | None):
        config = email_configuration(self._env)
        email_status = "manual_log_only"
        email_error = None
        recipient_masked = "、".join(config["recipients_masked"])
        if self._is_run_active(run_token):
            if config["configured"]:
                try:
                    self._email_sender(
                        config,
                        target=target,
                        event_type=event_type,
                        summary=summary,
                        previous=previous,
                        current=current,
                        checked_at=checked_at,
                    )
                    email_status = "sent"
                except Exception as exc:
                    log.exception("CardCookie email failed for %s", target["slug"])
                    email_status = "failed"
                    email_error = str(exc)[:1000]
            else:
                email_status = "not_configured"
        self._insert_event(
            target, event_type, summary, previous, current,
            email_status=email_status, email_error=email_error,
            recipient_masked=recipient_masked, checked_at=checked_at,
        )

    def _insert_event(self, target: dict, event_type: str, summary: str,
                      previous: dict | None, current: dict | None, *,
                      email_status: str, checked_at: str,
                      email_error: str | None = None, recipient_masked: str = ""):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cardcookie_events
                  (target_slug, event_type, created_at, summary, previous_json,
                   current_json, email_status, email_error, recipient_masked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target["slug"], event_type, checked_at, summary,
                    json.dumps(previous, ensure_ascii=False) if previous is not None else None,
                    json.dumps(current, ensure_ascii=False) if current is not None else None,
                    email_status, email_error, recipient_masked,
                ),
            )

    def runtime_status(self) -> dict:
        with self._state_lock:
            thread_alive = bool(self._thread and self._thread.is_alive())
            return {
                "running": self._running,
                "checking": self._checking,
                "mode": "running" if self._running else ("checking" if self._checking else "stopped"),
                "interval_seconds": self._interval_seconds,
                "effective_wait_seconds": self._effective_wait_seconds,
                "backoff_reason": self._backoff_reason,
                "selected_targets": list(self._selected_targets),
                "started_at": self._started_at,
                "last_cycle_started_at": self._last_cycle_started_at,
                "last_cycle_finished_at": self._last_cycle_finished_at,
                "next_check_at": self._next_check_at,
                "worker_alive": thread_alive,
            }

    def status(self, *, event_limit=60, snapshot_limit=30) -> dict:
        event_limit = max(1, min(200, int(event_limit)))
        snapshot_limit = max(1, min(100, int(snapshot_limit)))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cardcookie_target_state ORDER BY target_slug"
            ).fetchall()
            events = conn.execute(
                """
                SELECT id, target_slug, event_type, created_at, summary,
                       email_status, email_error, recipient_masked
                FROM cardcookie_events ORDER BY id DESC LIMIT ?
                """,
                (event_limit,),
            ).fetchall()
            snapshots = conn.execute(
                """
                SELECT id, target_slug, checked_at, fetch_status, availability,
                       offer_count, inventory_units, max_discount_pct, source_url,
                       http_status, error
                FROM cardcookie_snapshots ORDER BY id DESC LIMIT ?
                """,
                (snapshot_limit,),
            ).fetchall()

        targets = []
        by_slug = {row["target_slug"]: row for row in rows}
        for slug, target in TARGETS.items():
            row = by_slug.get(slug)
            try:
                offers = json.loads(row["offers_json"] or "[]") if row else []
            except (TypeError, ValueError, json.JSONDecodeError):
                offers = []
            targets.append({
                "slug": slug,
                "brand": target["brand"],
                "source_url": target["url"],
                "last_attempt_at": row["last_attempt_at"] if row else None,
                "last_success_at": row["last_success_at"] if row else None,
                "availability": row["availability"] if row else None,
                "offer_count": row["offer_count"] if row else None,
                "inventory_units": row["inventory_units"] if row else None,
                "max_discount_pct": row["max_discount_pct"] if row else None,
                "offers": offers,
                "consecutive_failures": int(row["consecutive_failures"] or 0) if row else 0,
                "last_error": row["last_error"] if row else None,
                "last_http_status": row["last_http_status"] if row else None,
            })

        runtime = self.runtime_status()
        email = self.email_status()
        return {
            "available": True,
            "runtime": runtime,
            "email": email,
            "targets": targets,
            "events": [dict(row) for row in events],
            "snapshots": [dict(row) for row in snapshots],
            "policy": {
                "default_off": True,
                "first_success_is_baseline": True,
                "manual_check_sends_email": False,
                "failure_alert_threshold": FAILURE_ALERT_THRESHOLD,
                "minimum_interval_seconds": MIN_INTERVAL_SECONDS,
                "blocked_backoff_seconds": BLOCKED_BACKOFF_SECONDS,
                "server_restart_resets_to_off": True,
                "failed_fetch_preserves_last_state": True,
            },
        }
