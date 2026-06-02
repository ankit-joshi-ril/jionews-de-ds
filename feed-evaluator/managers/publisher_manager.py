"""
Publisher Feed Manager
Handles CSV-based feed configuration: search, list, add, query, export.
"""

import io
from pathlib import Path

import pandas as pd

from validators.constants import LANGUAGE_ID_MAP, VALID_CATEGORIES

_CONFIG_DIR = Path(__file__).parent.parent / "config"

FEED_TYPES = {
    "headlines": "headlines_publishers_feeds.csv",
    "videos": "mrss_videos_feeds.csv",
    "summaries": "summaries_publishers_feeds.csv",
}

# Cache loaded DataFrames
_cache: dict[str, pd.DataFrame] = {}


def _load_csv(feed_type: str) -> pd.DataFrame:
    """Load a CSV config file into a DataFrame, with caching."""
    if feed_type not in FEED_TYPES:
        raise ValueError(f"Unknown feed type: {feed_type}. Must be one of: {list(FEED_TYPES.keys())}")
    if feed_type not in _cache:
        path = _CONFIG_DIR / FEED_TYPES[feed_type]
        _cache[feed_type] = pd.read_csv(path, encoding="utf-8")
    return _cache[feed_type]


def _save_csv(feed_type: str, df: pd.DataFrame):
    """Save a DataFrame back to its CSV file and update cache."""
    path = _CONFIG_DIR / FEED_TYPES[feed_type]
    df.to_csv(path, index=False, encoding="utf-8")
    _cache[feed_type] = df


def reload_all():
    """Force reload all CSVs from disk."""
    _cache.clear()


def check_feed_exists(feed_url: str) -> dict:
    """
    Search all 3 CSVs for a feed URL.
    Returns match details or not-found.
    """
    feed_url = feed_url.strip().rstrip("/")
    results = []

    for feed_type in FEED_TYPES:
        df = _load_csv(feed_type)
        # Normalize URLs for comparison
        df_urls = df["feed_url"].astype(str).str.strip().str.rstrip("/")
        matches = df[df_urls == feed_url]

        if not matches.empty:
            for _, row in matches.iterrows():
                results.append({
                    "feed_type": feed_type,
                    "id": int(row.get("id", 0)),
                    "feed_url": str(row.get("feed_url", "")),
                    "pub_name": str(row.get("pub_name", "")),
                    "language": str(row.get("language_name", "")),
                    "category": str(row.get("category_name", "")),
                    "publication_id": int(row.get("publication_id", 0)),
                })

    if results:
        return {
            "exists": True,
            "match_count": len(results),
            "matches": results,
        }
    return {
        "exists": False,
        "match_count": 0,
        "matches": [],
        "message": "Feed URL not found in any configuration file.",
    }


def list_feeds(
    feed_type: str,
    language: str = "",
    publisher: str = "",
    category: str = "",
    limit: int = 50,
) -> dict:
    """List feeds with optional filters."""
    df = _load_csv(feed_type)
    original_count = len(df)

    if language:
        df = df[df["language_name"].astype(str).str.lower() == language.lower()]
    if publisher:
        df = df[df["pub_name"].astype(str).str.lower().str.contains(publisher.lower(), na=False)]
    if category:
        df = df[df["category_name"].astype(str).str.lower().str.contains(category.lower(), na=False)]

    filtered_count = len(df)
    df_limited = df.head(limit)

    # Build records for display
    records = []
    for _, row in df_limited.iterrows():
        rec = {
            "id": int(row.get("id", 0)),
            "pub_name": str(row.get("pub_name", "")),
            "feed_url": str(row.get("feed_url", "")),
            "language": str(row.get("language_name", "")),
            "category": str(row.get("category_name", "")),
        }
        if "is_active" in row:
            rec["is_active"] = str(row.get("is_active", ""))
        records.append(rec)

    return {
        "feed_type": feed_type,
        "total_count": original_count,
        "filtered_count": filtered_count,
        "showing": len(records),
        "limit": limit,
        "filters_applied": {
            "language": language or None,
            "publisher": publisher or None,
            "category": category or None,
        },
        "feeds": records,
    }


