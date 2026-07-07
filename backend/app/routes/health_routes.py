"""
Phase 8 — Health check + Diagnostics routes.

  GET /health            → JSON status (for Docker health check + status pages)
  GET /diagnostics       → Diagnostics page (system info)
  GET /api/diagnostics   → JSON diagnostics (used by the page and the admin tools)
"""
from __future__ import annotations

import os
import platform
import shutil
import sqlite3
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config.database import DB_PATH, get_db
from app.config.settings import LOG_DIR, REPORTS_DIR, UPLOAD_DIR
from app.models.app_settings import APP_VERSION
from app.repositories import dataset_repository, smtp_settings_repository
from app.services.smtp_service import is_complete
from app.services.app_logging import log_event


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ── Health endpoint (used by Docker + status pages) ─────────────────────

def _dir_status(path: str) -> Dict[str, Any]:
    """Return whether a directory exists + is writable + its free space."""
    try:
        exists = os.path.isdir(path)
        writable = os.access(path, os.W_OK)
        usage = shutil.disk_usage(path)
        return {
            "path":    path,
            "exists":  exists,
            "writable": writable,
            "freeGb":  round(usage.free / (1024 ** 3), 2),
            "totalGb": round(usage.total / (1024 ** 3), 2),
        }
    except Exception as exc:
        return {"path": path, "exists": False, "writable": False, "error": str(exc)}


def _db_status() -> Dict[str, Any]:
    """Check the SQLite file: exists, openable, and current count of datasets."""
    try:
        info: Dict[str, Any] = {"path": DB_PATH, "ok": False}
        if not os.path.exists(DB_PATH):
            info["error"] = "Database file does not exist yet"
            return info
        # Open with the stdlib sqlite3 module to avoid pulling in SQLAlchemy
        # session machinery on a hot path.
        conn = sqlite3.connect(DB_PATH, timeout=2)
        try:
            cur = conn.execute("SELECT sqlite_version()")
            info["sqliteVersion"] = cur.fetchone()[0]
            cur = conn.execute("SELECT count(*) FROM datasets")
            info["datasetCount"] = cur.fetchone()[0]
            info["ok"] = True
        finally:
            conn.close()
        info["sizeMb"] = round(os.path.getsize(DB_PATH) / (1024 * 1024), 2)
        return info
    except Exception as exc:
        return {"path": DB_PATH, "ok": False, "error": str(exc)}


def _smtp_status(db: Session) -> Dict[str, Any]:
    try:
        row = smtp_settings_repository.get_settings(db)
        complete = bool(row and is_complete(row))
        return {
            "configured": complete,
            "host":      (row.host if row else "") or "",
            "username":  (row.username if row else "") or "",
            "sender":    (row.sender_email if row else "") or "",
        }
    except Exception as exc:
        return {"configured": False, "error": str(exc)}


@router.get("/health")
def health(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return the current health of every subsystem.

    The shape is stable: a status ("ok" / "degraded" / "down") per
    subsystem, plus a top-level status that the Docker health check
    can read in one go.
    """
    db_status = _db_status()
    uploads = _dir_status(UPLOAD_DIR)
    reports = _dir_status(REPORTS_DIR)
    logs = _dir_status(LOG_DIR)
    smtp = _smtp_status(db)

    overall = "ok"
    if not db_status.get("ok"):
        overall = "down"
    elif not (uploads.get("exists") and uploads.get("writable")):
        overall = "degraded"
    elif not (reports.get("exists") and reports.get("writable")):
        overall = "degraded"

    return {
        "status":         overall,
        "version":        APP_VERSION,
        "currentTime":    datetime.utcnow().isoformat() + "Z",
        "database":       db_status,
        "uploadsFolder":  uploads,
        "reportsFolder":  reports,
        "logsFolder":     logs,
        "smtp":           smtp,
    }


# ── Diagnostics page + JSON API ─────────────────────────────────────────

@router.get("/diagnostics", response_class=HTMLResponse)
async def diagnostics_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "diagnostics.html",
        {"request": request, "version": APP_VERSION},
    )


def _collect_diagnostics(db: Session) -> Dict[str, Any]:
    """Pure function — used by both the page and the JSON API."""
    db_status = _db_status()
    uploads = _dir_status(UPLOAD_DIR)
    reports = _dir_status(REPORTS_DIR)
    logs = _dir_status(LOG_DIR)

    # Count datasets (and total rows / columns for storage usage context).
    try:
        dataset_count = db.query(func.count(dataset_repository.Dataset.id)).scalar() or 0
    except Exception:
        dataset_count = 0

    # Storage usage — sum of upload files.
    upload_bytes = 0
    try:
        for fn in os.listdir(UPLOAD_DIR):
            fp = os.path.join(UPLOAD_DIR, fn)
            if os.path.isfile(fp):
                upload_bytes += os.path.getsize(fp)
    except Exception:
        pass
    reports_bytes = 0
    try:
        for root, _dirs, files in os.walk(REPORTS_DIR):
            for fn in files:
                fp = os.path.join(root, fn)
                try:
                    reports_bytes += os.path.getsize(fp)
                except OSError:
                    pass
    except Exception:
        pass

    smtp = _smtp_status(db)

    return {
        "application": {
            "version":     APP_VERSION,
            "python":      platform.python_version(),
            "sqlite":      db_status.get("sqliteVersion", "unknown"),
            "os":          f"{platform.system()} {platform.release()} ({platform.machine()})",
            "hostname":    platform.node(),
        },
        "health": {
            "status":     "ok" if db_status.get("ok") else "down",
            "checkedAt":  datetime.utcnow().isoformat() + "Z",
        },
        "database":    db_status,
        "folders":     {
            "uploads":  uploads,
            "reports":  reports,
            "logs":     logs,
        },
        "smtp":        smtp,
        "storage": {
            "datasetCount":      int(dataset_count),
            "uploadsBytes":      int(upload_bytes),
            "uploadsMb":         round(upload_bytes / (1024 * 1024), 2),
            "reportsBytes":      int(reports_bytes),
            "reportsMb":         round(reports_bytes / (1024 * 1024), 2),
        },
    }


@router.get("/api/diagnostics")
def api_diagnostics(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return _collect_diagnostics(db)
