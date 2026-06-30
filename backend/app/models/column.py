"""
SQLAlchemy model for the 'dataset_columns' table.
"""

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.config.database import Base


class DatasetColumn(Base):
    __tablename__ = "dataset_columns"

    id          = Column(Integer, primary_key=True, index=True)
    dataset_id  = Column(Integer, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    sheet_name  = Column(String, nullable=False)
    column_name = Column(String, nullable=False)
    # inferred type: string | integer | float | boolean | datetime
    data_type   = Column(String, nullable=False, default="string")
    is_nullable = Column(Boolean, nullable=False, default=True)

    # FK to dataset_sheets for easy joins
    sheet_id = Column(Integer, ForeignKey("dataset_sheets.id", ondelete="CASCADE"), nullable=True)
    sheet    = relationship("DatasetSheet", back_populates="columns")
