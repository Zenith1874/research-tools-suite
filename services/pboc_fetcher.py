"""Thin PBOC fetcher adapter.

The legacy crawler still lives in server.py for compatibility. This module is
kept as the service boundary for the first-stage refactor.
"""

def update_pboc_from_legacy(scrape_func):
    return scrape_func()

