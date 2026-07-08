"""
Email history service — Phase 6.

Read-side helper for the email history page and the recent-recipient
autocomplete. The write-side lives in
`email_history_repository` and is called directly by `email_service`.
This module just shapes the records into the response format the
frontend expects.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.email_history import EmailHistory
from app.models.recent_recipient import RecentRecipient
from app.repositories import email_history_repository
from app.config.settings import REPORTS_DIR
from app.utils.tz import iso_ist, format_ist


def serialize_history(row: EmailHistory) -> Dict[str, Any]:
    """Turn an EmailHistory ORM row into the public-facing dict
    the frontend consumes."""
    to_addrs = _safe_json_list(row.to_addresses_json)
    cc_addrs = _safe_json_list(row.cc_addresses_json)
    bcc_addrs = _safe_json_list(row.bcc_addresses_json)
    has_attachment = bool(
        row.attachment_path
        and os.path.exists(os.path.join(REPORTS_DIR, row.attachment_path))
    )
    # ``sent_at_ist`` is the human-readable IST string the frontend
    # passes to ``AppFormat.ist`` (or renders directly).  We send
    # both the ISO-8601-in-IST string (machine-friendly) and the
    # formatted string (display-friendly) so the frontend never has
    # to guess the timezone.
    return {
        "id": row.id,
        "sent_at": row.sent_at.isoformat() if row.sent_at else "",
        "sent_at_ist": iso_ist(row.sent_at),
        "subject": row.subject or "",
        "to_addresses": to_addrs,
        "cc_addresses": cc_addrs,
        "bcc_addresses": bcc_addrs,
        "dataset_id": row.dataset_id,
        "dataset_name": row.dataset_name,
        "sheet_name": row.sheet_name,
        "pivot_rows_count": int(row.pivot_rows_count or 0),
        "attached_records_count": int(row.attached_records_count or 0),
        "status": row.status or "failed",
        "error_message": row.error_message,
        "attachment_filename": row.attachment_filename,
        "has_attachment": has_attachment,
    }


def list_history(db: Session, limit: int = 100) -> List[Dict[str, Any]]:
    rows = email_history_repository.list_history(db, limit=limit)
    return [serialize_history(r) for r in rows]


def get_history(db: Session, history_id: int) -> Dict[str, Any]:
    row = email_history_repository.get_history(db, history_id)
    if not row:
        return None
    return serialize_history(row)


def serialize_recent_recipient(row: RecentRecipient) -> Dict[str, Any]:
    return {
        "address": row.address,
        "recipient_type": row.recipient_type,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else "",
        "last_used_at_ist": iso_ist(row.last_used_at),
        "use_count": int(row.use_count or 0),
    }


def list_recent_recipients(
    db: Session,
    recipient_type: str = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    rows = email_history_repository.list_recent_recipients(
        db, recipient_type=recipient_type, limit=limit,
    )
    return [serialize_recent_recipient(r) for r in rows]


def _safe_json_list(s: str) -> List[str]:
    if not s:
        return []
    try:
        loaded = json.loads(s)
    except (ValueError, TypeError):
        return []
    if not isinstance(loaded, list):
        return []
    return [str(x) for x in loaded if x]
