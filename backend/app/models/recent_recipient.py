"""
SQLAlchemy model for the 'recent_recipients' table.

Stores email addresses the user has recently used in the To / CC / BCC
fields of the composer. Used to power the typeahead autocomplete in
the email modal. The same address can appear once per recipient_type
(so a single email can be suggested for "to", "cc", and "bcc"
independently).
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from app.config.database import Base


class RecentRecipient(Base):
    __tablename__ = "recent_recipients"
    __table_args__ = (
        # One row per (address, recipient_type) — typeahead suggestions
        # for "to" and "cc" are independent.
        UniqueConstraint("address", "recipient_type", name="uq_recent_recipient"),
    )

    id             = Column(Integer, primary_key=True, index=True)
    address        = Column(String, nullable=False, index=True)
    # "to" | "cc" | "bcc"
    recipient_type = Column(String, nullable=False)
    last_used_at   = Column(DateTime, default=datetime.utcnow,
                            onupdate=datetime.utcnow, nullable=False)
    use_count      = Column(Integer, nullable=False, default=1)
