"""
Dataset service — orchestrates post-upload metadata persistence and
on-demand sheet / column / preview queries.

Called by:
  - upload_routes  : after a file is saved to disk
  - dataset_routes : for API responses
"""

from typing import List, Dict, Any
from sqlalchemy.orm import Session

from app.config.settings import UPLOAD_DIR, PREVIEW_ROW_LIMIT
from app.utils.file_utils import build_upload_path
from app.repositories.sheet_repository import (
    create_sheet,
    get_sheets_by_dataset,
    get_sheet,
)
from app.repositories.column_repository import (
    create_columns,
    get_columns_by_sheet,
)
from app.repositories.dataset_repository import get_dataset_by_id
from app.services.excel_service import load_sheet_df, infer_column_info, _df_to_preview
from app.schemas.dataset import ColumnInfo, SheetOut, DatasetDetail, PreviewResponse


# ---------------------------------------------------------------------------
# Called immediately after upload — persist sheet + column metadata
# ---------------------------------------------------------------------------

def persist_sheet_metadata(
    db: Session,
    dataset_id: int,
    sheet_columns: Dict[str, List[ColumnInfo]],
    sheet_row_counts: Dict[str, int],
) -> None:
    """
    For every sheet in the uploaded file, write:
      - one dataset_sheets row
      - N dataset_columns rows (one per column)
    Everything in a single transaction (caller commits).
    """
    for sheet_name, columns in sheet_columns.items():
        row_count = sheet_row_counts.get(sheet_name, 0)
        sheet_record = create_sheet(db, dataset_id, sheet_name, row_count)
        create_columns(db, dataset_id, sheet_record.id, sheet_name, columns)
    db.commit()


# ---------------------------------------------------------------------------
# Query helpers used by dataset_routes
# ---------------------------------------------------------------------------

def get_dataset_detail(db: Session, dataset_id: int) -> DatasetDetail:
    """Return full dataset detail (dataset + all sheets + columns)."""
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        return None

    sheets_db = get_sheets_by_dataset(db, dataset_id)
    sheets_out: List[SheetOut] = []

    for s in sheets_db:
        cols_db = get_columns_by_sheet(db, dataset_id, s.sheet_name)
        col_infos = [
            ColumnInfo(
                column_name=c.column_name,
                data_type=c.data_type,
                is_nullable=c.is_nullable,
            )
            for c in cols_db
        ]
        sheets_out.append(
            SheetOut(
                id=s.id,
                dataset_id=s.dataset_id,
                sheet_name=s.sheet_name,
                row_count=s.row_count,
                columns=col_infos,
            )
        )

    return DatasetDetail(
        id=dataset.id,
        filename=dataset.filename,
        stored_filename=dataset.stored_filename,
        upload_time=dataset.upload_time,
        total_rows=dataset.total_rows,
        total_columns=dataset.total_columns,
        sheets=sheets_out,
    )


def get_sheet_columns(db: Session, dataset_id: int, sheet_name: str) -> List[ColumnInfo]:
    """Return inferred column metadata for a specific sheet from the DB."""
    cols_db = get_columns_by_sheet(db, dataset_id, sheet_name)
    return [
        ColumnInfo(
            column_name=c.column_name,
            data_type=c.data_type,
            is_nullable=c.is_nullable,
        )
        for c in cols_db
    ]


def get_sheet_preview(
    db: Session, dataset_id: int, sheet_name: str
) -> PreviewResponse:
    """
    Load the sheet from disk, return PREVIEW_ROW_LIMIT rows + column info.
    Column info comes from DB (already inferred at upload time).
    """
    dataset = get_dataset_by_id(db, dataset_id)
    filepath = build_upload_path(dataset.stored_filename, UPLOAD_DIR)

    df = load_sheet_df(filepath, sheet_name)
    rows = _df_to_preview(df)
    columns = get_sheet_columns(db, dataset_id, sheet_name)

    return PreviewResponse(
        dataset_id=dataset_id,
        sheet_name=sheet_name,
        columns=columns,
        rows=rows,
    )
