"""
SQLAlchemy model for the `deleted_datasets` table — Phase 8 cleanup.

When a dataset is hard-deleted (via the admin Cleanup utility or the
existing DELETE /api/dataset/{id} endpoint), the original metadata is
moved here so the operator can still see what was deleted and recover
the file path if needed. This table is never used by the read-side
endpoints — it's purely an admin breadcrumb.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from app.config.database import Base


class DeletedDataset(Base):
    __tablename__ = "deleted_datasets"

    id              = Column(Integer, primary_key=True, index=True)
    original_id     = Column(Integer, nullable=False, index=True)
    filename        = Column(String, nullable=False, default="")
    stored_filename = Column(String, nullable=False, default="")
    total_rows      = Column(Integer, nullable=False, default=0)
    total_columns   = Column(Integer, nullable=False, default=0)
    upload_time     = Column(DateTime, nullable=True)
    deleted_at      = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    deleted_by      = Column(String, nullable=True)  # "ui" / "cleanup"
