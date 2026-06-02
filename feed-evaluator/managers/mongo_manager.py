"""
MongoDB Manager
Read-only MongoDB wrapper for the Smart Analytics Engine.
Only allows: find, aggregate, count_documents, distinct operations.
"""

import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Strict whitelist of allowed operations
ALLOWED_OPERATIONS = {"find", "aggregate", "count_documents", "distinct"}

# Connection singleton
_client = None
_db = None


def _get_db():
    """Get or create the MongoDB database connection."""
    global _client, _db
    if _db is not None:
        return _db

    try:
        from pymongo import MongoClient

        uri = os.getenv("MONGODB_URI", "")
        db_name = os.getenv("MONGODB_DATABASE", "ingestion-data")

        if not uri:
            logger.warning("MONGODB_URI not set. MongoDB features disabled.")
            return None

        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        # Test connection
        _client.admin.command("ping")
        _db = _client[db_name]
        logger.info(f"Connected to MongoDB database: {db_name}")
        return _db
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        return None


def is_connected() -> bool:
    """Check if MongoDB is available."""
    db = _get_db()
    return db is not None


def list_collections() -> dict:
    """List all collections in the database."""
    db = _get_db()
    if db is None:
        return {"error": "MongoDB not connected. Check MONGODB_URI in .env"}
    try:
        collections = db.list_collection_names()
        return {
            "database": db.name,
            "collection_count": len(collections),
            "collections": sorted(collections),
        }
    except Exception as e:
        return {"error": f"Failed to list collections: {str(e)}"}


def execute_query(
    collection_name: str,
    operation: str,
    query: dict = None,
    pipeline: list = None,
    projection: dict = None,
    sort: list = None,
    limit: int = 20,
    field: str = None,
) -> dict:
    """
    Execute a read-only MongoDB query.

    Parameters:
        collection_name: Name of the collection
        operation: One of find, aggregate, count_documents, distinct
        query: Filter dict for find/count_documents/distinct
        pipeline: Aggregation pipeline for aggregate
        projection: Fields to include/exclude for find
        sort: Sort specification as list of [field, direction] pairs
        limit: Max results for find (default 20)
        field: Field name for distinct operation
    """
    # Security: Only allow whitelisted operations
    if operation not in ALLOWED_OPERATIONS:
        return {
            "error": f"Operation '{operation}' is not allowed. Permitted: {sorted(ALLOWED_OPERATIONS)}",
            "security": "Only read operations are permitted.",
        }

    db = _get_db()
    if db is None:
        return {"error": "MongoDB not connected. Check MONGODB_URI in .env"}

    try:
        collection = db[collection_name]
        query = query or {}

        if operation == "find":
            cursor = collection.find(query, projection)
            if sort:
                cursor = cursor.sort(sort)
            cursor = cursor.limit(min(limit, 100))  # Hard cap at 100
            results = list(cursor)
            # Convert ObjectId to string for JSON serialization
            for doc in results:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
                # Convert datetime objects
                for key, value in doc.items():
                    if isinstance(value, datetime):
                        doc[key] = value.isoformat()

            total = collection.count_documents(query)
            return {
                "operation": "find",
                "collection": collection_name,
                "query": _safe_json(query),
                "result_count": len(results),
                "total_matching": total,
                "showing": min(limit, 100),
                "results": results,
            }

        elif operation == "aggregate":
            if not pipeline:
                return {"error": "Pipeline is required for aggregate operation"}
            # Security: Check pipeline stages for write operations
            write_stages = {"$out", "$merge"}
            for stage in pipeline:
                if any(key in write_stages for key in stage.keys()):
                    return {"error": "Write operations ($out, $merge) are not allowed in pipelines."}

            # Add $limit if not present
            has_limit = any("$limit" in stage for stage in pipeline)
            if not has_limit:
                pipeline.append({"$limit": min(limit, 100)})

            results = list(collection.aggregate(pipeline))
            for doc in results:
                if "_id" in doc and not isinstance(doc["_id"], (str, int, float)):
                    doc["_id"] = str(doc["_id"])
                for key, value in doc.items():
                    if isinstance(value, datetime):
                        doc[key] = value.isoformat()

            return {
                "operation": "aggregate",
                "collection": collection_name,
                "pipeline": _safe_json(pipeline),
                "result_count": len(results),
                "results": results,
            }

        elif operation == "count_documents":
            count = collection.count_documents(query)
            return {
                "operation": "count_documents",
                "collection": collection_name,
                "query": _safe_json(query),
                "count": count,
            }

        elif operation == "distinct":
            if not field:
                return {"error": "Field name is required for distinct operation"}
            values = collection.distinct(field, query)
            # Convert non-serializable types
            values = [str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v for v in values]
            return {
                "operation": "distinct",
                "collection": collection_name,
                "field": field,
                "query": _safe_json(query),
                "value_count": len(values),
                "values": values[:100],  # Cap at 100 distinct values
            }

    except Exception as e:
        return {"error": f"Query execution failed: {str(e)}"}


def get_collection_info(collection_name: str) -> dict:
    """Get basic info about a collection (field names, document count)."""
    db = _get_db()
    if db is None:
        return {"error": "MongoDB not connected"}
    try:
        collection = db[collection_name]
        count = collection.estimated_document_count()
        # Sample a document to get field names
        sample = collection.find_one()
        fields = list(sample.keys()) if sample else []
        return {
            "collection": collection_name,
            "estimated_documents": count,
            "fields": fields,
        }
    except Exception as e:
        return {"error": f"Failed to get collection info: {str(e)}"}


def _safe_json(obj) -> str:
    """Convert query/pipeline to a safe JSON string for display."""
    try:
        return json.dumps(obj, default=str, indent=2)
    except Exception:
        return str(obj)
