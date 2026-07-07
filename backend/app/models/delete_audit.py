"""
SQLAlchemy model for the `delete_audit` table — Phase 8.

Every pivot-row delete creates a single audit row. The `selection_criteria`
column stores the JSON of the per-row-field selection values so the
Log Viewer can show "what was deleted" and an admin can reproduce the
delete from a different machine if needed.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.config.database import Base


class DeleteAudit(Base):
    __tablename__ = "delete_audit"

    id                   = Column(Integer, primary_key=True, index=True)
    timestamp            = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    dataset_id           = Column(Integer, nullable=False, index=True)
    dataset_name         = Column(String, nullable=False, default="")
    sheet_name           = Column(String, nullable=False, default="")
    pivot_rows_count     = Column(Integer, nullable=False, default=0)
    source_records_found = Column(Integer, nullable=False, default=0)
    source_records_deleted = Column(Integer, nullable=False, default=0)
    selection_criteria   = Column(Text, nullable=True)  # JSON list of {field: value}
    status               = Column(String, nullable=False, default="success")  # success / failed
    error_message        = Column(Text, nullable=True)
    actor                = Column(String, nullable=True)  # e.g. "ui" / "cleanup"
    pivot_payload_json   = Column(Text, nullable=True)
