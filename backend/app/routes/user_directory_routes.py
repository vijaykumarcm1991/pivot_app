"""
User Directory API — endpoints the email composer uses to
typeahead-suggest recipients from the configured directory CSVs.

  GET  /api/users/suggest?q=<prefix>&limit=8&kind=user|distribution_list
        → List of matching entries (name, email, alias, kind).
           When `kind` is omitted, both users and distribution
           lists are searched; the result is sorted by relevance
           with users ranking above distribution lists on a tie.
           Empty query returns [] — the frontend uses the
           "recent" list from /api/email/recent-recipients for the
           empty-query case.

  GET  /api/users/recent?limit=8
        → A small starter set of entries (alphabetical) so the
           dropdown has something to show on focus.  Mixes users
           and distribution lists.

  GET  /api/users/status
        → Cache health: users + dls file paths, total / enabled
           counts, last reload time (IST), last error message (if
           any).  Drives the User Directory card on the Settings
           page.

  POST /api/users/reload
        → Force-reload the cache from disk (admin use, after
           updating one or both CSVs).  Returns the reload
           summary so the UI can show a success / error toast.
"""
from __future__ import annotations

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
    alias: str = ""
    kind: str  # "user" or "distribution_list"
    department: str = ""
    jobTitle: str = ""


class ReloadResponse(BaseModel):
    ok: bool
    users: int
    dls: int
    usersPath: str
    dlsPath: str
    message: str
    skipped: Optional[bool] = None


# ── Endpoints ──────────────────────────────────────────────────────────

@router.get("/api/users/suggest")
def api_users_suggest(
    q: str = Query(default="", description="Free-text query (name, email, alias)"),
    limit: int = Query(default=8, ge=1, le=50),
    enabled_only: bool = Query(default=True, description="Filter to enabled entries (currently always True for CSVs)"),
    kind: Optional[str] = Query(
        default=None,
        description="Restrict to one source: 'user' or 'distribution_list'.  Omit to search both.",
    ),
) -> Dict[str, Any]:
    """
    Typeahead endpoint for the email composer.  Returns up to
    `limit` entries matching the query, ranked by exact-email /
    email-prefix / name-prefix / kind (user above distribution list
    on a tie).
    """
    if kind is not None and kind not in ("user", "distribution_list"):
        # Silently fall back to "both" — the typeahead frontend
        # never sends a bad value, but the URL is user-editable.
        kind = None
    results = user_directory.search(
        q, limit=limit, enabled_only=enabled_only, kind=kind,
    )
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
    Starter set of entries shown in the dropdown when no query is
    typed.  Alphabetical, enabled-only, mixed across both sources.
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
def api_users_reload(force: bool = Query(default=True, description="Force reload even if mtimes unchanged")) -> ReloadResponse:
    """
    Force-reload the directory cache from disk.  Use this after
    updating one or both CSVs — the auto-reload watcher will also
    pick up the change on the next request, but this endpoint
    gives the UI immediate feedback.
    """
    result = user_directory.reload(force=force)
    return ReloadResponse(
        ok=bool(result.get("ok")),
        users=int(result.get("users", 0)),
        dls=int(result.get("dls", 0)),
        usersPath=str(result.get("usersPath", "")),
        dlsPath=str(result.get("dlsPath", "")),
        message=str(result.get("message", "")),
        skipped=result.get("skipped"),
    )
