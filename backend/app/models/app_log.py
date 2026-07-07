"""
SQLAlchemy model for the `app_log` table.

Phase 8 — rotating log file written by `app.services.app_logging` is the
authoritative source of truth for log records, but the most recent records
are also mirrored here so the Log Viewer page can search / filter
without having to read the log file. Long-term storage remains on disk
(rotating file handler in `app_logging.py`).
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from app.config.database import Base


class AppLog(Base):
    __tablename__ = "app_log"

    id         = Column(Integer, primary_key=True, index=True)
    timestamp  = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    level      = Column(String, nullable=False, default="info")  # debug / info / warning / error
    category   = Column(String, nullable=False, default="general")  # upload / pivot / email / etc.
    message    = Column(String, nullable=False, default="")
    details    = Column(Text, nullable=True)
    source     = Column(String, nullable=True)  # URL / request path
    user_agent = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_app_log_timestamp_level", "timestamp", "level"),
    )
