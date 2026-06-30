"""
Dataset repository — all database operations for the datasets table.
"""

from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.schemas.dataset import DatasetCreate


def create_dataset(db: Session, data: DatasetCreate) -> Dataset:
    """Insert a new dataset record and return it."""
    record = Dataset(
        filename=data.filename,
        stored_filename=data.stored_filename,
        total_rows=data.total_rows,
        total_columns=data.total_columns,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_dataset_by_id(db: Session, dataset_id: int) -> Optional[Dataset]:
    """Fetch a single dataset by primary key."""
    return db.query(Dataset).filter(Dataset.id == dataset_id).first()


def get_all_datasets(db: Session) -> List[Dataset]:
    """Return all datasets ordered by most-recent first."""
    return db.query(Dataset).order_by(Dataset.upload_time.desc()).all()


def delete_dataset(db: Session, dataset_id: int) -> bool:
    """Delete a dataset record. Returns True if deleted, False if not found."""
    record = get_dataset_by_id(db, dataset_id)
    if not record:
        return False
    db.delete(record)
    db.commit()
    return True
