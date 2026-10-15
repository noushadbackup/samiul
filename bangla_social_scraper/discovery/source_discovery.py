"""Incremental, resumable source discovery.

Each call to ``discover_next`` performs ONE discovery request for the keyword
(or configured page/account) that has been searched the least so far, stores
the found posts/sources in SQLite, and persists the cursor in ``crawl_state``.
Rotating across keywords spreads the batch over many topics and creators
instead of draining a single search.
"""

from __future__ import annotations

from typing import Optional

from core.logging_setup import get_logger, log_event
from scraper.base import BaseScraper, DiscoveryResult
from storage.database import Database

log = get_logger("discovery")


class SourceDiscovery:
    def __init__(self, db: Database, scraper: BaseScraper, domain: str, keywords: list[str]):
        self.db = db
        self.scraper = scraper
        self.domain = domain
        self.keywords = keywords
        scraper.domain_keywords = list(keywords)

    def _scopes(self) -> list[tuple[str, str, str]]:
        scopes = [("kw", kw, f"kw:{kw}") for kw in self.keywords]
        targets = list(self.scraper.configured_targets(self.domain))
        # targets found during earlier discovery (persisted in crawl_state)
        for key in self.db.list_scopes(self.scraper.platform, self.domain, "target:"):
            t = key[len("target:"):]
            if t not in targets:
                targets.append(t)
        scopes += [("target", t, f"target:{t}") for t in targets]
        return scopes

    def _next_scope(self) -> Optional[tuple[str, str, str, dict]]:
        best = None
        for kind, value, key in self._scopes():
            state, exhausted = self.db.get_crawl_state(self.scraper.platform, self.domain, key)
            if exhausted:
                continue
            pages = int(state.get("pages", 0))
            if best is None or pages < best[0]:
                best = (pages, kind, value, key, state)
        if best is None:
            return None
        return best[1], best[2], best[3], best[4]

    def exhausted(self) -> bool:
        return self._next_scope() is None

    def discover_next(self) -> Optional[int]:
        """Run one discovery step. Returns number of NEW posts, or None if everything is exhausted."""
        nxt = self._next_scope()
        if nxt is None:
            return None
        kind, value, key, state = nxt
        if kind == "kw":
            result: DiscoveryResult = self.scraper.discover(self.domain, value, state)
        else:
            result = self.scraper.discover_target(self.domain, value, state)
        new_posts = self.store(result)
        for t in result.new_targets:
            self.db.add_scope_if_missing(self.scraper.platform, self.domain, f"target:{t}")
        st = dict(result.state or {})
        st["pages"] = max(int(st.get("pages", 0)), int(state.get("pages", 0)) + 1)
        self.db.set_crawl_state(self.scraper.platform, self.domain, key, st, result.exhausted)
        self.db.commit()
        log_event(
            log,
            "discovery_step",
            platform=self.scraper.platform,
            domain=self.domain,
            scope=key,
            posts_returned=len(result.posts),
            new_posts=new_posts,
            exhausted=result.exhausted,
        )
        return new_posts

    def store(self, result: DiscoveryResult) -> int:
        for src in result.sources:
            self.db.upsert_source(src)
        new = 0
        for post in result.posts:
            if self.db.add_post(post, self.domain):
                new += 1
        return new

    def run(self, max_steps: int) -> dict:
        """Used by the `discover` CLI command: run up to max_steps discovery requests."""
        steps = new = 0
        while steps < max_steps:
            got = self.discover_next()
            if got is None:
                break
            steps += 1
            new += got
        return {
            "platform": self.scraper.platform,
            "steps": steps,
            "new_posts": new,
            "pending_posts": self.db.count_posts(self.scraper.platform, self.domain, "pending"),
            "total_posts": self.db.count_posts(self.scraper.platform, self.domain),
            "exhausted": self.exhausted(),
        }
