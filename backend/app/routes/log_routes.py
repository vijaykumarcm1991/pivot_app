"""
Phase 8 — Log Viewer routes.

  GET  /logs                → Log Viewer page
  GET  /api/logs            → JSON: search / filter
  GET  /api/logs/download   → Download the current log file
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.services.app_logging import (
    log_categories,
    log_file_path,
    log_levels,
    search_logs,
)
from app.models.app_settings import APP_VERSION


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/logs", response_class=HTMLResponse)
async def logs_page():
    return templates.TemplateResponse(
        "logs.html",
        {
            # We don't have a `request` here; the template uses the global nav.
            "request":  None,
            "version":  APP_VERSION,
            "levels":   log_levels(),
            "categories": log_categories(),
        },
    )


def _parse_dt(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        # Accept "2024-01-30" or "2024-01-30T12:34:56"
        if "T" in raw or " " in raw:
            return datetime.fromisoformat(raw.replace("Z", ""))
        return datetime.fromisoformat(raw + "T00:00:00")
    except Exception:
        return None


@router.get("/api/logs")
def api_logs(
    q: Optional[str] = Query(default=None),
    level: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    return search_logs(
        db,
        query=q,
        level=level,
        category=category,
        date_from=_parse_dt(date_from),
        date_to=_parse_dt(date_to),
        limit=limit,
    )


@router.get("/api/logs/download")
def api_logs_download():
    path = log_file_path()
    if not path or not __import__("os").path.exists(path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Log file not found on disk yet.")
    return FileResponse(
        path=path,
        media_type="text/plain",
        filename="pivot_app.log",
    )
