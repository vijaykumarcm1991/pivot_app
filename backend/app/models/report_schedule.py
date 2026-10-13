"""
SQLAlchemy model for `report_schedules` — emails a saved pivot on a
schedule (see app.services.scheduler_service).

Times are stored as "HH:MM" in the application timezone (Settings page);
`next_run_at` / `last_run_at` are naive UTC like every other timestamp.
"""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from app.config.database import Base


class ReportSchedule(Base):
    __tablename__ = "report_schedules"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String, nullable=False)
    saved_pivot_id  = Column(Integer, nullable=False, index=True)
    enabled         = Column(Boolean, nullable=False, default=True)
    # daily | weekdays | weekly | monthly
    frequency       = Column(String, nullable=False, default="weekdays")
    run_time        = Column(String, nullable=False, default="09:00")
    # weekly: comma-separated ISO weekday numbers, 0 = Monday … 6 = Sunday
    weekdays        = Column(String, nullable=False, default="0")
    # monthly: 1–28
    day_of_month    = Column(Integer, nullable=False, default=1)
    to_json         = Column(Text, nullable=False, default="[]")
    cc_json         = Column(Text, nullable=False, default="[]")
    bcc_json        = Column(Text, nullable=False, default="[]")
    subject         = Column(String, nullable=False, default="")
    message         = Column(Text, nullable=False, default="")
    skip_if_empty   = Column(Boolean, nullable=False, default=True)
    next_run_at     = Column(DateTime, nullable=True, index=True)
    last_run_at     = Column(DateTime, nullable=True)
    last_status     = Column(String, nullable=True)   # success | failed | skipped
    last_error      = Column(Text, nullable=True)
    last_history_id = Column(Integer, nullable=True)
    created_at      = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at      = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
