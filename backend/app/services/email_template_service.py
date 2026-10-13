"""
Email templates (#7) — reusable subject / message / recipients for the
composer and for scheduled reports. Placeholders such as {date} and
{dataset} are rendered at send time by email_service.render_placeholders.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.email_template import EmailTemplate
from app.utils.tz import iso_ist


class TemplateError(ValueError):
    """Invalid template request (HTTP 400)."""


class TemplateConflict(TemplateError):
    """Duplicate name (HTTP 409)."""


def serialize(row: EmailTemplate) -> Dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "subject": row.subject or "",
        "message": row.message or "",
        "to": row.to_text or "",
        "cc": row.cc_text or "",
        "bcc": row.bcc_text or "",
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        "updatedAtIst": iso_ist(row.updated_at),
    }


def list_templates(db: Session) -> List[Dict[str, Any]]:
    return [serialize(r) for r in db.query(EmailTemplate).order_by(EmailTemplate.name.asc()).all()]


def get_template(db: Session, template_id: int) -> Optional[EmailTemplate]:
    return db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()


def _name(db: Session, name: str, exclude_id: Optional[int] = None) -> str:
    name = (name or "").strip()
    if not name:
        raise TemplateError("Template name is required.")
    q = db.query(EmailTemplate).filter(func.lower(EmailTemplate.name) == name.lower())
    if exclude_id is not None:
        q = q.filter(EmailTemplate.id != exclude_id)
    if q.first():
        raise TemplateConflict(f'A template named "{name}" already exists.')
    return name


def save_template(db: Session, data: Dict[str, Any], row: Optional[EmailTemplate] = None) -> EmailTemplate:
    if row is None:
        row = EmailTemplate()
        db.add(row)
    row.name = _name(db, data.get("name", row.name or ""), exclude_id=row.id)
    row.subject = (data.get("subject") or "").strip()
    row.message = data.get("message") or ""
    row.to_text = (data.get("to") or "").strip()
    row.cc_text = (data.get("cc") or "").strip()
    row.bcc_text = (data.get("bcc") or "").strip()
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def delete_template(db: Session, row: EmailTemplate) -> None:
    db.delete(row)
    db.commit()
