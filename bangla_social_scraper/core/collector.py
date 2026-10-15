"""Batch collection loop: round-robin over platforms until the target is met.

* One domain per batch (never mixed).
* Each platform is isolated: configuration errors, auth errors, quota
  exhaustion, persistent rate limits or crashes disable THAT platform for the
  run; the others keep going.
* Work is done in small units (one discovery request or one comment page), the
  database is committed after every unit, so the batch can be resumed at any
  point without recollecting anything.
* Diversity caps (per post / per creator) are enforced while collecting.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional

from core.config import Config
from core.logging_setup import get_logger, log_event
from core.pipeline import Pipeline
from discovery.source_discovery import SourceDiscovery
from scraper.base import BaseScraper
from scraper.http import (
    AuthError,
    ConfigurationError,
    QuotaExceededError,
    RateLimitError,
    ResourceError,
    ScraperError,
)
from storage.database import Database, utcnow

log = get_logger("collector")

MAX_CONSECUTIVE_ERRORS = 5


@dataclass
class DiversityLimits:
    post_cap: int
    creator_cap: int
    min_posts: int
    min_creators: int

    @classmethod
    def from_config(cls, cfg: dict, target: int) -> "DiversityLimits":
        max_post = int(cfg.get("max_per_post", 50))
        max_creator = int(cfg.get("max_per_creator", 150))
        per_1000 = float(cfg.get("min_distinct_posts_per_1000", 20))
        floor = int(cfg.get("min_distinct_posts_floor", 5))
        min_creators = int(cfg.get("min_distinct_creators", 5))
        min_posts = max(floor, math.ceil(per_1000 * target / 1000.0))
        post_cap = max(1, min(max_post, math.ceil(target / min_posts)))
        creator_cap = max(1, min(max_creator, math.ceil(target / max(1, min_creators))))
        creator_cap = max(creator_cap, post_cap)
        return cls(post_cap, creator_cap, min_posts, min_creators)


@dataclass
class PlatformState:
    name: str
    scraper: BaseScraper
    discovery: SourceDiscovery
    active: bool = True
    stop_reason: Optional[str] = None
    consecutive_errors: int = 0
    units_without_accept: int = 0
    pages: int = 0
    fetched: int = 0
    accepted: int = 0
    rejected: int = 0
    errors: int = 0
    skipped_posts: dict = field(default_factory=dict)


class Collector:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        pipeline: Pipeline,
        batch_id: str,
        domain: str,
        target: int,
        scrapers: dict[str, BaseScraper],
        keywords: dict[str, list[str]],
    ):
        self.cfg = cfg
        self.db = db
        self.pipeline = pipeline
        self.batch_id = batch_id
        self.domain = domain
        self.target = target
        self.limits = DiversityLimits.from_config(cfg.section("diversity"), target)
        self.states: list[PlatformState] = []
        for name, scraper in scrapers.items():
            disc = SourceDiscovery(db, scraper, domain, keywords.get(name, []))
            self.states.append(PlatformState(name, scraper, disc))
        self.max_empty = int(cfg.get("collection.max_empty_pages_per_platform", 200))
        self.max_runtime = float(cfg.get("collection.max_runtime_minutes", 0) or 0) * 60
        # "capped" is only a per-run shortcut; caps depend on the batch target and
        # are re-checked for every item, so re-open capped posts at the start of a run.
        db.reset_capped_posts(domain)
        self.post_counts = db.accepted_counts_by(batch_id, "post_id")
        self.creator_counts = db.accepted_counts_by(batch_id, "source_id")
        self.accepted_count = self.accepted_total()
        self._retro_seen = 0

    # --------------------------------------------------------------- helpers
    def accepted_total(self) -> int:
        return self.db.count_comments(self.batch_id, "accepted")

    def _refresh_counts(self) -> None:
        # Retro-rejections (bot copies) can lower counts; re-read from the DB.
        self.post_counts = self.db.accepted_counts_by(self.batch_id, "post_id")
        self.creator_counts = self.db.accepted_counts_by(self.batch_id, "source_id")
        self.accepted_count = self.accepted_total()

    def _creator_full(self, platform: str, source_id: Optional[str]) -> bool:
        return bool(source_id) and self.creator_counts.get((platform, source_id), 0) >= self.limits.creator_cap

    def _post_full(self, platform: str, post_id: str) -> bool:
        return self.post_counts.get((platform, post_id), 0) >= self.limits.post_cap

    def _disable(self, st: PlatformState, reason: str, exc: Optional[Exception] = None) -> None:
        st.active = False
        st.stop_reason = reason
        status = getattr(exc, "status", None)
        self.db.log_error(self.batch_id, st.name, "platform", reason, str(exc) if exc else reason, status)
        log_event(log, "platform_stopped", platform=st.name, reason=reason, detail=str(exc)[:300] if exc else None)

    # ---------------------------------------------------------- unit of work
    def _next_post(self, st: PlatformState):
        for row in self.db.pending_posts(st.name, self.domain, limit=200):
            if self._post_full(st.name, row["post_id"]):
                self.db.update_post(st.name, row["post_id"], self.domain, status="capped")
                continue
            if self._creator_full(st.name, row["source_id"]):
                # keep pending for future batches; skip in this one
                st.skipped_posts[row["post_id"]] = "max_per_creator"
                continue
            return row
        return None

    def _work_unit(self, st: PlatformState) -> bool:
        """Do one request's worth of work. Returns False when the platform has nothing left."""
        row = self._next_post(st)
        if row is None:
            return st.discovery.discover_next() is not None

        post = self.db.row_to_post(row)
        try:
            page = st.scraper.fetch_page(post, row["next_cursor"])
        except ResourceError as exc:
            self.db.update_post(st.name, post.post_id, self.domain, status="unavailable", last_error=str(exc)[:500])
            self.db.log_error(self.batch_id, st.name, f"post:{post.post_id}", "resource_unavailable", str(exc), exc.status)
            self.db.commit()
            log_event(log, "post_unavailable", platform=st.name, post_id=post.post_id, reason=str(exc)[:200])
            return True

        st.pages += 1
        accepted_before = self.pipeline.counters.accepted
        rejected_before = self.pipeline.counters.rejected
        deferred = 0
        for item in page.items:
            why = None
            if self.accepted_count >= self.target:
                why = "target_reached"
            elif self._post_full(st.name, post.post_id):
                why = "max_per_post"
            elif self._creator_full(st.name, post.source_id):
                why = "max_per_creator"
            if why:
                if not self.db.is_processed(item.platform, item.item_id):
                    self.pipeline.defer(item, why)
                    deferred += 1
                continue
            outcome = self.pipeline.process(item)
            if outcome == "accepted":
                self.accepted_count += 1
                k = (st.name, post.post_id)
                self.post_counts[k] = self.post_counts.get(k, 0) + 1
                if post.source_id:
                    c = (st.name, post.source_id)
                    self.creator_counts[c] = self.creator_counts.get(c, 0) + 1
        new_acc = self.pipeline.counters.accepted - accepted_before
        new_rej = self.pipeline.counters.rejected - rejected_before
        st.fetched += len(page.items)
        st.accepted += new_acc
        st.rejected += new_rej
        st.units_without_accept = 0 if new_acc else st.units_without_accept + 1

        # post status bookkeeping. If items on this page were deferred (cap or
        # target reached) the cursor is NOT advanced, so a later batch/resume
        # re-reads this page and processes only the not-yet-processed items.
        next_cursor = row["next_cursor"] if deferred else page.next_cursor
        status = "done" if (page.next_cursor is None and not deferred) else "active"
        processed, accepted = self.db.post_counts(self.batch_id, st.name, post.post_id)
        min_proc = int(st.scraper.cfg.get("low_yield_min_processed", 0) or 0)
        min_rate = float(st.scraper.cfg.get("low_yield_min_accept_rate", 0) or 0)
        if status == "active" and min_proc and processed >= min_proc and accepted / processed < min_rate:
            status = "low_yield"
        if status == "active" and self._post_full(st.name, post.post_id):
            status = "capped"
        self.db.update_post(
            st.name,
            post.post_id,
            self.domain,
            status=status,
            next_cursor=next_cursor,
            items_seen=(row["items_seen"] or 0) + len(page.items),
        )
        self.db.commit()
        if self.pipeline.raw is not None:
            self.pipeline.raw.flush()
        if self.pipeline.counters.retro_rejected != self._retro_seen:
            self._retro_seen = self.pipeline.counters.retro_rejected
            self._refresh_counts()
        log_event(
            log,
            "page_processed",
            platform=st.name,
            source=post.source_name,
            post_id=post.post_id,
            fetched=len(page.items),
            accepted=new_acc,
            rejected=new_rej,
            post_status=status,
            batch_accepted=self.accepted_total(),
            target=self.target,
        )
        return True

    # ------------------------------------------------------------------ run
    def _step(self, st: PlatformState) -> None:
        """Run one unit for a platform, converting failures into platform shutdowns."""
        try:
            if not self._work_unit(st):
                self._disable(st, "sources_exhausted")
                return
            st.consecutive_errors = 0
            if st.units_without_accept >= self.max_empty:
                self._disable(st, "no_accepted_records_in_recent_pages")
        except QuotaExceededError as exc:
            self.db.rollback()
            self._disable(st, "quota_exceeded", exc)
        except RateLimitError as exc:
            self.db.rollback()
            self._disable(st, "rate_limited", exc)
        except (ConfigurationError, AuthError) as exc:
            self.db.rollback()
            self._disable(st, "auth_or_config_error", exc)
        except ScraperError as exc:
            self.db.rollback()
            st.errors += 1
            st.consecutive_errors += 1
            self.db.log_error(self.batch_id, st.name, "request", "api_error", str(exc), exc.status)
            log_event(log, "api_error", platform=st.name, status=exc.status, error=str(exc)[:300])
            if st.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                self._disable(st, "too_many_consecutive_errors", exc)
        except Exception as exc:  # isolate unexpected connector bugs from other platforms
            self.db.rollback()
            log.exception("unexpected_error", extra={"platform": st.name})
            self._disable(st, "unexpected_error", exc)
        else:
            return
        self._refresh_counts()  # a rolled-back unit may have touched the in-memory counts

    def run(self) -> dict:
        started = time.monotonic()
        accepted = self.accepted_total()
        log_event(
            log,
            "collection_start",
            batch_id=self.batch_id,
            domain=self.domain,
            target=self.target,
            already_accepted=accepted,
            platforms=[s.name for s in self.states],
            post_cap=self.limits.post_cap,
            creator_cap=self.limits.creator_cap,
        )
        outcome = "incomplete"
        try:
            while accepted < self.target and outcome == "incomplete":
                active = [s for s in self.states if s.active]
                if not active:
                    break
                for st in active:
                    if self.max_runtime and time.monotonic() - started > self.max_runtime:
                        outcome = "time_limit"
                        break
                    self._step(st)
                    accepted = self.accepted_total()
                    if accepted >= self.target:
                        break
            if accepted >= self.target:
                outcome = "completed"
        except KeyboardInterrupt:
            outcome = "interrupted"
            self.db.commit()
        finally:
            elapsed = time.monotonic() - started
            self.db.add_batch_elapsed(self.batch_id, elapsed)
            self.db.update_batch(
                self.batch_id,
                status=outcome,
                finished_at=utcnow() if outcome == "completed" else None,
            )
            if self.pipeline.raw is not None:
                self.pipeline.raw.flush()

        summary = {
            "batch_id": self.batch_id,
            "outcome": outcome,
            "accepted": self.accepted_total(),
            "target": self.target,
            "run_seconds": round(time.monotonic() - started, 1),
            "platforms": {
                s.name: {
                    "active": s.active,
                    "stop_reason": s.stop_reason,
                    "pages": s.pages,
                    "fetched": s.fetched,
                    "accepted": s.accepted,
                    "rejected": s.rejected,
                    "errors": s.errors,
                    "posts_skipped_creator_cap": len(s.skipped_posts),
                    "http": s.scraper.stats(),
                }
                for s in self.states
            },
            "run_counters": dict(vars(self.pipeline.counters)),
            "limits": dict(vars(self.limits)),
        }
        log_event(log, "collection_end", **summary)
        if outcome == "interrupted":
            raise KeyboardInterrupt
        return summary
