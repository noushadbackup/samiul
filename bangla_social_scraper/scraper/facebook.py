"""Facebook connector — official Graph API, public Pages only.

Legitimate access paths (choose one, put the token in FACEBOOK_ACCESS_TOKEN):

1. App with the **Page Public Content Access (PPCA)** feature approved through
   Meta App Review. Lets an app read public posts/comments of public Pages and
   use Pages Search.
2. A **Page access token** for Pages you (or your institution) manage.

What is collected: comments on posts of public Pages listed in
``sources.facebook.pages.<domain>`` and (if PPCA allows) Pages found by
keyword search. Personal profiles, groups and anything behind a login wall are
never touched.

Note: Meta only returns the commenter (``from``) to Page tokens; with PPCA the
author is usually absent and author_anonymous_id stays null.
For large-scale academic work Meta's official route is the Meta Content
Library / API (application via ICPSR/SOMAR), which is not a public HTTP API and
therefore not automated here.
"""

from __future__ import annotations

from typing import Optional

from core.logging_setup import log_event
from core.models import Page, Post, RawItem, Source
from scraper.base import BaseScraper, DiscoveryResult
from scraper.http import ResourceError
from scraper.meta_common import graph_url, meta_classify, next_after

POST_FIELDS = (
    "id,message,created_time,permalink_url,"
    "comments.summary(true).limit(0),reactions.summary(true).limit(0)"
)
COMMENT_FIELDS = "id,message,created_time,like_count,comment_count,parent{id},from{id},permalink_url"


def _int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


class FacebookScraper(BaseScraper):
    platform = "facebook"
    required_env = ("FACEBOOK_ACCESS_TOKEN",)

    def classify_response(self, resp, payload):
        return meta_classify(resp, payload)

    def _get(self, path: str, params: dict) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        params["access_token"] = self.env("FACEBOOK_ACCESS_TOKEN")
        return self.http.get(graph_url(self.cfg, path), params=params)

    # ------------------------------------------------------------- discovery
    def configured_targets(self, domain: str) -> list[str]:
        return [str(p) for p in ((self.cfg.get("pages") or {}).get(domain) or [])]

    def discover(self, domain: str, keyword: str, state: dict) -> DiscoveryResult:
        """Keyword -> public Pages via Pages Search (requires PPCA). Pages become crawl targets."""
        if not self.cfg.get("use_page_search", True):
            return DiscoveryResult(posts=[], state=state, exhausted=True)
        try:
            data = self._get("pages/search", {"q": keyword, "fields": "id,name,link", "limit": 25})
        except ResourceError as exc:
            log_event(
                self.log,
                "page_search_unavailable",
                platform=self.platform,
                keyword=keyword,
                reason=str(exc)[:200],
                note="Token lacks Page Public Content Access; using configured pages only.",
            )
            return DiscoveryResult(posts=[], state={"search_unavailable": True}, exhausted=True)
        sources, targets = [], []
        for p in data.get("data", []) or []:
            pid = p.get("id")
            if not pid:
                continue
            targets.append(pid)
            sources.append(
                Source(self.platform, pid, p.get("name"), "facebook_page", p.get("link") or f"https://www.facebook.com/{pid}")
            )
        return DiscoveryResult(posts=[], sources=sources, state={"pages": 1}, exhausted=True, new_targets=targets)

    def discover_target(self, domain: str, target: str, state: dict) -> DiscoveryResult:
        """Read recent public posts of one Page."""
        pages_done = int(state.get("pages", 0))
        if pages_done >= int(self.cfg.get("max_posts_pages_per_source", 4)):
            return DiscoveryResult(posts=[], state=state, exhausted=True)
        try:
            page_info = state.get("page") or self._get(target, {"fields": "id,name,link"})
            data = self._get(
                f"{page_info.get('id', target)}/posts",
                {"fields": POST_FIELDS, "limit": 25, "after": state.get("after")},
            )
        except ResourceError as exc:
            log_event(self.log, "page_unavailable", platform=self.platform, page=target, reason=str(exc)[:200])
            return DiscoveryResult(posts=[], state={"error": str(exc)[:200]}, exhausted=True)

        page_id = page_info.get("id", target)
        source = Source(
            self.platform,
            page_id,
            page_info.get("name"),
            "facebook_page",
            page_info.get("link") or f"https://www.facebook.com/{page_id}",
        )
        keywords = [k.casefold() for k in self.domain_keywords]
        posts = []
        for p in data.get("data", []) or []:
            message = p.get("message")
            if self.cfg.get("require_keyword_match") and keywords:
                if not message or not any(k in message.casefold() for k in keywords):
                    continue
            comments = (p.get("comments") or {}).get("summary") or {}
            reactions = (p.get("reactions") or {}).get("summary") or {}
            count = _int(comments.get("total_count"))
            if count == 0:
                continue
            posts.append(
                Post(
                    platform=self.platform,
                    post_id=p["id"],
                    source_id=page_id,
                    source_name=page_info.get("name"),
                    source_type="facebook_post",
                    title=None,  # Facebook posts have no title
                    text=message,
                    url=p.get("permalink_url") or f"https://www.facebook.com/{p['id']}",
                    created_at=p.get("created_time"),
                    like_count=None,  # reactions are not likes; kept separately below
                    comment_count=count,
                    discovered_via=f"page:{target}",
                    extra={"reactions_total": _int(reactions.get("total_count"))},
                )
            )
        after = next_after(data)
        return DiscoveryResult(
            posts=posts,
            sources=[source],
            state={"page": page_info, "after": after, "pages": pages_done + 1},
            exhausted=after is None or pages_done + 1 >= int(self.cfg.get("max_posts_pages_per_source", 4)),
        )

    # -------------------------------------------------------------- comments
    def fetch_page(self, post: Post, cursor: Optional[str]) -> Page:
        data = self._get(
            f"{post.post_id}/comments",
            {
                "fields": COMMENT_FIELDS,
                "filter": "stream",  # top-level comments and replies, with parent{id}
                "order": "chronological",
                "limit": 100,
                "after": cursor,
            },
        )
        texts: dict[str, Optional[str]] = {}
        items = []
        for c in data.get("data", []) or []:
            cid = c.get("id")
            if not cid:
                continue
            parent_id = (c.get("parent") or {}).get("id")
            texts[cid] = c.get("message")
            items.append(
                RawItem(
                    platform=self.platform,
                    item_id=cid,
                    record_type="reply" if parent_id else "comment",
                    text=c.get("message"),
                    post=post,
                    parent_comment_id=parent_id,
                    parent_text=texts.get(parent_id) if parent_id else None,
                    author_key=(c.get("from") or {}).get("id"),
                    created_at=c.get("created_time"),
                    like_count=_int(c.get("like_count")),
                    reply_count=_int(c.get("comment_count")),
                    url=c.get("permalink_url") or post.url,
                )
            )
        return Page(items=items, next_cursor=next_after(data))
