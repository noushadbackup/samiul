"""Instagram connector — official Instagram Graph API (Business/Creator account).

Credentials: INSTAGRAM_ACCESS_TOKEN + INSTAGRAM_BUSINESS_ACCOUNT_ID (the IG
user id of YOUR professional account linked to a Facebook Page; the app needs
``instagram_basic`` and, for hashtag search, the "Instagram Public Content
Access" feature).

What the API legitimately exposes for content you do NOT own:
  * Hashtag Search  -> public posts/reels (caption, counts, permalink, time)
                       max 30 unique hashtags per 7 days per account
  * Business Discovery -> public posts/reels of other Business/Creator accounts
Comments of other people's media are NOT available through the API, so for
third-party media this connector stores the public CAPTION as a record with
record_type = "post". Comments are collected only for media owned by the
authenticated account (``collect_own_media_comments: true``).
"""

from __future__ import annotations

import unicodedata
from typing import Optional

from core.logging_setup import log_event
from core.models import Page, Post, RawItem, Source
from scraper.base import BaseScraper, DiscoveryResult
from scraper.http import ResourceError
from scraper.meta_common import graph_url, meta_classify, next_after

MEDIA_FIELDS = "id,caption,media_type,media_product_type,comments_count,like_count,permalink,timestamp"
OWN_MEDIA_TARGET = "own_media"


def _int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def keyword_to_hashtag(keyword: str) -> str:
    """'Bangladesh Cricket' -> 'bangladeshcricket'; keeps Bengali letters AND vowel signs."""
    kept = [
        ch
        for ch in keyword.strip().lstrip("#")
        if unicodedata.category(ch)[0] in ("L", "M", "N") or ch == "_"
    ]
    return "".join(kept).lower()


