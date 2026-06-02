"""
Feeds data router.
Handles feed listing, download, and stats endpoints.
"""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from managers.publisher_manager import list_feeds, export_feeds, get_stats, query_feeds

router = APIRouter(prefix="/api/feeds", tags=["feeds"])


@router.get("/list")
async def feeds_list(
    feed_type: str = Query(..., description="headlines, videos, or summaries"),
    language: str = Query("", description="Filter by language"),
    publisher: str = Query("", description="Filter by publisher name"),
    category: str = Query("", description="Filter by category"),
    limit: int = Query(50, description="Max results", ge=1, le=500),
):
    """List feeds with optional filters."""
    try:
        result = list_feeds(
            feed_type=feed_type,
            language=language,
            publisher=publisher,
            category=category,
            limit=limit,
        )
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/download")
async def feeds_download(
    feed_type: str = Query(..., description="headlines, videos, or summaries"),
    format: str = Query("csv", description="csv, excel, or json"),
):
    """Download feed configuration as CSV, Excel, or JSON."""
    try:
        content, content_type, filename = export_feeds(feed_type, format)
        return Response(
            content=content,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/stats")
async def feeds_stats():
    """Get aggregate statistics about feed configurations."""
    try:
        stats = get_stats()
        return JSONResponse(stats)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/query")
async def feeds_query(
    query_type: str = Query(..., description="count_by_publisher, count_by_language, count_by_category, search, total_counts"),
    feed_type: str = Query("", description="Feed type to query"),
    filter_value: str = Query("", description="Search/filter term"),
):
    """Run analytics queries on feed data."""
    try:
        result = query_feeds(
            query_type=query_type,
            feed_type=feed_type,
            filter_value=filter_value,
        )
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
