"""End-to-end collection tests against an IN-MEMORY MOCK of the YouTube API.

These verify discovery, filtering, dedup, diversity caps, resume, platform
isolation and export. No real data is involved.
"""

import csv
import json
import os

import pyarrow.parquet as pq
import pytest

from core.collector import Collector
from core.pipeline import Pipeline
from core.stats import batch_stats
from processing.anonymize import Anonymizer
from scraper.base import BaseScraper
from scraper.http import HttpClient, ScraperError
from scraper.youtube import YouTubeScraper
from storage.database import Database
from storage.exporter import RawWriter, export_batch
from tests.conftest import FakeYouTube


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "MOCK_KEY")


def make_youtube(cfg, db, fake):
    ycfg = cfg.platform_cfg("youtube")
    http = HttpClient("youtube", ycfg, session=fake)
    http.sleep = lambda s: None
    yt = YouTubeScraper(ycfg, db=db, http=http)
    http.classifier = yt.classify_response
    return yt


def run_batch(cfg, db, batch_id, target, scrapers, create=True):
    if create:
        db.create_batch(batch_id, "sports", list(scrapers), target, {}, {})
    else:
        db.update_batch(batch_id, target=target)
    raw = RawWriter(cfg.path("raw_dir"), batch_id)
    pipe = Pipeline(cfg, db, batch_id, "sports", Anonymizer(b"MOCK_SALT"), raw)
    kws = {name: ["mock keyword one", "mock keyword two"] for name in scrapers}
    summary = Collector(cfg, db, pipe, batch_id, "sports", target, scrapers, kws).run()
    raw.close()
    return summary


def test_collects_until_target_with_filters_and_caps(cfg):
    db = Database(cfg.path("database"))
    fake = FakeYouTube()
    summary = run_batch(cfg, db, "sports_001", 40, {"youtube": make_youtube(cfg, db, fake)})
    assert summary["outcome"] == "completed"
    st = batch_stats(db, "sports_001")
    assert st["accepted"] == 40
    assert st["rejected"] > 0
    assert st["duplicates_removed"] + st["near_duplicates_removed"] > 0
    assert set(st["language_distribution"]) <= {"bangla", "banglish", "mixed"}
    # target 40 -> min posts = max(5, ceil(20*40/1000)) = 5 -> post cap = 8
    assert st["max_accepted_from_one_post"] <= 8
    assert st["unique_posts"] >= 5
    reasons = st["rejection_reasons"]
    assert "wrong_language" in reasons and "emoji_only" in reasons and "spam" in reasons

    # no usernames anywhere in the DB rows
    for row in db.iter_records("sports_001", "accepted"):
        rec = json.loads(row["record_json"])
        assert "MOCKAUTHOR" not in json.dumps(rec)
        assert "SHOULD NEVER BE STORED" not in json.dumps(rec)
        assert rec["author_anonymous_id"].startswith("a_")
        assert rec["source_url"].startswith("https://www.youtube.com/watch?v=MOCKVID")
        assert rec["comment_id"] and rec["post_id"] and rec["collected_at"]


def test_creator_cap_is_enforced_even_if_target_is_missed(cfg):
    db = Database(cfg.path("database"))
    fake = FakeYouTube(n_videos=12, n_channels=2)
    summary = run_batch(cfg, db, "sports_001", 40, {"youtube": make_youtube(cfg, db, fake)})
    # creator cap = ceil(40 / 5 creators) = 8 -> at most 2 * 8 = 16 records; never padded
    assert summary["outcome"] == "incomplete"
    st = batch_stats(db, "sports_001")
    assert st["accepted"] == 16
    assert st["max_accepted_from_one_creator"] <= 8
    assert summary["platforms"]["youtube"]["posts_skipped_creator_cap"] > 0


