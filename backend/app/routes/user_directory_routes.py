"""
User Directory API — endpoints the email composer uses to
typeahead-suggest recipients from the configured users.json file.

  GET  /api/users/suggest?q=<prefix>&limit=8
        → List of matching users (name, email, department, job title).
           Empty query returns [] — the frontend uses the
           "recent" list from /api/email/recent-recipients for the
           empty-query case.

  GET  /api/users/recent?limit=8
        → A small starter set of users (alphabetical, enabled only)
           so the dropdown has something to show on focus.

  GET  /api/users/status
        → Cache health: file path, total / enabled counts, last
           reload time (IST), last error message (if any).  Drives
           the User Directory card on the Settings page.

  POST /api/users/reload
        → Force-reload the cache from disk (admin use, after
           uploading a new users.json).  Returns the reload
           summary so the UI can show a success / error toast.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services import user_directory


router = APIRouter()


# ── Response models (just for OpenAPI docs) ───────────────────────────

class UserSuggestItem(BaseModel):
    id: str
    email: str
    name: str
    department: str = ""
    jobTitle: str = ""


class ReloadResponse(BaseModel):
    ok: bool
    loaded: int
    path: str
    message: str
    skipped: Optional[bool] = None


# ── Endpoints ──────────────────────────────────────────────────────────

@router.get("/api/users/suggest")
def api_users_suggest(
    q: str = Query(default="", description="Free-text query (name, email, nickname, department)"),
    limit: int = Query(default=8, ge=1, le=50),
    enabled_only: bool = Query(default=True, description="Filter to AccountEnabled users"),
) -> Dict[str, Any]:
    """
    Typeahead endpoint for the email composer.  Returns up to
    `limit` users matching the query, ranked by exact-email /
    email-prefix / name-prefix.
    """
    results = user_directory.search(q, limit=limit, enabled_only=enabled_only)
    return {
        "query":   q,
        "count":   len(results),
        "results": results,
    }


@router.get("/api/users/recent")
def api_users_recent(
    limit: int = Query(default=8, ge=1, le=50),
) -> Dict[str, Any]:
    """
    Starter set of users shown in the dropdown when no query is
    typed.  Alphabetical, enabled-only.
    """
    results = user_directory.list_recent(limit=limit)
    return {
        "count":   len(results),
        "results": results,
    }


@router.get("/api/users/status")
def api_users_status() -> Dict[str, Any]:
    """
    Cache health for the Settings page's "User Directory" card.
    """
    return user_directory.status()


@router.post("/api/users/reload", response_model=ReloadResponse)
def api_users_reload(force: bool = Query(default=True, description="Force reload even if mtime unchanged")) -> ReloadResponse:
    """
    Force-reload the user directory cache from disk.  Use this
    after uploading a new users.json — the auto-reload watcher
    will also pick up the change on the next request, but
    this endpoint gives the UI immediate feedback.
    """
    result = user_directory.reload(force=force)
    return ReloadResponse(
        ok=bool(result.get("ok")),
        loaded=int(result.get("loaded", 0)),
        path=str(result.get("path", "")),
        message=str(result.get("message", "")),
        skipped=result.get("skipped"),
    )
