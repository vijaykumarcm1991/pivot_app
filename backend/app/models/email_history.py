"""
SQLAlchemy model for the 'email_history' table.

One row per email the user sends. Stores subject, recipient lists,
the pivot context (dataset + sheet + row counts), the resulting
status, and the on-disk path of the generated attachment. Passwords
are never stored here.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.config.database import Base


class EmailHistory(Base):
    __tablename__ = "email_history"

    id                      = Column(Integer, primary_key=True, index=True)
    sent_at                 = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    subject                 = Column(String, nullable=False, default="")
    # JSON-encoded lists of addresses; kept as Text for SQLite portability.
    to_addresses_json       = Column(Text, nullable=False, default="[]")
    cc_addresses_json       = Column(Text, nullable=False, default="[]")
    bcc_addresses_json      = Column(Text, nullable=False, default="[]")
    dataset_id              = Column(Integer, nullable=True)
    dataset_name            = Column(String, nullable=True)
    sheet_name              = Column(String, nullable=True)
    pivot_rows_count        = Column(Integer, nullable=False, default=0)
    attached_records_count  = Column(Integer, nullable=False, default=0)
    # "success" | "failed"
    status                  = Column(String, nullable=False, default="failed", index=True)
    error_message           = Column(Text, nullable=True)
    attachment_filename     = Column(String, nullable=True)
    # The generated Excel attachment is kept on disk so the user can
    # re-download it from the history page. Path is relative to REPORTS_DIR.
    attachment_path         = Column(String, nullable=True)
    # Original pivot payload (JSON) — kept so future phases can re-render
    # the email body from the history page without re-querying the dataset.
    pivot_payload_json      = Column(Text, nullable=True)
