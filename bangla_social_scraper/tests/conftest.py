"""Shared test helpers.

EVERYTHING in the tests is MOCK DATA used only to exercise code paths. It is
generated in memory, never written to data/, and must never be mixed with the
research dataset.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config  # noqa: E402
from core.logging_setup import setup_logging  # noqa: E402

MOCK_BN_VOCAB = (
    "ভাই খেলা দারুণ আজকে ম্যাচ জিতলো হারলো দল ব্যাটিং বোলিং ফিল্ডিং অধিনায়ক টাইগার "
    "সেরা বাজে খুশি দুঃখ মাঠ দর্শক রান উইকেট ছক্কা চার আউট সিরিজ কোচ নির্বাচক "
    "সমর্থক স্বপ্ন গর্ব লজ্জা শিক্ষা অভিজ্ঞতা তরুণ পুরনো নতুন শক্তি দুর্বল আশা"
).split()
MOCK_BANGLISH_VOCAB = (
    "bhai khela valo darun aj match jitlo harlo dol batting bowling sera baje khushi "
    "dukkho mathe ami tumi apni amar kemon ache hobe korbe dekhi jani onek khub"
).split()


def mock_text(rng: random.Random, banglish: bool = False) -> str:
    vocab = MOCK_BANGLISH_VOCAB if banglish else MOCK_BN_VOCAB
    return " ".join(rng.sample(vocab, 7))


class FakeResponse:
    def __init__(self, status: int, payload, headers=None, url=""):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.url = url
        self.text = str(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeYouTube:
    """In-memory imitation of the YouTube Data API v3 endpoints we use. MOCK ONLY."""

    def __init__(self, n_videos=16, n_channels=8, comments_per_video=60, seed=7, page_size=25):
        rng = random.Random(seed)
        self.page_size = page_size
        self.calls: list[tuple[str, dict]] = []
        self.fail_quota = False
        self.videos = {}
        for v in range(n_videos):
            vid = f"MOCKVID{v:03d}"
            comments = []
            for c in range(comments_per_video):
                kind = rng.random()
                if kind < 0.55:
                    text = mock_text(rng)
                elif kind < 0.7:
                    text = mock_text(rng, banglish=True)
                elif kind < 0.78:
                    text = "What a great match, well played everyone"
                elif kind < 0.84:
                    text = "😂😂🔥"
                elif kind < 0.9:
                    text = "এই লোকটা একদম বোকা" + rng.choice(["", "।", "!"])
                else:
                    text = "subscribe my channel please"
                comments.append(
                    {
                        "id": f"{vid}_C{c:04d}",
                        "text": text,
                        "author": f"MOCKAUTHOR{rng.randrange(400)}",
                    }
                )
            self.videos[vid] = {
                "channel": f"MOCKCHAN{v % n_channels}",
                "title": f"MOCK video {v} বাংলাদেশ ক্রিকেট",
                "comments": comments,
            }

    # -- requests.Session-compatible ------------------------------------
    headers: dict = {}

    def request(self, method, url, params=None, timeout=None, **kw):
        params = dict(params or {})
        endpoint = urlparse(url).path.rsplit("/", 1)[-1]
        self.calls.append((endpoint, params))
        if self.fail_quota:
            return FakeResponse(
                403,
                {"error": {"code": 403, "message": "quota", "errors": [{"reason": "quotaExceeded"}]}},
                url=url,
            )
        if endpoint == "search":
            ids = list(self.videos)
            start = int(params.get("pageToken") or 0)
            chunk = ids[start : start + 5]
            nxt = start + 5
            return FakeResponse(
                200,
                {
                    "items": [{"id": {"videoId": v}} for v in chunk],
                    **({"nextPageToken": str(nxt)} if nxt < len(ids) else {}),
                },
                url=url,
            )
        if endpoint == "videos":
            items = []
            for vid in params["id"].split(","):
                v = self.videos[vid]
                items.append(
                    {
                        "id": vid,
                        "snippet": {
                            "channelId": v["channel"],
                            "channelTitle": f"Mock Channel {v['channel']}",
                            "title": v["title"],
                            "description": "MOCK description",
                            "publishedAt": "2026-01-01T00:00:00Z",
                        },
                        "statistics": {"commentCount": str(len(v["comments"])), "likeCount": "10"},
                    }
                )
            return FakeResponse(200, {"items": items}, url=url)
        if endpoint == "commentThreads":
            v = self.videos[params["videoId"]]
            start = int(params.get("pageToken") or 0)
            chunk = v["comments"][start : start + self.page_size]
            nxt = start + self.page_size
            items = [
                {
                    "snippet": {
                        "totalReplyCount": 0,
                        "topLevelComment": {
                            "id": c["id"],
                            "snippet": {
                                "textOriginal": c["text"],
                                "authorChannelId": {"value": c["author"]},
                                "authorDisplayName": "SHOULD NEVER BE STORED",
                                "likeCount": 1,
                                "publishedAt": "2026-01-02T00:00:00Z",
                            },
                        },
                    }
                }
                for c in chunk
            ]
            return FakeResponse(
                200,
                {"items": items, **({"nextPageToken": str(nxt)} if nxt < len(v["comments"]) else {})},
                url=url,
            )
        return FakeResponse(404, {"error": {"code": 404, "message": "not found"}}, url=url)


@pytest.fixture()
def cfg(tmp_path):
    overrides = {
        "paths": {
            "database": str(tmp_path / "state.sqlite3"),
            "raw_dir": str(tmp_path / "raw"),
            "accepted_dir": str(tmp_path / "accepted"),
            "rejected_dir": str(tmp_path / "rejected"),
            "log_dir": str(tmp_path / "logs"),
        },
        "sources": {"youtube": {"request_delay_seconds": 0, "max_retries": 1, "backoff_base_seconds": 0}},
    }
    c = load_config(ROOT / "config.yaml", overrides=overrides)
    setup_logging(c.path("log_dir"))
    return c


def parse_url_params(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
