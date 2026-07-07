"""
Phase 8 — Application Settings routes.

Pages:
  GET  /settings                 → settings page

API:
  GET  /api/settings             → current settings
  POST /api/settings             → save current settings

The SMTP block on this page is a small embedded copy of the
SMTP settings form (read-only labels + an "edit" link to
/email/settings) — we don't duplicate the SMTP CRUD here so
there is one source of truth.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.repositories import smtp_settings_repository
from app.services import app_settings_service
from app.schemas.settings import AppSettingsIn, AppSettingsOut
from app.services.app_logging import log_event


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    """Render the application settings page."""
    smtp = smtp_settings_repository.get_or_create_settings(db)
    smtp_configured = bool(smtp.password)
    return templates.TemplateResponse(
        "settings.html",
        {
            "request":          request,
            "smtp_configured":  smtp_configured,
            "smtp_host":        smtp.host or "",
            "smtp_username":    smtp.username or "",
            "smtp_sender":      smtp.sender_email or "",
        },
    )


@router.get("/api/settings", response_model=AppSettingsOut, response_model_by_alias=True)
def api_get_settings(db: Session = Depends(get_db)):
    data = app_settings_service.to_dict(db)
    return AppSettingsOut(**data)


@router.post("/api/settings", response_model=AppSettingsOut, response_model_by_alias=True)
def api_post_settings(payload: AppSettingsIn, db: Session = Depends(get_db)):
    app_settings_service.update_from_payload(db, payload.model_dump(by_alias=True))
    log_event("info", "Application settings updated", category="general", request=None)
    return AppSettingsOut(**app_settings_service.to_dict(db))
