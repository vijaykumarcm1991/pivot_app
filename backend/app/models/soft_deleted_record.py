"""
SQLAlchemy model for the `soft_deleted_records` table — Phase 8 soft delete.

When the user deletes a pivot row from the Pivot page, the engine finds
every raw record represented by the selected pivot rows and inserts one
`SoftDeletedRecord` row per source record instead of physically removing
the row from the source file. The next time the engine loads the sheet,
it filters out anything whose `source_key` is in this table.

`source_key` is a stable per-dataset signature of the original row
(we use a JSON-sorted hash of every column), so soft-deletes are
preserved across re-uploads of the same file (we re-key by the
stored filename).
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from app.config.database import Base


class SoftDeletedRecord(Base):
    __tablename__ = "soft_deleted_records"

    id             = Column(Integer, primary_key=True, index=True)
    dataset_id     = Column(Integer, nullable=False, index=True)
    sheet_name     = Column(String, nullable=False)
    source_key     = Column(Text, nullable=False, index=True)  # stable JSON of the row
    row_payload    = Column(Text, nullable=True)  # JSON snapshot of the row (for re-render)
    pivot_request  = Column(Text, nullable=True)  # JSON snapshot of the pivot request that produced the selection
    deleted_at     = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    deleted_by     = Column(String, nullable=True)  # "ui" / "cleanup" / "api" — for the audit trail
    delete_audit_id = Column(Integer, nullable=True, index=True)  # FK into delete_audit (logical)

    __table_args__ = (
        Index("ix_soft_deleted_dataset_sheet", "dataset_id", "sheet_name"),
    )
