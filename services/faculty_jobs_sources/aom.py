# -*- coding: utf-8
"""Academy of Management Career Center status adapter."""

from .base import AdapterResponse, SourceAdapter


class AOMAdapter(SourceAdapter):
    name = "aom"
    adapter_name = "aom"
    region = "United States"
    base_url = "https://career-center.aom.org/jobs"
    priority = 8
    enabled = False
    support_status = "manual"
    support_reason = "Bounded public audit returned a Cloudflare challenge for the listing page; no bypass or private endpoint is used."

    def fetch(self):
        return AdapterResponse([], pages_fetched=0, notes=[self.support_reason])
