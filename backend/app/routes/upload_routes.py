"""
Upload routes — handles file upload, metadata extraction, and preview rendering.

Routes:
  GET  /             → Upload page (index)
  POST /api/upload   → Upload & parse file, return JSON metadata
  GET  /preview/{id} → Dataset preview page
  GET  /datasets     → List all uploaded datasets
"""

import os
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.settings import UPLOAD_DIR, MAX_UPLOAD_BYTES
from app.repositories import app_settings_repository
from app.schemas.dataset import DatasetCreate, UploadResponse
from app.services.excel_service import extract_metadata
from app.services.dataset_service import persist_sheet_metadata
from app.models.dataset import Dataset
from app.repositories.column_repository import delete_columns_by_dataset
from app.repositories.sheet_repository import delete_sheets_by_dataset
from app.repositories.dataset_repository import (
    create_dataset,
    get_dataset_by_id,
    get_all_datasets,
)
from app.utils.file_utils import generate_stored_filename, build_upload_path
from app.utils.file_validation import FileValidationError, perform_full_validation
from app.utils.tz import format_ist
from app.services.app_logging import log_event

router = APIRouter()

# Templates are located at backend/app/templates/
from app.templating import templates


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def upload_page(request: Request):
    """Render the file upload page."""
    return templates.TemplateResponse("upload.html", {"request": request})


@router.get("/datasets", response_class=HTMLResponse)
def datasets_page(request: Request, db: Session = Depends(get_db)):
    """Render the list of all uploaded datasets."""
    datasets = get_all_datasets(db)
    # The user asked for every visible timestamp in the app to be
    # in IST — pre-format ``upload_time`` here so the Jinja
    # template can render it directly without doing tz math.
    for ds in datasets:
        ds.upload_time_ist = format_ist(ds.upload_time)
        ds.refreshed_at_ist = format_ist(ds.refreshed_at) if ds.refreshed_at else ""
    return templates.TemplateResponse(
        "datasets.html", {"request": request, "datasets": datasets}
    )


@router.get("/preview/{dataset_id}", response_class=HTMLResponse)
def preview_page(request: Request, dataset_id: int, db: Session = Depends(get_db)):
    """Render the dataset preview page for a given dataset id."""
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Pre-format ``upload_time`` in IST so the Jinja template
    # can render it directly.
    dataset.upload_time_ist = format_ist(dataset.upload_time)
    dataset.refreshed_at_ist = format_ist(dataset.refreshed_at) if dataset.refreshed_at else ""

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

def _runtime_max_upload_bytes(db: Session) -> int:
    """Phase 8 — prefer the configured max upload size, fall back to the
    environment default. The configured value lives in `app_settings`."""
    try:
        row = app_settings_repository.get_settings(db)
        if row and row.max_upload_bytes and row.max_upload_bytes > 0:
            return int(row.max_upload_bytes)
    except Exception:
        pass
    return int(MAX_UPLOAD_BYTES)


_UPLOAD_CHUNK = 1024 * 1024


def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Read the upload in chunks and stop as soon as it exceeds the
    limit, instead of buffering an arbitrarily large body first."""
    chunks = []
    total = 0
    while True:
        chunk = file.file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. The maximum allowed size is "
                       f"{round(max_bytes / (1024 * 1024), 1)} MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def ingest_upload(file: UploadFile, db: Session):
    """Validate, store and parse an uploaded file.

    Returns (stored_filename, save_path, meta). On any failure the stored
    file is removed and an HTTPException is raised. Shared by new uploads
    and by "Refresh data" (replacing a dataset's file).
    """
    # --- Validate extension (cheap, first layer) ---
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".xlsx", ".csv"}:
        msg = (f"Unsupported file extension '{ext or '(none)'}'. "
               "Allowed: .xlsx, .csv.")
        log_event("warning", "Upload rejected (extension)", category="upload",
                  details=f"{file.filename}: {msg}")
        raise HTTPException(status_code=400, detail=msg)

    # --- Read file content (enforce runtime-configured size limit) ---
    max_bytes = _runtime_max_upload_bytes(db)
    try:
        content = _read_limited(file, max_bytes)
    except HTTPException:
        log_event("warning", "Upload rejected (size)", category="upload",
                  details=f"{file.filename}: over limit {max_bytes} bytes")
        raise

    # --- Save to disk with unique name ---
    stored_filename = generate_stored_filename(file.filename)
    save_path = build_upload_path(stored_filename, UPLOAD_DIR)
    with open(save_path, "wb") as f:
        f.write(content)

    # --- Validate MIME + magic bytes + full file integrity ---
    try:
        perform_full_validation(
            filename=file.filename or "",
            content_type=file.content_type,
            head_bytes=content[:8],
            full_path=save_path,
        )
    except FileValidationError as exc:
        _remove_quietly(save_path)
        log_event("warning", "Upload rejected (validation)", category="upload",
                  details=f"{file.filename}: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        _remove_quietly(save_path)
        raise

    # --- Parse metadata ---
    try:
        meta = extract_metadata(save_path)
    except Exception as exc:
        _remove_quietly(save_path)
        log_event("error", "Upload failed (parse)", category="upload",
                  details=f"{file.filename}: {exc}")
        raise HTTPException(status_code=422, detail=f"Failed to parse file: {exc}")

    return stored_filename, save_path, meta


@router.post("/api/upload", response_model=UploadResponse)
def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Accept an .xlsx or .csv file, save it, extract metadata, persist to DB.
    Returns full metadata + preview rows as JSON.

    Phase 8 — three layers of validation (extension / MIME / magic bytes)
    + a runtime-configurable max upload size from /api/settings.

    This is a plain (sync) route on purpose: parsing a workbook with
    pandas is CPU-bound, and FastAPI runs sync routes in a worker thread
    so a large upload no longer freezes every other request.
    """
    stored_filename, save_path, meta = ingest_upload(file, db)

    # --- Persist dataset + sheet + column metadata ---
    # If anything fails after the dataset row exists, remove the row and
    # the file so we never leave a dataset without metadata (or a file
    # without a dataset).
    dataset_record = None
    try:
        dataset_record = create_dataset(
            db,
            DatasetCreate(
                filename=file.filename,
                stored_filename=stored_filename,
                total_rows=meta["total_rows"],
                total_columns=meta["total_cols"],
            ),
        )
        sheet_row_counts = {s.sheet_name: s.row_count for s in meta["sheets"]}
        persist_sheet_metadata(
            db,
            dataset_id=dataset_record.id,
            sheet_columns=meta["sheet_columns"],
            sheet_row_counts=sheet_row_counts,
        )
    except Exception as exc:
        db.rollback()
        if dataset_record is not None:
            try:
                delete_columns_by_dataset(db, dataset_record.id)
                delete_sheets_by_dataset(db, dataset_record.id)
                db.query(Dataset).filter(Dataset.id == dataset_record.id).delete()
                db.commit()
            except Exception:
                db.rollback()
        _remove_quietly(save_path)
        log_event("error", "Upload failed (persist)", category="upload",
                  details=f"{file.filename}: {exc}")
        raise HTTPException(status_code=500, detail=f"Could not save dataset: {exc}")

    log_event(
        "info",
        "Dataset uploaded",
        category="upload",
        details=f"id={dataset_record.id} file={file.filename} "
                f"sheets={len(meta['sheets'])} rows={meta['total_rows']}",
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
