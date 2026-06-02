"""
Shared helper functions for all feed validators.
"""

import re
import warnings
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from .constants import YOUTUBE_DOMAINS, STREAMING_DOMAINS

warnings.filterwarnings("ignore", message=".*SSL.*")
warnings.filterwarnings("ignore", message=".*Unverified.*")


def _safe_get(obj, *keys, default=None):
    """Safely extract a value from a nested dict/object trying multiple keys."""
    for key in keys:
        if isinstance(obj, dict):
            val = obj.get(key)
            if val is not None and val != "":
                return val
        elif hasattr(obj, key):
            val = getattr(obj, key, None)
            if val is not None and val != "":
                return val
    return default


def _extract_img_from_html(html_str: str) -> str | None:
    """Parse an HTML string and return the first <img src> URL found."""
    if not html_str or not isinstance(html_str, str):
        return None
    try:
        soup = BeautifulSoup(html_str, "html.parser")
        img = soup.find("img")
        if img and img.get("src"):
            src = img["src"]
            if src.startswith("http"):
                return src
    except Exception:
        pass
    return None


def _parse_date(raw) -> datetime | None:
    """Best-effort date parsing to UTC datetime."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        try:
            return dateutil_parser.parse(raw, fuzzy=True).astimezone(timezone.utc)
        except Exception:
            return None
    return None


def _http_client(**kwargs) -> httpx.Client:
    """Create an httpx Client with SSL verification disabled for publisher feeds."""
    kwargs.setdefault("verify", False)
    kwargs.setdefault("follow_redirects", True)
    return httpx.Client(**kwargs)


def _is_valid_url(url: str) -> bool:
    """Check if a string is a valid HTTP/HTTPS URL."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _classify_video_url(url: str) -> str:
    """Classify a video URL as mp4_direct, youtube, other_platform, or unknown."""
    if not url or not isinstance(url, str):
        return "unknown"
    url_lower = url.lower().strip()
    try:
        parsed = urlparse(url_lower)
        host = parsed.hostname or ""
    except Exception:
        return "unknown"

    if any(yt in host for yt in YOUTUBE_DOMAINS):
        return "youtube"
    if any(sp in host for sp in STREAMING_DOMAINS):
        return "other_platform"
    if ".mp4" in parsed.path:
        return "mp4_direct"
    return "unknown"
