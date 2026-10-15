"""Keyword lists per research domain.

Sources, in order (duplicates removed, order preserved):
  1. ``keywords_by_platform.<platform>.<domain>`` in config.yaml, if present,
     otherwise ``keywords.<domain>``
  2. ``keywords/<domain>.txt`` (one keyword per line, # comments allowed)
  3. ``--keywords`` given on the command line replaces everything above
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.config import Config


class KeywordManager:
    def __init__(self, cfg: Config, override: Optional[list[str]] = None):
        self.cfg = cfg
        self.override = [k.strip() for k in (override or []) if k and k.strip()]
        self.keyword_dir = cfg.root / "keywords"

    @staticmethod
    def _unique(items: list[str]) -> list[str]:
        seen, out = set(), []
        for item in items:
            key = item.strip().casefold()
            if item.strip() and key not in seen:
                seen.add(key)
                out.append(item.strip())
        return out

    def _file_keywords(self, domain: str) -> list[str]:
        path: Path = self.keyword_dir / f"{domain}.txt"
        if not path.exists():
            return []
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def keywords(self, domain: str, platform: Optional[str] = None) -> list[str]:
        self.cfg.validate_domain(domain)
        if self.override:
            return self._unique(self.override)
        base = None
        if platform:
            base = (self.cfg.get("keywords_by_platform") or {}).get(platform, {}).get(domain)
        if not base:
            base = self.cfg.get(f"keywords.{domain}") or []
        return self._unique(list(base) + self._file_keywords(domain))

    def snapshot(self, domain: str, platforms: list[str]) -> dict:
        return {p: self.keywords(domain, p) for p in platforms}
