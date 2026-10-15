"""Rule-based Bangla / Banglish / mixed language identification.

Labels: bangla | banglish | mixed | english | other

* bangla   – Bengali script, (almost) no Latin-script words
* mixed    – Bengali script with a meaningful share of Latin-script words, or
             Latin-script Banglish with a large share of English words
* banglish – Latin script with romanised-Bangla vocabulary
* english  – Latin script, English vocabulary, no Banglish signal
* other    – other scripts dominate (Hindi, Urdu, Arabic, ...), Hinglish, or
             no linguistic signal at all

Script detection is exact (Unicode blocks). Banglish vs. English vs. Hinglish
uses editable lexicons in processing/lexicons/. Generic off-the-shelf language
identifiers do not handle romanised Bangla, which is why a lexicon is used.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

LEXICON_DIR = Path(__file__).resolve().parent / "lexicons"

URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|net|org|io|me|ly|be|bd|xyz|info|link)(?:/\S*)?")
MENTION_RE = re.compile(r"(?<!\w)@[\w.\-]+")
HASHTAG_RE = re.compile(r"(?<!\w)#[\wঀ-৿_]+")
TIMESTAMP_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
# A "letter" is any Unicode letter OR combining mark: Python's \w does not match
# Bengali vowel signs (Mc/Mn), which would otherwise split words like "ভাই".
_LETTER = r"(?:[^\W\d_]|[\u0981-\u0983\u09bc\u09be-\u09d7\u09e2\u09e3\u0300-\u036f\u200c\u200d])"
TOKEN_RE = re.compile(_LETTER + r"+(?:['’]" + _LETTER + r"+)?", re.UNICODE)

BENGALI_START, BENGALI_END = 0x0980, 0x09FF

LABELS = ("bangla", "banglish", "mixed", "english", "other")


def _read_lexicon(path: Path) -> set[str]:
    if not path.exists():
        return set()
    words = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            words.add(line)
    return words


@lru_cache(maxsize=8)
def _lexicons(extra_path: str | None) -> tuple[frozenset, frozenset, frozenset]:
    english = _read_lexicon(LEXICON_DIR / "english.txt")
    banglish = _read_lexicon(LEXICON_DIR / "banglish.txt")
    if extra_path:
        banglish |= _read_lexicon(Path(extra_path))
    hinglish = _read_lexicon(LEXICON_DIR / "hinglish.txt")
    banglish -= english  # never count an English word as Banglish evidence
    return frozenset(banglish), frozenset(english), frozenset(hinglish)


def _is_bengali(ch: str) -> bool:
    return BENGALI_START <= ord(ch) <= BENGALI_END


def _is_latin_letter(ch: str) -> bool:
    if ch.isascii():
        return ch.isalpha()
    try:
        return unicodedata.name(ch).startswith("LATIN")
    except ValueError:
        return False


def strip_non_linguistic(text: str) -> str:
    """Remove URLs, @mentions, #hashtags and video timestamps before analysis."""
    t = URL_RE.sub(" ", text)
    t = MENTION_RE.sub(" ", t)
    t = HASHTAG_RE.sub(" ", t)
    t = TIMESTAMP_RE.sub(" ", t)
    return t


_BANGLISH_SUFFIX_RE = re.compile(r"^[a-z]{3,}(?:chi|che|chen|lam|ilam|tesi|tese|teche|techi|chilo|silo|bena|tasi|tase)$")


@dataclass
class LanguageResult:
    label: str
    bengali_chars: int = 0
    latin_chars: int = 0
    other_chars: int = 0
    banglish_hits: float = 0.0
    english_hits: int = 0
    hinglish_hits: int = 0
    details: dict = field(default_factory=dict)


class LanguageDetector:
    def __init__(self, cfg: dict | None = None, root: Path | None = None):
        cfg = cfg or {}
        self.mixed_min_latin_ratio = float(cfg.get("mixed_min_latin_ratio", 0.15))
        self.banglish_min_hits = float(cfg.get("banglish_min_hits", 1))
        self.mixed_english_ratio = float(cfg.get("banglish_mixed_english_ratio", 0.5))
        extra = cfg.get("extra_banglish_words_file")
        if extra and root is not None and not Path(extra).is_absolute():
            extra = str(root / extra)
        self.banglish, self.english, self.hinglish = _lexicons(extra)

    # ------------------------------------------------------------------ tokens
    @staticmethod
    def _variants(word: str) -> list[str]:
        v1 = re.sub(r"(.)\1{2,}", r"\1", word)  # valoooo -> valo
        v2 = re.sub(r"(.)\1+", r"\1", word)  # bhaii -> bhai
        out = [word]
        for v in (v1, v2):
            if v not in out:
                out.append(v)
        return out

    def _hit(self, word: str, lexicon: frozenset) -> bool:
        return any(v in lexicon for v in self._variants(word))

    # ------------------------------------------------------------------ detect
    def detect(self, text: str | None) -> LanguageResult:
        if not text:
            return LanguageResult("other")
        t = strip_non_linguistic(text)
        bn = lat = oth = 0
        for ch in t:
            cat = unicodedata.category(ch)
            if cat[0] not in ("L", "M"):
                continue
            if _is_bengali(ch):
                bn += 1
            elif cat[0] == "M":
                continue  # combining marks belong to the preceding letter
            elif _is_latin_letter(ch):
                lat += 1
            else:
                oth += 1
        total = bn + lat + oth
        res = LanguageResult("other", bn, lat, oth)
        if total == 0:
            return res

        if oth > bn and oth / total > 0.3:
            res.label = "other"
            return res

        tokens = TOKEN_RE.findall(t)
        bn_tokens = [w for w in tokens if any(_is_bengali(c) for c in w)]
        lat_tokens = [w.lower() for w in tokens if all(_is_latin_letter(c) or c in "'’" for c in w)]

        if bn > 0:
            meaningful_lat = [w for w in lat_tokens if len(w) >= 2]
            denom = len(bn_tokens) + len(lat_tokens)
            ratio = len(meaningful_lat) / denom if denom else 0.0
            res.details["latin_token_ratio"] = round(ratio, 3)
            res.label = "mixed" if ratio >= self.mixed_min_latin_ratio else "bangla"
            return res

        # Latin-only text: Banglish vs English vs Hinglish
        b = 0.0
        e = h = 0
        for w in lat_tokens:
            w = w.replace("’", "'")
            if self._hit(w, self.banglish):
                b += 1
            elif self._hit(w, self.english):
                e += 1
            elif self._hit(w, self.hinglish):
                h += 1
            elif _BANGLISH_SUFFIX_RE.match(w):
                b += 0.5
        res.banglish_hits, res.english_hits, res.hinglish_hits = b, e, h

        if h >= 2 and h > b:
            res.label = "other"
        elif b >= self.banglish_min_hits:
            if e > 0 and e / (b + e) >= self.mixed_english_ratio:
                res.label = "mixed"
            else:
                res.label = "banglish"
        elif e > 0:
            res.label = "english"
        else:
            res.label = "other"
        return res
