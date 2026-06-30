"""
SQLAlchemy model for the 'smtp_settings' table.

Stores the (singleton) SMTP configuration used to send emails. The
password is stored as-is in the database; in production this column
should be encrypted at rest (e.g. with Fernet) or moved to a
secret manager. For Version 1 we accept the simple plaintext row
to keep the implementation focused.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.config.database import Base


class SMTPSettings(Base):
    __tablename__ = "smtp_settings"

    # Single-row table — the application always reads/writes the row
    # with id=1. This keeps the schema simple and avoids the need for
    # a "current settings" pointer.
    id           = Column(Integer, primary_key=True, default=1)
    host         = Column(String, nullable=False, default="")
    port         = Column(Integer, nullable=False, default=587)
    username     = Column(String, nullable=False, default="")
    # NOTE: plaintext for Version 1. See module docstring.
    password     = Column(String, nullable=False, default="")
    use_tls      = Column(Boolean, nullable=False, default=True)
    sender_name  = Column(String, nullable=False, default="")
    sender_email = Column(String, nullable=False, default="")
    updated_at   = Column(DateTime, default=datetime.utcnow,
                          onupdate=datetime.utcnow)
