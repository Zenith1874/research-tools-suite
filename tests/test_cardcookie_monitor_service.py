# -*- coding: utf-8 -*-
"""CardCookie parser, state, alert, and default-off contract tests."""

import json
import tempfile
import threading
import unittest
from pathlib import Path

import requests

from services.cardcookie_monitor_service import (
    BLOCKED_BACKOFF_SECONDS,
    CardCookieMonitorError,
    CardCookieMonitorManager,
    MIN_INTERVAL_SECONDS,
    discover_legacy_email_settings,
    email_configuration,
    parse_cardcookie_html,
)


ROOT = Path(__file__).resolve().parents[1]


def offer_page(brand="Walmart", rows=None):
    rows = rows or [(20, 6, 18.8)]
    body = "".join(
        f"<tr><td>{brand}</td><td>${value:.2f}</td><td>{discount}%</td>"
        f"<td>${price:.2f}</td><td>Add to cart</td></tr>"
        for value, discount, price in rows
    )
    return (
        "<html><body><table>"
        "<tr><th>Gift Card</th><th>Value</th><th>Discount</th>"
        "<th>Price</th><th></th></tr>"
        f"{body}</table></body></html>"
    )


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class MutableGetter:
    def __init__(self, html):
        self.html = html
        self.status_code = 200
        self.error = None
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return FakeResponse(self.html, self.status_code)


class CardCookieParserTests(unittest.TestCase):
    def test_offer_parser_aggregates_identical_cards(self):
        result = parse_cardcookie_html(
            offer_page(rows=[(20, 6, 18.8), (20, 6, 18.8), (11, 6, 10.34)]),
            brand="Walmart",
            source_url="https://example.test/walmart",
        )
        self.assertEqual(result["availability"], "in_stock")
        self.assertEqual(result["offer_count"], 2)
        self.assertEqual(result["inventory_units"], 3)
        self.assertEqual(result["max_discount_pct"], 6.0)
        quantities = {item["value"]: item["quantity"] for item in result["offers"]}
        self.assertEqual(quantities, {11.0: 1, 20.0: 2})

    def test_row_order_does_not_change_fingerprint(self):
        first = parse_cardcookie_html(
            offer_page(rows=[(20, 6, 18.8), (11, 6, 10.34)]),
            brand="Walmart", source_url="x")
        second = parse_cardcookie_html(
            offer_page(rows=[(11, 6, 10.34), (20, 6, 18.8)]),
            brand="Walmart", source_url="x")
        self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_explicit_out_of_stock_is_distinct_from_parse_failure(self):
        result = parse_cardcookie_html(
            "<html><body><h1>Best Buy</h1><p>Gift cards are out of stock.</p></body></html>",
            brand="Best Buy", source_url="x")
        self.assertEqual(result["availability"], "out_of_stock")
        self.assertEqual(result["offers"], [])

    def test_unknown_page_does_not_overwrite_as_out_of_stock(self):
        with self.assertRaises(CardCookieMonitorError) as caught:
            parse_cardcookie_html(
                "<html><body><h1>Temporary page</h1></body></html>",
                brand="Best Buy", source_url="x")
        self.assertEqual(caught.exception.code, "parse_error")

    def test_verification_page_is_skipped(self):
        with self.assertRaises(CardCookieMonitorError) as caught:
            parse_cardcookie_html(
                "<html><body>Please verify you are human</body></html>",
                brand="Walmart", source_url="x")
        self.assertEqual(caught.exception.code, "blocked")


class CardCookieManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "cardcookie.db"
        self.secrets_path = Path(self.temp_dir.name) / ".secrets"
        self.getter = MutableGetter(offer_page())
        self.sent = []
        self.env = {
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "465",
            "SMTP_USE_SSL": "1",
            "SMTP_USER": "sender@example.test",
            "SMTP_PASS": "test-only-app-password",
            "NOTIFY_TO": "recipient@example.test",
        }

        def fake_sender(config, **kwargs):
            self.sent.append({"config": config, **kwargs})

        self.manager = CardCookieMonitorManager(
            self.db_path,
            http_get=self.getter,
            email_sender=fake_sender,
            env=self.env,
            secrets_path=self.secrets_path,
        )
        with self.manager._state_lock:
            self.manager._running = True
            self.manager._run_token = 7
            self.manager._stop_event = threading.Event()

    def tearDown(self):
        self.manager.stop()
        self.temp_dir.cleanup()

    def test_first_success_is_baseline_then_real_change_emails_once(self):
        self.manager._perform_cycle(["walmart"], run_token=7)
        self.assertEqual(self.sent, [])
        events = self.manager.status()["events"]
        self.assertEqual(events[0]["event_type"], "baseline")
        self.assertEqual(events[0]["email_status"], "baseline")

        self.getter.html = offer_page(rows=[(25, 9, 22.75)])
        self.manager._perform_cycle(["walmart"], run_token=7)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["event_type"], "offers_changed")
        self.assertEqual(self.manager.status()["events"][0]["email_status"], "sent")

        self.manager._perform_cycle(["walmart"], run_token=7)
        self.assertEqual(len(self.sent), 1, "unchanged state must not send again")

    def test_manual_cycle_records_change_but_never_emails(self):
        self.manager._perform_cycle(["walmart"], run_token=None)
        self.getter.html = offer_page(rows=[(50, 7, 46.5)])
        self.manager._perform_cycle(["walmart"], run_token=None)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.manager.status()["events"][0]["email_status"],
                         "manual_log_only")

    def test_three_failures_alert_once_and_preserve_last_valid_state(self):
        self.manager._perform_cycle(["walmart"], run_token=7)
        before = self.manager.status()["targets"][0]
        self.assertEqual(before["availability"], "in_stock")

        self.getter.error = requests.ConnectionError("offline")
        for _ in range(4):
            self.manager._perform_cycle(["walmart"], run_token=7)
        after = self.manager.status()["targets"][0]
        self.assertEqual(after["availability"], "in_stock")
        self.assertEqual(after["offers"], before["offers"])
        self.assertEqual(after["consecutive_failures"], 4)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["event_type"], "fetch_failure")

    def test_status_never_exposes_smtp_password(self):
        serialized = json.dumps(self.manager.status(), ensure_ascii=False)
        self.assertNotIn(self.env["SMTP_PASS"], serialized)
        self.assertNotIn("sender@example.test", serialized)
        self.assertIn("se***@example.test", serialized)

    def test_cardcookie_namespace_does_not_mix_generic_password(self):
        env = dict(self.env)
        env.update({
            "CARDCOOKIE_SMTP_HOST": "smtp.qq.com",
            "CARDCOOKIE_SMTP_PORT": "587",
            "CARDCOOKIE_SMTP_STARTTLS": "1",
            "CARDCOOKIE_SMTP_USER": "cardcookie@example.test",
            "CARDCOOKIE_SMTP_FROM": "cardcookie@example.test",
            "CARDCOOKIE_NOTIFY_TO": "alerts@example.test",
        })
        config = email_configuration(env)
        self.assertEqual(config["namespace"], "cardcookie")
        self.assertFalse(config["configured"])
        self.assertEqual(config["password"], "")
        self.assertIn("CARDCOOKIE_SMTP_PASS", config["missing"])

    def test_legacy_notebook_discovery_ignores_plaintext_password(self):
        legacy_dir = Path(self.temp_dir.name) / "legacy"
        legacy_dir.mkdir()
        notebook = {
            "cells": [{
                "cell_type": "code",
                "source": [
                    "smtp_server = 'smtp.qq.com'\n",
                    "smtp_port = 587\n",
                    "email_user = 'sender@example.test'\n",
                    "email_pass = 'old-plaintext-secret'\n",
                    "to_email = 'recipient@example.test'\n",
                    "smtp = smtplib.SMTP(smtp_server, smtp_port)\n",
                    "smtp.starttls()\n",
                ],
            }],
        }
        (legacy_dir / "monitor.ipynb").write_text(
            json.dumps(notebook), encoding="utf-8")
        discovered = discover_legacy_email_settings(legacy_dir)
        self.assertEqual(discovered["host"], "smtp.qq.com")
        self.assertEqual(discovered["port"], 587)
        self.assertTrue(discovered["starttls"])
        self.assertTrue(discovered["legacy_password_ignored"])
        self.assertNotIn("old-plaintext-secret", json.dumps(discovered))
        self.assertNotIn("password", discovered)

    def test_email_settings_save_is_local_preserves_other_secrets_and_sends_nothing(self):
        self.secrets_path.write_text(
            "# existing\nDEEPSEEK_API_KEY=keep-this-value\n", encoding="utf-8")
        manager = CardCookieMonitorManager(
            Path(self.temp_dir.name) / "settings.db",
            env={},
            secrets_path=self.secrets_path,
        )
        settings = {
            "provider": "qq",
            "host": "smtp.qq.com",
            "port": 587,
            "use_ssl": False,
            "starttls": True,
            "user": "sender@example.test",
            "sender": "sender@example.test",
            "recipients": "recipient@example.test",
            "password": "",
        }
        first = manager.save_email_settings(settings)
        contents = self.secrets_path.read_text(encoding="utf-8")
        self.assertIn("DEEPSEEK_API_KEY=keep-this-value", contents)
        self.assertNotIn("CARDCOOKIE_SMTP_PASS=", contents)
        self.assertFalse(first["settings"]["configured"])
        self.assertIn("CARDCOOKIE_SMTP_PASS", first["settings"]["missing"])
        self.assertIn("本次没有发送邮件", first["message"])

        settings["password"] = "new-test-app-password"
        second = manager.save_email_settings(settings)
        self.assertTrue(second["settings"]["configured"])
        self.assertTrue(second["settings"]["password_set"])
        self.assertIn(
            "CARDCOOKIE_SMTP_PASS=new-test-app-password",
            self.secrets_path.read_text(encoding="utf-8"),
        )
        self.assertNotIn("new-test-app-password", json.dumps(second))
        self.assertNotIn("password", second["email"])

        settings["password"] = ""
        third = manager.save_email_settings(settings)
        self.assertTrue(third["settings"]["configured"])
        self.assertIn(
            "CARDCOOKIE_SMTP_PASS=new-test-app-password",
            self.secrets_path.read_text(encoding="utf-8"),
        )

    def test_configured_email_requires_explicit_start_confirmation(self):
        self.manager.stop()
        with self.assertRaises(CardCookieMonitorError) as caught:
            self.manager.start(
                targets=["walmart"], interval_seconds=300, confirm_email=False)
        self.assertEqual(caught.exception.code, "email_confirmation_required")
        self.assertFalse(self.manager.runtime_status()["running"])

    def test_explicit_empty_target_list_is_rejected(self):
        self.manager.stop()
        with self.assertRaises(CardCookieMonitorError) as caught:
            self.manager.start(targets=[], interval_seconds=300, confirm_email=True)
        self.assertEqual(caught.exception.code, "no_targets")
        with self.assertRaises(CardCookieMonitorError):
            self.manager.check_now(targets=[])

    def test_one_two_three_minute_intervals_are_allowed(self):
        self.assertEqual(MIN_INTERVAL_SECONDS, 60)
        for seconds in (60, 120, 180):
            self.assertEqual(self.manager._validate_interval(seconds), seconds)
        with self.assertRaises(CardCookieMonitorError):
            self.manager._validate_interval(59)

        page = (ROOT / "static" / "cardcookie_monitor.html").read_text(encoding="utf-8")
        for seconds, minutes in ((60, 1), (120, 2), (180, 3)):
            self.assertIn(f'<option value="{seconds}">每 {minutes} 分钟</option>', page)

    def test_page_has_local_email_settings_form_and_no_test_send(self):
        page = (ROOT / "static" / "cardcookie_monitor.html").read_text(encoding="utf-8")
        for field_id in (
                "email-provider", "email-host", "email-port", "email-user",
                "email-sender", "email-recipients", "email-password"):
            self.assertIn(f'id="{field_id}"', page)
        self.assertIn("保存邮件配置", page)
        self.assertIn("保存不发送邮件", page)
        self.assertNotIn("test-email", page)

    def test_access_limit_uses_fifteen_minute_backoff(self):
        self.getter.status_code = 429
        result = self.manager._perform_cycle(["walmart"], run_token=7)
        self.assertTrue(result["blocked"])
        self.manager._interval_seconds = 60
        wait_seconds, reason = self.manager._wait_policy(result)
        self.assertEqual(BLOCKED_BACKOFF_SECONDS, 900)
        self.assertEqual(wait_seconds, 900)
        self.assertIn("退避 15 分钟", reason)
        snapshot = self.manager.status()["snapshots"][0]
        self.assertEqual(snapshot["fetch_status"], "blocked")
        self.assertEqual(snapshot["http_status"], 429)

    def test_new_manager_is_off_and_database_is_idempotent(self):
        second = CardCookieMonitorManager(self.db_path, env={})
        self.assertFalse(second.runtime_status()["running"])
        self.assertFalse(second.runtime_status()["checking"])
        self.assertTrue(second.status()["policy"]["default_off"])


if __name__ == "__main__":
    unittest.main()
