"""
PlagiarismCheck.org provider — chosen first because it's built for
EdTech/LMS use cases specifically, and includes AI-detection (TraceGPT)
alongside plagiarism matching.

CONFIRM BEFORE PRODUCTION USE: the exact endpoint paths and JSON field
names below follow that vendor's general submit -> poll -> fetch-report
pattern, but vendor APIs change their schemas over time. Check the current
contract at https://plagiarismcheck.org/for-developers/ with your API token
before trusting this against real traffic — treat this as correctly-shaped
scaffolding, not a guaranteed-byte-for-byte-accurate client.
"""
import time

import requests
from django.conf import settings

from .base import CheckResult, MatchedSource, PlagiarismProvider

API_BASE = "https://plagiarismcheck.org/api/v1"


class PlagiarismCheckProvider(PlagiarismProvider):
    name = "plagiarismcheck"

    def __init__(self, api_token=None):
        self.api_token = api_token or settings.CONTENT_INTEGRITY_PLAGIARISMCHECK_API_TOKEN

    def _headers(self):
        return {"X-API-TOKEN": self.api_token}

    def check_text(self, text: str) -> CheckResult:
        submit_resp = requests.post(
            f"{API_BASE}/text",
            headers=self._headers(),
            data={"text": text, "language": "en"},
            timeout=20,
        )
        submit_resp.raise_for_status()
        check_id = submit_resp.json()["data"]["id"]

        result = self._poll_for_result(check_id)
        return self._parse_result(result)

    def _poll_for_result(self, check_id, max_wait_seconds=120, interval_seconds=5) -> dict:
        elapsed = 0
        while elapsed < max_wait_seconds:
            resp = requests.get(f"{API_BASE}/text/{check_id}", headers=self._headers(), timeout=20)
            resp.raise_for_status()
            payload = resp.json()["data"]
            if payload.get("state") == "checked":
                return payload
            time.sleep(interval_seconds)
            elapsed += interval_seconds
        raise TimeoutError(f"PlagiarismCheck.org check {check_id} did not complete in time")

    def _parse_result(self, payload: dict) -> CheckResult:
        sources = [
            MatchedSource(
                url=src.get("url", ""),
                similarity=float(src.get("percent", 0)),
                matched_snippet=src.get("text", "")[:300],
            )
            for src in payload.get("sources", [])
        ]
        return CheckResult(
            score=float(payload.get("percent", 0)),
            matched_sources=sources,
            ai_generated_likelihood=payload.get("ai_percent"),
            raw_response=payload,
        )
