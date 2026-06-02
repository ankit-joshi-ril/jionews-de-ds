"""
Health check router.
"""

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from managers.mongo_manager import is_connected as mongo_connected

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health():
    """Health check endpoint."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    return JSONResponse({
        "status": "healthy",
        "api_key_configured": bool(api_key and len(api_key) > 10),
        "model": os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        "mongodb_connected": mongo_connected(),
        "modules": ["onboarding", "analytics"],
    })
