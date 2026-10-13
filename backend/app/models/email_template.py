"""
SQLAlchemy model for `email_templates` — reusable subject / message /
recipient presets for the email composer and scheduled reports.

Subject and message may contain placeholders rendered at send time:
{date}, {datetime}, {dataset}, {sheet}, {rows}.
"""
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text
from app.config.database import Base


class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String, nullable=False, unique=True)
    subject    = Column(String, nullable=False, default="")
    message    = Column(Text, nullable=False, default="")
    to_text    = Column(Text, nullable=False, default="")
    cc_text    = Column(Text, nullable=False, default="")
    bcc_text   = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
