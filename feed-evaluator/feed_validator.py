"""
JioNews Feed Validator Engine
Implements the validation logic from:
  - headlines-publisher-onboarding SKILL.md
  - native-videos-publisher-onboarding SKILL.md
"""

import re
import struct
import logging
import warnings
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from typing import Optional
from collections import Counter

import httpx
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

# Suppress SSL warnings since many publisher feeds have cert issues
warnings.filterwarnings("ignore", message=".*SSL.*")
warnings.filterwarnings("ignore", message=".*certificate.*")

logger = logging.getLogger(__name__)

# ── Reference Mappings ──────────────────────────────────────────────
LANGUAGE_ID_MAP = {
    "English": 1, "Hindi": 2, "Marathi": 3, "Gujarati": 4,
    "Malayalam": 6, "Tamil": 7, "Urdu": 8, "Kannada": 9,
    "Punjabi": 10, "Telugu": 11, "Bangla": 13, "Odia": 18, "Assamese": 19,
}

VALID_CATEGORIES = [
    "Agro", "Astrology", "Auto/Automobile", "Business", "Career/Education",
    "Entertainment", "Health", "India/National", "International/World",
    "Latest News/Top News", "Lifestyle/Fashion", "Sci and Tech", "Sports", "Cricket",
]

YOUTUBE_DOMAINS = {"youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com"}
STREAMING_DOMAINS = {"dailymotion.com", "vimeo.com", "www.dailymotion.com", "www.vimeo.com"}

MP4_FTYP_BRANDS = {b"isom", b"iso2", b"avc1", b"mp41", b"mp42", b"M4V ", b"mp71", b"MSNV"}


# ── Helpers ─────────────────────────────────────────────────────────

def _safe_get(entry, *keys, default=None):
    """Try multiple keys on a feedparser entry / dict."""
    for k in keys:
        try:
            val = entry.get(k) if isinstance(entry, dict) else getattr(entry, k, None)
            if val is not None:
                return val
        except Exception:
            continue
    return default


def _extract_img_from_html(html: str) -> Optional[str]:
    """Parse HTML for <img> tags and return the first src."""
    if not html:
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]
    except Exception:
        pass
    return None