def add_feed(
    feed_type: str,
    feed_url: str,
    publisher_name: str,
    language: str,
    category: str,
    publication_id: int = 0,
) -> dict:
    """Append a new feed row to the appropriate CSV."""
    df = _load_csv(feed_type)

    # Generate next ID
    max_id = int(df["id"].max()) if not df.empty else 0
    new_id = max_id + 1

    # Resolve language_id
    language_id = LANGUAGE_ID_MAP.get(language, 0)

    # Resolve category_id (use existing mapping from the CSV)
    cat_rows = df[df["category_name"].astype(str).str.lower() == category.lower()]
    category_id = int(cat_rows["category_id"].iloc[0]) if not cat_rows.empty else 0

    # Build the new row based on feed type schema
    if feed_type == "headlines":
        new_row = {
            "id": new_id,
            "category_id": category_id,
            "language_id": language_id,
            "publication_id": publication_id,
            "feed_url": feed_url.strip(),
            "category_name": category,
            "pub_name": publisher_name,
            "language_name": language,
            "is_active": "TRUE",
        }
    elif feed_type == "videos":
        new_row = {
            "id": new_id,
            "publication_id": publication_id,
            "pub_name": publisher_name,
            "feed_url": feed_url.strip(),
            "language_name": language,
            "language_id": language_id,
            "category_id": category_id,
            "category_name": category,
        }
    elif feed_type == "summaries":
        new_row = {
            "id": new_id,
            "category_id": category_id,
            "language_id": language_id,
            "publication_id": publication_id,
            "feed_url": feed_url.strip(),
            "category_name": category,
            "pub_name": publisher_name,
            "language_name": language,
        }
    else:
        return {"error": f"Unknown feed type: {feed_type}"}

    # Append and save
    new_df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    _save_csv(feed_type, new_df)

    return {
        "success": True,
        "feed_type": feed_type,
        "new_row": new_row,
        "message": f"Feed added successfully with ID {new_id} to {FEED_TYPES[feed_type]}",
    }


def query_feeds(
    query_type: str,
    feed_type: str = "",
    filter_value: str = "",
) -> dict:
    """
    Analytics queries on feed configs.
    query_type: count_by_publisher, count_by_language, count_by_category, search, total_counts
    """
    if query_type == "total_counts":
        counts = {}
        for ft in FEED_TYPES:
            df = _load_csv(ft)
            counts[ft] = len(df)
        return {"query": "total_counts", "counts": counts, "total": sum(counts.values())}

    if not feed_type:
        # Apply across all feed types
        all_results = {}
        for ft in FEED_TYPES:
            all_results[ft] = _query_single(query_type, ft, filter_value)
        return {"query": query_type, "results": all_results}

    return _query_single(query_type, feed_type, filter_value)


def _query_single(query_type: str, feed_type: str, filter_value: str) -> dict:
    """Run a query on a single feed type."""
    df = _load_csv(feed_type)

    if query_type == "count_by_publisher":
        counts = df["pub_name"].value_counts().head(30).to_dict()
        return {"feed_type": feed_type, "query": query_type, "total_publishers": df["pub_name"].nunique(), "counts": counts}

    elif query_type == "count_by_language":
        counts = df["language_name"].value_counts().to_dict()
        return {"feed_type": feed_type, "query": query_type, "counts": counts}

    elif query_type == "count_by_category":
        counts = df["category_name"].value_counts().to_dict()
        return {"feed_type": feed_type, "query": query_type, "counts": counts}

    elif query_type == "search":
        if not filter_value:
            return {"error": "filter_value required for search query"}
        mask = (
            df["pub_name"].astype(str).str.lower().str.contains(filter_value.lower(), na=False)
            | df["feed_url"].astype(str).str.lower().str.contains(filter_value.lower(), na=False)
            | df["language_name"].astype(str).str.lower().str.contains(filter_value.lower(), na=False)
            | df["category_name"].astype(str).str.lower().str.contains(filter_value.lower(), na=False)
        )
        results = df[mask].head(50)
        records = []
        for _, row in results.iterrows():
            records.append({
                "id": int(row.get("id", 0)),
                "pub_name": str(row.get("pub_name", "")),
                "feed_url": str(row.get("feed_url", "")),
                "language": str(row.get("language_name", "")),
                "category": str(row.get("category_name", "")),
            })
        return {"feed_type": feed_type, "query": "search", "search_term": filter_value, "match_count": len(records), "results": records}

    return {"error": f"Unknown query_type: {query_type}"}


def export_feeds(feed_type: str, fmt: str = "csv") -> tuple[bytes, str, str]:
    """
    Export feeds as CSV, Excel, or JSON.
    Returns: (bytes_content, content_type, filename)
    """
    df = _load_csv(feed_type)
    base_name = FEED_TYPES[feed_type].replace(".csv", "")

    if fmt == "csv":
        content = df.to_csv(index=False).encode("utf-8")
        return content, "text/csv", f"{base_name}.csv"

    elif fmt == "excel":
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        buf.seek(0)
        return buf.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{base_name}.xlsx"

    elif fmt == "json":
        content = df.to_json(orient="records", indent=2).encode("utf-8")
        return content, "application/json", f"{base_name}.json"

    raise ValueError(f"Unsupported format: {fmt}")


def get_stats() -> dict:
    """Get aggregate statistics for system prompt context."""
    stats = {}
    for feed_type in FEED_TYPES:
        df = _load_csv(feed_type)
        stats[feed_type] = {
            "total_feeds": len(df),
            "publishers": int(df["pub_name"].nunique()),
            "languages": int(df["language_name"].nunique()),
            "categories": int(df["category_name"].nunique()),
        }
    return stats


def get_summary_stats() -> str:
    """Get a human-readable summary for the system prompt."""
    stats = get_stats()
    lines = ["### Current Feed Configuration Summary"]
    for ft, s in stats.items():
        lines.append(f"- **{ft.title()}**: {s['total_feeds']} feeds from {s['publishers']} publishers across {s['languages']} languages and {s['categories']} categories")
    return "\n".join(lines)
