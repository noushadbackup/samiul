"""Error classification shared by the Facebook and Instagram Graph API connectors.

Meta error codes (https://developers.facebook.com/docs/graph-api/guides/error-handling):
  1, 2                     temporary / unknown service error   -> retry
  4, 17, 32, 613, 80001-80014  application / user / page / BUC rate limits -> rate_limit (back off)
  190, 102, 463, 467       invalid / expired access token      -> auth
  10, 200-299              permission missing for this object  -> resource
  100, 803                 object missing / unsupported request -> resource
  24 (IG)                  media unavailable                   -> resource
"""

from __future__ import annotations

from typing import Optional

RATE_LIMIT_CODES = {4, 17, 32, 613}


def meta_classify(resp, payload) -> Optional[str]:
    if resp.status_code < 400 and not (isinstance(payload, dict) and "error" in payload):
        return None
    err = payload.get("error") if isinstance(payload, dict) else None
    code = None
    if isinstance(err, dict):
        try:
            code = int(err.get("code")) if err.get("code") is not None else None
        except (TypeError, ValueError):
            code = None
        if err.get("is_transient"):
            return "retry"
    if code in RATE_LIMIT_CODES or (code is not None and 80001 <= code <= 80014) or resp.status_code == 429:
        return "rate_limit"
    if code in (190, 102, 463, 467):
        return "auth"
    if code == 10 or (code is not None and 200 <= code <= 299):
        return "resource"
    if code in (100, 803, 24) or resp.status_code == 404:
        return "resource"
    if code in (1, 2) or resp.status_code >= 500:
        return "retry"
    return "fatal"


def graph_url(cfg: dict, path: str) -> str:
    base = cfg.get("api_base", "https://graph.facebook.com").rstrip("/")
    version = cfg.get("graph_api_version", "v23.0")
    return f"{base}/{version}/{path.lstrip('/')}"


def next_after(payload: dict) -> Optional[str]:
    """Return the 'after' cursor only when the API says another page exists."""
    paging = (payload or {}).get("paging") or {}
    if not paging.get("next"):
        return None
    return (paging.get("cursors") or {}).get("after")
