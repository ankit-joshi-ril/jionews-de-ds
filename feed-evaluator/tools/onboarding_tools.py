"""
Onboarding Tools
Tool definitions and dispatcher for the Publisher Onboarding module.
"""

import json
import logging

from validators.headline_validator import HeadlineFeedValidator
from validators.video_validator import VideoFeedValidator
from validators.summary_validator import SummaryFeedValidator
from managers.publisher_manager import (
    check_feed_exists,
    list_feeds,
    query_feeds,
    add_feed,
)

logger = logging.getLogger(__name__)

# ── Shared Enum Values ─────────────────────────────────────────────

_LANGUAGES = [
    "English", "Hindi", "Marathi", "Gujarati", "Malayalam",
    "Tamil", "Urdu", "Kannada", "Punjabi", "Telugu",
    "Bangla", "Odia", "Assamese",
]

_CATEGORIES = [
    "Agro", "Astrology", "Auto/Automobile", "Business",
    "Career/Education", "Entertainment", "Health",
    "India/National", "International/World",
    "Latest News/Top News", "Lifestyle/Fashion",
    "Sci and Tech", "Sports", "Cricket",
    "Top News", "Photogallery", "Technology",
    "Miscellaneous", "news", "Religion",
]

# ── Tool Definitions ───────────────────────────────────────────────

TOOLS = [
    {
        "name": "check_feed_exists",
        "description": (
            "Check if a feed URL already exists in any of the configuration files "
            "(headlines, videos, summaries). ALWAYS use this FIRST before validating a feed. "
            "Returns publisher name, language, category, and feed type if found."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "feed_url": {
                    "type": "string",
                    "description": "The feed URL to check across all configuration files.",
                },
            },
            "required": ["feed_url"],
        },
    },
    {
        "name": "validate_headline_feed",
        "description": (
            "Validates an RSS or JSON feed for Headlines ingestion into JioNews. "
            "Performs comprehensive checks: feed accessibility, format detection (XML/JSON), "
            "entry parsing, metadata validation (titles, URLs, thumbnails via 12-step extraction, dates), "
            "freshness check, duplicate detection, and confidence scoring. "
            "Only feed_url is required - do NOT ask for publisher name, language, or category yet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "feed_url": {
                    "type": "string",
                    "description": "Full HTTP/HTTPS URL of the RSS or JSON feed to validate.",
                },
            },
            "required": ["feed_url"],
        },
    },
    {
        "name": "validate_video_feed",
        "description": (
            "Validates an MRSS or RSS feed for Native Videos ingestion into JioNews. "
            "Performs headline validations PLUS video-specific checks: "
            "MP4 URL format verification (flags YouTube/Vimeo as invalid), "
            "MP4 URL accessibility via HEAD requests, MP4 file integrity check (ftyp signature), "
            "video resolution verification, and YouTube URL detection. "
            "Only feed_url is required - do NOT ask for publisher name, language, or category yet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "feed_url": {
                    "type": "string",
                    "description": "Full HTTP/HTTPS URL of the MRSS or RSS video feed to validate.",
                },
            },
            "required": ["feed_url"],
        },
    },
    {
        "name": "validate_summary_feed",
        "description": (
            "Validates an RSS or JSON feed for Summaries ingestion into JioNews. "
            "Performs headline-style validations PLUS summary-specific hygiene checks: "
            "title length validation (26-105 characters), summary length validation (200-360 characters), "
            "HTML contamination detection, special character analysis, and content quality scoring. "
            "Only feed_url is required - do NOT ask for publisher name, language, or category yet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "feed_url": {
                    "type": "string",
                    "description": "Full HTTP/HTTPS URL of the RSS or JSON feed to validate for summaries.",
                },
            },
            "required": ["feed_url"],
        },
    },
    {
        "name": "list_feeds",
        "description": (
            "List existing feeds from the configuration with optional filters. "
            "Returns a paginated list of feeds with their details (publisher, language, category, URL). "
            "Use this when users ask about existing feeds, e.g., 'show me all Hindi video feeds'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "feed_type": {
                    "type": "string",
                    "description": "Type of feeds to list.",
                    "enum": ["headlines", "videos", "summaries"],
                },
                "language": {
                    "type": "string",
                    "description": "Filter by language (optional).",
                },
                "publisher": {
                    "type": "string",
                    "description": "Filter by publisher name - supports partial match (optional).",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category - supports partial match (optional).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 50, max 200).",
                    "default": 50,
                },
            },
            "required": ["feed_type"],
        },
    },
    {
        "name": "query_feeds",
        "description": (
            "Run analytics queries on feed configuration data. "
            "Supports: count_by_publisher, count_by_language, count_by_category, search, total_counts. "
            "Use this when users ask analytical questions like 'how many English feeds do we have?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "description": "Type of analytics query to run.",
                    "enum": ["count_by_publisher", "count_by_language", "count_by_category", "search", "total_counts"],
                },
                "feed_type": {
                    "type": "string",
                    "description": "Feed type to query. Leave empty to query across all types.",
                    "enum": ["headlines", "videos", "summaries"],
                },
                "filter_value": {
                    "type": "string",
                    "description": "Search term for 'search' query type. Also used as filter for other queries.",
                },
            },
            "required": ["query_type"],
        },
    },
    {
        "name": "add_feed_to_config",
        "description": (
            "Add a new feed to the configuration CSV after successful validation. "
            "Appends a new row with auto-incremented ID. "
            "ONLY use this after: 1) checking feed doesn't already exist, 2) validation passed, "
            "3) user has provided publisher name, language, and category."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "feed_type": {
                    "type": "string",
                    "description": "Type of feed configuration to add to.",
                    "enum": ["headlines", "videos", "summaries"],
                },
                "feed_url": {
                    "type": "string",
                    "description": "The validated feed URL to add.",
                },
                "publisher_name": {
                    "type": "string",
                    "description": "Human-readable publisher name.",
                },
                "language": {
                    "type": "string",
                    "description": "Language of the feed content.",
                    "enum": _LANGUAGES,
                },
                "category": {
                    "type": "string",
                    "description": "Content category for the feed.",
                },
            },
            "required": ["feed_type", "feed_url", "publisher_name", "language", "category"],
        },
    },
]


