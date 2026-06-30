"""
SQLAlchemy model for the 'datasets' table.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from app.config.database import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id              = Column(Integer, primary_key=True, index=True)
    filename        = Column(String, nullable=False)           # original filename
    stored_filename = Column(String, nullable=False, unique=True)  # UUID-based name on disk
    upload_time     = Column(DateTime, default=datetime.utcnow)
    total_rows      = Column(Integer, nullable=False, default=0)
    total_columns   = Column(Integer, nullable=False, default=0)
