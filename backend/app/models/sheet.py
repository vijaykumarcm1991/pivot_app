"""
SQLAlchemy model for the 'dataset_sheets' table.
"""

from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.config.database import Base


class DatasetSheet(Base):
    __tablename__ = "dataset_sheets"

    id         = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    sheet_name = Column(String, nullable=False)
    row_count  = Column(Integer, nullable=False, default=0)

    # back-reference to columns belonging to this sheet
    columns = relationship("DatasetColumn", back_populates="sheet", cascade="all, delete-orphan")
