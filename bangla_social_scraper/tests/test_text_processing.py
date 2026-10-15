"""Unit tests for cleaning, language ID and quality filtering (MOCK strings only)."""

import pytest

from processing.language import LanguageDetector
from processing.normalize import clean_text, exact_key, skeleton_key
from processing.quality import QualityFilter


@pytest.fixture()
def lang(cfg):
    return LanguageDetector(cfg.section("language"), cfg.root)


@pytest.fixture()
def quality(cfg):
    return QualityFilter(cfg.section("quality"))


# ------------------------------------------------------------------ cleaning
def test_clean_text_keeps_text_verbatim():
    s = "এই লোক টা একদম বোকা!!  valo na 😡\nnext line"
    assert clean_text(s) == s


def test_clean_text_keeps_zwj_and_precomposed_bengali():
    s = "র‍্যাব য়"  # ZWJ conjunct + precomposed য় (NFC would decompose it)
    assert clean_text(s) == s


def test_clean_text_removes_control_and_invalid():
    assert clean_text("ভাই\x00\x07 খেলা\r\nভালো\ud800") == "ভাই খেলা\nভালো"


def test_exact_key_only_normalises_spacing():
    assert exact_key("এই  লোকটা ​একদম বোকা ।") == "এই লোকটা একদম বোকা।"
    # case and punctuation are kept for EXACT matching
    assert exact_key("Valo") != exact_key("valo")


def test_skeleton_key_examples():
    a = skeleton_key("এই লোকটা একদম বোকা")
    assert a == skeleton_key("এই লোকটা একদম বোকা।") == skeleton_key("এই লোক টা একদম বোকা")


# ------------------------------------------------------------------ language
@pytest.mark.parametrize(
    "text,label",
    [
        ("শালা হারামি", "bangla"),
        ("এই লোকটা একদম বোকা।", "bangla"),
        ("bhai khub valo khelse", "banglish"),
        ("ami tomake onek valobashi", "banglish"),
        ("Shakib is the best player ami tare love kori", "mixed"),
        ("Shakib ভাই is the best", "mixed"),
        ("What a great match, well played", "english"),
        ("bhai kya baat hai yaar bahut accha", "other"),
        ("क्या बात है", "other"),
        ("ما شاء الله", "other"),
    ],
)
def test_language_labels(lang, text, label):
    assert lang.detect(text).label == label


def test_language_ignores_urls_mentions_hashtags(lang):
    assert lang.detect("@someone ভাই দারুণ খেলেছে #bdcricket https://example.com").label == "bangla"


# ------------------------------------------------------------------- quality
@pytest.mark.parametrize("text", ["শালা হারামি", "ভাই", "valoooo", "10:25 ei jaygay dekhen", "হা হা হা"])
def test_short_meaningful_comments_are_kept(quality, text):
    assert quality.check(text).ok


@pytest.mark.parametrize(
    "text,reason,detail",
    [
        (None, "missing_text", None),
        ("   ​ ", "empty", None),
        ("😂😂🔥", "emoji_only", None),
        ("👍🏽", "emoji_only", None),
        ("!!!", "too_low_quality", "punctuation_only"),
        ("https://example.com/x", "too_low_quality", "url_only"),
        ("@someone @other", "too_low_quality", "tag_only"),
        ("#bdcricket #bpl", "too_low_quality", "tag_only"),
        ("a", "too_low_quality", "too_few_letters"),
        ("কককককক", "too_low_quality", "repeated_character"),
        ("asdfghjkl", "too_low_quality", "keyboard_spam"),
        ("subscribe my channel please", "spam", None),
        ("আমার চ্যানেল সাবস্ক্রাইব করুন", "spam", None),
        ("whatsapp 01712345678", "spam", None),
        ("visit https://shop.example.com free offer", "spam", None),
    ],
)
def test_quality_rejections(quality, text, reason, detail):
    res = quality.check(text)
    assert not res.ok
    assert res.reason == reason
    if detail:
        assert res.detail == detail
