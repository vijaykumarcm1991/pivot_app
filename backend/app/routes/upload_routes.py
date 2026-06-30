"""
Upload routes — handles file upload, metadata extraction, and preview rendering.

Routes:
  GET  /             → Upload page (index)
  POST /api/upload   → Upload & parse file, return JSON metadata
  GET  /preview/{id} → Dataset preview page
  GET  /datasets     → List all uploaded datasets
"""

import os
import aiofiles

from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.settings import UPLOAD_DIR, MAX_UPLOAD_BYTES
from app.schemas.dataset import DatasetCreate, UploadResponse
from app.services.excel_service import extract_metadata
from app.services.dataset_service import persist_sheet_metadata
from app.repositories.dataset_repository import (
    create_dataset,
    get_dataset_by_id,
    get_all_datasets,
)
from app.utils.file_utils import generate_stored_filename, is_allowed_file, build_upload_path

router = APIRouter()

# Templates are located at backend/app/templates/
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def upload_page(request: Request):
    """Render the file upload page."""
    return templates.TemplateResponse("upload.html", {"request": request})


@router.get("/datasets", response_class=HTMLResponse)
async def datasets_page(request: Request, db: Session = Depends(get_db)):
    """Render the list of all uploaded datasets."""
    datasets = get_all_datasets(db)
    return templates.TemplateResponse(
        "datasets.html", {"request": request, "datasets": datasets}
    )


@router.get("/preview/{dataset_id}", response_class=HTMLResponse)
async def preview_page(request: Request, dataset_id: int, db: Session = Depends(get_db)):
    """Render the dataset preview page for a given dataset id."""
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Re-parse to get sheet metadata and preview rows
    filepath = build_upload_path(dataset.stored_filename, UPLOAD_DIR)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Uploaded file not found on disk")

    meta = extract_metadata(filepath)
    first_sheet_name = meta["sheets"][0].sheet_name if meta["sheets"] else "Sheet1"
    column_types = {
        c.column_name: c.data_type
        for c in meta["sheet_columns"].get(first_sheet_name, [])
    }

    return templates.TemplateResponse(
        "preview.html",
        {
            "request":      request,
            "dataset":      dataset,
            "sheets":       meta["sheets"],
            "preview":      meta["preview"],
            "columns":      meta["sheets"][0].column_names if meta["sheets"] else [],
            "column_types": column_types,
        },
    )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@router.post("/api/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Accept an .xlsx or .csv file, save it, extract metadata, persist to DB.
    Returns full metadata + preview rows as JSON.
    """
    # --- Validate extension ---
    if not is_allowed_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: .xlsx, .csv",
        )

    # --- Read file content (enforce size limit) ---
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is 50 MB.",
        )

    # --- Save to disk with unique name ---
    stored_filename = generate_stored_filename(file.filename)
    save_path = build_upload_path(stored_filename, UPLOAD_DIR)

    async with aiofiles.open(save_path, "wb") as f:
        await f.write(content)

    # --- Parse metadata ---
    try:
        meta = extract_metadata(save_path)
    except Exception as exc:
        os.remove(save_path)  # clean up on failure
        raise HTTPException(status_code=422, detail=f"Failed to parse file: {exc}")

    # --- Persist dataset record ---
    dataset_record = create_dataset(
        db,
        DatasetCreate(
            filename=file.filename,
            stored_filename=stored_filename,
            total_rows=meta["total_rows"],
            total_columns=meta["total_cols"],
        ),
    )

    # --- Persist sheet + column metadata (Phase 2) ---
    sheet_row_counts = {s.sheet_name: s.row_count for s in meta["sheets"]}
    persist_sheet_metadata(
        db,
        dataset_id=dataset_record.id,
        sheet_columns=meta["sheet_columns"],
        sheet_row_counts=sheet_row_counts,
    )

    return UploadResponse(
        dataset_id=dataset_record.id,
        filename=dataset_record.filename,
        stored_filename=dataset_record.stored_filename,
        total_rows=dataset_record.total_rows,
        total_columns=dataset_record.total_columns,
        sheets=meta["sheets"],
        preview=meta["preview"],
    )
