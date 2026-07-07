"""
App settings repository — singleton row CRUD for the `app_settings` table.
"""
from typing import Optional
from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings


def get_settings(db: Session) -> Optional[AppSettings]:
    return db.query(AppSettings).filter(AppSettings.id == 1).first()


def get_or_create_settings(db: Session) -> AppSettings:
    """Return the singleton, creating defaults the first time."""
    row = get_settings(db)
    if row is None:
        row = AppSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def upsert_settings(db: Session, **fields) -> AppSettings:
    """Insert or update the singleton row."""
    row = get_or_create_settings(db)
    for key, value in fields.items():
        if value is None:
            continue
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row
