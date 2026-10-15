"""Duplicate / near-duplicate detection tests (MOCK strings only)."""

from processing.dedup import DedupIndex
from storage.database import Database


def _index(path, **cfg):
    db = Database(path)
    return db, DedupIndex(db, {"near_dup_min_length": 12, **cfg})


def _accept(db, idx, key, text, batch="b1", author=None):
    keys = idx.keys(text)
    db.insert_comment(key, batch, {"platform": key.split(":")[0], "domain": "sports", "comment_text": text},
                      "accepted", None, None, keys.exact_hash, keys.skeleton)
    idx.register(keys, key, batch, author)
    db.commit()


def test_exact_duplicate(tmp_path):
    db, idx = _index(tmp_path / "s.db")
    _accept(db, idx, "youtube:1", "ভাই দারুণ খেলেছে আজকে")
    res = idx.check(idx.keys("ভাই  দারুণ খেলেছে আজকে"), "b1")  # only whitespace differs
    assert res.status == "duplicate"


def test_spec_near_duplicate_examples(tmp_path):
    db, idx = _index(tmp_path / "s.db")
    _accept(db, idx, "youtube:1", "এই লোকটা একদম বোকা")
    for variant in ("এই লোকটা একদম বোকা।", "এই লোক টা একদম বোকা"):
        assert idx.check(idx.keys(variant), "b1").status == "near_duplicate"


def test_minhash_near_duplicate_with_small_edit(tmp_path):
    db, idx = _index(tmp_path / "s.db")
    _accept(db, idx, "youtube:1", "বাংলাদেশ দল আজকে অসাধারণ খেলেছে সবাইকে অভিনন্দন জানাই")
    res = idx.check(idx.keys("বাংলাদেশ দল আজকে অসাধারণ খেলেছে সবাইকে অভিনন্দন জানাই ভাই"), "b1")
    assert res.status == "near_duplicate"
    assert res.detail == "minhash_lsh_jaccard"
    assert res.similarity >= 0.8


def test_different_texts_are_not_duplicates(tmp_path):
    db, idx = _index(tmp_path / "s.db")
    _accept(db, idx, "youtube:1", "বাংলাদেশ দল আজকে অসাধারণ খেলেছে সবাইকে অভিনন্দন")
    assert idx.check(idx.keys("কোচের সিদ্ধান্ত একদম ভুল ছিল, ওপেনিং বদলানো দরকার"), "b1").status is None


def test_cross_platform_and_persistence(tmp_path):
    path = tmp_path / "s.db"
    db, idx = _index(path)
    _accept(db, idx, "youtube:1", "আজকের ম্যাচটা মনে থাকবে অনেকদিন")
    db.close()
    db2, idx2 = _index(path)  # restart
    res = idx2.check(idx2.keys("আজকের ম্যাচটা মনে থাকবে অনেকদিন"), "b2")
    assert res.status == "duplicate" and res.matched_key == "youtube:1"


def test_batch_scope(tmp_path):
    db, idx = _index(tmp_path / "s.db", scope="batch")
    _accept(db, idx, "youtube:1", "আজকের ম্যাচটা মনে থাকবে অনেকদিন", batch="b1")
    assert idx.check(idx.keys("আজকের ম্যাচটা মনে থাকবে অনেকদিন"), "b2").status is None
    assert idx.check(idx.keys("আজকের ম্যাচটা মনে থাকবে অনেকদিন"), "b1").status == "duplicate"
