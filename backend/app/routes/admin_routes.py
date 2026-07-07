"""
Phase 8 — Admin cleanup page + JSON API.

  GET  /admin/cleanup           → Cleanup page
  GET  /api/admin/cleanup/preview → preview the cleanup targets
  POST /api/admin/cleanup/run   → actually delete the selected categories

Plus:

  GET  /admin/audit             → Delete audit page (per-request view)
  GET  /api/admin/audit         → JSON list of recent deletes
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.app_settings import APP_VERSION
from app.services.cleanup_service import preview_cleanup, run_cleanup
from app.services.soft_delete_service import list_audit
from app.services.app_logging import log_event


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/admin/cleanup", response_class=HTMLResponse)
async def cleanup_page(request: Request):
    return templates.TemplateResponse(
        "cleanup.html",
        {"request": request, "version": APP_VERSION},
    )


@router.get("/api/admin/cleanup/preview")
def api_cleanup_preview(older_than_days: int = 7, db: Session = Depends(get_db)):
    targets = preview_cleanup(older_than_days=older_than_days, db=db)
    return {
        "olderThanDays": older_than_days,
        "targets":       [t.to_dict() for t in targets],
    }


@router.post("/api/admin/cleanup/run")
def api_cleanup_run(payload: dict, db: Session = Depends(get_db)):
    keys: List[str] = list((payload or {}).get("keys") or [])
    older_than_days = int((payload or {}).get("olderThanDays") or 7)
    if not keys:
        return {"deleted": {}, "freedBytes": 0, "freedMb": 0.0,
                "message": "No categories selected."}
    result = run_cleanup(keys=keys, older_than_days=older_than_days, actor="admin", db=db)
    log_event("info", "Admin cleanup executed", category="cleanup",
              details=f"keys={keys} olderThanDays={older_than_days}")
    return result


@router.get("/admin/audit", response_class=HTMLResponse)
async def audit_page(request: Request):
    return templates.TemplateResponse(
        "audit.html",
        {"request": request, "version": APP_VERSION},
    )


@router.get("/api/admin/audit")
def api_audit(
    q: Optional[str] = None,
    status: Optional[str] = None,
    dataset_id: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return {
        "rows": list_audit(db, query=q, status=status, dataset_id=dataset_id, limit=limit),
        "count": len(list_audit(db, query=q, status=status, dataset_id=dataset_id, limit=limit)),
    }