# ── Tool Execution Dispatcher ──────────────────────────────────────

def execute_tool(name: str, inputs: dict) -> dict:
    """Execute an onboarding tool and return the result."""
    logger.info(f"Executing tool: {name}")
    try:
        if name == "check_feed_exists":
            return check_feed_exists(inputs["feed_url"])

        elif name == "validate_headline_feed":
            validator = HeadlineFeedValidator()
            return validator.validate(feed_url=inputs["feed_url"])

        elif name == "validate_video_feed":
            validator = VideoFeedValidator()
            return validator.validate(feed_url=inputs["feed_url"])

        elif name == "validate_summary_feed":
            validator = SummaryFeedValidator()
            return validator.validate(feed_url=inputs["feed_url"])

        elif name == "list_feeds":
            return list_feeds(
                feed_type=inputs["feed_type"],
                language=inputs.get("language", ""),
                publisher=inputs.get("publisher", ""),
                category=inputs.get("category", ""),
                limit=min(inputs.get("limit", 50), 200),
            )

        elif name == "query_feeds":
            return query_feeds(
                query_type=inputs["query_type"],
                feed_type=inputs.get("feed_type", ""),
                filter_value=inputs.get("filter_value", ""),
            )

        elif name == "add_feed_to_config":
            return add_feed(
                feed_type=inputs["feed_type"],
                feed_url=inputs["feed_url"],
                publisher_name=inputs["publisher_name"],
                language=inputs["language"],
                category=inputs["category"],
            )

        else:
            return {"error": f"Unknown tool: {name}"}

    except Exception as exc:
        logger.exception(f"Tool execution failed: {name}")
        return {"error": str(exc)}
