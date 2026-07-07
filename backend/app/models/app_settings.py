"""
SQLAlchemy model for the singleton `app_settings` table.

Stores user-configurable application settings:
  - Application name, company name
  - Timezone (IANA name)
  - Maximum upload size (bytes)
  - Default export folder
  - App version (read-only — sourced from code)

The application always reads/writes the row with id=1.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, BigInteger, DateTime
from app.config.database import Base


# Read from a single source of truth so the version string stays
# in sync with the value shown on the Settings page and the
# `GET /health` endpoint.
APP_VERSION = "1.0.0"


class AppSettings(Base):
    __tablename__ = "app_settings"

    # Single-row table — same pattern as smtp_settings.
    id                  = Column(Integer, primary_key=True, default=1)
    application_name    = Column(String, nullable=False, default="Pivot App")
    company_name        = Column(String, nullable=False, default="")
    timezone            = Column(String, nullable=False, default="UTC")
    max_upload_bytes    = Column(BigInteger, nullable=False, default=50 * 1024 * 1024)
    default_export_dir  = Column(String, nullable=False, default="")
    updated_at          = Column(DateTime, default=datetime.utcnow,
                                 onupdate=datetime.utcnow)
