"""YouTube connector — official YouTube Data API v3 only (API key, public data).

Endpoints and quota cost (default quota: 10,000 units/day per Google Cloud project):
  search.list          100 units  – keyword discovery of public videos
  videos.list            1 unit   – exact titles/descriptions + comment counts
  commentThreads.list    1 unit   – up to 100 top-level comments (+ up to 5 replies each)
  comments.list          1 unit   – remaining replies (only if fetch_all_replies: true)

Quota is tracked locally in SQLite (reset at midnight Pacific Time, like
Google's) and the connector stops before the configured daily budget.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

try:
    from zoneinfo import ZoneInfo

    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - tzdata missing
    _PACIFIC = None

from core.logging_setup import log_event
from core.models import Page, Post, RawItem, Source
from scraper.base import BaseScraper, DiscoveryResult
from scraper.http import QuotaExceededError, ResourceError

COSTS = {"search": 100, "videos": 1, "commentThreads": 1, "comments": 1}


def _int(value) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class YouTubeScraper(BaseScraper):
    platform = "youtube"
    required_env = ("YOUTUBE_API_KEY",)

    # ---------------------------------------------------------------- errors
    def classify_response(self, resp, payload):
        if resp.status_code < 400:
            return None
        reasons = set()
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            for e in payload["error"].get("errors", []) or []:
                if isinstance(e, dict) and e.get("reason"):
                    reasons.add(e["reason"])
            for d in payload["error"].get("details", []) or []:  # google.rpc.ErrorInfo
                if isinstance(d, dict) and d.get("reason"):
                    reasons.add(d["reason"])
            status = payload["error"].get("status")
            if status:
                reasons.add(status)
        if reasons & {"quotaExceeded", "dailyLimitExceeded", "dailyLimitExceededUnreg"}:
            return "quota"
        if reasons & {"rateLimitExceeded", "userRateLimitExceeded", "RESOURCE_EXHAUSTED"} or resp.status_code == 429:
            return "rate_limit"
        if reasons & {"commentsDisabled", "videoNotFound", "channelNotFound", "commentThreadNotFound", "processingFailure"}:
            return "resource"
        if reasons & {
            "API_KEY_INVALID",
            "API_KEY_EXPIRED",
            "API_KEY_SERVICE_BLOCKED",
            "API_KEY_HTTP_REFERRER_BLOCKED",
            "API_KEY_IP_ADDRESS_BLOCKED",
            "SERVICE_DISABLED",
        }:
            return "auth"
        if reasons & {"keyInvalid", "keyExpired", "accessNotConfigured", "PERMISSION_DENIED", "ipRefererBlocked", "forbidden"} and resp.status_code in (400, 401, 403):
            # "forbidden" on commentThreads usually means comments are restricted for this video
            if "forbidden" in reasons and "PERMISSION_DENIED" not in reasons and "/commentThreads" in resp.url:
                return "resource"
            return "auth"
        if resp.status_code == 404:
            return "resource"
        if resp.status_code >= 500:
            return "retry"
        return "fatal"

    # ----------------------------------------------------------------- quota
    def _quota_day(self) -> str:
        now = datetime.now(_PACIFIC) if _PACIFIC else datetime.utcnow()
        return now.strftime("%Y-%m-%d")

    def _call(self, endpoint: str, params: dict) -> dict:
        cost = COSTS[endpoint]
        budget = int(self.cfg.get("daily_quota_units", 9000))
        if self.db is not None:
            used = self.db.quota_used(self.platform, self._quota_day())
            if used + cost > budget:
                raise QuotaExceededError(
                    f"Local YouTube quota budget reached ({used}/{budget} units today, Pacific time). "
                    "Resume after midnight Pacific or raise daily_quota_units if your project has more quota."
                )
        params = {k: v for k, v in params.items() if v is not None}
        params["key"] = self.env("YOUTUBE_API_KEY")
        base = self.cfg.get("api_base", "https://www.googleapis.com/youtube/v3").rstrip("/")
        try:
            return self.http.get(f"{base}/{endpoint}", params=params)
        finally:
            # Google charges for failed requests too.
            if self.db is not None:
                self.db.add_quota(self.platform, cost, self._quota_day())

    # ------------------------------------------------------------- discovery
    def discover(self, domain: str, keyword: str, state: dict) -> DiscoveryResult:
        pages_done = int(state.get("pages", 0))
        max_pages = int(self.cfg.get("max_search_pages_per_keyword", 5))
        if pages_done >= max_pages or state.get("done"):
            return DiscoveryResult(posts=[], state=state, exhausted=True)

        search = self._call(
            "search",
            {
                "part": "snippet",
                "q": keyword,
                "type": "video",
                "maxResults": 50,
                "regionCode": self.cfg.get("region_code"),
                "relevanceLanguage": self.cfg.get("relevance_language"),
                "order": self.cfg.get("search_order", "relevance"),
                "publishedAfter": self.cfg.get("published_after"),
                "pageToken": state.get("page_token"),
                "safeSearch": "none",
            },
        )
        video_ids = []
        for item in search.get("items", []) or []:
            vid = (item.get("id") or {}).get("videoId")
            if vid and vid not in video_ids:
                video_ids.append(vid)

        posts, sources = self._load_videos(video_ids, keyword)
        next_token = search.get("nextPageToken")
        new_state = {"page_token": next_token, "pages": pages_done + 1, "done": not next_token}
        log_event(
            self.log,
            "discovery_page",
            platform=self.platform,
            domain=domain,
            keyword=keyword,
            page=pages_done + 1,
            videos_found=len(video_ids),
            videos_usable=len(posts),
        )
        return DiscoveryResult(
            posts=posts,
            sources=sources,
            state=new_state,
            exhausted=not next_token or pages_done + 1 >= max_pages,
        )

    def _load_videos(self, video_ids: list[str], keyword: str) -> tuple[list[Post], list[Source]]:
        if not video_ids:
            return [], []
        data = self._call("videos", {"part": "snippet,statistics", "id": ",".join(video_ids[:50]), "maxResults": 50})
        min_comments = int(self.cfg.get("min_comment_count", 5))
        posts, sources = [], {}
        for v in data.get("items", []) or []:
            snip = v.get("snippet") or {}
            stats = v.get("statistics") or {}
            comment_count = _int(stats.get("commentCount"))
            if comment_count is None or comment_count < min_comments:
                continue  # comments disabled or too few to be worth a request
            channel_id = snip.get("channelId")
            if channel_id and channel_id not in sources:
                sources[channel_id] = Source(
                    platform=self.platform,
                    source_id=channel_id,
                    source_name=snip.get("channelTitle"),
                    source_type="youtube_channel",
                    url=f"https://www.youtube.com/channel/{channel_id}",
                )
            posts.append(
                Post(
                    platform=self.platform,
                    post_id=v["id"],
                    source_id=channel_id,
                    source_name=snip.get("channelTitle"),
                    source_type="youtube_video",
                    title=snip.get("title"),
                    text=snip.get("description"),
                    url=f"https://www.youtube.com/watch?v={v['id']}",
                    created_at=snip.get("publishedAt"),
                    like_count=_int(stats.get("likeCount")),
                    comment_count=comment_count,
                    discovered_via=keyword,
                    extra={
                        k: snip.get(k)
                        for k in ("defaultLanguage", "defaultAudioLanguage")
                        if snip.get(k) is not None
                    },
                )
            )
        return posts, list(sources.values())

    # -------------------------------------------------------------- comments
    @staticmethod
    def _text(snippet: dict) -> Optional[str]:
        text = snippet.get("textOriginal")
        if text is None:
            text = snippet.get("textDisplay")  # requested with textFormat=plainText
        return text

    def _comment_item(self, post: Post, c: dict, record_type: str, parent_id=None, parent_text=None, reply_count=None) -> RawItem:
        s = c.get("snippet") or {}
        author = (s.get("authorChannelId") or {}).get("value")
        cid = c.get("id")
        return RawItem(
            platform=self.platform,
            item_id=cid,
            record_type=record_type,
            text=self._text(s),
            post=post,
            parent_comment_id=parent_id,
            parent_text=parent_text,
            author_key=author,
            created_at=s.get("publishedAt"),
            like_count=_int(s.get("likeCount")),
            reply_count=reply_count,
            url=f"https://www.youtube.com/watch?v={post.post_id}&lc={cid}" if cid else post.url,
        )

    def fetch_page(self, post: Post, cursor: Optional[str]) -> Page:
        data = self._call(
            "commentThreads",
            {
                "part": "snippet,replies" if self.cfg.get("include_replies", True) else "snippet",
                "videoId": post.post_id,
                "maxResults": 100,
                "order": self.cfg.get("comment_order", "relevance"),
                "textFormat": "plainText",
                "pageToken": cursor,
            },
        )
        items: list[RawItem] = []
        for thread in data.get("items", []) or []:
            tsnip = thread.get("snippet") or {}
            top = tsnip.get("topLevelComment") or {}
            if not top.get("id"):
                continue
            total_replies = _int(tsnip.get("totalReplyCount"))
            top_item = self._comment_item(post, top, "comment", reply_count=total_replies)
            items.append(top_item)
            if not self.cfg.get("include_replies", True):
                continue
            embedded = (thread.get("replies") or {}).get("comments", []) or []
            if self.cfg.get("fetch_all_replies", False) and total_replies and total_replies > len(embedded):
                try:
                    embedded = self._all_replies(top["id"])
                except ResourceError:
                    pass
            for r in embedded:
                if r.get("id"):
                    items.append(
                        self._comment_item(post, r, "reply", parent_id=top["id"], parent_text=top_item.text)
                    )
        return Page(items=items, next_cursor=data.get("nextPageToken"))

    def _all_replies(self, parent_id: str) -> list[dict]:
        out: list[dict] = []
        token = None
        while True:
            data = self._call(
                "comments",
                {"part": "snippet", "parentId": parent_id, "maxResults": 100, "textFormat": "plainText", "pageToken": token},
            )
            out.extend(data.get("items", []) or [])
            token = data.get("nextPageToken")
            if not token:
                return out
