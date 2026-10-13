"""
SQLAlchemy model for `saved_pivots` — a named pivot configuration.

`config_json` holds the same payload the Pivot Builder sends to
POST /api/pivot (rows, columns, values, filters, dateGrouping, sorting,
totals, layout, valueFilters, displayOptions). The dataset / sheet are
also stored as columns so saved pivots can be listed per dataset and
removed when their dataset is deleted.
"""
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text
from app.config.database import Base


class SavedPivot(Base):
    __tablename__ = "saved_pivots"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    dataset_id  = Column(Integer, nullable=False, index=True)
    sheet_name  = Column(String, nullable=False)
    config_json = Column(Text, nullable=False, default="{}")
    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at  = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