class InstagramScraper(BaseScraper):
    platform = "instagram"
    required_env = ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_BUSINESS_ACCOUNT_ID")

    def classify_response(self, resp, payload):
        return meta_classify(resp, payload)

    @property
    def ig_user(self) -> str:
        return self.env("INSTAGRAM_BUSINESS_ACCOUNT_ID")

    def _get(self, path: str, params: dict) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        params["access_token"] = self.env("INSTAGRAM_ACCESS_TOKEN")
        return self.http.get(graph_url(self.cfg, path), params=params)

    # --------------------------------------------------------------- helpers
    def _media_to_post(self, m: dict, via: str, source: Optional[Source], own: bool = False) -> Post:
        product = (m.get("media_product_type") or "").upper()
        return Post(
            platform=self.platform,
            post_id=m["id"],
            source_id=source.source_id if source else None,  # hashtag media do not expose the owner
            source_name=source.source_name if source else None,
            source_type="instagram_reel" if product == "REELS" else "instagram_post",
            title=None,
            text=m.get("caption"),
            url=m.get("permalink"),
            created_at=m.get("timestamp"),
            like_count=_int(m.get("like_count")),
            comment_count=_int(m.get("comments_count")),
            discovered_via=via,
            extra={"media_type": m.get("media_type"), "own": own},
        )

    # ------------------------------------------------------------- discovery
    def configured_targets(self, domain: str) -> list[str]:
        targets = [f"hashtag:{h}" for h in ((self.cfg.get("hashtags") or {}).get(domain) or [])]
        targets += [f"account:{a}" for a in ((self.cfg.get("accounts") or {}).get(domain) or [])]
        if self.cfg.get("collect_own_media_comments"):
            targets.append(OWN_MEDIA_TARGET)
        return targets

    def discover(self, domain: str, keyword: str, state: dict) -> DiscoveryResult:
        tag = keyword_to_hashtag(keyword)
        if not tag or not self.cfg.get("use_hashtag_search", True):
            return DiscoveryResult(posts=[], state=state, exhausted=True)
        return self._hashtag(tag, state)

    def discover_target(self, domain: str, target: str, state: dict) -> DiscoveryResult:
        if target.startswith("hashtag:"):
            if not self.cfg.get("use_hashtag_search", True):
                return DiscoveryResult(posts=[], state=state, exhausted=True)
            return self._hashtag(keyword_to_hashtag(target.split(":", 1)[1]), state)
        if target.startswith("account:"):
            return self._business_discovery(target.split(":", 1)[1], state)
        if target == OWN_MEDIA_TARGET:
            return self._own_media(state)
        return DiscoveryResult(posts=[], state=state, exhausted=True)

    def _hashtag(self, tag: str, state: dict) -> DiscoveryResult:
        edges = list(self.cfg.get("hashtag_edges", ["top_media", "recent_media"]))
        max_pages = int(self.cfg.get("max_media_pages_per_hashtag", 2))
        st = dict(state)
        try:
            if not st.get("hashtag_id"):
                found = self._get("ig_hashtag_search", {"user_id": self.ig_user, "q": tag})
                ids = [d.get("id") for d in found.get("data", []) or [] if d.get("id")]
                if not ids:
                    return DiscoveryResult(posts=[], state={"no_hashtag": tag}, exhausted=True)
                st.update({"hashtag_id": ids[0], "edge": 0, "edge_pages": 0, "after": None})
            edge_idx = int(st.get("edge", 0))
            if edge_idx >= len(edges):
                return DiscoveryResult(posts=[], state=st, exhausted=True)
            data = self._get(
                f"{st['hashtag_id']}/{edges[edge_idx]}",
                {"user_id": self.ig_user, "fields": MEDIA_FIELDS, "limit": 50, "after": st.get("after")},
            )
        except ResourceError as exc:
            log_event(self.log, "hashtag_unavailable", platform=self.platform, hashtag=tag, reason=str(exc)[:200])
            return DiscoveryResult(posts=[], state={"error": str(exc)[:200]}, exhausted=True)
        posts = [self._media_to_post(m, f"hashtag:{tag}", None) for m in data.get("data", []) or [] if m.get("id")]
        after = next_after(data)
        st["edge_pages"] = int(st.get("edge_pages", 0)) + 1
        if after and st["edge_pages"] < max_pages:
            st["after"] = after
        else:
            st.update({"edge": int(st.get("edge", 0)) + 1, "edge_pages": 0, "after": None})
        return DiscoveryResult(posts=posts, state=st, exhausted=int(st["edge"]) >= len(edges))

    def _business_discovery(self, username: str, state: dict) -> DiscoveryResult:
        max_pages = int(self.cfg.get("max_media_pages_per_account", 2))
        pages = int(state.get("pages", 0))
        if pages >= max_pages:
            return DiscoveryResult(posts=[], state=state, exhausted=True)
        media = f"media.limit(25){{{MEDIA_FIELDS}}}"
        if state.get("after"):
            media = f"media.after({state['after']}).limit(25){{{MEDIA_FIELDS}}}"
        try:
            data = self._get(
                self.ig_user,
                {"fields": f"business_discovery.username({username}){{id,username,name,{media}}}"},
            )
        except ResourceError as exc:
            log_event(self.log, "account_unavailable", platform=self.platform, account=username, reason=str(exc)[:200])
            return DiscoveryResult(posts=[], state={"error": str(exc)[:200]}, exhausted=True)
        bd = data.get("business_discovery") or {}
        if not bd.get("id"):
            return DiscoveryResult(posts=[], state=state, exhausted=True)
        source = Source(
            self.platform,
            bd["id"],
            bd.get("username"),
            "instagram_account",
            f"https://www.instagram.com/{bd.get('username')}/" if bd.get("username") else None,
        )
        media_block = bd.get("media") or {}
        posts = [self._media_to_post(m, f"account:{username}", source) for m in media_block.get("data", []) or [] if m.get("id")]
        after = next_after(media_block)
        return DiscoveryResult(
            posts=posts,
            sources=[source],
            state={"after": after, "pages": pages + 1},
            exhausted=after is None or pages + 1 >= max_pages,
        )

    def _own_media(self, state: dict) -> DiscoveryResult:
        data = self._get(f"{self.ig_user}/media", {"fields": MEDIA_FIELDS, "limit": 50, "after": state.get("after")})
        posts = [self._media_to_post(m, "own_media", Source(self.platform, self.ig_user), own=True) for m in data.get("data", []) or []]
        after = next_after(data)
        return DiscoveryResult(posts=posts, state={"after": after}, exhausted=after is None)

    # ------------------------------------------------------------ fetch page
    def fetch_page(self, post: Post, cursor: Optional[str]) -> Page:
        own = bool(post.extra.get("own"))
        items: list[RawItem] = []
        if cursor is None and self.cfg.get("collect_captions", True):
            items.append(
                RawItem(
                    platform=self.platform,
                    item_id=post.post_id,
                    record_type="post",
                    text=post.text,
                    post=post,
                    author_key=post.source_id,
                    created_at=post.created_at,
                    like_count=post.like_count,
                    reply_count=post.comment_count,
                    url=post.url,
                )
            )
        if not (own and self.cfg.get("collect_own_media_comments")):
            return Page(items=items, next_cursor=None)

        after = None if cursor in (None, "comments") else cursor
        data = self._get(
            f"{post.post_id}/comments",
            {
                "fields": "id,text,timestamp,like_count,from{id},replies{id,text,timestamp,like_count,from{id}}",
                "limit": 50,
                "after": after,
            },
        )
        for c in data.get("data", []) or []:
            if not c.get("id"):
                continue
            replies = (c.get("replies") or {}).get("data", []) or []
            items.append(
                RawItem(
                    platform=self.platform,
                    item_id=c["id"],
                    record_type="comment",
                    text=c.get("text"),
                    post=post,
                    author_key=(c.get("from") or {}).get("id"),
                    created_at=c.get("timestamp"),
                    like_count=_int(c.get("like_count")),
                    reply_count=len(replies) if "replies" in c else None,
                    url=post.url,
                )
            )
            for r in replies:
                if r.get("id"):
                    items.append(
                        RawItem(
                            platform=self.platform,
                            item_id=r["id"],
                            record_type="reply",
                            text=r.get("text"),
                            post=post,
                            parent_comment_id=c["id"],
                            parent_text=c.get("text"),
                            author_key=(r.get("from") or {}).get("id"),
                            created_at=r.get("timestamp"),
                            like_count=_int(r.get("like_count")),
                            url=post.url,
                        )
                    )
        return Page(items=items, next_cursor=next_after(data))
