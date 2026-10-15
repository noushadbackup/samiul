"""Polite HTTP client shared by all connectors.

* fixed minimum delay between requests (per connector)
* timeouts on every request
* exponential backoff with jitter on 429 / 5xx / network errors
* honours ``Retry-After``
* bounded retries
* platform-specific rate-limit / quota detection via a classifier callback

It never rotates IPs, spoofs fingerprints, solves CAPTCHAs or otherwise tries
to get around a limit: when a platform says "stop", the connector stops.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Optional

import requests

from core.logging_setup import get_logger, log_event

USER_AGENT = "BanglaResearchCollector/1.0 (academic research; official APIs only)"


class ScraperError(Exception):
    """Base error for connector failures."""

    def __init__(self, message: str, status: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class ConfigurationError(ScraperError):
    """Missing credentials / misconfiguration. The platform is disabled for the run."""


class AuthError(ScraperError):
    """Credentials rejected or insufficient permission for the whole platform."""


class RateLimitError(ScraperError):
    """Temporary rate limit that persisted after all retries."""


class QuotaExceededError(ScraperError):
    """Daily quota / budget exhausted. The platform stops until the quota resets."""


class ResourceError(ScraperError):
    """A single resource is unavailable (comments disabled, deleted post, private...)."""


# Classifier result: one of None (fine), "retry", "rate_limit", "quota", "auth", "resource", "fatal"
Classifier = Callable[[requests.Response, Any], Optional[str]]


class HttpClient:
    def __init__(
        self,
        platform: str,
        cfg: dict,
        classifier: Optional[Classifier] = None,
        session: Optional[requests.Session] = None,
    ):
        self.platform = platform
        self.delay = float(cfg.get("request_delay_seconds", 1.0))
        self.timeout = float(cfg.get("timeout_seconds", 30))
        self.max_retries = int(cfg.get("max_retries", 4))
        self.backoff_base = float(cfg.get("backoff_base_seconds", 2.0))
        self.backoff_max = float(cfg.get("backoff_max_seconds", 120))
        self.classifier = classifier
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self._last_request = 0.0
        self.log = get_logger(platform)
        self.stats = {"requests": 0, "retries": 0, "rate_limited": 0, "errors": 0}
        self.sleep = time.sleep  # injectable for tests

    def _wait_turn(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            self.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def _backoff(self, attempt: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.backoff_max)
            except ValueError:
                pass
        base = self.backoff_base * (2**attempt)
        return min(base + random.uniform(0, base * 0.25), self.backoff_max)

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Perform a request and return parsed JSON (or raise a ScraperError subclass)."""
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self._wait_turn()
            self.stats["requests"] += 1
            try:
                resp = self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                self.stats["errors"] += 1
                if attempt >= self.max_retries:
                    break
                wait = self._backoff(attempt, None)
                self.stats["retries"] += 1
                log_event(self.log, "network_retry", platform=self.platform, attempt=attempt + 1, wait_s=round(wait, 1), error=str(exc)[:200])
                self.sleep(wait)
                continue

            try:
                payload = resp.json()
            except ValueError:
                payload = None

            verdict = self.classifier(resp, payload) if self.classifier else None
            if verdict is None:
                if resp.status_code >= 500:
                    verdict = "retry"
                elif resp.status_code == 429:
                    verdict = "rate_limit"
                elif resp.status_code >= 400:
                    verdict = "fatal"
            if verdict is None:
                return payload if payload is not None else {}

            message = self._error_message(resp, payload)
            if verdict == "quota":
                log_event(self.log, "quota_exceeded", platform=self.platform, status=resp.status_code, message=message)
                raise QuotaExceededError(message, resp.status_code, payload)
            if verdict == "auth":
                raise AuthError(message, resp.status_code, payload)
            if verdict == "resource":
                raise ResourceError(message, resp.status_code, payload)
            if verdict == "fatal":
                self.stats["errors"] += 1
                raise ScraperError(message, resp.status_code, payload)

            # retry / rate_limit: back off and try again (bounded)
            if verdict == "rate_limit":
                self.stats["rate_limited"] += 1
            if attempt >= self.max_retries:
                if verdict == "rate_limit":
                    raise RateLimitError(message, resp.status_code, payload)
                raise ScraperError(message, resp.status_code, payload)
            wait = self._backoff(attempt, resp.headers.get("Retry-After"))
            self.stats["retries"] += 1
            log_event(
                self.log,
                "rate_limited" if verdict == "rate_limit" else "http_retry",
                platform=self.platform,
                status=resp.status_code,
                attempt=attempt + 1,
                wait_s=round(wait, 1),
                message=message[:200],
            )
            self.sleep(wait)
        raise ScraperError(f"Network failure after {self.max_retries} retries: {last_exc}")

    def get(self, url: str, **kwargs: Any) -> Any:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self.request("POST", url, **kwargs)

    @staticmethod
    def _error_message(resp: requests.Response, payload: Any) -> str:
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                return f"HTTP {resp.status_code}: {err.get('message') or err.get('code') or err}"
            if isinstance(err, str):
                return f"HTTP {resp.status_code}: {err}"
        return f"HTTP {resp.status_code}: {resp.text[:300]}"