def _parse_date(raw) -> Optional[datetime]:
    """Attempt to parse a date string into a UTC datetime."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)
    try:
        dt = dateparser.parse(str(raw))
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        elif dt:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None


def _http_client(**kwargs) -> httpx.Client:
    """Create an httpx Client with SSL verification disabled for publisher feeds."""
    kwargs.setdefault("verify", False)
    kwargs.setdefault("follow_redirects", True)
    return httpx.Client(**kwargs)


def _is_valid_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _classify_video_url(url: str) -> str:
    """Classify a video URL: mp4_direct, youtube, other_platform, unknown."""
    if not url:
        return "unknown"
    domain = urlparse(url).netloc.lower()
    if domain in YOUTUBE_DOMAINS:
        return "youtube"
    if domain in STREAMING_DOMAINS:
        return "other_platform"
    if ".mp4" in url.lower():
        return "mp4_direct"
    return "unknown"


# ── Headline Feed Validator ─────────────────────────────────────────

class HeadlineFeedValidator:
    """
    Validates RSS/JSON feeds for Headlines ingestion.
    Implements every step from headlines-publisher-onboarding/SKILL.md.
    """

    def validate(self, feed_url: str, publisher_name: str, language: str, category: str) -> dict:
        now = datetime.now(timezone.utc)
        result = {
            "skill_name": "headlines-publisher-onboarding",
            "run_mode": "dry-run",
            "timestamp": now.isoformat(),
            "inputs": {
                "feed_url": feed_url,
                "publisher_name": publisher_name,
                "language": language,
                "category": category,
            },
            "output": {},
            "validation_status": "passed",
            "confidence_score": 0,
            "issues": [],
            "recommendations": [],
        }
        out = result["output"]

        # ── Input Validation ────────────────────────────────────
        if language not in LANGUAGE_ID_MAP:
            result["validation_status"] = "failed"
            result["issues"].append(f"Invalid language '{language}'. Must be one of: {', '.join(LANGUAGE_ID_MAP.keys())}")
            return result
        if category not in VALID_CATEGORIES:
            result["validation_status"] = "failed"
            result["issues"].append(f"Invalid category '{category}'. Must be one of: {', '.join(VALID_CATEGORIES)}")
            return result

        # ── Step 1: Fetch Feed ──────────────────────────────────
        try:
            with _http_client(timeout=10, follow_redirects=True, max_redirects=3) as client:
                resp = client.get(feed_url)
            out["feed_accessible"] = resp.status_code < 400
            out["http_status_code"] = resp.status_code
            out["response_time_ms"] = int(resp.elapsed.total_seconds() * 1000)
            content_type = resp.headers.get("content-type", "")
            body = resp.text
        except httpx.TimeoutException:
            out["feed_accessible"] = False
            out["http_status_code"] = None
            out["response_time_ms"] = 10000
            result["validation_status"] = "failed"
            result["confidence_score"] = 0
            result["issues"].append("Feed URL timed out after 10 seconds.")
            return result
        except Exception as exc:
            out["feed_accessible"] = False
            out["http_status_code"] = None
            out["response_time_ms"] = None
            result["validation_status"] = "failed"
            result["confidence_score"] = 0
            result["issues"].append(f"Network error fetching feed: {exc}")
            return result

        if not out["feed_accessible"]:
            result["validation_status"] = "failed"
            result["confidence_score"] = 0
            result["issues"].append(f"Feed returned HTTP {out['http_status_code']}.")
            return result

        # ── Step 2: Detect Format ───────────────────────────────
        feed_format = None
        if any(t in content_type for t in ("json",)):
            feed_format = "json"
        elif any(t in content_type for t in ("xml", "rss", "atom")):
            feed_format = "xml"
        elif body.lstrip().startswith(("{", "[")):
            feed_format = "json"
        elif body.lstrip().startswith(("<",)):
            feed_format = "xml"

        out["feed_format"] = feed_format

        # ── Step 3: Parse Entries ───────────────────────────────
        entries = []
        if feed_format == "json":
            try:
                import json
                data = json.loads(body)
                for path in ("items", "articles", "data"):
                    if isinstance(data, dict) and isinstance(data.get(path), list):
                        entries = data[path]
                        break
                if not entries and isinstance(data, dict) and "feed" in data and isinstance(data["feed"].get("items"), list):
                    entries = data["feed"]["items"]
                if not entries and isinstance(data, list):
                    entries = data
            except Exception:
                pass

        if feed_format == "xml" or (feed_format is None and not entries):
            try:
                parsed = feedparser.parse(body)
                if parsed.entries:
                    entries = parsed.entries
                    if feed_format is None:
                        feed_format = "xml"
                        out["feed_format"] = "xml"
            except Exception:
                pass

        # Last resort: try JSON if XML also failed
        if not entries and feed_format != "json":
            try:
                import json
                data = json.loads(body)
                for path in ("items", "articles", "data"):
                    if isinstance(data, dict) and isinstance(data.get(path), list):
                        entries = data[path]
                        feed_format = "json"
                        out["feed_format"] = "json"
                        break
                if not entries and isinstance(data, list):
                    entries = data
                    feed_format = "json"
                    out["feed_format"] = "json"
            except Exception:
                pass

        out["total_entries"] = len(entries)

        if len(entries) == 0:
            result["validation_status"] = "failed"
            result["confidence_score"] = 0
            result["issues"].append("Zero entries found in the feed.")
            return result

        # ── Step 4: Validate Metadata Per Entry ─────────────────
        titles, urls, thumbnails, dates = [], [], [], []
        thumbnail_methods = Counter()
        all_titles_raw = []

        for entry in entries:
            # 4a Title
            title = _safe_get(entry, "title", "headline")
            title = str(title).strip() if title else ""
            titles.append(bool(title and len(title) >= 10))
            all_titles_raw.append(title.lower().strip())

            # 4b URL/Link
            link = _safe_get(entry, "link", "url", "sourceUrl")
            if isinstance(link, list) and link:
                link = link[0].get("href", "") if isinstance(link[0], dict) else str(link[0])
            urls.append(_is_valid_url(str(link)) if link else False)

            # 4c Thumbnail (12-step priority chain)
            thumb = None
            method = None
            try:
                mc = getattr(entry, "media_content", None) or entry.get("media_content")
                if mc and isinstance(mc, list) and mc[0].get("url"):
                    thumb, method = mc[0]["url"], "media_content_url"
            except Exception:
                pass
            if not thumb:
                try:
                    mt = getattr(entry, "media_thumbnail", None) or entry.get("media_thumbnail")
                    if mt:
                        if isinstance(mt, list) and mt[0].get("url"):
                            thumb, method = mt[0]["url"], "media_thumbnail_url"
                        elif isinstance(mt, str):
                            thumb, method = mt, "media_thumbnail_str"
                except Exception:
                    pass
            if not thumb:
                for key, m in [("thumbimage", "thumbimage"), ("fullimage", "fullimage"),
                               ("fullimageimage", "fullimageimage")]:
                    val = _safe_get(entry, key)
                    if val:
                        if isinstance(val, dict) and val.get("url"):
                            thumb, method = val["url"], m
                        elif isinstance(val, str) and _is_valid_url(val):
                            thumb, method = val, m
                        break
            if not thumb:
                img_val = _safe_get(entry, "image")
                if img_val:
                    if isinstance(img_val, dict):
                        thumb = img_val.get("url") or img_val.get("link")
                        method = "image_dict"
                    elif isinstance(img_val, str) and _is_valid_url(img_val):
                        thumb, method = img_val, "image_str"
            if not thumb:
                try:
                    links = getattr(entry, "links", None) or entry.get("links", [])
                    if isinstance(links, list) and len(links) > 1 and links[1].get("href"):
                        thumb, method = links[1]["href"], "links_1_href"
                except Exception:
                    pass
            if not thumb:
                try:
                    images = entry.get("images")
                    if isinstance(images, list) and images:
                        thumb, method = (images[0].get("url", images[0]) if isinstance(images[0], dict) else images[0]), "images_array"
                except Exception:
                    pass
            if not thumb:
                html = _safe_get(entry, "summary", "description", "content")
                if isinstance(html, list) and html:
                    html = html[0].get("value", "") if isinstance(html[0], dict) else str(html[0])
                extracted = _extract_img_from_html(str(html) if html else "")
                if extracted:
                    thumb, method = extracted, "html_img_parse"

            thumbnails.append(bool(thumb))
            if method:
                thumbnail_methods[method] += 1

            # 4d Published Date
            raw_date = _safe_get(entry, "published", "pubDate", "publishedAt", "created_at", "date", "updated")
            dates.append(_parse_date(raw_date))

        out["entries_with_title"] = sum(titles)
        out["entries_with_url"] = sum(urls)
        out["entries_with_thumbnail"] = sum(thumbnails)
        out["thumbnail_extraction_methods"] = dict(thumbnail_methods)
        out["entries_with_date"] = sum(1 for d in dates if d is not None)

        # ── Step 5: Feed Freshness ──────────────────────────────
        valid_dates = [d for d in dates if d is not None]
        if valid_dates:
            newest = max(valid_dates)
            age_hours = (now - newest).total_seconds() / 3600
            out["newest_entry_age_hours"] = round(age_hours, 1)
            out["entries_within_24h"] = sum(1 for d in valid_dates if (now - d).total_seconds() < 86400)
        else:
            out["newest_entry_age_hours"] = None
            out["entries_within_24h"] = 0

        # ── Step 6: Duplicate Titles ────────────────────────────
        normalized = [" ".join(t.split()) for t in all_titles_raw if t]
        title_counts = Counter(normalized)
        duplicates = sum(c - 1 for c in title_counts.values() if c > 1)
        out["duplicate_titles"] = duplicates

        # ── Step 7: Proposed Config Row ─────────────────────────
        if feed_format == "xml":
            # Determine schema
            has_media = any(thumbnail_methods.get(m, 0) > 0 for m in ("media_content_url", "media_thumbnail_url"))
            schema = "rss_media" if has_media else "rss_standard"
        elif feed_format == "json":
            schema = "json_items"
        else:
            schema = "default"

        out["proposed_config"] = {
            "id": "<TO_BE_ASSIGNED>",
            "feed_url": feed_url,
            "is_active": "true",
            "pub_name": publisher_name,
            "publication_id": "<TO_BE_ASSIGNED>",
            "category_id": "<LOOKUP_REQUIRED>",
            "category_name": category,
            "language_id": str(LANGUAGE_ID_MAP.get(language, "?")),
            "language_name": language,
            "mapping_schema": schema,
        }

        # ── Confidence Score ────────────────────────────────────
        score = 0
        total = len(entries)

        if out["feed_accessible"]:
            score += 20
        if out["feed_format"] is not None:
            score += 10
        if total >= 10:
            score += 10

        title_pct = out["entries_with_title"] / total if total else 0
        url_pct = out["entries_with_url"] / total if total else 0
        thumb_pct = out["entries_with_thumbnail"] / total if total else 0
        date_pct = out["entries_with_date"] / total if total else 0

        if title_pct == 1.0:
            score += 15
        else:
            score += 15
            score -= int((1.0 - title_pct) * 10) * 3

        if url_pct == 1.0:
            score += 15
        else:
            score += 15
            score -= int((1.0 - url_pct) * 10) * 3

        if thumb_pct >= 0.8:
            score += 10
        else:
            score -= int((0.8 - thumb_pct) * 10) * 2

        if date_pct >= 0.8:
            score += 5

        if out["entries_within_24h"] and out["entries_within_24h"] > 0:
            score += 10
        else:
            score -= 10

        if duplicates == 0:
            score += 5
        elif duplicates / total > 0.1:
            score -= 5

        if out.get("response_time_ms") and out["response_time_ms"] > 5000:
            score -= 5

        score = max(0, min(100, score))
        result["confidence_score"] = score

        # ── Determine Status ────────────────────────────────────
        if score >= 70:
            result["validation_status"] = "passed"
        elif score >= 50:
            result["validation_status"] = "warning"
        else:
            result["validation_status"] = "failed"

        # ── Issues & Recommendations ────────────────────────────
        if title_pct < 1.0:
            missing = total - out["entries_with_title"]
            result["issues"].append(f"{missing} entries are missing valid titles (< 10 chars or empty).")
        if url_pct < 1.0:
            missing = total - out["entries_with_url"]
            result["issues"].append(f"{missing} entries are missing valid URLs.")
        if thumb_pct < 0.8:
            missing = total - out["entries_with_thumbnail"]
            result["recommendations"].append(
                f"{missing} entries are missing thumbnails. Verify publisher supports media:content or media:thumbnail tags."
            )
        if out["entries_within_24h"] == 0:
            age = out.get("newest_entry_age_hours")
            result["issues"].append(f"No entries within the last 24 hours. Newest entry is {age}h old." if age else "No entries with parseable dates found.")
        if duplicates > 0:
            result["recommendations"].append(f"{duplicates} duplicate titles detected. Verify feed is not duplicating content.")
        missing_dates = total - out["entries_with_date"]
        if missing_dates > 0:
            result["recommendations"].append(f"{missing_dates} entries have no parseable published date.")

        # Add sample entries for reference
        sample_entries = []
        for i, entry in enumerate(entries[:3]):
            title = _safe_get(entry, "title", "headline")
            link = _safe_get(entry, "link", "url", "sourceUrl")
            if isinstance(link, list) and link:
                link = link[0].get("href", "") if isinstance(link[0], dict) else str(link[0])
            sample_entries.append({"title": str(title)[:100] if title else None, "url": str(link)[:200] if link else None})
        out["sample_entries"] = sample_entries

        return result


# ── Video Feed Validator ────────────────────────────────────────────

class VideoFeedValidator:
    """
    Validates MRSS/RSS feeds for Native Videos ingestion.
    Implements every step from native-videos-publisher-onboarding/SKILL.md.
    """

    def validate(self, feed_url: str, publisher_name: str, language: str, category: str) -> dict:
        now = datetime.now(timezone.utc)
        result = {
            "skill_name": "native-videos-publisher-onboarding",
            "run_mode": "dry-run",
            "timestamp": now.isoformat(),
            "inputs": {
                "feed_url": feed_url,
                "publisher_name": publisher_name,
                "language": language,
                "category": category,
            },
            "output": {},
            "validation_status": "passed",
            "confidence_score": 0,
            "issues": [],
            "recommendations": [],
        }
        out = result["output"]

        # ── Input Validation ────────────────────────────────────
        if language not in LANGUAGE_ID_MAP:
            result["validation_status"] = "failed"
            result["issues"].append(f"Invalid language '{language}'. Must be one of: {', '.join(LANGUAGE_ID_MAP.keys())}")
            return result
        if category not in VALID_CATEGORIES:
            result["validation_status"] = "failed"
            result["issues"].append(f"Invalid category '{category}'. Must be one of: {', '.join(VALID_CATEGORIES)}")
            return result

        # ── Step 1: Fetch Feed ──────────────────────────────────
        try:
            with _http_client(timeout=10, follow_redirects=True, max_redirects=3) as client:
                resp = client.get(feed_url)
            out["feed_accessible"] = resp.status_code < 400
            out["http_status_code"] = resp.status_code
            out["response_time_ms"] = int(resp.elapsed.total_seconds() * 1000)
            content_type = resp.headers.get("content-type", "")
            body = resp.text
        except httpx.TimeoutException:
            out["feed_accessible"] = False
            out["http_status_code"] = None
            out["response_time_ms"] = 10000
            result["validation_status"] = "failed"
            result["confidence_score"] = 0
            result["issues"].append("Feed URL timed out after 10 seconds.")
            return result
        except Exception as exc:
            out["feed_accessible"] = False
            out["http_status_code"] = None
            out["response_time_ms"] = None
            result["validation_status"] = "failed"
            result["confidence_score"] = 0
            result["issues"].append(f"Network error fetching feed: {exc}")
            return result

        if not out["feed_accessible"]:
            result["validation_status"] = "failed"
            result["confidence_score"] = 0
            result["issues"].append(f"Feed returned HTTP {out['http_status_code']}.")
            return result

        # ── Step 2: Detect Format & Parse ───────────────────────
        feed_format = None
        entries = []

        if any(t in content_type for t in ("json",)):
            feed_format = "json"
        elif any(t in content_type for t in ("xml", "rss", "atom")):
            feed_format = "xml"
        elif body.lstrip().startswith(("{", "[")):
            feed_format = "json"
        elif body.lstrip().startswith(("<",)):
            feed_format = "xml"

        if feed_format == "json":
            try:
                import json
                data = json.loads(body)
                for path in ("items", "data", "articles"):
                    if isinstance(data, dict) and isinstance(data.get(path), list):
                        entries = data[path]
                        break
                if not entries and isinstance(data, list):
                    entries = data
            except Exception:
                pass

        if feed_format == "xml" or not entries:
            try:
                parsed = feedparser.parse(body)
                if parsed.entries:
                    entries = parsed.entries
                    if feed_format is None:
                        feed_format = "xml"
            except Exception:
                pass

        out["feed_format"] = feed_format
        out["total_entries"] = len(entries)

        if len(entries) == 0:
            result["validation_status"] = "failed"
            result["confidence_score"] = 0
            result["issues"].append("Zero entries found in the feed.")
            return result

        # ── Step 3: Validate Metadata Per Entry ─────────────────
        titles = []
        thumbnails = []
        video_urls = []
        video_classifications = []
        dates_parsed = []
        all_titles_raw = []

        for entry in entries:
            # 3a Title
            title = _safe_get(entry, "title", "headline")
            title = str(title).strip() if title else ""
            titles.append(bool(title and len(title) >= 10))
            all_titles_raw.append(title.lower().strip())

            # 3b Thumbnail
            thumb = None
            try:
                mt = getattr(entry, "media_thumbnail", None) or (entry.get("media_thumbnail") if isinstance(entry, dict) else None)
                if mt and isinstance(mt, list) and mt[0].get("url"):
                    thumb = mt[0]["url"]
            except Exception:
                pass
            if not thumb:
                try:
                    mc = getattr(entry, "media_content", None) or (entry.get("media_content") if isinstance(entry, dict) else None)
                    if mc and isinstance(mc, list):
                        for item in mc:
                            mtype = item.get("medium", "") or item.get("type", "")
                            if "image" in str(mtype).lower():
                                thumb = item.get("url")
                                break
                except Exception:
                    pass
            if not thumb:
                for key in ("thumbnail", "thumbUrl", "image"):
                    val = _safe_get(entry, key)
                    if val:
                        if isinstance(val, dict) and val.get("url"):
                            thumb = val["url"]
                        elif isinstance(val, str) and _is_valid_url(val):
                            thumb = val
                        break
            if not thumb:
                html = _safe_get(entry, "description", "summary")
                if isinstance(html, list) and html:
                    html = html[0].get("value", "") if isinstance(html[0], dict) else str(html[0])
                extracted = _extract_img_from_html(str(html) if html else "")
                if extracted:
                    thumb = extracted
            thumbnails.append(bool(thumb))

            # 3c Video URL Extraction
            video_url = None
            try:
                mc = getattr(entry, "media_content", None) or (entry.get("media_content") if isinstance(entry, dict) else None)
                if mc and isinstance(mc, list):
                    # First try: medium=video or type=video/*
                    for item in mc:
                        medium = item.get("medium", "")
                        mtype = item.get("type", "")
                        if "video" in str(medium).lower() or str(mtype).lower().startswith("video/"):
                            video_url = item.get("url")
                            break
                    # Fallback: first media_content with .mp4
                    if not video_url:
                        for item in mc:
                            url = item.get("url", "")
                            if ".mp4" in url.lower():
                                video_url = url
                                break
                    # Last fallback: just first media_content url
                    if not video_url and mc[0].get("url"):
                        video_url = mc[0]["url"]
            except Exception:
                pass

            if not video_url:
                for key in ("video", "videoUrl", "video_url"):
                    val = _safe_get(entry, key)
                    if val and isinstance(val, str):
                        video_url = val
                        break

            if not video_url:
                try:
                    enclosures = getattr(entry, "enclosures", None) or entry.get("enclosures", [])
                    if enclosures:
                        for enc in enclosures:
                            if str(enc.get("type", "")).startswith("video/"):
                                video_url = enc.get("href") or enc.get("url")
                                break
                except Exception:
                    pass

            if not video_url:
                try:
                    links = getattr(entry, "links", None) or entry.get("links", [])
                    if links:
                        for lnk in links:
                            if str(lnk.get("type", "")).startswith("video/"):
                                video_url = lnk.get("href") or lnk.get("url")
                                break
                except Exception:
                    pass

            video_urls.append(video_url)
            video_classifications.append(_classify_video_url(video_url) if video_url else "none")

            # Date
            raw_date = _safe_get(entry, "published", "pubDate", "publishedAt", "created_at", "date", "updated")
            dates_parsed.append(_parse_date(raw_date))

        out["entries_with_title"] = sum(titles)
        out["entries_with_thumbnail"] = sum(thumbnails)
        out["entries_with_video_url"] = sum(1 for v in video_urls if v)
        out["entries_with_date"] = sum(1 for d in dates_parsed if d is not None)

        # ── Step 4: Video-Specific Validations ──────────────────

        # 4a MP4 URL Format Check
        mp4_count = sum(1 for c in video_classifications if c == "mp4_direct")
        yt_count = sum(1 for c in video_classifications if c == "youtube")
        other_count = sum(1 for c in video_classifications if c == "other_platform")
        unknown_count = sum(1 for c in video_classifications if c == "unknown")
        none_count = sum(1 for c in video_classifications if c == "none")

        out["entries_with_mp4_url"] = mp4_count
        out["entries_with_youtube_url"] = yt_count
        out["video_url_breakdown"] = {
            "mp4_direct": mp4_count,
            "youtube": yt_count,
            "other_platform": other_count,
            "unknown": unknown_count,
            "no_video_url": none_count,
        }

        youtube_urls_found = [v for v, c in zip(video_urls, video_classifications) if c == "youtube" and v]
        if youtube_urls_found:
            out["youtube_urls_found"] = youtube_urls_found[:5]

        total_with_video = out["entries_with_video_url"]
        if total_with_video > 0 and yt_count / total_with_video > 0.5:
            result["validation_status"] = "failed"
            result["issues"].append(
                f"CRITICAL: {yt_count} of {total_with_video} video URLs ({int(yt_count/total_with_video*100)}%) are YouTube links. "
                "Publishers must provide direct MP4 CDN URLs."
            )

        # 4b MP4 URL Accessibility Check (first 3 MP4 URLs)
        mp4_urls_to_test = [v for v, c in zip(video_urls, video_classifications) if c == "mp4_direct" and v][:3]
        mp4_checks = []
        for url in mp4_urls_to_test:
            check = {"url": url, "status_code": None, "content_type": None, "content_length_bytes": None, "accessible": False}
            try:
                with _http_client(timeout=15, follow_redirects=True) as client:
                    head_resp = client.head(url)
                check["status_code"] = head_resp.status_code
                check["content_type"] = head_resp.headers.get("content-type")
                cl = head_resp.headers.get("content-length")
                check["content_length_bytes"] = int(cl) if cl else None
                check["accessible"] = head_resp.status_code in (200, 206)
                if check["content_type"] and "video/" not in check["content_type"].lower():
                    check["accessible"] = False
                    result["recommendations"].append(f"MP4 URL returned Content-Type '{check['content_type']}' instead of video/mp4: {url[:80]}")
            except Exception as exc:
                check["accessible"] = False
                result["recommendations"].append(f"Could not reach MP4 URL: {url[:80]} - {exc}")
            mp4_checks.append(check)

        out["mp4_url_checks"] = mp4_checks
        out["mp4_urls_accessible"] = sum(1 for c in mp4_checks if c["accessible"])
        out["mp4_urls_tested"] = len(mp4_checks)

        # 4c MP4 File Integrity (first accessible URL)
        out["mp4_signature_valid"] = None
        out["ftyp_brand"] = None
        accessible_mp4 = next((c["url"] for c in mp4_checks if c["accessible"]), None)
        if accessible_mp4:
            try:
                with _http_client(timeout=30, follow_redirects=True) as client:
                    partial = client.get(accessible_mp4, headers={"Range": "bytes=0-1048575"})
                if len(partial.content) >= 8:
                    ftyp_marker = partial.content[4:8]
                    if ftyp_marker == b"ftyp":
                        out["mp4_signature_valid"] = True
                        brand = partial.content[8:12]
                        out["ftyp_brand"] = brand.decode("ascii", errors="replace").strip()
                    else:
                        out["mp4_signature_valid"] = False
                        result["recommendations"].append("MP4 file signature check failed: bytes 4-7 are not 'ftyp'. File may not be a valid MP4.")
            except Exception as exc:
                result["recommendations"].append(f"Could not perform MP4 integrity check: {exc}")

        # 4d Video Resolution Check (from MRSS metadata)
        out["video_resolution"] = "unknown"
        out["is_1080p"] = None
        try:
            for entry in entries:
                mc = getattr(entry, "media_content", None) or (entry.get("media_content") if isinstance(entry, dict) else None)
                if mc and isinstance(mc, list):
                    for item in mc:
                        w = item.get("width")
                        h = item.get("height")
                        if w and h:
                            w, h = int(w), int(h)
                            out["video_resolution"] = f"{w}x{h}"
                            out["is_1080p"] = (w >= 1920 or h >= 1080)
                            break
                if out["video_resolution"] != "unknown":
                    break
        except Exception:
            pass

        # ── Step 5: Feed Freshness ──────────────────────────────
        valid_dates = [d for d in dates_parsed if d is not None]
        if valid_dates:
            newest = max(valid_dates)
            age_hours = (now - newest).total_seconds() / 3600
            out["newest_entry_age_hours"] = round(age_hours, 1)
            out["entries_within_24h"] = sum(1 for d in valid_dates if (now - d).total_seconds() < 86400)
        else:
            out["newest_entry_age_hours"] = None
            out["entries_within_24h"] = 0

        # Duplicate titles
        normalized = [" ".join(t.split()) for t in all_titles_raw if t]
        title_counts = Counter(normalized)
        duplicates = sum(c - 1 for c in title_counts.values() if c > 1)
        out["duplicate_titles"] = duplicates

        # ── Step 6: YouTube URL Reporting ───────────────────────
        if yt_count > 0:
            result["issues"].append(
                f"Found {yt_count} entries with YouTube URLs instead of direct MP4 links."
            )
            result["recommendations"].append(
                "Publisher must provide direct MP4 CDN URLs, not YouTube links. "
                "YouTube URLs cannot be ingested by the native videos pipeline because: "
                "(1) YouTube does not allow direct video download, "
                "(2) YouTube URLs require separate YouTube Data API processing, "
                "(3) transcoder cannot process YouTube URLs."
            )

        # ── Step 7: Proposed Config Row ─────────────────────────
        out["proposed_config"] = {
            "id": "<TO_BE_ASSIGNED>",
            "feed_url": feed_url,
            "is_active": "true",
            "pub_name": publisher_name,
            "publication_id": "<TO_BE_ASSIGNED>",
            "category_id": "<LOOKUP_REQUIRED>",
            "category_name": category,
            "language_id": str(LANGUAGE_ID_MAP.get(language, "?")),
            "language_name": language,
            "content_type": "videos",
            "mapping_schema": "mrss_media" if feed_format == "xml" else "json_video",
        }

        # ── Confidence Score ────────────────────────────────────
        score = 0
        total = len(entries)

        if out["feed_accessible"]:
            score += 15
        if out["feed_format"]:
            score += 5
        if total >= 5:
            score += 5

        title_pct = out["entries_with_title"] / total if total else 0
        thumb_pct = out["entries_with_thumbnail"] / total if total else 0
        video_pct = out["entries_with_video_url"] / total if total else 0

        if title_pct == 1.0:
            score += 10
        if thumb_pct >= 0.8:
            score += 5
        if video_pct >= 0.8:
            score += 10

        # MP4 quality
        if total_with_video > 0 and mp4_count == total_with_video:
            score += 15  # 100% MP4 direct
        elif yt_count > 0:
            if yt_count / total_with_video > 0.5:
                score -= 25
            else:
                score -= 15

        # Accessibility
        if out["mp4_urls_tested"] > 0 and out["mp4_urls_accessible"] == out["mp4_urls_tested"]:
            score += 10
        elif out["mp4_urls_tested"] > 0:
            score -= 5 * (out["mp4_urls_tested"] - out["mp4_urls_accessible"])

        if out["mp4_signature_valid"] is True:
            score += 5
        elif out["mp4_signature_valid"] is False:
            score -= 5

        if out["is_1080p"] is True:
            score += 10
        elif out["is_1080p"] is False:
            score -= 10
        else:
            score -= 5  # unknown

        if out["entries_within_24h"] and out["entries_within_24h"] > 0:
            score += 5
        else:
            score -= 5

        if duplicates == 0:
            score += 5
        elif total and duplicates / total > 0.1:
            score -= 5

        if out.get("response_time_ms") and out["response_time_ms"] > 5000:
            score -= 3

        score = max(0, min(100, score))
        result["confidence_score"] = score

        # ── Determine Status ────────────────────────────────────
        if result["validation_status"] != "failed":
            if score >= 70:
                result["validation_status"] = "passed"
            elif score >= 50:
                result["validation_status"] = "warning"
            else:
                result["validation_status"] = "failed"

        # ── Additional Issues & Recommendations ─────────────────
        if total_with_video == 0:
            result["issues"].append("No video URLs found in any feed entry.")
        if mp4_count == 0 and yt_count == 0:
            result["issues"].append("No MP4 direct URLs and no YouTube URLs found. Feed may not contain video content.")
        if out["mp4_urls_tested"] > 0 and out["mp4_urls_accessible"] < out["mp4_urls_tested"]:
            failed_count = out["mp4_urls_tested"] - out["mp4_urls_accessible"]
            result["issues"].append(f"{failed_count} of {out['mp4_urls_tested']} tested MP4 URLs are not accessible.")
        if out["video_resolution"] == "unknown":
            result["recommendations"].append("Video resolution could not be determined from feed metadata. Consider verifying manually with ffprobe.")
        if out["entries_within_24h"] == 0:
            result["issues"].append("No entries within the last 24 hours. Feed may be stale.")

        # Sample entries
        sample_entries = []
        for i, (entry, vid_url, vid_class) in enumerate(zip(entries[:3], video_urls[:3], video_classifications[:3])):
            title = _safe_get(entry, "title", "headline")
            sample_entries.append({
                "title": str(title)[:100] if title else None,
                "video_url": str(vid_url)[:200] if vid_url else None,
                "video_type": vid_class,
            })
        out["sample_entries"] = sample_entries

        return result
