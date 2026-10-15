"""Per-item processing: clean -> raw log -> quality -> language -> dedup -> store.

Identical for every platform. Nothing is generated or rewritten: the stored
``comment_text`` is the platform text with only invalid Unicode / control
characters removed (see processing.normalize.clean_text).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional

from core.config import Config
from core.logging_setup import get_logger, log_event
from core.models import RawItem, Record
from processing.anonymize import Anonymizer
from processing.dedup import DedupIndex
from processing.language import LanguageDetector
from processing.normalize import clean_text
from processing.quality import QualityFilter
from storage.database import Database, utcnow
from storage.exporter import RawWriter

log = get_logger("pipeline")

PLATFORM_PREFIX = {"youtube": "yt", "facebook": "fb", "instagram": "ig", "tiktok": "tt"}


def record_key(platform: str, item_id: str) -> str:
    return f"{platform}:{item_id}"


def sample_id(platform: str, item_id: str) -> str:
    """Stable, reproducible sample id derived from platform + platform item id."""
    digest = hashlib.sha256(record_key(platform, item_id).encode("utf-8")).hexdigest()[:16]
    return f"{PLATFORM_PREFIX.get(platform, platform[:2])}_{digest}"


@dataclass
class Counters:
    fetched: int = 0
    already_processed: int = 0
    deferred: int = 0
    accepted: int = 0
    rejected: int = 0
    retro_rejected: int = 0
    reasons: dict = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.rejected += 1
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


class Pipeline:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        batch_id: str,
        domain: str,
        anonymizer: Anonymizer,
        raw_writer: Optional[RawWriter] = None,
    ):
        self.cfg = cfg
        self.db = db
        self.batch_id = batch_id
        self.domain = domain
        self.anon = anonymizer
        self.raw = raw_writer
        qcfg = cfg.section("quality")
        self.quality = QualityFilter(qcfg)
        self.lang = LanguageDetector(cfg.section("language"), cfg.root)
        self.accept_langs = set(cfg.get("language.accept", ["bangla", "banglish", "mixed"]))
        self.dedup = DedupIndex(
            db,
            cfg.section("dedup"),
            enabled=bool(qcfg.get("duplicate_detection", True)),
            near_enabled=bool(qcfg.get("near_duplicate_detection", True)),
        )
        self.bot_threshold = int(qcfg.get("bot_copy_author_threshold", 3))
        self.bot_min_len = int(qcfg.get("bot_copy_min_length", 25))
        self.counters = Counters()

    # --------------------------------------------------------------- records
    def build_record(self, item: RawItem, text: Optional[str]) -> Record:
        post = item.post
        if item.record_type == "reply":
            context = item.parent_text
        elif item.record_type == "post":
            context = None
        else:
            context = post.title if post.title is not None else post.text
        return Record(
            sample_id=sample_id(item.platform, item.item_id),
            platform=item.platform,
            domain=self.domain,
            record_type=item.record_type,
            comment_text=text,
            post_title=post.title,
            post_text=post.text,
            context_text=clean_text(context) if context is not None else None,
            post_id=post.post_id,
            comment_id=item.item_id if item.record_type != "post" else None,
            parent_comment_id=item.parent_comment_id,
            source_url=item.url or post.url,
            author_anonymous_id=self.anon.author_id(item.platform, item.author_key),
            comment_created_at=item.created_at,
            post_created_at=post.created_at,
            like_count=item.like_count,
            reply_count=item.reply_count,
            collected_at=utcnow(),
            language=None,
            source_name=post.source_name,
            source_type=post.source_type,
            source_id=post.source_id,
            batch_id=self.batch_id,
        )

    # ---------------------------------------------------------------- deferral
    def defer(self, item: RawItem, why: str) -> None:
        """Item not processed because a diversity cap was hit. Logged to raw only, NOT marked processed."""
        self.counters.deferred += 1
        if self.raw is not None:
            rec = self.build_record(item, clean_text(item.text)).to_dict()
            rec["pipeline_status"] = "deferred"
            rec["pipeline_detail"] = why
            self.raw.write(item.platform, rec)

    # --------------------------------------------------------------- process
    def process(self, item: RawItem) -> str:
        """Returns 'accepted', 'rejected' or 'skipped' (already processed earlier)."""
        self.counters.fetched += 1
        if self.db.is_processed(item.platform, item.item_id):
            self.counters.already_processed += 1
            return "skipped"

        key = record_key(item.platform, item.item_id)
        text = clean_text(item.text)
        record = self.build_record(item, text)
        lang_result = self.lang.detect(text) if text else None
        record.language = lang_result.label if lang_result else None
        rec = record.to_dict()

        status, reason, detail, keys = "accepted", None, None, None
        if not record.post_id or not record.source_url:
            status, reason, detail = "rejected", "invalid_source", "missing_post_id_or_url"
        if status == "accepted":
            q = self.quality.check(text)
            if not q.ok:
                status, reason, detail = "rejected", q.reason, q.detail
        if status == "accepted" and record.language not in self.accept_langs:
            status, reason, detail = "rejected", "wrong_language", f"detected:{record.language}"
        if status == "accepted":
            keys = self.dedup.keys(text)
            d = self.dedup.check(keys, self.batch_id)
            if d.status:
                status, reason = "rejected", d.status
                detail = f"{d.detail}; matches {d.matched_key}"
                if d.similarity is not None and d.status == "near_duplicate":
                    detail += f"; jaccard={d.similarity}"
                self._track_copy(d.matched_key, record.author_anonymous_id)

        if self.raw is not None:
            raw_row = dict(rec)
            raw_row["pipeline_status"] = status
            raw_row["pipeline_detail"] = reason
            self.raw.write(item.platform, raw_row)

        self.db.insert_comment(
            key,
            self.batch_id,
            rec,
            status,
            reason,
            detail,
            keys.exact_hash if keys else None,
            keys.skeleton if keys else None,
        )
        if status == "accepted":
            self.dedup.register(keys, key, self.batch_id, record.author_anonymous_id)
            self.counters.accepted += 1
        else:
            self.counters.reject(reason)
        self.db.mark_processed(item.platform, item.item_id, self.batch_id, status)
        return status

    def _track_copy(self, original_key: Optional[str], author: Optional[str]) -> None:
        """Detect copy-pasted / bot texts posted by many different accounts."""
        if not original_key or not author:
            return
        orig = self.db.get_comment(original_key)
        if orig is None or orig["status"] != "accepted":
            return
        authors = self.dedup.note_copy(orig["exact_hash"], author)
        if authors >= self.bot_threshold and (orig["text_length"] or 0) >= self.bot_min_len:
            if self.db.retro_reject(original_key, "spam", f"bot_copy:{authors}_distinct_authors"):
                self.counters.retro_rejected += 1
                log_event(log, "retro_rejected_bot_copy", record_key=original_key, distinct_authors=authors)