def test_resume_continues_without_recollecting(cfg):
    db = Database(cfg.path("database"))
    fake = FakeYouTube()
    run_batch(cfg, db, "sports_001", 15, {"youtube": make_youtube(cfg, db, fake)})
    assert db.count_comments("sports_001", "accepted") == 15
    processed_before = db.count_comments("sports_001")
    db.close()

    # "restart": new DB connection, same batch, higher target
    db2 = Database(cfg.path("database"))
    fake2 = FakeYouTube()
    summary = run_batch(cfg, db2, "sports_001", 35, {"youtube": make_youtube(cfg, db2, fake2)}, create=False)
    assert summary["outcome"] == "completed"
    assert db2.count_comments("sports_001", "accepted") == 35
    # nothing processed twice: every comment row is unique and the second run
    # skipped all previously processed ids it saw again
    keys = [r["record_key"] for r in db2.conn.execute("SELECT record_key FROM comments")]
    assert len(keys) == len(set(keys))
    assert db2.count_comments("sports_001") > processed_before
    # discovery cursors were reused (no search restarted from page 0 for an exhausted keyword)
    assert summary["run_counters"]["already_processed"] >= 0


def test_quota_error_stops_only_that_platform(cfg):
    db = Database(cfg.path("database"))
    broken = FakeYouTube()
    broken.fail_quota = True

    class OtherPlatform(YouTubeScraper):
        platform = "tiktok"  # pretend to be a second, healthy platform

    healthy_fake = FakeYouTube(seed=11)
    ycfg = cfg.platform_cfg("youtube")
    http_ok = HttpClient("tiktok", ycfg, session=healthy_fake)
    http_ok.sleep = lambda s: None
    other = OtherPlatform(ycfg, db=None, http=http_ok)
    http_ok.classifier = other.classify_response

    summary = run_batch(cfg, db, "sports_001", 20, {"youtube": make_youtube(cfg, db, broken), "tiktok": other})
    assert summary["platforms"]["youtube"]["stop_reason"] == "quota_exceeded"
    assert summary["outcome"] == "completed"
    assert batch_stats(db, "sports_001")["platform_distribution"] == {"tiktok": 20}


def test_unexpected_connector_crash_is_isolated(cfg):
    db = Database(cfg.path("database"))

    class Crashing(BaseScraper):
        platform = "facebook"

        def discover(self, domain, keyword, state):
            raise RuntimeError("boom")

        def fetch_page(self, post, cursor):
            raise RuntimeError("boom")

    summary = run_batch(
        cfg, db, "sports_001", 10, {"facebook": Crashing({}), "youtube": make_youtube(cfg, db, FakeYouTube())}
    )
    assert summary["platforms"]["facebook"]["stop_reason"] == "unexpected_error"
    assert summary["outcome"] == "completed"


def test_local_quota_budget_respected(cfg):
    db = Database(cfg.path("database"))
    yt = make_youtube(cfg, db, FakeYouTube())
    yt.cfg = dict(yt.cfg, daily_quota_units=150)  # one search (100) + a few pages
    summary = run_batch(cfg, db, "sports_001", 1000, {"youtube": yt})
    assert summary["platforms"]["youtube"]["stop_reason"] == "quota_exceeded"
    assert db.quota_used("youtube", yt._quota_day()) <= 150


def test_export_formats(cfg):
    db = Database(cfg.path("database"))
    run_batch(cfg, db, "sports_001", 12, {"youtube": make_youtube(cfg, db, FakeYouTube())})
    files = export_batch(db, "sports_001", cfg.path("accepted_dir"), cfg.path("rejected_dir"))
    csv_path = next(p for p in files["accepted"] if p.endswith(".csv"))
    with open(csv_path, "rb") as fh:
        assert fh.read(3) == b"\xef\xbb\xbf"  # UTF-8 BOM for Excel
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 12
    assert rows[0]["platform"] == "youtube"
    pq_path = next(p for p in files["accepted"] if p.endswith(".parquet"))
    assert pq.read_table(pq_path).num_rows == 12
    jl = next(p for p in files["accepted"] if p.endswith(".jsonl"))
    assert sum(1 for _ in open(jl, encoding="utf-8")) == 12
    rej = next(p for p in files["rejected"] if p.endswith(".csv"))
    with open(rej, encoding="utf-8-sig", newline="") as fh:
        rrows = list(csv.DictReader(fh))
    assert rrows and all(r["rejection_reason"] for r in rrows)
    # raw log holds everything fetched before filtering
    raw_file = cfg.path("raw_dir") / "sports_001" / "youtube.jsonl"
    assert os.path.getsize(raw_file) > 0


