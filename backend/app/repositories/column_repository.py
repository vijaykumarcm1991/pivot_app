"""
Repository for dataset_columns table operations.
"""

from typing import List
from sqlalchemy.orm import Session

from app.models.column import DatasetColumn
from app.schemas.dataset import ColumnInfo


def create_columns(
    db: Session,
    dataset_id: int,
    sheet_id: int,
    sheet_name: str,
    columns: List[ColumnInfo],
) -> None:
    """Bulk-insert column metadata for one sheet."""
    records = [
        DatasetColumn(
            dataset_id=dataset_id,
            sheet_id=sheet_id,
            sheet_name=sheet_name,
            column_name=col.column_name,
            data_type=col.data_type,
            is_nullable=col.is_nullable,
        )
        for col in columns
    ]
    db.bulk_save_objects(records)
    db.flush()


def get_columns_by_sheet(
    db: Session, dataset_id: int, sheet_name: str
) -> List[DatasetColumn]:
    return (
        db.query(DatasetColumn)
        .filter(
            DatasetColumn.dataset_id == dataset_id,
            DatasetColumn.sheet_name == sheet_name,
        )
        .order_by(DatasetColumn.id)
        .all()
    )


def delete_columns_by_dataset(db: Session, dataset_id: int) -> None:
    db.query(DatasetColumn).filter(DatasetColumn.dataset_id == dataset_id).delete()
    db.flush()
