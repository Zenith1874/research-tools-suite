# -*- coding: utf-8 -*-
"""Public, independent source adapters for the Academic Career domain."""

from .base import (SourceAdapter, SourceJob, AdapterError, CrawlBudgetExhaustedError,
                   adapter_catalog, reset_crawl_budgets)

__all__ = ["SourceAdapter", "SourceJob", "AdapterError", "CrawlBudgetExhaustedError",
           "adapter_catalog", "reset_crawl_budgets"]
