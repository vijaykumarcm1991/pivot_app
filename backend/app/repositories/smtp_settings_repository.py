"""
SMTP settings repository — singleton row CRUD for the smtp_settings table.
"""
from typing import Optional
from sqlalchemy.orm import Session

from app.models.smtp_settings import SMTPSettings
from app.utils import secret_box


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
    if "username" in fields and not (fields.get("username") or "").strip():
        # No username = no login; drop any saved password with it.
        fields = {**fields, "password": None}
        row.password = ""
    for key, value in fields.items():
        if key == "password":
            if value is None or value == "":
                # Keep the existing password — empty input means "no change".
                continue
            value = secret_box.encrypt(value)  # never stored in plaintext
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def plaintext_password(row: Optional[SMTPSettings]) -> str:
    """The decrypted SMTP password (raises secret_box.SecretError)."""
    return secret_box.decrypt(row.password if row else "")


def encrypt_legacy_password(db: Session) -> bool:
    """Encrypt a password saved by an older version in plaintext.
    Returns True if a row was changed. Called once at startup."""
    row = get_settings(db)
    if row is None or not row.password or secret_box.is_encrypted(row.password):
        return False
    row.password = secret_box.encrypt(row.password)
    db.commit()
    return True
