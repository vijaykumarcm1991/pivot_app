"""
Repository for dataset_sheets table operations.
"""

from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.sheet import DatasetSheet


def create_sheet(db: Session, dataset_id: int, sheet_name: str, row_count: int) -> DatasetSheet:
    record = DatasetSheet(
        dataset_id=dataset_id,
        sheet_name=sheet_name,
        row_count=row_count,
    )
    db.add(record)
    db.flush()   # get the id without committing the outer transaction
    return record


def get_sheets_by_dataset(db: Session, dataset_id: int) -> List[DatasetSheet]:
    return (
        db.query(DatasetSheet)
        .filter(DatasetSheet.dataset_id == dataset_id)
        .order_by(DatasetSheet.id)
        .all()
    )


def get_sheet(db: Session, dataset_id: int, sheet_name: str) -> Optional[DatasetSheet]:
    return (
        db.query(DatasetSheet)
        .filter(
            DatasetSheet.dataset_id == dataset_id,
            DatasetSheet.sheet_name == sheet_name,
        )
        .first()
    )


def delete_sheets_by_dataset(db: Session, dataset_id: int) -> None:
    db.query(DatasetSheet).filter(DatasetSheet.dataset_id == dataset_id).delete()
    db.flush()
