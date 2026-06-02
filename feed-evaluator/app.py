"""
JioNews Data & Analytics Dashboard
Slim FastAPI entry point - all logic lives in routers, services, and managers.
"""

import logging
import os

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Ensure .env is found regardless of working directory
load_dotenv(Path(__file__).parent / ".env", override=True)
logging.basicConfig(level=logging.INFO)

# ── App Setup ───────────────────────────────────────────────────────

app = FastAPI(title="JioNews Data & Analytics Dashboard", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── Include Routers ─────────────────────────────────────────────────

from routers.health import router as health_router
from routers.onboarding import router as onboarding_router
from routers.analytics import router as analytics_router
from routers.feeds import router as feeds_router

app.include_router(health_router)
app.include_router(onboarding_router)
app.include_router(analytics_router)
app.include_router(feeds_router)

# ── Root ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the dashboard UI."""
    return templates.TemplateResponse("index.html", {"request": request})

# ── Run ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
