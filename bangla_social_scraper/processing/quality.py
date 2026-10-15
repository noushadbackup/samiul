"""Quality filtering.

Rejects obviously non-linguistic or promotional content. Short comments are NOT
rejected for being short: "শালা হারামি" (11 characters) is valid data. Only text
with fewer than ``min_characters`` letters (after removing URLs, @mentions and
#hashtags) is rejected, so single meaningless characters are dropped.

Each rejection has a ``reason`` from the fixed research vocabulary
(see core.models.REJECTION_REASONS) and a more specific ``detail``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from processing.language import HASHTAG_RE, MENTION_RE, URL_RE
from processing.normalize import strip_zero_width

_KEYBOARD_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890")
_KEYBOARD_SEQS = set()
for _row in _KEYBOARD_ROWS:
    for _r in (_row, _row[::-1]):
        for _i in range(len(_r) - 4):
            _KEYBOARD_SEQS.add(_r[_i : _i + 5])

_VOWELS = set("aeiouy")
_LATIN_WORD_RE = re.compile(r"[a-z]+")
_PROMO_WORDS_RE = re.compile(
    r"(?i)(subscribe|channel|visit|click|join|order|offer|free|follow|link\s+in|"
    r"সাবস্ক্রাইব|চ্যানেল|ভিজিট|ক্লিক|জয়েন|অর্ডার|অফার|ফ্রি|ফলো|লিংক)"
)
_VARIATION_SELECTORS = {"\ufe0e", "\ufe0f"}


@dataclass
class QualityResult:
    ok: bool
    reason: Optional[str] = None
    detail: Optional[str] = None


def _is_emoji_like(ch: str) -> bool:
    if ch in _VARIATION_SELECTORS or ch == "\u200d" or ch == "\u20e3":
        return True
    cp = ord(ch)
    if 0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x1F1E6 <= cp <= 0x1F1FF:
        return True
    return unicodedata.category(ch) in ("So", "Sk", "Me")


def _letters(text: str) -> list[str]:
    return [ch for ch in text if unicodedata.category(ch)[0] in ("L", "M")]


class QualityFilter:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.min_characters = int(cfg.get("min_characters", 3))
        self.reject_keyboard_spam = bool(cfg.get("reject_keyboard_spam", True))
        self.reject_ads = bool(cfg.get("reject_advertising_spam", True))
        self.spam_patterns = []
        for pat in cfg.get("spam_patterns", []) or []:
            try:
                self.spam_patterns.append((pat, re.compile(pat, re.IGNORECASE | re.UNICODE)))
            except re.error as exc:  # surface bad config early
                raise ValueError(f"Invalid spam pattern {pat!r}: {exc}") from exc

    # ------------------------------------------------------------------ checks
    def _keyboard_spam(self, text: str) -> bool:
        words = _LATIN_WORD_RE.findall(text.lower())
        if not words:
            return False
        bad = 0
        for w in words:
            if len(w) >= 5 and any(w[i : i + 5] in _KEYBOARD_SEQS for i in range(len(w) - 4)):
                bad += 1
            elif len(w) >= 6 and not (set(w) & _VOWELS):
                bad += 1
        letters = _letters(text)
        latin_letters = sum(1 for ch in letters if ch.isascii())
        # Only spam if gibberish dominates the comment (Latin-script share and words).
        return bad > 0 and bad / len(words) >= 0.5 and latin_letters >= 0.6 * max(1, len(letters))

    def check(self, text: Optional[str]) -> QualityResult:
        if text is None:
            return QualityResult(False, "missing_text", "no_text_field")
        stripped = strip_zero_width(text).strip()
        if not stripped:
            return QualityResult(False, "empty", "blank")

        no_space = "".join(ch for ch in stripped if not ch.isspace())
        has_emoji = any(_is_emoji_like(ch) for ch in no_space)
        has_wordish = any(unicodedata.category(ch)[0] in ("L", "M", "N") for ch in no_space)
        if not has_wordish:
            if has_emoji:
                return QualityResult(False, "emoji_only", "emoji_or_symbols_only")
            return QualityResult(False, "too_low_quality", "punctuation_only")

        no_url = URL_RE.sub(" ", stripped)
        if not any(unicodedata.category(ch)[0] in ("L", "M", "N") for ch in no_url):
            return QualityResult(False, "too_low_quality", "url_only")
        no_tags = HASHTAG_RE.sub(" ", MENTION_RE.sub(" ", no_url))
        letters = _letters(no_tags)
        if not letters:
            if not any(unicodedata.category(ch)[0] == "N" for ch in no_tags) and (
                MENTION_RE.search(no_url) or HASHTAG_RE.search(no_url)
            ):
                return QualityResult(False, "too_low_quality", "tag_only")
            return QualityResult(False, "too_low_quality", "no_letters")

        if len(letters) < self.min_characters:
            return QualityResult(False, "too_low_quality", "too_few_letters")

        collapsed = re.sub(r"(.)\1+", r"\1", "".join(letters).casefold())
        if len(set(collapsed)) < 2:
            return QualityResult(False, "too_low_quality", "repeated_character")

        if self.reject_ads:
            for pat, rx in self.spam_patterns:
                if rx.search(stripped):
                    return QualityResult(False, "spam", f"pattern:{pat}")
            if URL_RE.search(stripped) and _PROMO_WORDS_RE.search(stripped):
                return QualityResult(False, "spam", "url_with_promo_words")

        if self.reject_keyboard_spam and self._keyboard_spam(no_tags):
            return QualityResult(False, "too_low_quality", "keyboard_spam")

        return QualityResult(True)
