"""
Email history repository — CRUD for the email_history and
recent_recipients tables.
"""
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.email_history import EmailHistory
from app.models.recent_recipient import RecentRecipient


# ── email_history ────────────────────────────────────────────────────────

def create_history(db: Session, **fields) -> EmailHistory:
    """Insert a new email_history row. The status is `failed` by
    default — the caller updates it after the SMTP send completes."""
    row = EmailHistory(**fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_history(db: Session, history_id: int, **fields) -> Optional[EmailHistory]:
    row = db.query(EmailHistory).filter(EmailHistory.id == history_id).first()
    if not row:
        return None
    for key, value in fields.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def list_history(db: Session, limit: int = 100) -> List[EmailHistory]:
    """Return the most recent history rows, newest first."""
    return (
        db.query(EmailHistory)
        .order_by(desc(EmailHistory.sent_at))
        .limit(limit)
        .all()
    )


def get_history(db: Session, history_id: int) -> Optional[EmailHistory]:
    return db.query(EmailHistory).filter(EmailHistory.id == history_id).first()


# ── recent_recipients ────────────────────────────────────────────────────

def upsert_recent_recipient(db: Session, address: str, recipient_type: str) -> None:
    """Add or update a recent recipient. If (address, recipient_type)
    already exists, increment use_count and bump last_used_at. The
    address is lowercased and trimmed so the same email in any case
    merges to a single row."""
    address = (address or "").strip().lower()
    if not address:
        return

    row = (
        db.query(RecentRecipient)
        .filter(RecentRecipient.address == address,
                RecentRecipient.recipient_type == recipient_type)
        .first()
    )
    if row is None:
        row = RecentRecipient(
            address=address,
            recipient_type=recipient_type,
            last_used_at=datetime.utcnow(),
            use_count=1,
        )
        db.add(row)
    else:
        row.use_count = (row.use_count or 0) + 1
        row.last_used_at = datetime.utcnow()
    db.commit()


def list_recent_recipients(
    db: Session,
    recipient_type: Optional[str] = None,
    limit: int = 50,
) -> List[RecentRecipient]:
    """Return recent recipients, most recently used first. If
    recipient_type is set, filter to that kind (to/cc/bcc)."""
    q = db.query(RecentRecipient)
    if recipient_type:
        q = q.filter(RecentRecipient.recipient_type == recipient_type)
    return q.order_by(desc(RecentRecipient.last_used_at)).limit(limit).all()
