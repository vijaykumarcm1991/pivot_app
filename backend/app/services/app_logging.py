"""
Phase 8 — application logging.

A small, dependency-free logging system:
  - rotating file handler under `LOG_DIR` (`pivot_app.log` + `.N`)
  - mirror to a SQLite `app_log` table for the Log Viewer page
    (search, date filter, level filter, download)
  - a tiny `log_event()` helper for application code

Design goals:
  - no new dependencies (uses stdlib `logging` + `RotatingFileHandler`)
  - best-effort: a logging failure NEVER breaks a request
  - the file is the source of truth (the SQLite mirror is a window
    onto the most recent N records for search)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.config.settings import LOG_DIR
from app.config.database import SessionLocal
from app.models.app_log import AppLog
from app.utils.tz import iso_ist


# 5 MB x 5 backups ~ 25 MB max on disk
LOG_FILE = os.path.join(LOG_DIR, "pivot_app.log")
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5


# Tracks the most recent N records mirrored to the DB. The Log Viewer
# reads from the DB; a small bounded set keeps writes fast.
DB_MIRROR_LIMIT = 5000

# In-memory cache of the most recent records to enforce the cap on
# the SQLite mirror without counting every time.
_recent_count = 0


class _DBMirrorHandler(logging.Handler):
    """
    Custom logging handler that mirrors records into the `app_log`
    SQLite table. Uses its own short-lived Session so a logging
    failure cannot break a request that is already mid-transaction.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        global _recent_count
        try:
            category = getattr(record, "category", "general")
            details = getattr(record, "details", None)
            source = getattr(record, "source", None)
            user_agent = getattr(record, "user_agent", None)
            message = record.getMessage()
            level = (record.levelname or "INFO").lower()

            db: Session = SessionLocal()
            try:
                row = AppLog(
                    timestamp=datetime.utcnow(),
                    level=level,
                    category=category,
                    message=message[:500],
                    details=str(details)[:4000] if details is not None else None,
                    source=str(source)[:500] if source else None,
                    user_agent=str(user_agent)[:500] if user_agent else None,
                )
                db.add(row)
                db.commit()
                _recent_count += 1
                # If we exceeded the mirror limit, trim the oldest rows.
                if _recent_count > DB_MIRROR_LIMIT:
                    self._trim(db)
                    _recent_count = DB_MIRROR_LIMIT
            except Exception:
                db.rollback()
            finally:
                db.close()
        except Exception:
            # Never let logging break a request.
            pass

    @staticmethod
    def _trim(db: Session) -> None:
        try:
            # Keep the most recent DB_MIRROR_LIMIT rows.
            from sqlalchemy import select, func
            count = db.query(func.count(AppLog.id)).scalar() or 0
            excess = int(count) - DB_MIRROR_LIMIT
            if excess <= 0:
                return
            # Delete the oldest `excess` rows.
            oldest = (
                db.query(AppLog.id)
                .order_by(AppLog.timestamp.asc(), AppLog.id.asc())
                .limit(excess)
                .all()
            )
            ids = [r[0] for r in oldest]
            if ids:
                db.query(AppLog).filter(AppLog.id.in_(ids)).delete(synchronize_session=False)
                db.commit()
        except Exception:
            db.rollback()


def configure_logging(log_dir: str) -> None:
    """
    Set up the root logger with:
      - console (INFO+)
      - rotating file (INFO+, 5 MB x 5)
      - SQLite mirror (INFO+)
    Idempotent — safe to call multiple times (e.g. in tests).
    """
    os.makedirs(log_dir, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid adding duplicate handlers when reloaded.
    if any(getattr(h, "_pivot_app_handler", False) for h in root.handlers):
        return

    fmt = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    console._pivot_app_handler = True  # type: ignore[attr-defined]
    root.addHandler(console)

    try:
        rfh = RotatingFileHandler(
            LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        rfh.setLevel(logging.INFO)
        rfh.setFormatter(fmt)
        rfh._pivot_app_handler = True  # type: ignore[attr-defined]
        root.addHandler(rfh)
    except Exception:
        # Disk full / read-only filesystem — keep going without a file.
        pass

    db_handler = _DBMirrorHandler()
    db_handler._pivot_app_handler = True  # type: ignore[attr-defined]
    root.addHandler(db_handler)

    # Quiet down noisy libraries.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)


# ── Public API ──────────────────────────────────────────────────────────

def log_event(
    level: str,
    message: str,
    *,
    category: str = "general",
    details: Any = None,
    request: Any = None,
) -> None:
    """
    Convenience helper for application code.

      log_event("info", "Dataset uploaded", category="upload", details="foo.xlsx")
      log_event("warning", "Pivot truncated", category="pivot")
      log_event("error", "SMTP failed", category="email", details=str(exc),
                request=request)

    The function is best-effort: any logging failure is swallowed.
    """
    try:
        logger = logging.getLogger("pivot_app")
        source = None
        user_agent = None
        if request is not None:
            try:
                source = getattr(request, "url", None) and str(request.url)
            except Exception:
                source = None
            try:
                user_agent = request.headers.get("user-agent")
            except Exception:
                user_agent = None

        extra = {
            "category": category,
            "details": details,
            "source": source,
            "user_agent": user_agent,
        }
        lvl = (level or "info").upper()
        if lvl == "DEBUG":
            logger.debug(message, extra=extra)
        elif lvl in ("WARN", "WARNING"):
            logger.warning(message, extra=extra)
        elif lvl == "ERROR":
            logger.error(message, extra=extra)
        elif lvl == "CRITICAL":
            logger.critical(message, extra=extra)
        else:
            logger.info(message, extra=extra)
    except Exception:
        pass


# ── Log viewer helpers ──────────────────────────────────────────────────

def search_logs(
    db: Session,
    *,
    query: Optional[str] = None,
    level: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 500,
) -> Dict[str, Any]:
    """Return log rows matching the filters, newest first."""
    q = db.query(AppLog)
    if query:
        like = f"%{query}%"
        q = q.filter((AppLog.message.ilike(like)) | (AppLog.details.ilike(like)))
    if level:
        q = q.filter(AppLog.level == level.lower())
    if category:
        q = q.filter(AppLog.category == category)
    if date_from:
        q = q.filter(AppLog.timestamp >= date_from)
    if date_to:
        q = q.filter(AppLog.timestamp <= date_to)
    rows = q.order_by(AppLog.timestamp.desc()).limit(limit).all()
    return {
        "rows": [
            {
                "id":         r.id,
                "timestamp":  r.timestamp.isoformat() if r.timestamp else None,
                # IST-formatted ISO-8601 string for the frontend.
                "timestamp_ist": iso_ist(r.timestamp),
                "level":      r.level,
                "category":   r.category,
                "message":    r.message,
                "details":    r.details,
                "source":     r.source,
                "userAgent":  r.user_agent,
            }
            for r in rows
        ],
        "count": len(rows),
    }


def log_file_path() -> str:
    return LOG_FILE


def log_levels() -> list:
    return ["debug", "info", "warning", "error", "critical"]


def log_categories() -> list:
    """A static set — extend as we add new categories. Used to populate
    the filter dropdown on the Log Viewer page."""
    return [
        "general",
        "startup",
        "shutdown",
        "upload",
        "dataset",
        "pivot",
        "pivot_delete",
        "drilldown",
        "export",
        "email_preview",
        "email_sent",
        "email_failed",
        "cleanup",
        "error",
        "auth",
    ]
