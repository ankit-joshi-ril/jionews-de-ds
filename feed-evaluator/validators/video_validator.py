"""
Video Feed Validator
Validates MRSS/RSS feeds for Native Videos ingestion pipeline.
"""

import json
from collections import Counter
from datetime import datetime, timezone

import feedparser
import httpx

from .constants import LANGUAGE_ID_MAP, VALID_CATEGORIES
from .helpers import _safe_get, _extract_img_from_html, _parse_date, _http_client, _is_valid_url, _classify_video_url


class VideoFeedValidator:
    """
    Validates MRSS/RSS feeds for Native Videos ingestion.
    Implements every step from native-videos-publisher-onboarding skill.
    """

    def validate(self, feed_url: str, publisher_name: str = "", language: str = "", category: str = "") -> dict:
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

        # ── Input Validation (skip if empty) ─────────────────────
        if language and language not in LANGUAGE_ID_MAP:
            result["validation_status"] = "failed"
            result["issues"].append(f"Invalid language '{language}'. Must be one of: {', '.join(LANGUAGE_ID_MAP.keys())}")
            return result
        if category and category not in VALID_CATEGORIES:
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
                    for item in mc:
                        medium = item.get("medium", "")
                        mtype = item.get("type", "")
                        if "video" in str(medium).lower() or str(mtype).lower().startswith("video/"):
                            video_url = item.get("url")
                            break
                    if not video_url:
                        for item in mc:
                            url = item.get("url", "")
                            if ".mp4" in url.lower():
                                video_url = url
                                break
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
            "pub_name": publisher_name or "<TO_BE_PROVIDED>",
            "publication_id": "<TO_BE_ASSIGNED>",
            "category_id": "<LOOKUP_REQUIRED>",
            "category_name": category or "<TO_BE_PROVIDED>",
            "language_id": str(LANGUAGE_ID_MAP.get(language, "?")) if language else "?",
            "language_name": language or "<TO_BE_PROVIDED>",
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
            score += 15
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
            score -= 5

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
