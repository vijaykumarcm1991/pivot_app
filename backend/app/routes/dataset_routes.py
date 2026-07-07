"""
Dataset management routes — Phase 2 + Phase 8.

API endpoints:
  GET /api/datasets                                    → list all datasets
  GET /api/dataset/{id}                               → dataset detail + sheets + columns
  DELETE /api/dataset/{id}                            → delete dataset + files + metadata
  GET /api/dataset/{id}/sheet/{sheet_name}/columns    → column metadata for one sheet
  GET /api/dataset/{id}/sheet/{sheet_name}/preview    → row preview for one sheet

Page endpoints:
  GET /manage                                         → Dataset Management UI
"""

import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List

from app.config.database import get_db
from app.config.settings import UPLOAD_DIR
from app.models.deleted_dataset import DeletedDataset
from app.repositories.dataset_repository import get_all_datasets, get_dataset_by_id, delete_dataset
from app.repositories.sheet_repository import get_sheet, delete_sheets_by_dataset
from app.repositories.column_repository import delete_columns_by_dataset
from app.utils.file_utils import build_upload_path
from app.schemas.dataset import DatasetOut, DatasetDetail, ColumnInfo, PreviewResponse
from app.services.dataset_service import (
    get_dataset_detail,
    get_sheet_columns,
    get_sheet_preview,
)
from app.services import metadata_cache
from app.services.app_logging import log_event

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@router.get("/manage", response_class=HTMLResponse)
async def manage_page(request: Request, db: Session = Depends(get_db)):
    """Render the Dataset Management UI."""
    datasets = get_all_datasets(db)
    return templates.TemplateResponse(
        "manage.html", {"request": request, "datasets": datasets}
    )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@router.get("/api/datasets", response_model=List[DatasetOut])
def api_list_datasets(db: Session = Depends(get_db)):
    """Return all datasets ordered by most-recent first."""
    return get_all_datasets(db)


@router.get("/api/dataset/{dataset_id}", response_model=DatasetDetail)
def api_get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    """Return full dataset detail including sheets and inferred column types."""
    detail = get_dataset_detail(db, dataset_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return detail


@router.get(
    "/api/dataset/{dataset_id}/sheet/{sheet_name}/columns",
    response_model=List[ColumnInfo],
)
def api_get_columns(dataset_id: int, sheet_name: str, db: Session = Depends(get_db)):
    """Return inferred column metadata for a specific sheet."""
    # Verify dataset exists
    if not get_dataset_by_id(db, dataset_id):
        raise HTTPException(status_code=404, detail="Dataset not found")
    # Verify sheet exists
    if not get_sheet(db, dataset_id, sheet_name):
        raise HTTPException(status_code=404, detail=f"Sheet '{sheet_name}' not found")

    return get_sheet_columns(db, dataset_id, sheet_name)


@router.get(
    "/api/dataset/{dataset_id}/sheet/{sheet_name}/preview",
    response_model=PreviewResponse,
)
def api_get_preview(dataset_id: int, sheet_name: str, db: Session = Depends(get_db)):
    """Return the first N rows of a sheet along with column metadata."""
    if not get_dataset_by_id(db, dataset_id):
        raise HTTPException(status_code=404, detail="Dataset not found")
    if not get_sheet(db, dataset_id, sheet_name):
        raise HTTPException(status_code=404, detail=f"Sheet '{sheet_name}' not found")

    try:
        return get_sheet_preview(db, dataset_id, sheet_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Preview failed: {exc}")


@router.delete("/api/dataset/{dataset_id}")
def api_delete_dataset(dataset_id: int, req: Request, db: Session = Depends(get_db)):
    """Delete a dataset and its associated files, sheets, columns, and soft-deleted records."""
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    try:
        # Phase 8 — capture metadata for the deleted_datasets audit
        # before we drop the row.
        snapshot = DeletedDataset(
            original_id=dataset.id,
            filename=dataset.filename or "",
            stored_filename=dataset.stored_filename or "",
            total_rows=int(dataset.total_rows or 0),
            total_columns=int(dataset.total_columns or 0),
            upload_time=dataset.upload_time,
            deleted_at=datetime.utcnow(),
            deleted_by="ui",
        )
        db.add(snapshot)

        # 1. Delete the stored file from disk
        filepath = build_upload_path(dataset.stored_filename, UPLOAD_DIR)
        if os.path.exists(filepath):
            os.remove(filepath)

        # 2. Delete columns metadata
        delete_columns_by_dataset(db, dataset_id)

        # 3. Delete sheets metadata
        delete_sheets_by_dataset(db, dataset_id)

        # 4. Delete the dataset record itself
        delete_dataset(db, dataset_id)

        # 5. Drop any soft-deleted records for this dataset (cascading)
        from app.models.soft_deleted_record import SoftDeletedRecord
        from app.models.delete_audit import DeleteAudit
        db.query(SoftDeletedRecord).filter(SoftDeletedRecord.dataset_id == dataset_id).delete()
        db.query(DeleteAudit).filter(DeleteAudit.dataset_id == dataset_id).delete()

        # 6. Commit all deletions
        db.commit()

        # 7. Phase 8 — invalidate the in-memory cache so any open
        # pivot for this dataset gets a fresh view on next compute.
        metadata_cache.invalidate_dataset(dataset_id)

        log_event(
            "info",
            "Dataset deleted",
            category="dataset",
            details=f"id={dataset_id} file={dataset.filename}",
            request=req,
        )

        return JSONResponse(
            content={
                "message": f"Dataset '{dataset.filename}' deleted successfully",
                "deleted_id": dataset_id,
            },
            status_code=200,
        )
    except Exception as exc:
        db.rollback()
        log_event(
            "error",
            "Dataset delete failed",
            category="dataset",
            details=f"id={dataset_id} error={exc}",
            request=req,
        )
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}")
