"""
Saved pivots — named pivot configurations (#1).

A saved pivot stores the same payload the Pivot Builder posts to
/api/pivot. It is validated against `PivotRequest` on save, so a saved
pivot can always be re-run as-is (e.g. by a scheduled report).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.models.report_schedule import ReportSchedule
from app.models.saved_pivot import SavedPivot
from app.repositories.dataset_repository import get_dataset_by_id
from app.schemas.pivot import PivotRequest
from app.utils.tz import iso_ist

# Keys of the Pivot Builder payload that are worth persisting.
_CONFIG_KEYS = (
    "datasetId", "sheetName", "rows", "columns", "values", "filters",
    "dateGrouping", "sorting", "totals", "layout", "displayOptions", "valueFilters",
)


class SavedPivotError(ValueError):
    """Invalid saved-pivot request (maps to HTTP 400)."""


class SavedPivotConflict(SavedPivotError):
    """Name already used (maps to HTTP 409)."""


def clean_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only pivot keys and check the result is a valid PivotRequest."""
    if not isinstance(config, dict):
        raise SavedPivotError("config must be an object.")
    cleaned = {k: config[k] for k in _CONFIG_KEYS if k in config}
    try:
        PivotRequest(**cleaned)
    except Exception as exc:
        raise SavedPivotError(f"Invalid pivot configuration: {exc}") from exc
    return cleaned


def to_pivot_request(saved: SavedPivot) -> PivotRequest:
    config = json.loads(saved.config_json or "{}")
    config["datasetId"] = saved.dataset_id
    config["sheetName"] = saved.sheet_name
    return PivotRequest(**{k: config[k] for k in _CONFIG_KEYS if k in config})


def _check_name(db: Session, name: str, exclude_id: Optional[int] = None) -> str:
    name = (name or "").strip()
    if not name:
        raise SavedPivotError("Name is required.")
    if len(name) > 120:
        raise SavedPivotError("Name is too long (max 120 characters).")
    q = db.query(SavedPivot).filter(func.lower(SavedPivot.name) == name.lower())
    if exclude_id is not None:
        q = q.filter(SavedPivot.id != exclude_id)
    if q.first():
        raise SavedPivotConflict(f'A saved pivot named "{name}" already exists.')
    return name


def serialize(db: Session, row: SavedPivot, *, include_config: bool = False) -> Dict[str, Any]:
    dataset = db.query(Dataset).filter(Dataset.id == row.dataset_id).first()
    schedules = db.query(func.count(ReportSchedule.id)).filter(ReportSchedule.saved_pivot_id == row.id).scalar() or 0
    out = {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "datasetId": row.dataset_id,
        "datasetName": dataset.filename if dataset else "",
        "sheetName": row.sheet_name,
        "scheduleCount": int(schedules),
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        "updatedAtIst": iso_ist(row.updated_at),
    }
    if include_config:
        out["config"] = json.loads(row.config_json or "{}")
    return out


def list_saved(db: Session, dataset_id: Optional[int] = None) -> List[Dict[str, Any]]:
    q = db.query(SavedPivot)
    if dataset_id is not None:
        q = q.filter(SavedPivot.dataset_id == dataset_id)
    return [serialize(db, r) for r in q.order_by(SavedPivot.name.asc()).all()]


def get_saved(db: Session, saved_id: int) -> Optional[SavedPivot]:
    return db.query(SavedPivot).filter(SavedPivot.id == saved_id).first()


def create_saved(db: Session, *, name: str, description: str, config: Dict[str, Any]) -> SavedPivot:
    cleaned = clean_config(config)
    if not get_dataset_by_id(db, int(cleaned["datasetId"])):
        raise SavedPivotError("Dataset not found.")
    row = SavedPivot(
        name=_check_name(db, name),
        description=(description or "").strip() or None,
        dataset_id=int(cleaned["datasetId"]),
        sheet_name=cleaned["sheetName"],
        config_json=json.dumps(cleaned, default=str),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_saved(
    db: Session, row: SavedPivot, *,
    name: Optional[str] = None, description: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> SavedPivot:
    if name is not None:
        row.name = _check_name(db, name, exclude_id=row.id)
    if description is not None:
        row.description = description.strip() or None
    if config is not None:
        cleaned = clean_config(config)
        if int(cleaned["datasetId"]) != row.dataset_id:
            raise SavedPivotError("A saved pivot can't be moved to another dataset; save a new one instead.")
        row.sheet_name = cleaned["sheetName"]
        row.config_json = json.dumps(cleaned, default=str)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def delete_saved(db: Session, row: SavedPivot) -> int:
    """Delete a saved pivot and its schedules. Returns schedules removed."""
    removed = db.query(ReportSchedule).filter(ReportSchedule.saved_pivot_id == row.id).delete()
    db.delete(row)
    db.commit()
    return int(removed)


def delete_for_dataset(db: Session, dataset_id: int) -> None:
    """Remove saved pivots (and their schedules) of a deleted dataset.
    Does not commit — the caller's transaction does."""
    ids = [r.id for r in db.query(SavedPivot.id).filter(SavedPivot.dataset_id == dataset_id).all()]
    if ids:
        db.query(ReportSchedule).filter(ReportSchedule.saved_pivot_id.in_(ids)).delete(synchronize_session=False)
        db.query(SavedPivot).filter(SavedPivot.id.in_(ids)).delete(synchronize_session=False)


def check_against_dataset(db: Session, dataset_id: int) -> List[str]:
    """Warnings for saved pivots that reference sheets / columns the
    dataset no longer has (used after a data refresh)."""
    from app.repositories.column_repository import get_columns_by_sheet
    from app.repositories.sheet_repository import get_sheet

    warnings: List[str] = []
    for row in db.query(SavedPivot).filter(SavedPivot.dataset_id == dataset_id).all():
        if not get_sheet(db, dataset_id, row.sheet_name):
            warnings.append(f'Saved pivot "{row.name}": sheet "{row.sheet_name}" no longer exists.')
            continue
        cols = {c.column_name for c in get_columns_by_sheet(db, dataset_id, row.sheet_name)}
        cfg = json.loads(row.config_json or "{}")
        used = set(cfg.get("rows") or []) | set(cfg.get("columns") or []) | set((cfg.get("filters") or {}).keys())
        used |= {v.get("field") for v in (cfg.get("values") or []) if isinstance(v, dict)}
        missing = sorted(f for f in used if f and f not in cols)
        if missing:
            warnings.append(f'Saved pivot "{row.name}": missing column(s) {", ".join(missing)}.')
    return warnings
