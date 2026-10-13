"""
Saved pivots API.

  GET    /api/saved-pivots[?dataset_id=]   list
  GET    /api/saved-pivots/{id}            detail incl. config
  POST   /api/saved-pivots                 {name, description?, config}
  PUT    /api/saved-pivots/{id}            {name?, description?, config?}
  DELETE /api/saved-pivots/{id}            also removes its schedules
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.services import saved_pivot_service as svc
from app.services.app_logging import log_event

router = APIRouter()


class SavedPivotIn(BaseModel):
    name: str
    description: str = ""
    config: Dict[str, Any]


class SavedPivotUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


def _raise(exc: svc.SavedPivotError):
    status = 409 if isinstance(exc, svc.SavedPivotConflict) else 400
    raise HTTPException(status_code=status, detail=str(exc)) from exc


def _get_or_404(db: Session, saved_id: int):
    row = svc.get_saved(db, saved_id)
    if not row:
        raise HTTPException(status_code=404, detail="Saved pivot not found")
    return row


@router.get("/api/saved-pivots")
def api_list(dataset_id: Optional[int] = None, db: Session = Depends(get_db)):
    return svc.list_saved(db, dataset_id)


@router.get("/api/saved-pivots/{saved_id}")
def api_get(saved_id: int, db: Session = Depends(get_db)):
    return svc.serialize(db, _get_or_404(db, saved_id), include_config=True)


@router.post("/api/saved-pivots", status_code=201)
def api_create(payload: SavedPivotIn, db: Session = Depends(get_db)):
    try:
        row = svc.create_saved(db, name=payload.name, description=payload.description, config=payload.config)
    except svc.SavedPivotError as exc:
        _raise(exc)
    log_event("info", "Pivot saved", category="pivot", details=f"id={row.id} name={row.name}")
    return svc.serialize(db, row, include_config=True)


@router.put("/api/saved-pivots/{saved_id}")
def api_update(saved_id: int, payload: SavedPivotUpdate, db: Session = Depends(get_db)):
    row = _get_or_404(db, saved_id)
    try:
        row = svc.update_saved(db, row, name=payload.name, description=payload.description, config=payload.config)
    except svc.SavedPivotError as exc:
        _raise(exc)
    return svc.serialize(db, row, include_config=True)


@router.delete("/api/saved-pivots/{saved_id}")
def api_delete(saved_id: int, db: Session = Depends(get_db)):
    row = _get_or_404(db, saved_id)
    name = row.name
    removed = svc.delete_saved(db, row)
    log_event("info", "Saved pivot deleted", category="pivot", details=f"id={saved_id} name={name} schedules={removed}")
    return {"deleted": saved_id, "schedulesDeleted": removed}
