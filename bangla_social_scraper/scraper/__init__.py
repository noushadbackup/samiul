"""Platform connectors. Each is imported lazily so a broken/unconfigured
connector never prevents the others from running."""

from __future__ import annotations

import importlib

from core.config import PLATFORMS, Config
from core.logging_setup import get_logger, log_event
from scraper.http import ConfigurationError

log = get_logger("scrapers")

_CLASSES = {
    "youtube": ("scraper.youtube", "YouTubeScraper"),
    "facebook": ("scraper.facebook", "FacebookScraper"),
    "instagram": ("scraper.instagram", "InstagramScraper"),
    "tiktok": ("scraper.tiktok", "TikTokScraper"),
}


def resolve_platforms(cfg: Config, requested: str | None) -> list[str]:
    if not requested:
        return list(cfg.get("collection.platforms", ["youtube"]))
    if requested == "all":
        order = cfg.get("collection.platform_order", list(PLATFORMS))
        return [p for p in order if p in PLATFORMS]
    names = [p.strip().lower() for p in requested.split(",") if p.strip()]
    unknown = [p for p in names if p not in PLATFORMS]
    if unknown:
        raise ValueError(f"Unknown platform(s): {', '.join(unknown)}. Choose from {', '.join(PLATFORMS)} or 'all'.")
    return names


def build_scrapers(cfg: Config, db, platforms: list[str]) -> tuple[dict, dict]:
    """Instantiate usable connectors. Returns (scrapers, skipped{platform: reason})."""
    scrapers, skipped = {}, {}
    for name in platforms:
        if not cfg.platform_enabled(name):
            skipped[name] = "disabled in config.yaml (sources.%s.enabled: false)" % name
            continue
        module_name, cls_name = _CLASSES[name]
        try:
            cls = getattr(importlib.import_module(module_name), cls_name)
            scraper = cls(cfg.platform_cfg(name), db=db)
            scraper.check_configuration()
        except ConfigurationError as exc:
            skipped[name] = str(exc)
            continue
        except Exception as exc:  # pragma: no cover - defensive isolation
            skipped[name] = f"failed to initialise: {exc!r}"
            continue
        scrapers[name] = scraper
    for name, reason in skipped.items():
        log_event(log, "platform_skipped", platform=name, reason=reason)
    return scrapers, skipped
