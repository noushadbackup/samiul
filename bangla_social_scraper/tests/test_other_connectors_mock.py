"""Parsing / error-classification tests for Facebook, Instagram and TikTok
connectors using canned MOCK API payloads (shapes follow the official docs)."""

import pytest

from core.collector import Collector
from core.models import Post
from core.pipeline import Pipeline
from core.stats import batch_stats
from processing.anonymize import Anonymizer
from scraper.facebook import FacebookScraper
from scraper.http import HttpClient, QuotaExceededError, RateLimitError, ResourceError
from scraper.instagram import InstagramScraper, keyword_to_hashtag
from scraper.tiktok import TikTokScraper
from storage.database import Database
from tests.conftest import FakeResponse


class Router:
    """requests.Session stand-in: routes by URL substring to canned payloads."""

    headers: dict = {}

    def __init__(self, routes):
        self.routes = routes  # list of (substring, status, payload)
        self.calls = []

    def request(self, method, url, params=None, json=None, data=None, headers=None, timeout=None, **kw):
        self.calls.append((method, url, params, json))
        for sub, status, payload in self.routes:
            if sub in url:
                return FakeResponse(status, payload, url=url)
        return FakeResponse(404, {"error": {"code": 803, "message": "unknown route"}}, url=url)


def make(cls, cfg_dict, router, db=None):
    http = HttpClient(cls.platform, {"request_delay_seconds": 0, "max_retries": 1, "backoff_base_seconds": 0}, session=router)
    http.sleep = lambda s: None
    sc = cls(cfg_dict, db=db, http=http)
    http.classifier = sc.classify_response
    return sc


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("FACEBOOK_ACCESS_TOKEN", "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_BUSINESS_ACCOUNT_ID", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"):
        monkeypatch.setenv(k, "MOCK")


# ----------------------------------------------------------------- Facebook
FB_POSTS = {
    "data": [
        {
            "id": "111_222",
            "message": "MOCK পোস্ট",
            "created_time": "2026-01-01T10:00:00+0000",
            "permalink_url": "https://www.facebook.com/111/posts/222",
            "comments": {"summary": {"total_count": 3}},
            "reactions": {"summary": {"total_count": 9}},
        },
        {"id": "111_333", "message": "no comments", "comments": {"summary": {"total_count": 0}}},
    ],
    "paging": {"cursors": {"after": "AFTER1"}, "next": "https://graph.facebook.com/next"},
}
FB_COMMENTS = {
    "data": [
        {"id": "c1", "message": "MOCK মন্তব্য এক", "created_time": "2026-01-01T11:00:00+0000", "like_count": 2, "comment_count": 1, "from": {"id": "u1"}},
        {"id": "c2", "message": "MOCK উত্তর", "created_time": "2026-01-01T12:00:00+0000", "like_count": 0, "comment_count": 0, "parent": {"id": "c1"}},
    ],
    "paging": {"cursors": {"after": "X"}},
}


def test_facebook_page_posts_and_comments():
    router = Router([
        ("/posts", 200, FB_POSTS),
        ("/comments", 200, FB_COMMENTS),
        ("v23.0/mockpage", 200, {"id": "111", "name": "Mock Page", "link": "https://www.facebook.com/mockpage"}),
    ])
    fb = make(FacebookScraper, {"pages": {"sports": ["mockpage"]}}, router)
    assert fb.configured_targets("sports") == ["mockpage"]
    res = fb.discover_target("sports", "mockpage", {})
    assert [p.post_id for p in res.posts] == ["111_222"]  # zero-comment post skipped
    assert res.posts[0].like_count is None and res.posts[0].extra["reactions_total"] == 9
    assert res.state["after"] == "AFTER1" and not res.exhausted
    page = fb.fetch_page(res.posts[0], None)
    assert [i.record_type for i in page.items] == ["comment", "reply"]
    assert page.items[1].parent_comment_id == "c1" and page.items[1].parent_text == "MOCK মন্তব্য এক"
    assert page.items[0].author_key == "u1" and page.items[1].author_key is None
    assert page.next_cursor is None  # no paging.next


def test_facebook_page_search_without_ppca_falls_back():
    router = Router([("pages/search", 400, {"error": {"code": 10, "message": "requires Page Public Content Access"}})])
    fb = make(FacebookScraper, {}, router)
    res = fb.discover("sports", "bd cricket", {})
    assert res.exhausted and res.posts == [] and res.state.get("search_unavailable")


@pytest.mark.parametrize("code,exc", [(4, RateLimitError), (32, RateLimitError), (100, ResourceError)])
def test_facebook_error_classification(code, exc):
    router = Router([("/comments", 400, {"error": {"code": code, "message": "x"}})])
    fb = make(FacebookScraper, {}, router)
    with pytest.raises(exc):
        fb.fetch_page(Post("facebook", "p1", url="https://www.facebook.com/p1"), None)


# ---------------------------------------------------------------- Instagram
def test_instagram_hashtag_captions():
    router = Router([
        ("ig_hashtag_search", 200, {"data": [{"id": "H1"}]}),
        ("H1/top_media", 200, {"data": [{"id": "M1", "caption": "MOCK ক্যাপশন #bdcricket", "media_product_type": "REELS", "comments_count": 4, "like_count": 7, "permalink": "https://www.instagram.com/reel/M1/", "timestamp": "2026-01-01T00:00:00+0000"}]}),
    ])
    ig = make(InstagramScraper, {"hashtag_edges": ["top_media"], "max_media_pages_per_hashtag": 1}, router)
    res = ig.discover("sports", "bd cricket", {})
    assert router.calls[0][2]["q"] == "bdcricket"
    assert res.exhausted and res.posts[0].source_type == "instagram_reel" and res.posts[0].source_id is None
    page = ig.fetch_page(res.posts[0], None)
    assert len(page.items) == 1 and page.items[0].record_type == "post"
    assert page.items[0].text == "MOCK ক্যাপশন #bdcricket" and page.next_cursor is None


def test_keyword_to_hashtag():
    assert keyword_to_hashtag("Bangladesh Cricket") == "bangladeshcricket"
    assert keyword_to_hashtag("#বাংলা গান") == "বাংলাগান"


# ------------------------------------------------------------------- TikTok
TT_VIDEOS = {
    "data": {
        "videos": [
            {"id": 7300000000000000001, "video_description": "MOCK ভিডিও", "create_time": 1767225600, "region_code": "BD", "like_count": 5, "comment_count": 20, "username": "mock_creator"},
            {"id": 7300000000000000002, "video_description": "few", "create_time": 1767225600, "comment_count": 1, "username": "x"},
        ],
        "cursor": 100,
        "has_more": True,
        "search_id": "S1",
    },
    "error": {"code": "ok", "message": ""},
}
TT_COMMENTS = {
    "data": {
        "comments": [
            {"id": 1, "video_id": 7300000000000000001, "text": "MOCK কমেন্ট", "like_count": 3, "reply_count": 1, "parent_comment_id": 7300000000000000001, "create_time": 1767225700},
            {"id": 2, "video_id": 7300000000000000001, "text": "MOCK রিপ্লাই", "like_count": 0, "reply_count": 0, "parent_comment_id": 1, "create_time": 1767225800},
        ],
        "cursor": 2,
        "has_more": False,
    },
    "error": {"code": "ok"},
}


def test_tiktok_query_and_comments(cfg):
    db = Database(cfg.path("database"))
    router = Router([
        ("oauth/token", 200, {"access_token": "T", "expires_in": 7200, "token_type": "Bearer"}),
        ("video/query", 200, TT_VIDEOS),
        ("comment/list", 200, TT_COMMENTS),
    ])
    tt = make(TikTokScraper, {"lookback_days": 60, "max_pages_per_window": 3, "min_comment_count": 5}, router, db=db)
    res = tt.discover("sports", "bd cricket", {})
    assert [p.post_id for p in res.posts] == ["7300000000000000001"]
    assert res.posts[0].url == "https://www.tiktok.com/@mock_creator/video/7300000000000000001"
    assert res.state["cursor"] == 100 and res.state["search_id"] == "S1" and not res.exhausted
    page = tt.fetch_page(res.posts[0], None)
    assert [i.record_type for i in page.items] == ["comment", "reply"]
    assert page.items[0].parent_comment_id is None and page.items[1].parent_comment_id == "1"
    assert page.items[0].author_key is None and page.next_cursor is None
    assert db.quota_used("tiktok") == 2


def test_tiktok_rate_limit_and_budget(cfg):
    db = Database(cfg.path("database"))
    router = Router([
        ("oauth/token", 200, {"access_token": "T", "expires_in": 7200}),
        ("video/query", 429, {"error": {"code": "rate_limit_exceeded", "message": "slow down"}}),
    ])
    tt = make(TikTokScraper, {}, router, db=db)
    with pytest.raises(RateLimitError):
        tt.discover("sports", "x", {})
    tt.cfg = {"daily_request_budget": 0}
    with pytest.raises(QuotaExceededError):
        tt.discover("sports", "x", {})


# ------------------------------------------------------- multi-platform run
def test_all_platforms_round_robin_with_one_failing(cfg):
    """Facebook works, Instagram auth fails, TikTok works -> batch still completes."""
    db = Database(cfg.path("database"))
    fb_comments = {
        "data": [{"id": f"fbc{i}", "message": t, "from": {"id": f"u{i}"}} for i, t in enumerate([
            "ভাই আজকের খেলাটা দারুণ হয়েছে সত্যি", "bhai khub valo khelse aj", "কোচের সিদ্ধান্ত একদম ভুল ছিল",
            "What a great match", "😂😂",
        ])]
    }
    fb_router = Router([
        ("/posts", 200, {"data": [{"id": "P_1", "permalink_url": "https://www.facebook.com/P/1", "comments": {"summary": {"total_count": 5}}}]}),
        ("/comments", 200, fb_comments),
        ("v23.0/pg", 200, {"id": "P", "name": "Mock Page"}),
    ])
    ig_router = Router([("", 400, {"error": {"code": 190, "message": "Invalid OAuth access token"}})])
    tt_router = Router([
        ("oauth/token", 200, {"access_token": "T", "expires_in": 7200}),
        ("video/query", 200, TT_VIDEOS),
        ("comment/list", 200, {"data": {"comments": [
            {"id": 11, "text": "অসাধারণ একটা ইনিংস খেলেছে আজকে", "parent_comment_id": 7300000000000000001},
            {"id": 12, "text": "ami tomader dol k support kori sobsomoy", "parent_comment_id": 7300000000000000001},
        ], "has_more": False}, "error": {"code": "ok"}}),
    ])
    scrapers = {
        "facebook": make(FacebookScraper, {"pages": {"sports": ["pg"]}, "use_page_search": False}, fb_router),
        "instagram": make(InstagramScraper, {"hashtags": {"sports": ["bdcricket"]}}, ig_router),
        "tiktok": make(TikTokScraper, {"lookback_days": 30}, tt_router, db=db),
    }
    # tiny target: relax diversity floors so 1 post per platform may supply several rows
    cfg.data["diversity"].update({"min_distinct_posts_floor": 1, "min_distinct_creators": 1})
    db.create_batch("sports_001", "sports", list(scrapers), 5, {}, {})
    pipe = Pipeline(cfg, db, "sports_001", "sports", Anonymizer(b"MOCK"), None)
    summary = Collector(cfg, db, pipe, "sports_001", "sports", 5, scrapers, {k: ["kw"] for k in scrapers}).run()
    assert summary["platforms"]["instagram"]["stop_reason"] == "auth_or_config_error"
    st = batch_stats(db, "sports_001")
    assert st["accepted"] == 5
    assert set(st["platform_distribution"]) == {"facebook", "tiktok"}
