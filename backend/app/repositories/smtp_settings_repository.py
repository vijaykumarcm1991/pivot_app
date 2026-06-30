"""
SMTP settings repository — singleton row CRUD for the smtp_settings table.
"""
from typing import Optional
from sqlalchemy.orm import Session

from app.models.smtp_settings import SMTPSettings


def get_settings(db: Session) -> Optional[SMTPSettings]:
    """Return the singleton SMTP settings row, or None if it has
    never been created. We always read row id=1 to keep the API
    stable across application restarts."""

    return db.query(SMTPSettings).filter(SMTPSettings.id == 1).first()


def get_or_create_settings(db: Session) -> SMTPSettings:
    """Return the singleton, creating an empty row the first time
    so the form has something to edit."""

    row = get_settings(db)
    if row is None:
        row = SMTPSettings(
            id=1,
            host="",
            port=587,
            username="",
            password="",
            use_tls=True,
            sender_name="",
            sender_email="",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def upsert_settings(db: Session, **fields) -> SMTPSettings:
    """Insert or update the singleton row. `password` is kept if
    the incoming value is an empty string."""

    row = get_or_create_settings(db)
    for key, value in fields.items():
        if key == "password" and (value is None or value == ""):
            # Keep the existing password — empty input means "no change".
            continue
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row
