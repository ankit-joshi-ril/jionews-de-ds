"""
Analytics Tools
Tool definitions and dispatcher for the Smart Analytics Engine (MongoDB).
"""

import json
import logging
import time
from datetime import datetime, timezone, timedelta

from managers.mongo_manager import (
    execute_query,
    list_collections,
    get_collection_info,
    is_connected,
)

logger = logging.getLogger(__name__)


# ── Tool Definitions ───────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_current_epoch",
        "description": (
            "Get the current Unix epoch timestamp in seconds and pre-computed epoch thresholds "
            "for common time ranges (last 1, 3, 5, 7, 14, 30 days). "
            "ALWAYS call this FIRST before any date/time-based query. "
            "The `createdAt` field in ALL collections stores epoch time in SECONDS."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_collections",
        "description": (
            "List all collections available in the MongoDB database. "
            "Use this first when you need to discover what data is available "
            "or when unsure about collection names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_collection_info",
        "description": (
            "Get information about a specific MongoDB collection including "
            "field names, estimated document count. Use this to understand "
            "the schema before writing queries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Name of the collection to inspect.",
                },
            },
            "required": ["collection_name"],
        },
    },
    {
        "name": "execute_mongo_query",
        "description": (
            "Execute a read-only MongoDB query. Supports find, aggregate, "
            "count_documents, and distinct operations ONLY. "
            "No write, update, or delete operations are permitted. "
            "Always show the generated query to the user for transparency."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Name of the MongoDB collection to query.",
                },
                "operation": {
                    "type": "string",
                    "description": "The read operation to perform.",
                    "enum": ["find", "aggregate", "count_documents", "distinct"],
                },
                "query": {
                    "type": "object",
                    "description": "Filter/query document for find, count_documents, or distinct. Example: {\"sourceLanguageName\": \"Hindi\"}",
                },
                "pipeline": {
                    "type": "array",
                    "description": "Aggregation pipeline stages for aggregate operation. Example: [{\"$group\": {\"_id\": \"$pub_name\", \"count\": {\"$sum\": 1}}}]",
                },
                "projection": {
                    "type": "object",
                    "description": "Fields to include (1) or exclude (0) for find. Example: {\"title\": 1, \"url\": 1, \"_id\": 0}",
                },
                "sort": {
                    "type": "array",
                    "description": "Sort specification as array of [field, direction] pairs. Direction: 1 for ascending, -1 for descending. Example: [[\"createdAt\", -1]]",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 20, max 100).",
                    "default": 20,
                },
                "field": {
                    "type": "string",
                    "description": "Field name for distinct operation. Example: \"sourceLanguageName\"",
                },
            },
            "required": ["collection_name", "operation"],
        },
    },
]


# ── Tool Execution Dispatcher ──────────────────────────────────────

def execute_tool(name: str, inputs: dict) -> dict:
    """Execute an analytics tool and return the result."""
    logger.info(f"Executing analytics tool: {name}")
    try:
        if name == "get_current_epoch":
            now = int(time.time())
            IST = timezone(timedelta(hours=5, minutes=30))
            now_ist = datetime.now(IST)
            ist_today_start = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
            ist_today_start_epoch = int(ist_today_start.timestamp())
            return {
                "current_epoch": now,
                "current_utc": datetime.now(timezone.utc).isoformat(),
                "current_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
                "current_ist_date": now_ist.strftime("%Y-%m-%d"),
                "today_ist_start_epoch": ist_today_start_epoch,
                "today_ist_end_epoch": ist_today_start_epoch + 86400,
                "thresholds": {
                    "last_1_day": now - 86400,
                    "last_3_days": now - (3 * 86400),
                    "last_5_days": now - (5 * 86400),
                    "last_7_days": now - (7 * 86400),
                    "last_14_days": now - (14 * 86400),
                    "last_30_days": now - (30 * 86400),
                },
                "usage_hint": "Use these values in queries like: {\"createdAt\": {\"$gte\": <threshold>}}. For 'today' use today_ist_start_epoch and today_ist_end_epoch.",
            }

        elif name == "list_collections":
            return list_collections()

        elif name == "get_collection_info":
            return get_collection_info(inputs["collection_name"])

        elif name == "execute_mongo_query":
            return execute_query(
                collection_name=inputs["collection_name"],
                operation=inputs["operation"],
                query=inputs.get("query"),
                pipeline=inputs.get("pipeline"),
                projection=inputs.get("projection"),
                sort=inputs.get("sort"),
                limit=min(inputs.get("limit", 20), 100),
                field=inputs.get("field"),
            )

        else:
            return {"error": f"Unknown analytics tool: {name}"}

    except Exception as exc:
        logger.exception(f"Analytics tool execution failed: {name}")
        return {"error": str(exc)}
