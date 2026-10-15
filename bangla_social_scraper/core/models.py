"""Data models shared by all connectors and the pipeline.

Connectors only ever fill fields with values the platform actually returned.
Anything unavailable stays ``None`` (exported as null / empty cell).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# Column order of the final research files.
OUTPUT_FIELDS = [
    "sample_id",
    "platform",
    "domain",
    "record_type",
    "comment_text",
    "post_title",
    "post_text",
    "context_text",
    "post_id",
    "comment_id",
    "parent_comment_id",
    "source_url",
    "author_anonymous_id",
    "comment_created_at",
    "post_created_at",
    "like_count",
    "reply_count",
    "collected_at",
    "language",
    "source_name",
    "source_type",
    "source_id",
    "batch_id",
]

REJECTED_EXTRA_FIELDS = ["rejection_reason", "rejection_detail"]

REJECTION_REASONS = (
    "duplicate",
    "near_duplicate",
    "wrong_language",
    "too_low_quality",
    "spam",
    "empty",
    "emoji_only",
    "invalid_source",
    "missing_text",
)


@dataclass
class Source:
    """A creator / page / channel / account."""

    platform: str
    source_id: str
    source_name: Optional[str] = None
    source_type: Optional[str] = None  # youtube_channel, facebook_page, instagram_account, tiktok_creator
    url: Optional[str] = None


@dataclass
class Post:
    """A video / post / reel whose comments can be collected."""

    platform: str
    post_id: str
    source_id: Optional[str] = None
    source_name: Optional[str] = None
    source_type: Optional[str] = None  # youtube_video, facebook_post, instagram_reel, tiktok_video, ...
    title: Optional[str] = None
    text: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[str] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    discovered_via: Optional[str] = None  # keyword / hashtag / configured page
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawItem:
    """One comment / reply / post caption exactly as returned by the platform."""

    platform: str
    item_id: str  # comment id (or post id for record_type=post)
    record_type: str  # comment | reply | post
    text: Optional[str]
    post: Post
    parent_comment_id: Optional[str] = None
    parent_text: Optional[str] = None
    author_key: Optional[str] = None  # platform author id — hashed before storage, never exported
    created_at: Optional[str] = None
    like_count: Optional[int] = None
    reply_count: Optional[int] = None
    url: Optional[str] = None  # direct link to the comment if the platform provides one


@dataclass
class Record:
    sample_id: str
    platform: str
    domain: str
    record_type: str
    comment_text: Optional[str]
    post_title: Optional[str]
    post_text: Optional[str]
    context_text: Optional[str]
    post_id: Optional[str]
    comment_id: Optional[str]
    parent_comment_id: Optional[str]
    source_url: Optional[str]
    author_anonymous_id: Optional[str]
    comment_created_at: Optional[str]
    post_created_at: Optional[str]
    like_count: Optional[int]
    reply_count: Optional[int]
    collected_at: str
    language: Optional[str]
    source_name: Optional[str]
    source_type: Optional[str]
    source_id: Optional[str]
    batch_id: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Page:
    """One page of items fetched for a post, with the cursor to continue."""

    items: list[RawItem]
    next_cursor: Optional[str]  # None => post finished
