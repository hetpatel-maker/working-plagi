"""
Copyleaks provider — uses the Copyleaks Plagiarism Detection API v3.

The API requires:
1. Login via POST /v3/account/login/api to get a Bearer token.
2. Submit text as a base64-encoded file via PUT /v3/scans/submit/file/{scanId}.
3. Poll for results or receive via webhook.

In sandbox mode, Copyleaks returns fake (but realistic) results at zero cost.

Docs: https://api.copyleaks.com/
"""
import base64
import json
import logging
import time
import uuid
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.conf import settings

from .base import CheckResult, MatchedSource, PlagiarismProvider

log = logging.getLogger(__name__)

LOGIN_URL = "https://id.copyleaks.com/v3/account/login/api"
API_BASE = "https://api.copyleaks.com/v3"


class CopyleaksProvider(PlagiarismProvider):
    name = "copyleaks"

    def __init__(self, email=None, api_key=None):
        self.email = email or getattr(settings, "CONTENT_INTEGRITY_COPYLEAKS_EMAIL", "")
        self.api_key = api_key or getattr(settings, "CONTENT_INTEGRITY_COPYLEAKS_API_KEY", "")
        self._token = None
        
        # Configure robust HTTP session with exponential backoff for rate limits
        self.session = requests.Session()
        retries = Retry(
            total=5, 
            backoff_factor=2, 
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "PUT", "POST", "OPTIONS"]
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def _get_token(self) -> str:
        from django.core.cache import cache
        cache_key = "content_integrity:copyleaks_token"
        cached = cache.get(cache_key)
        if cached:
            log.debug("[content_integrity] Using cached Copyleaks auth token")
            return cached

        log.info("[content_integrity] Requesting new Copyleaks auth token for email=%s", self.email)
        log.info("[content_integrity] Requesting new Copyleaks auth token for email=%s", self.email)
        resp = self.session.post(LOGIN_URL, json={"email": self.email, "key": self.api_key}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        
        # Copyleaks tokens are valid for 48 hours. We cache it for 24 hours to be safe.
        cache.set(cache_key, token, timeout=86400)
        self._token = token
        log.info("[content_integrity] Copyleaks auth token obtained and cached for 24h")
        return token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def _get_fresh_webhook_token(self) -> str:
        """Get a FRESH webhook.site token for each scan.

        We intentionally do NOT cache/reuse tokens because webhook.site
        free tier caps at ~50 webhooks per token. After a day of testing,
        old scan results clog the token and new results get dropped.
        A fresh token guarantees 0 old webhooks = instant result pickup.
        """
        log.info("[content_integrity] Requesting fresh webhook.site token for this scan")
        log.info("[content_integrity] Requesting fresh webhook.site token for this scan")
        resp = self.session.post("https://webhook.site/token", timeout=10)
        resp.raise_for_status()
        token = resp.json()["uuid"]
        log.info("[content_integrity] Got fresh webhook.site token: %s", token)
        return token

    def check_text(self, text: str, webhook_url: Optional[str] = None, scan_id: Optional[str] = None) -> CheckResult:
        # Generate a unique scan ID if not provided by the caller.
        scan_id = scan_id or f"ci-{uuid.uuid4().hex[:12]}"
        log.info(
            "[content_integrity] Copyleaks check_text START: scan_id=%s, text_length=%d chars, webhook_url=%s",
            scan_id, len(text), webhook_url,
        )

        # Base64-encode the text as the API requires.
        text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")

        sandbox = getattr(settings, "CONTENT_INTEGRITY_COPYLEAKS_SANDBOX", True)
        log.info("[content_integrity] Copyleaks sandbox mode: %s", sandbox)
        
        secret = getattr(settings, "CONTENT_INTEGRITY_WEBHOOK_SECRET", "ci-secret-token")
        is_fallback_polling = False
        if webhook_url:
            # We have a real URL provided by the CMS, use it!
            # webhook_url is the domain, e.g. https://studio.myuniversity.com
            final_webhook_url = f"{webhook_url.rstrip('/')}/api/content-integrity/v1/copyleaks-webhook/{scan_id}/{{STATUS}}/?token={secret}"
        else:
            # Local dev fallback: use webhook.site
            log.info("[content_integrity] No webhook_url provided, falling back to webhook.site polling for local dev.")
            webhook_token = self._get_fresh_webhook_token()
            final_webhook_url = f"https://webhook.site/{webhook_token}?scan_id={scan_id}&status={{STATUS}}&token={secret}"
            is_fallback_polling = True
        payload = {
            "base64": text_b64,
            "filename": "content.txt",
            "properties": {
                "sandbox": sandbox,
                "webhooks": {
                    "status": final_webhook_url
                },
                "pdf": {
                    "create": True,
                    "reportVersion": "latest"
                }
            }
        }
        
        # Only request premium features if explicitly enabled in settings,
        # otherwise Copyleaks throws 402 Payment Required for accounts without AI/Grammar subscriptions.
        if getattr(settings, "CONTENT_INTEGRITY_ENABLE_AI_DETECTION", False):
            payload["properties"]["aiGeneratedText"] = {"detect": True}
        if getattr(settings, "CONTENT_INTEGRITY_ENABLE_GRAMMAR", False):
            payload["properties"]["writingFeedback"] = {"enable": True}

        # Determine endpoint (Business vs Education tier)
        endpoint_type = getattr(settings, "CONTENT_INTEGRITY_COPYLEAKS_ENDPOINT", "scans")

        # Submit the scan
        log.info("[content_integrity] Submitting scan %s to Copyleaks API (%s endpoint)", scan_id, endpoint_type)
        resp = self.session.put(
            f"{API_BASE}/{endpoint_type}/submit/file/{scan_id}",
            json=payload,
            headers=self._headers(),
            timeout=15,
        )
        
        if not resp.ok:
            log.error("[content_integrity] Copyleaks API submission failed for %s: %s %s", scan_id, resp.status_code, resp.text)
            resp.raise_for_status()

        log.info("[content_integrity] Scan %s submitted successfully (HTTP %d)", scan_id, resp.status_code)

        if not is_fallback_polling:
            # Real webhook mode: we are done! The webhook view will receive the result later.
            log.info("[content_integrity] Scan %s using real webhook. Returning PENDING.", scan_id)
            return CheckResult(is_pending=True, scan_id=scan_id)

        # Fallback polling mode
        log.info("[content_integrity] Polling webhook.site for scan %s result...", scan_id)
        result = self._poll_for_result(scan_id, webhook_token)
        log.info("[content_integrity] Scan %s poll completed.", scan_id)
        
        parsed_result = self._parse_result(result)
        parsed_result.scan_id = scan_id
        return parsed_result

    def _poll_for_result(self, scan_id, webhook_token, max_wait_seconds=600, interval_seconds=10) -> dict:
        elapsed = 0
        poll_count = 0
        rate_limit_hits = 0

        log.info(
            "[content_integrity] Starting poll for scan %s (token=%s, max_wait=%ds, interval=%ds)",
            scan_id, webhook_token[:8], max_wait_seconds, interval_seconds,
        )

        while elapsed < max_wait_seconds:
            poll_count += 1
            try:
                resp = self.session.get(
                    f"https://webhook.site/token/{webhook_token}/requests",
                    timeout=20,
                )

                # --- RATE LIMITING DETECTION ---
                if resp.status_code == 429:
                    rate_limit_hits += 1
                    retry_after = resp.headers.get("Retry-After", "unknown")
                    log.error(
                        "[content_integrity] ⚠️ RATE LIMITED by webhook.site! "
                        "scan=%s, poll=#%d, rate_limit_hits=%d, Retry-After=%s. "
                        "Free tier limit likely exceeded.",
                        scan_id, poll_count, rate_limit_hits, retry_after,
                    )
                    # Back off longer when rate limited
                    time.sleep(30)
                    elapsed += 30
                    continue

                # --- TOKEN EXPIRED DETECTION ---
                if resp.status_code == 404:
                    log.error(
                        "[content_integrity] ⚠️ TOKEN EXPIRED! webhook.site returned 404 for token %s. "
                        "The token no longer exists. Scan %s result is LOST. "
                        "Clearing cached token so a new one is created next time.",
                        webhook_token[:8], scan_id,
                    )
                    from django.core.cache import cache
                    cache.delete("content_integrity:webhook_site_token")
                    raise RuntimeError(
                        f"webhook.site token {webhook_token[:8]}... expired (404). "
                        f"Scan {scan_id} result is lost. Will retry with a new token."
                    )

                # --- OTHER HTTP ERRORS ---
                if resp.status_code != 200:
                    log.warning(
                        "[content_integrity] webhook.site returned HTTP %d for scan %s (poll #%d). "
                        "Response: %s",
                        resp.status_code, scan_id, poll_count, resp.text[:200],
                    )
                    time.sleep(interval_seconds)
                    elapsed += interval_seconds
                    continue

                # --- SUCCESS: Parse webhooks ---
                data = resp.json()
                all_webhooks = data.get("data", [])
                total_webhooks = data.get("total", len(all_webhooks))

                log.debug(
                    "[content_integrity] Poll #%d for scan %s: %d webhooks on page, %d total on token",
                    poll_count, scan_id, len(all_webhooks), total_webhooks,
                )

                # Look through the received webhooks for our scan_id
                found_our_scan = False
                for req in all_webhooks:
                    query = req.get("query", {})
                    if query.get("scan_id") == scan_id:
                        found_our_scan = True
                        status = query.get("status")
                        if status == "completed":
                            log.info(
                                "[content_integrity] ✅ Scan %s COMPLETED after %ds (%d polls, %d rate-limit hits)",
                                scan_id, elapsed, poll_count, rate_limit_hits,
                            )
                            return json.loads(req["content"])
                        elif status == "error":
                            log.error(
                                "[content_integrity] ❌ Scan %s returned ERROR status from Copyleaks: %s",
                                scan_id, req.get("content", "")[:500],
                            )
                            raise RuntimeError(f"Copyleaks returned error status: {req['content']}")
                        else:
                            log.info(
                                "[content_integrity] Scan %s found with status='%s' (not completed yet), waiting...",
                                scan_id, status,
                            )

                if not found_our_scan and poll_count % 6 == 0:
                    # Every ~60 seconds, log that we still haven't found our scan
                    log.info(
                        "[content_integrity] ⏳ Scan %s NOT found in %d webhooks after %ds. "
                        "Copyleaks may still be processing. (poll #%d)",
                        scan_id, total_webhooks, elapsed, poll_count,
                    )

            except requests.exceptions.RequestException as e:
                log.warning(
                    "[content_integrity] Network error polling webhook.site for scan %s (poll #%d): %s",
                    scan_id, poll_count, e,
                )
            except RuntimeError:
                raise
            except Exception as e:
                log.warning(
                    "[content_integrity] Unexpected error polling webhook.site for scan %s (poll #%d): %s",
                    scan_id, poll_count, e,
                )

            time.sleep(interval_seconds)
            elapsed += interval_seconds

        log.error(
            "[content_integrity] ❌ Scan %s TIMED OUT after %ds (%d polls, %d rate-limit hits). "
            "Possible causes: (1) webhook.site rate limiting, (2) token expired, "
            "(3) Copyleaks still processing, (4) network issues.",
            scan_id, max_wait_seconds, poll_count, rate_limit_hits,
        )
        raise TimeoutError(f"Copyleaks scan {scan_id} did not complete in time")

    def _parse_result(self, payload: dict) -> CheckResult:
        results = payload.get("results", {}).get("internet", []) or []
        
        # Copyleaks V3 aggregatedScore is a percentage (e.g., 15.4 means 15.4%)
        score = payload.get("results", {}).get("score", {}).get("aggregatedScore", 0)
        
        total_words = payload.get("scannedDocument", {}).get("totalWords", 1)
        
        sources = [
            MatchedSource(
                url=r.get("url", ""),
                # similarity is matchedWords / totalWords as a percentage
                similarity=float(r.get("matchedWords", 0)) / max(total_words, 1) * 100,
                matched_snippet=r.get("introduction", ""),
                title=r.get("title", ""),
                matched_words=int(r.get("matchedWords", 0)),
            )
            for r in results
        ]

        log.info(
            "[content_integrity] Parsed Copyleaks result: score=%.1f, total_words=%d, internet_sources=%d",
            float(score), total_words, len(results),
        )

        grammar_score = payload.get("writingFeedback", {}).get("score", {}).get("overallScore")
        readability_text = payload.get("writingFeedback", {}).get("readability", {}).get("readabilityLevelText", "")
        
        # Copyleaks can put AI data in a few places depending on the exact plan/version
        ai_data = payload.get("ai", {})
        ai_likelihood = ai_data.get("summary", {}).get("ai")

        return CheckResult(
            score=float(score),
            matched_sources=sources,
            ai_generated_likelihood=ai_likelihood,
            grammar_score=float(grammar_score) if grammar_score is not None else None,
            readability_text=str(readability_text),
            raw_response=payload,
        )

    def export_pdf_report(self, scan_id: str, export_id: str, webhook_url: str):
        """
        Triggers the Copyleaks Export API to generate and send a PDF report to our webhook.
        https://api.copyleaks.com/documentation/v3/downloads/export
        """
        log.info(
            "[content_integrity] Copyleaks export_pdf_report START: scan_id=%s, export_id=%s, webhook_url=%s",
            scan_id, export_id, webhook_url,
        )

        payload = {
            "pdfReport": {
                "verb": "POST",
                "endpoint": webhook_url,
                "headers": [
                    ["Authorization", f"Bearer {getattr(settings, 'CONTENT_INTEGRITY_WEBHOOK_SECRET', 'ci-secret-token')}"]
                ]
            },
            "completionWebhook": f"{webhook_url}?event=export_completed"
        }

        log.info("[content_integrity] Submitting export request to Copyleaks for scan %s", scan_id)
        resp = self.session.post(
            f"{API_BASE}/downloads/{scan_id}/export/{export_id}",
            json=payload,
            headers=self._headers(),
            timeout=15,
        )
        
        if not resp.ok:
            log.error("[content_integrity] Copyleaks Export API failed for %s: %s %s", scan_id, resp.status_code, resp.text)
            resp.raise_for_status()

        log.info("[content_integrity] Export triggered successfully for scan %s (HTTP %d)", scan_id, resp.status_code)
