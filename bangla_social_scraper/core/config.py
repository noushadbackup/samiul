"""Configuration loading (config.yaml + .env)."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

try:  # python-dotenv is optional at import time; required in practice
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PLATFORMS = ("youtube", "facebook", "instagram", "tiktok")


class ConfigError(ValueError):
    pass


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class Config:
    """Thin wrapper around the parsed YAML with helpers for common lookups."""

    def __init__(self, data: dict, root: Path = PROJECT_ROOT):
        self.data = data
        self.root = root

    # ------------------------------------------------------------------ basics
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, dotted: str) -> dict:
        value = self.get(dotted, {})
        return value if isinstance(value, dict) else {}

    def path(self, key: str) -> Path:
        raw = self.get(f"paths.{key}")
        if raw is None:
            raise ConfigError(f"paths.{key} missing from config")
        p = Path(raw)
        return p if p.is_absolute() else self.root / p

    # ----------------------------------------------------------------- domains
    @property
    def domains(self) -> list[str]:
        return list((self.get("keywords") or {}).keys())

    def validate_domain(self, domain: str) -> str:
        if domain not in self.domains:
            raise ConfigError(
                f"Unknown domain '{domain}'. Configured domains: {', '.join(self.domains)}. "
                "Add it under `keywords:` in config.yaml."
            )
        return domain

    def platform_cfg(self, platform: str) -> dict:
        return self.section(f"sources.{platform}")

    def platform_enabled(self, platform: str) -> bool:
        return bool(self.platform_cfg(platform).get("enabled", False))

    def snapshot(self) -> dict:
        return copy.deepcopy(self.data)


def load_config(path: str | os.PathLike | None = None, overrides: dict | None = None) -> Config:
    """Load config.yaml (and .env into os.environ)."""
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    if not cfg_path.exists():
        raise ConfigError(f"Config file not found: {cfg_path}")
    if load_dotenv is not None:
        env_file = cfg_path.parent / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
    with open(cfg_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if overrides:
        data = _deep_merge(data, overrides)
    if not data.get("keywords"):
        raise ConfigError("config.yaml must define at least one domain under `keywords:`")
    return Config(data, root=cfg_path.parent.resolve())
