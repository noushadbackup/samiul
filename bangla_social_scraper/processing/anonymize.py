"""Author anonymisation.

Platform author identifiers are replaced by a keyed hash:

    author_anonymous_id = "a_" + HMAC-SHA256(ANON_SALT, "<platform>:<author_id>")[:20]

The salt is secret, so the hash cannot be reversed by brute-forcing known
channel IDs. The same author always maps to the same ID (needed for
duplicate/bot detection and per-author analysis). Usernames, display names and
profile pictures are never stored anywhere.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path
from typing import Optional

from core.logging_setup import get_logger, log_event

log = get_logger("anonymize")

MENTION_RE = re.compile(r"(?<![\w@])@[\w.\-]+")


def load_salt(fallback_file: Path) -> bytes:
    salt = os.environ.get("ANON_SALT", "").strip()
    if salt:
        return salt.encode("utf-8")
    if fallback_file.exists():
        return fallback_file.read_text(encoding="utf-8").strip().encode("utf-8")
    fallback_file.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    fallback_file.write_text(value, encoding="utf-8")
    try:
        os.chmod(fallback_file, 0o600)
    except OSError:
        pass
    log_event(
        log,
        "anon_salt_generated",
        path=str(fallback_file),
        note="Set ANON_SALT in .env to control it; keep it secret and stable.",
    )
    return value.encode("utf-8")


class Anonymizer:
    def __init__(self, salt: bytes):
        if not salt:
            raise ValueError("Anonymisation salt must not be empty")
        self._salt = salt

    def author_id(self, platform: str, author_key: Optional[str]) -> Optional[str]:
        if not author_key:
            return None
        digest = hmac.new(self._salt, f"{platform}:{author_key}".encode("utf-8"), hashlib.sha256).hexdigest()
        return "a_" + digest[:20]


def mask_mentions(text: Optional[str]) -> Optional[str]:
    """Replace @handles with @user (export-time option only)."""
    if text is None:
        return None
    return MENTION_RE.sub("@user", text)
