# -*- coding: utf-8 -*-
"""Regression tests for the watchdog's remote-connection safety boundary."""
import sys
import unittest
from unittest.mock import patch

from scripts import watchdog


class WatchdogTunnelPolicyTests(unittest.TestCase):
    def _run_one_tick(self, auto_tunnel):
        argv = ['watchdog.py', '--interval', '1']
        if auto_tunnel:
            argv.append('--auto-tunnel')

        with patch.object(watchdog, 'acquire_single_instance_lock', return_value=object()), \
                patch.object(watchdog, 'healthy', return_value=True), \
                patch.object(watchdog, 'log'), \
                patch.object(watchdog, 'ensure_tunnel') as ensure_tunnel, \
                patch.object(watchdog.time, 'sleep', side_effect=KeyboardInterrupt), \
                patch.object(sys, 'argv', argv):
            with self.assertRaises(KeyboardInterrupt):
                watchdog.main()
        return ensure_tunnel

    def test_default_watchdog_never_attempts_remote_tunnel(self):
        ensure_tunnel = self._run_one_tick(auto_tunnel=False)
        ensure_tunnel.assert_not_called()

    def test_remote_tunnel_requires_explicit_opt_in(self):
        ensure_tunnel = self._run_one_tick(auto_tunnel=True)
        self.assertGreaterEqual(ensure_tunnel.call_count, 1)


if __name__ == '__main__':
    unittest.main()