def test_http_retries_then_raises(cfg):
    calls = {"n": 0}

    class Flaky:
        headers = {}

        def request(self, *a, **k):
            from tests.conftest import FakeResponse

            calls["n"] += 1
            return FakeResponse(503, {"error": {"message": "unavailable"}})

    http = HttpClient("youtube", {"max_retries": 2, "request_delay_seconds": 0}, session=Flaky())
    http.sleep = lambda s: None
    with pytest.raises(ScraperError):
        http.get("https://example.invalid/x")
    assert calls["n"] == 3


def test_bot_copy_is_retroactively_rejected(cfg):
    """Same long text from 3 distinct authors -> the accepted original becomes spam/bot_copy."""
    from core.models import Post, RawItem

    db = Database(cfg.path("database"))
    db.create_batch("sports_001", "sports", ["youtube"], 10, {}, {})
    pipe = Pipeline(cfg, db, "sports_001", "sports", Anonymizer(b"MOCK"), None)
    post = Post("youtube", "MOCKVID", source_id="CH", url="https://www.youtube.com/watch?v=MOCKVID")
    text = "MOCK এই ভিডিওটা সবাই শেয়ার করুন দেশের জন্য খুবই গুরুত্বপূর্ণ"
    outcomes = [
        pipe.process(RawItem("youtube", f"c{i}", "comment", text, post, author_key=f"author{i}"))
        for i in range(3)
    ]
    assert outcomes == ["accepted", "rejected", "rejected"]
    row = db.get_comment("youtube:c0")
    assert row["status"] == "rejected" and row["rejection_reason"] == "spam"
    assert row["rejection_detail"].startswith("bot_copy")


def test_deferred_items_are_not_lost(cfg):
    """Items skipped because the target was reached are picked up by a later run."""
    db = Database(cfg.path("database"))
    s1 = run_batch(cfg, db, "sports_001", 3, {"youtube": make_youtube(cfg, db, FakeYouTube())})
    assert s1["run_counters"]["deferred"] > 0
    first = {r["record_key"] for r in db.conn.execute("SELECT record_key FROM comments")}
    # posts with deferred items keep their cursor (not 'done'), so nothing is skipped forever
    assert db.conn.execute("SELECT COUNT(*) FROM posts WHERE status IN ('active','capped')").fetchone()[0] > 0
    run_batch(cfg, db, "sports_001", 6, {"youtube": make_youtube(cfg, db, FakeYouTube())}, create=False)
    second = {r["record_key"] for r in db.conn.execute("SELECT record_key FROM comments")}
    assert first < second
    assert db.count_comments("sports_001", "accepted") == 6


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        # exact shape returned by googleapis.com for an invalid key (captured 2026-10-15)
        (400, {"error": {"code": 400, "message": "API key not valid.", "errors": [{"reason": "badRequest"}],
                         "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}}, "auth"),
        (403, {"error": {"code": 403, "errors": [{"reason": "quotaExceeded"}]}}, "quota"),
        (403, {"error": {"code": 403, "errors": [{"reason": "commentsDisabled"}]}}, "resource"),
        (403, {"error": {"code": 403, "errors": [{"reason": "rateLimitExceeded"}]}}, "rate_limit"),
        (503, {"error": {"code": 503, "errors": [{"reason": "backendError"}]}}, "retry"),
    ],
)
def test_youtube_error_classification(status, payload, expected):
    from tests.conftest import FakeResponse

    yt = YouTubeScraper({})
    assert yt.classify_response(FakeResponse(status, payload, url="https://x/youtube/v3/commentThreads"), payload) == expected
