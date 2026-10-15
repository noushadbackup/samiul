"""Connector interface every platform module implements.

A connector does two things and nothing else:

* ``discover(domain, keyword, state)`` – find public posts/videos for a
  keyword, returning them plus an updated cursor ``state`` (persisted by the
  caller so discovery resumes after a restart).
* ``fetch_page(post, cursor)`` – fetch ONE page of comments (or the caption)
  for a post, returning the raw items and the next cursor (None = finished).

Filtering, deduplication, anonymisation, diversity limits and storage are done
by the pipeline, identically for every platform.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from core.logging_setup import get_logger
from core.models import Page, Post, Source
from scraper.http import ConfigurationError, HttpClient


@dataclass
class DiscoveryResult:
    posts: list[Post]
    sources: list[Source] = field(default_factory=list)
    state: dict = field(default_factory=dict)  # cursor to persist
    exhausted: bool = False  # no more results for this keyword
    # Further discovery targets found along the way (e.g. Facebook pages found by
    # keyword search). They are crawled later via ``discover_target``.
    new_targets: list[str] = field(default_factory=list)


class BaseScraper(ABC):
    platform: str = "base"
    #: environment variables that must be set for this connector to run
    required_env: tuple[str, ...] = ()

    def __init__(self, cfg: dict, db=None, http: Optional[HttpClient] = None):
        self.cfg = cfg or {}
        self.db = db  # used for quota accounting only
        self.domain_keywords: list[str] = []  # set by SourceDiscovery
        self.log = get_logger(self.platform)
        self.http = http or HttpClient(self.platform, self.cfg, classifier=self.classify_response)

    # ------------------------------------------------------------- lifecycle
    def check_configuration(self) -> None:
        missing = [name for name in self.required_env if not os.environ.get(name, "").strip()]
        if missing:
            raise ConfigurationError(
                f"{self.platform}: missing environment variable(s) {', '.join(missing)} — see .env.example"
            )

    @staticmethod
    def env(name: str) -> str:
        return os.environ.get(name, "").strip()

    def classify_response(self, resp, payload) -> Optional[str]:  # pragma: no cover - overridden
        return None

    # ----------------------------------------------------------- operations
    @abstractmethod
    def discover(self, domain: str, keyword: str, state: dict) -> DiscoveryResult:
        ...

    @abstractmethod
    def fetch_page(self, post: Post, cursor: Optional[str]) -> Page:
        ...

    def configured_targets(self, domain: str) -> list[str]:
        """Extra non-keyword discovery targets (e.g. configured page IDs). Default: none."""
        return []

    def discover_target(self, domain: str, target: str, state: dict) -> DiscoveryResult:
        """Discover posts from a configured target (page/account). Default: nothing."""
        return DiscoveryResult(posts=[], exhausted=True)

    def stats(self) -> dict:
        return dict(self.http.stats)
