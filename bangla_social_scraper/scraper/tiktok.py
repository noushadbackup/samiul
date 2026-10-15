"""TikTok connector — official TikTok Research API (approved researchers only).

Apply at https://developers.tiktok.com/products/research-api/ . After approval
you get a client key/secret (TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET); the
connector obtains a client-credentials token automatically.

Endpoints:
  POST /v2/oauth/token/                       client-credentials token (2 h)
  POST /v2/research/video/query/              public videos by keyword + region, 30-day windows
  POST /v2/research/video/comment/list/       public comments of one video (100 per page)

The Research API allows 1,000 requests/day; the connector keeps a local budget
(``daily_request_budget``) and stops before it. The API does not return comment
authors, so author_anonymous_id is null for TikTok rows.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.logging_setup import log_event
from core.models import Page, Post, RawItem, Source
from scraper.base import BaseScraper, DiscoveryResult
from scraper.http import AuthError, QuotaExceededError

VIDEO_FIELDS = "id,video_description,create_time,region_code,like_count,comment_count,username,hashtag_names,view_count"
COMMENT_FIELDS = "id,video_id,text,like_count,reply_count,parent_comment_id,create_time"
WINDOW_DAYS = 30


def _int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _iso(ts) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


class TikTokScraper(BaseScraper):
    platform = "tiktok"
    required_env = ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET")

    def __init__(self, cfg, db=None, http=None):
        super().__init__(cfg, db=db, http=http)
        self._token: Optional[str] = None
        self._token_expiry = 0.0

    # ---------------------------------------------------------------- errors
    def classify_response(self, resp, payload):
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            code = err.get("code")
        else:
            code = err  # OAuth endpoint returns {"error": "invalid_client", ...}
        if resp.status_code < 400 and code in (None, "ok", ""):
            return None
        code = str(code or "")
        if "quota" in code or code == "daily_quota_limit_exceeded":
            return "quota"
        if resp.status_code == 429 or code == "rate_limit_exceeded":
            return "rate_limit"
        if resp.status_code == 401 or code in ("access_token_invalid", "invalid_client", "scope_not_authorized", "scope_permission_missed", "unauthorized_client"):
            return "auth"
        if resp.status_code == 404 or code in ("invalid_video_id", "video_not_found"):
            return "resource"
        if resp.status_code >= 500 or code == "internal_error":
            return "retry"
        return "fatal"

    # ----------------------------------------------------------------- token
    def _base(self) -> str:
        return self.cfg.get("api_base", "https://open.tiktokapis.com/v2").rstrip("/")

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        data = self.http.post(
            f"{self._base()}/oauth/token/",
            data={
                "client_key": self.env("TIKTOK_CLIENT_KEY"),
                "client_secret": self.env("TIKTOK_CLIENT_SECRET"),
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token = data.get("access_token")
        if not token:
            raise AuthError(f"TikTok token request failed: {data}")
        self._token = token
        self._token_expiry = time.time() + float(data.get("expires_in", 7200))
        return token

    def _spend(self) -> None:
        budget = int(self.cfg.get("daily_request_budget", 900))
        if self.db is not None:
            used = self.db.quota_used(self.platform)
            if used + 1 > budget:
                raise QuotaExceededError(f"Local TikTok Research API budget reached ({used}/{budget} requests today, UTC).")
            self.db.add_quota(self.platform, 1)

    def _post(self, path: str, fields: str, body: dict) -> dict:
        for attempt in range(2):
            self._spend()
            try:
                return self.http.post(
                    f"{self._base()}/{path}",
                    params={"fields": fields},
                    json=body,
                    headers={"Authorization": f"Bearer {self._get_token()}", "Content-Type": "application/json"},
                )
            except AuthError:
                if attempt == 0 and self._token:
                    self._token = None  # expired token: refresh once
                    continue
                raise
        raise AuthError("TikTok authentication failed")

    # ------------------------------------------------------------- discovery
    def _window(self, idx: int) -> tuple[str, str]:
        end = datetime.now(timezone.utc).date() - timedelta(days=1 + idx * WINDOW_DAYS)
        start = end - timedelta(days=WINDOW_DAYS - 1)
        return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    def discover(self, domain: str, keyword: str, state: dict) -> DiscoveryResult:
        n_windows = max(1, int(self.cfg.get("lookback_days", 180)) // WINDOW_DAYS)
        max_pages = int(self.cfg.get("max_pages_per_window", 3))
        st = {"window": 0, "cursor": None, "search_id": None, "window_pages": 0, **state}
        if st["window"] >= n_windows:
            return DiscoveryResult(posts=[], state=st, exhausted=True)
        start, end = self._window(st["window"])
        body = {
            "query": {
                "and": [
                    {"operation": "IN", "field_name": "region_code", "field_values": list(self.cfg.get("region_codes", ["BD"]))},
                    {"operation": "EQ", "field_name": "keyword", "field_values": [keyword]},
                ]
            },
            "start_date": start,
            "end_date": end,
            "max_count": 100,
        }
        if st.get("cursor") is not None:
            body["cursor"] = st["cursor"]
        if st.get("search_id"):
            body["search_id"] = st["search_id"]
        data = (self._post("research/video/query/", VIDEO_FIELDS, body) or {}).get("data") or {}

        min_comments = int(self.cfg.get("min_comment_count", 5))
        posts, sources = [], {}
        for v in data.get("videos", []) or []:
            vid = v.get("id")
            if vid is None:
                continue
            count = _int(v.get("comment_count"))
            if count is not None and count < min_comments:
                continue
            username = v.get("username")
            if username and username not in sources:
                sources[username] = Source(self.platform, username, username, "tiktok_creator", f"https://www.tiktok.com/@{username}")
            posts.append(
                Post(
                    platform=self.platform,
                    post_id=str(vid),
                    source_id=username,
                    source_name=username,
                    source_type="tiktok_video",
                    title=None,
                    text=v.get("video_description"),
                    url=f"https://www.tiktok.com/@{username}/video/{vid}" if username else None,
                    created_at=_iso(v.get("create_time")),
                    like_count=_int(v.get("like_count")),
                    comment_count=count,
                    discovered_via=keyword,
                    extra={"region_code": v.get("region_code"), "hashtags": v.get("hashtag_names")},
                )
            )
        st["window_pages"] += 1
        if data.get("has_more") and st["window_pages"] < max_pages:
            st["cursor"], st["search_id"] = data.get("cursor"), data.get("search_id")
        else:
            st.update({"window": st["window"] + 1, "cursor": None, "search_id": None, "window_pages": 0})
        log_event(self.log, "discovery_page", platform=self.platform, keyword=keyword, window=f"{start}-{end}", videos=len(posts))
        return DiscoveryResult(posts=posts, sources=list(sources.values()), state=st, exhausted=st["window"] >= n_windows)

    # -------------------------------------------------------------- comments
    def fetch_page(self, post: Post, cursor: Optional[str]) -> Page:
        body = {"video_id": int(post.post_id), "max_count": 100, "cursor": int(cursor or 0)}
        data = (self._post("research/video/comment/list/", COMMENT_FIELDS, body) or {}).get("data") or {}
        items = []
        for c in data.get("comments", []) or []:
            cid = c.get("id")
            if cid is None:
                continue
            parent = c.get("parent_comment_id")
            # top-level comments carry the video id as their parent
            is_reply = parent is not None and str(parent) != str(post.post_id)
            items.append(
                RawItem(
                    platform=self.platform,
                    item_id=str(cid),
                    record_type="reply" if is_reply else "comment",
                    text=c.get("text"),
                    post=post,
                    parent_comment_id=str(parent) if is_reply else None,
                    author_key=None,  # not provided by the Research API
                    created_at=_iso(c.get("create_time")),
                    like_count=_int(c.get("like_count")),
                    reply_count=_int(c.get("reply_count")),
                    url=post.url,
                )
            )
        next_cursor = str(data.get("cursor")) if data.get("has_more") and data.get("cursor") is not None else None
        return Page(items=items, next_cursor=next_cursor)
