"""
Email routes — Phase 6.

API endpoints (all under /api/email/*):
  GET  /api/email/smtp-settings          → load SMTP config (password is masked)
  POST /api/email/smtp-settings          → save SMTP config
  POST /api/email/test                   → send a test email to a single address
  POST /api/email/preview                → build the HTML preview + attachment
  POST /api/email/send                   → validate + send the actual email
  GET  /api/email/history                → list past emails
  GET  /api/email/recent-recipients      → autocomplete for To/CC/BCC fields

Attachment download endpoints (one-shot preview + re-download from history):
  GET  /api/email/preview-attachment/<rel-path>     → serve the preview file
  GET  /api/email/history/<id>/attachment           → re-download from history

Page endpoints:
  GET  /email/settings   → SMTP configuration page
  GET  /email/history    → email history page
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.settings import REPORTS_DIR
from app.repositories import smtp_settings_repository, email_history_repository
from app.schemas.email import (
    EmailHistoryOut,
    EmailPreviewResponse,
    EmailSendRequest,
    EmailSendResponse,
    RecentRecipientOut,
    SMTPSettingsIn,
    SMTPSettingsOut,
)
from app.services import email_history_service
from app.services.email_service import (
    EmailResult,
    EmailValidationError,
    compose_and_send,
    compose_preview,
)
from app.services.attachment_service import attachment_disk_path
from app.services.smtp_service import SMTPError, is_complete, send_email
from app.utils.tz import iso_ist


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ── Pages ───────────────────────────────────────────────────────────────

@router.get("/email/settings", response_class=HTMLResponse)
async def email_settings_page(request: Request, db: Session = Depends(get_db)):
    """Render the SMTP configuration page."""
    return templates.TemplateResponse("email_settings.html", {"request": request})


@router.get("/email/history", response_class=HTMLResponse)
async def email_history_page(request: Request, db: Session = Depends(get_db)):
    """Render the email history page."""
    return templates.TemplateResponse("email_history.html", {"request": request})


# ── SMTP settings ───────────────────────────────────────────────────────

@router.get("/api/email/smtp-settings", response_model=SMTPSettingsOut, response_model_by_alias=True)
def api_get_smtp_settings(db: Session = Depends(get_db)):
    """Return the current SMTP settings. The password is masked
    — we never echo it back to the client."""
    row = smtp_settings_repository.get_or_create_settings(db)
    return SMTPSettingsOut(
        host=row.host or "",
        port=int(row.port or 587),
        username=row.username or "",
        password_set=bool(row.password),
        use_tls=bool(row.use_tls),
        sender_name=row.sender_name or "",
        sender_email=row.sender_email or "",
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.post("/api/email/smtp-settings", response_model=SMTPSettingsOut, response_model_by_alias=True)
def api_post_smtp_settings(payload: SMTPSettingsIn, db: Session = Depends(get_db)):
    """Save the SMTP settings. An empty `password` field means
    "do not change the existing password"."""
    row = smtp_settings_repository.upsert_settings(
        db,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        use_tls=payload.use_tls,
        sender_name=payload.sender_name,
        sender_email=payload.sender_email,
    )
    return SMTPSettingsOut(
        host=row.host or "",
        port=int(row.port or 587),
        username=row.username or "",
        password_set=bool(row.password),
        use_tls=bool(row.use_tls),
        sender_name=row.sender_name or "",
        sender_email=row.sender_email or "",
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.post("/api/email/test")
def api_test_email(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """Send a small test email to a single recipient using the
    currently configured SMTP settings. Used by the SMTP settings
    page so the user can verify their credentials work before
    sending a real report."""
    recipient = (payload or {}).get("to", "").strip()
    if not recipient:
        raise HTTPException(status_code=400, detail="A recipient address is required.")

    settings = smtp_settings_repository.get_settings(db)
    if not is_complete(settings):
        raise HTTPException(
            status_code=400,
            detail="SMTP settings are incomplete. Fill in host, port, "
                   "username, password, sender name and sender email first.",
        )

    body = (
        "<p>This is a test email from Pivot App.</p>"
        "<p>If you received this, your SMTP configuration is working.</p>"
    )
    try:
        send_email(
            settings,
            to=[recipient],
            cc=[],
            bcc=[],
            subject="Pivot App — SMTP test",
            html_body=body,
        )
    except SMTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"ok": True, "sent_to": recipient, "sent_at": datetime.utcnow().isoformat()}


# ── Email preview + send ───────────────────────────────────────────────

@router.post("/api/email/preview", response_model=EmailPreviewResponse, response_model_by_alias=True)
def api_email_preview(payload: EmailSendRequest, db: Session = Depends(get_db)):
    """Build the HTML preview + the attachment, but do not send."""
    try:
        result: EmailResult = compose_preview(db, payload)
    except EmailValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Re-run the parse so the response shows the cleaned list
    # (especially important when the client sent a string).
    from app.services.email_service import parse_address_list
    return EmailPreviewResponse(
        html=result.html,
        subject=result.subject,
        to=parse_address_list(payload.to),
        cc=parse_address_list(payload.cc),
        bcc=parse_address_list(payload.bcc),
        attachment_filename=result.attachment_filename,
        attachment_download_url=result.attachment_download_url,
        attachment_record_count=result.attachment_record_count,
        matched_rows=result.matched_rows,
        pivot_rows_count=result.pivot_rows_count,
        dataset_name=result.dataset_name,
        sheet_name=result.sheet_name,
        generated_at=result.generated_at.isoformat(),
        # The user asked for every visible timestamp in the app
        # to be in IST — include the ISO-8601-in-IST string so the
        # frontend can display it directly.
        generated_at_ist=iso_ist(result.generated_at),
    )


@router.post("/api/email/send", response_model=EmailSendResponse, response_model_by_alias=True)
def api_email_send(payload: EmailSendRequest, db: Session = Depends(get_db)):
    """Validate, build, send, and record history."""
    try:
        result = compose_and_send(db, payload)
    except EmailValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SMTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return EmailSendResponse(
        history_id=result["history_id"],
        status=result["status"],
        sent_at=result["sent_at"],
        # IST-formatted ISO-8601 string for the frontend.
        sent_at_ist=iso_ist(result.get("sent_at_dt")) if result.get("sent_at_dt") else iso_ist(datetime.utcnow()),
        error_message=None,
    )


# ── Email history + recent recipients ───────────────────────────────────

@router.get("/api/email/history", response_model=List[EmailHistoryOut], response_model_by_alias=True)
def api_email_history(limit: int = 100, db: Session = Depends(get_db)):
    return email_history_service.list_history(db, limit=limit)


@router.get("/api/email/recent-recipients", response_model=List[RecentRecipientOut], response_model_by_alias=True)
def api_recent_recipients(
    type: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    rt = (type or "").strip().lower() or None
    if rt and rt not in {"to", "cc", "bcc"}:
        raise HTTPException(status_code=400, detail="type must be one of: to, cc, bcc")
    return email_history_service.list_recent_recipients(db, recipient_type=rt, limit=limit)


# ── Attachment download endpoints ───────────────────────────────────────

@router.get("/api/email/preview-attachment/{rel_path:path}")
def api_preview_attachment(rel_path: str):
    """Serve a one-shot preview attachment. Path is relative to
    REPORTS_DIR and must resolve to a file under that directory."""
    abs_path = attachment_disk_path(rel_path)
    if not abs_path:
        raise HTTPException(status_code=404, detail="Preview attachment not found")
    return FileResponse(
        path=abs_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(abs_path),
    )


@router.get("/api/email/history/{history_id}/attachment")
def api_history_attachment(history_id: int, db: Session = Depends(get_db)):
    """Re-download a past email's attachment (from the history page)."""
    row = email_history_repository.get_history(db, history_id)
    if not row:
        raise HTTPException(status_code=404, detail="History entry not found")
    abs_path = attachment_disk_path(row.attachment_path)
    if not abs_path:
        raise HTTPException(
            status_code=410,
            detail="Attachment no longer exists on disk",
        )
    return FileResponse(
        path=abs_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=row.attachment_filename or os.path.basename(abs_path),
    )
