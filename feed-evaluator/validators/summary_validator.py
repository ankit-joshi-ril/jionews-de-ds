"""
Summary Feed Validator
Validates RSS/JSON feeds for Summaries ingestion pipeline.
Extends headline validation with summary-specific hygiene checks.
"""

import json
import re
from collections import Counter
from datetime import datetime, timezone

import feedparser
import httpx

from .constants import LANGUAGE_ID_MAP, VALID_CATEGORIES
from .helpers import _safe_get, _extract_img_from_html, _parse_date, _http_client, _is_valid_url


class SummaryFeedValidator:
    """
    Validates RSS/JSON feeds for Summaries ingestion.
    Adds summary-specific hygiene pre-checks:
    - Title length: 26-105 chars
    - Summary/description length: 200-360 chars
    - HTML tag detection in title and summary
    - Special character count (< 3 allowed)
    """

    @staticmethod
    def _contains_html(text: str) -> bool:
        if not isinstance(text, str):
            return False
        return bool(re.search(r"</?[a-z][\s\S]*>", text, re.IGNORECASE))

    @staticmethod
    def _excess_special_chars(text: str) -> bool:
        if not isinstance(text, str):
            return False
        special = "@#$%^&*()_+=[]{}\\|<>/?"
        return sum(1 for ch in text if ch in special) >= 3

    def validate(self, feed_url: str, publisher_name: str = "", language: str = "", category: str = "") -> dict:
        now = datetime.now(timezone.utc)
        result = {
            "skill_name": "summaries-publisher-onboarding",
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

        if not entries and feed_format != "json":
            try:
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
        summaries_found = []
        hygiene_results = {
            "title_ok": 0, "title_too_short": 0, "title_too_long": 0,
            "title_has_html": 0, "title_special_chars": 0,
            "summary_ok": 0, "summary_too_short": 0, "summary_too_long": 0,
            "summary_has_html": 0, "summary_special_chars": 0,
            "summary_missing": 0,
        }
        all_titles_raw = []
        thumbnail_methods = Counter()

        for entry in entries:
            # 4a Title
            title = _safe_get(entry, "title", "headline")
            title = str(title).strip() if title else ""
            titles.append(bool(title and len(title) >= 10))
            all_titles_raw.append(title.lower().strip())

            # Title hygiene
            if title:
                if len(title) < 26:
                    hygiene_results["title_too_short"] += 1
                elif len(title) > 105:
                    hygiene_results["title_too_long"] += 1
                else:
                    hygiene_results["title_ok"] += 1
                if self._contains_html(title):
                    hygiene_results["title_has_html"] += 1
                if self._excess_special_chars(title):
                    hygiene_results["title_special_chars"] += 1

            # 4b URL/Link
            link = _safe_get(entry, "link", "url", "sourceUrl")
            if isinstance(link, list) and link:
                link = link[0].get("href", "") if isinstance(link[0], dict) else str(link[0])
            urls.append(_is_valid_url(str(link)) if link else False)

            # 4c Thumbnail (simplified chain)
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
                img_val = _safe_get(entry, "image", "thumbimage", "fullimage")
                if img_val:
                    if isinstance(img_val, dict):
                        thumb = img_val.get("url") or img_val.get("link")
                        method = "image_dict"
                    elif isinstance(img_val, str) and _is_valid_url(img_val):
                        thumb, method = img_val, "image_str"
            if not thumb:
                html_content = _safe_get(entry, "summary", "description", "content")
                if isinstance(html_content, list) and html_content:
                    html_content = html_content[0].get("value", "") if isinstance(html_content[0], dict) else str(html_content[0])
                extracted = _extract_img_from_html(str(html_content) if html_content else "")
                if extracted:
                    thumb, method = extracted, "html_img_parse"

            thumbnails.append(bool(thumb))
            if method:
                thumbnail_methods[method] += 1

            # 4d Summary/Description extraction + hygiene
            summary_text = _safe_get(entry, "summary", "description", "content", "brief")
            if isinstance(summary_text, list) and summary_text:
                summary_text = summary_text[0].get("value", "") if isinstance(summary_text[0], dict) else str(summary_text[0])
            summary_text = str(summary_text).strip() if summary_text else ""

            if not summary_text:
                hygiene_results["summary_missing"] += 1
                summaries_found.append(False)
            else:
                summaries_found.append(True)
                if len(summary_text) < 200:
                    hygiene_results["summary_too_short"] += 1
                elif len(summary_text) > 360:
                    hygiene_results["summary_too_long"] += 1
                else:
                    hygiene_results["summary_ok"] += 1
                if self._contains_html(summary_text):
                    hygiene_results["summary_has_html"] += 1
                if self._excess_special_chars(summary_text):
                    hygiene_results["summary_special_chars"] += 1

            # 4e Published Date
            raw_date = _safe_get(entry, "published", "pubDate", "publishedAt", "created_at", "date", "updated")
            dates.append(_parse_date(raw_date))

        total = len(entries)
        out["entries_with_title"] = sum(titles)
        out["entries_with_url"] = sum(urls)
        out["entries_with_thumbnail"] = sum(thumbnails)
        out["thumbnail_extraction_methods"] = dict(thumbnail_methods)
        out["entries_with_date"] = sum(1 for d in dates if d is not None)
        out["entries_with_summary"] = sum(summaries_found)
        out["hygiene_results"] = hygiene_results

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
            has_media = any(thumbnail_methods.get(m, 0) > 0 for m in ("media_content_url", "media_thumbnail_url"))
            schema = "rss_media" if has_media else "rss_standard"
        elif feed_format == "json":
            schema = "json_items"
        else:
            schema = "default"

        out["proposed_config"] = {
            "id": "<TO_BE_ASSIGNED>",
            "feed_url": feed_url,
            "pub_name": publisher_name or "<TO_BE_PROVIDED>",
            "publication_id": "<TO_BE_ASSIGNED>",
            "category_id": "<LOOKUP_REQUIRED>",
            "category_name": category or "Top News",
            "language_id": str(LANGUAGE_ID_MAP.get(language, "?")) if language else "?",
            "language_name": language or "<TO_BE_PROVIDED>",
            "mapping_schema": schema,
        }

        # ── Confidence Score ────────────────────────────────────
        score = 0

        if out["feed_accessible"]:
            score += 20
        if out["feed_format"] is not None:
            score += 10
        if total >= 10:
            score += 10

        title_pct = out["entries_with_title"] / total if total else 0
        url_pct = out["entries_with_url"] / total if total else 0
        thumb_pct = out["entries_with_thumbnail"] / total if total else 0
        summary_pct = out["entries_with_summary"] / total if total else 0

        # Title coverage
        if title_pct == 1.0:
            score += 10
        else:
            score += 10
            score -= int((1.0 - title_pct) * 10) * 3

        # URL coverage
        if url_pct == 1.0:
            score += 10
        else:
            score += 10
            score -= int((1.0 - url_pct) * 10) * 3

        # Summary presence
        if summary_pct >= 0.8:
            score += 10
        else:
            score -= int((0.8 - summary_pct) * 10) * 2

        # Summary length quality
        if total > 0 and hygiene_results["summary_ok"] / total >= 0.8:
            score += 5

        # HTML contamination
        html_count = hygiene_results["title_has_html"] + hygiene_results["summary_has_html"]
        if total > 0 and html_count / total <= 0.1:
            score += 5
        elif html_count > 0:
            score -= 5

        # Thumbnail coverage
        if thumb_pct >= 0.8:
            score += 5

        # Freshness
        if out["entries_within_24h"] and out["entries_within_24h"] > 0:
            score += 10
        else:
            score -= 10

        # Duplicates
        if duplicates == 0:
            score += 5
        elif total and duplicates / total > 0.1:
            score -= 5

        # Speed
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
            result["issues"].append(f"{missing} entries are missing valid titles.")
        if url_pct < 1.0:
            missing = total - out["entries_with_url"]
            result["issues"].append(f"{missing} entries are missing valid URLs.")
        if summary_pct < 0.8:
            missing = total - out["entries_with_summary"]
            result["issues"].append(f"{missing} entries are missing summary/description content.")
        if hygiene_results["title_too_short"] > 0:
            result["recommendations"].append(f"{hygiene_results['title_too_short']} titles are shorter than 26 characters.")
        if hygiene_results["title_too_long"] > 0:
            result["recommendations"].append(f"{hygiene_results['title_too_long']} titles exceed 105 characters.")
        if hygiene_results["summary_too_short"] > 0:
            result["recommendations"].append(f"{hygiene_results['summary_too_short']} summaries are shorter than 200 characters.")
        if hygiene_results["summary_too_long"] > 0:
            result["recommendations"].append(f"{hygiene_results['summary_too_long']} summaries exceed 360 characters.")
        if hygiene_results["title_has_html"] + hygiene_results["summary_has_html"] > 0:
            result["issues"].append(f"HTML tags detected in {hygiene_results['title_has_html']} titles and {hygiene_results['summary_has_html']} summaries.")
        if out["entries_within_24h"] == 0:
            age = out.get("newest_entry_age_hours")
            result["issues"].append(f"No entries within the last 24 hours. Newest entry is {age}h old." if age else "No entries with parseable dates found.")
        if duplicates > 0:
            result["recommendations"].append(f"{duplicates} duplicate titles detected.")

        # Sample entries
        sample_entries = []
        for entry in entries[:3]:
            title = _safe_get(entry, "title", "headline")
            link = _safe_get(entry, "link", "url", "sourceUrl")
            if isinstance(link, list) and link:
                link = link[0].get("href", "") if isinstance(link[0], dict) else str(link[0])
            summary_text = _safe_get(entry, "summary", "description", "content", "brief")
            if isinstance(summary_text, list) and summary_text:
                summary_text = summary_text[0].get("value", "") if isinstance(summary_text[0], dict) else str(summary_text[0])
            sample_entries.append({
                "title": str(title)[:100] if title else None,
                "url": str(link)[:200] if link else None,
                "summary_preview": str(summary_text)[:150] + "..." if summary_text and len(str(summary_text)) > 150 else str(summary_text) if summary_text else None,
            })
        out["sample_entries"] = sample_entries

        return result
