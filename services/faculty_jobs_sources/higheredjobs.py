# -*- coding: utf-8 -*-
"""HigherEdJobs public endpoint status.

The site currently presents an anti-bot challenge to this workstation.  The
adapter is retained as an explicit manual/unsupported source so the scheduler
reports the limitation and never attempts to bypass it.
"""

from .base import AdapterResponse, SourceAdapter


class HigherEdJobsAdapter(SourceAdapter):
    name = "higheredjobs"
    adapter_name = "higheredjobs"
    region = "United States"
    base_url = "https://www.higheredjobs.com/faculty/"
    priority = 25
    enabled = False
    support_status = "manual"
    support_reason = "Public page returned an anti-bot challenge during source audit; no bypass is attempted."

    def fetch(self):
        return AdapterResponse([], pages_fetched=0, notes=[self.support_reason])
