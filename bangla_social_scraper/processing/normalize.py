"""Text cleaning and normalisation helpers.

Two very different operations live here:

* ``clean_text`` produces the STORED ``comment_text``. It only removes invalid
  Unicode (lone surrogates, non-characters) and control characters, and turns
  CR / CRLF line endings into LF. It does NOT apply Unicode normalisation,
  because NFC would rewrite some Bengali code points (e.g. U+09DF ``য়``
  decomposes under NFC) and the research text must stay verbatim. ZWJ / ZWNJ
  are kept because they change how Bengali conjuncts render.

* ``exact_key`` / ``skeleton_key`` produce HASHING KEYS only. They are never
  written to the research file.
"""

from __future__ import annotations

import re
import unicodedata

ZERO_WIDTH = {
    "\u200b",  # zero width space
    "\u200c",  # ZWNJ
    "\u200d",  # ZWJ
    "\u2060",  # word joiner
    "\ufeff",  # BOM / zero width no-break space
    "\u180e",  # mongolian vowel separator
    "\u00ad",  # soft hyphen
}
_ZW_RE = re.compile("[" + "".join(ZERO_WIDTH) + "]")
_WS_RE = re.compile(r"\s+")
# Closing punctuation (incl. Bengali danda/double danda) never needs a space before it.
_CLOSERS = ".,!?;:।॥…)]}\"'”’"
_OPENERS = "([{“‘"
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([" + re.escape(_CLOSERS) + r"])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([" + re.escape(_OPENERS) + r"])\s+")


def _is_noncharacter(cp: int) -> bool:
    return (0xFDD0 <= cp <= 0xFDEF) or (cp & 0xFFFE) == 0xFFFE


def clean_text(text: str | None) -> str | None:
    """Remove only invalid Unicode and control characters. Everything else is kept verbatim."""
    if text is None:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for ch in text:
        cp = ord(ch)
        if 0xD800 <= cp <= 0xDFFF or _is_noncharacter(cp):
            continue  # invalid / non-character
        if ch in ("\n", "\t"):
            out.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat == "Cc":  # C0/C1 control characters
            continue
        out.append(ch)
    return "".join(out)


def exact_key(text: str) -> str:
    """Normalisation for EXACT duplicate detection.

    Only: Unicode NFC, zero-width removal, whitespace collapsing and punctuation
    spacing. Case and punctuation themselves are preserved.
    """
    t = unicodedata.normalize("NFC", text)
    t = _ZW_RE.sub("", t)
    t = _WS_RE.sub(" ", t).strip()
    t = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", t)
    t = _SPACE_AFTER_OPEN_RE.sub(r"\1", t)
    return t


def skeleton_key(text: str) -> str:
    """Aggressive normalisation used for NEAR-duplicate detection.

    NFKC + casefold, zero-width/punctuation/whitespace/emoji removed, and long
    character runs collapsed to two. "এই লোকটা একদম বোকা।" and
    "এই লোক টা একদম বোকা" both become "এইলোকটাএকদমবোকা".
    """
    t = unicodedata.normalize("NFKC", text).casefold()
    t = _ZW_RE.sub("", t)
    kept = []
    for ch in t:
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "M", "N"):
            kept.append(ch)
    t = "".join(kept)
    t = re.sub(r"(.)\1{2,}", r"\1\1", t)
    return t


def strip_zero_width(text: str) -> str:
    return _ZW_RE.sub("", text)
