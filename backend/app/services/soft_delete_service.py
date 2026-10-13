"""
Phase 8 — Soft-delete service.

When the user clicks "Delete Records" on a pivot row (or on a multi-row
selection) from the Pivot page, the service:

  1. finds every raw record represented by the selected pivot rows
     (the same selection criteria the drilldown endpoint uses, but
     applied to the source data);
  2. inserts a `SoftDeletedRecord` row for every match (so the same
     record is never inserted twice);
  3. records the operation in `DeleteAudit` with a selection-criteria
     snapshot and a status flag;
  4. logs the event to the application log;
  5. invalidates the in-memory cache so the next pivot re-computes
     against the un-deleted data.

We prefer soft delete over a hard file mutation because:

  - the source files (`.xlsx`) are stored in a binary form that is not
    trivial to mutate in place; the entire file would have to be
    rewritten and re-uploaded on every delete;
  - soft delete survives the re-upload of the same dataset — when the
    same file is uploaded again, the same `source_key` is re-computed
    and the same rows are kept out;
  - the audit trail is complete and queryable;
  - the user can request a hard-delete from the Cleanup page if they
    want to permanently free disk space.

The contract
------------
  soft_delete_from_pivot(db, dataset_id, sheet_name, pivot_request,
                          selections, *, actor="ui")
        → returns {"matched": int, "deleted": int, "audit_id": int,
                   "selections": int}

  count_matching_records(db, pivot_request=..., selections=...)
        → int  (dry run — nothing is written)

  The caller (the route) is responsible for turning this dict into
  a Pydantic response and triggering a re-render of the pivot on
  the client side.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.models.delete_audit import DeleteAudit
from app.models.soft_deleted_record import SoftDeletedRecord
from app.repositories.dataset_repository import get_dataset_by_id
from app.services.pivot_service import PivotError, _df_to_records, match_selections
from app.services.row_keys import frame_row_keys
from app.schemas.pivot import PivotRequest
from app.services import metadata_cache
from app.services.app_logging import log_event
from app.utils.tz import iso_ist


class SoftDeleteError(ValueError):
    """Raised when a soft-delete request is invalid."""


def _existing_keys(db: Session, dataset_id: int, sheet_name: str) -> set:
    """Return the set of source_keys already soft-deleted for this
    dataset + sheet."""
    rows = (
        db.query(SoftDeletedRecord.source_key)
        .filter(SoftDeletedRecord.dataset_id == dataset_id)
        .filter(SoftDeletedRecord.sheet_name == sheet_name)
        .all()
    )
    return {r[0] for r in rows if r[0]}


def _to_pivot_request(pivot_request: Any) -> PivotRequest:
    """Accept a PivotRequest or a plain camelCase / snake_case dict."""
    if isinstance(pivot_request, PivotRequest):
        return pivot_request
    if hasattr(pivot_request, "model_dump"):
        pivot_request = pivot_request.model_dump(by_alias=True)
    if not isinstance(pivot_request, dict):
        raise SoftDeleteError("Invalid pivot request.")
    data = {k: v for k, v in pivot_request.items() if k not in {"selection", "limit", "availableColumns", "datasetName"}}
    try:
        return PivotRequest(**data)
    except Exception as exc:
        raise SoftDeleteError(f"Invalid pivot request: {exc}") from exc


def _matched_records(db: Session, pivot_request: Any, selections: List[Dict[str, Any]]):
    """Return (request, matched DataFrame) for the union of `selections`."""
    if not selections:
        raise SoftDeleteError("No pivot rows selected for deletion.")
    if any(not isinstance(s, dict) or not s for s in selections):
        # An empty selection would match every record — refuse outright
        # unless the pivot has no row fields at all.
        req = _to_pivot_request(pivot_request)
        if req.rows:
            raise SoftDeleteError(
                "A selected row has no row-field values, so it cannot be "
                "matched safely. Nothing was deleted."
            )
    req = _to_pivot_request(pivot_request)
    try:
        matched = match_selections(db, req, selections)
    except PivotError as exc:
        raise SoftDeleteError(str(exc)) from exc
    return req, matched


def count_matching_records(
    db: Session, *, pivot_request: Any, selections: List[Dict[str, Any]]
) -> int:
    """Dry run: number of distinct source records a delete would hide."""
    _, matched = _matched_records(db, pivot_request, selections)
    return int(len(matched))


def soft_delete_from_pivot(
    db: Session,
    *,
    dataset_id: int,
    sheet_name: str,
    pivot_request: Any,
    selections: List[Dict[str, Any]],
    actor: str = "ui",
) -> Dict[str, Any]:
    """
    Soft-delete every raw record represented by the selected pivot rows.

    The caller passes the same `PivotRequest` the user used to compute
    the pivot (so the engine can rebuild the same filtered / grouped
    context) and a list of `selections` — each one a {field: value}
    map describing a pivot row to delete. Every matching record is
    deleted (there is no row cap).

    Returns a small dict with the matched/deleted counts and the new
    audit row id, ready to surface to the user as a success toast.
    """
    if not selections:
        raise SoftDeleteError("No pivot rows selected for deletion.")
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise SoftDeleteError("Dataset not found.")

    req = _to_pivot_request(pivot_request)
    if req.dataset_id != dataset_id or req.sheet_name != sheet_name:
        raise SoftDeleteError("Pivot request does not match the dataset / sheet being deleted from.")
    pivot_payload_json = json.dumps(req.model_dump(by_alias=True), default=str)

    audit = DeleteAudit(
        timestamp=datetime.utcnow(),
        dataset_id=dataset_id,
        dataset_name=dataset.filename or "",
        sheet_name=sheet_name,
        pivot_rows_count=len(selections),
        source_records_found=0,
        source_records_deleted=0,
        selection_criteria=json.dumps(selections, default=str),
        status="in_progress",
        actor=actor,
        pivot_payload_json=pivot_payload_json,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    log_event(
        "info",
        "Pivot records delete started",
        category="pivot_delete",
        details=f"dataset={dataset.filename} sheet={sheet_name} "
                f"pivot_rows={len(selections)} actor={actor}",
    )

    try:
        _, matched = _matched_records(db, req, selections)
        existing = _existing_keys(db, dataset_id, sheet_name)
        keys = frame_row_keys(matched)
        records = _df_to_records(matched)

        new_objects: List[SoftDeletedRecord] = []
        seen: set = set()
        now = datetime.utcnow()
        for key, row in zip(keys, records):
            if key in existing or key in seen:
                continue
            seen.add(key)
            new_objects.append(SoftDeletedRecord(
                dataset_id=dataset_id,
                sheet_name=sheet_name,
                source_key=key,
                row_payload=json.dumps(row, default=str)[:65000],
                pivot_request=pivot_payload_json,
                deleted_at=now,
                deleted_by=actor,
                delete_audit_id=audit.id,
            ))
        db.add_all(new_objects)

        audit.source_records_found   = int(len(matched))
        audit.source_records_deleted = len(new_objects)
        audit.status = "success"
        db.commit()
        db.refresh(audit)

        # Invalidate the cache so the next pivot recomputes fresh.
        metadata_cache.invalidate_dataset(dataset_id)

        log_event(
            "info",
            "Pivot records delete completed",
            category="pivot_delete",
            details=f"audit_id={audit.id} matched={len(matched)} "
                    f"deleted={len(new_objects)} actor={actor}",
        )

        return {
            "audit_id":     audit.id,
            "matched":      int(len(matched)),
            "deleted":      len(new_objects),
            "selections":   len(selections),
        }
    except Exception as exc:
        db.rollback()
        audit = db.query(DeleteAudit).filter(DeleteAudit.id == audit.id).first()
        if audit is not None:
            audit.status = "failed"
            audit.error_message = str(exc)[:4000]
            db.commit()
        log_event(
            "error",
            "Pivot records delete failed",
            category="pivot_delete",
            details=f"error={exc}",
        )
        raise


def list_audit(
    db: Session,
    *,
    query: Optional[str] = None,
    status: Optional[str] = None,
    dataset_id: Optional[int] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    q = db.query(DeleteAudit)
    if query:
        like = f"%{query}%"
        q = q.filter((DeleteAudit.dataset_name.ilike(like)) | (DeleteAudit.selection_criteria.ilike(like)))
    if status:
        q = q.filter(DeleteAudit.status == status)
    if dataset_id is not None:
        q = q.filter(DeleteAudit.dataset_id == dataset_id)
    rows = q.order_by(DeleteAudit.timestamp.desc()).limit(limit).all()
    return [
        {
            "id":                     r.id,
            "timestamp":              r.timestamp.isoformat() if r.timestamp else None,
            # IST-formatted ISO-8601 string for the frontend.
            "timestamp_ist":          iso_ist(r.timestamp),
            "datasetId":              r.dataset_id,
            "datasetName":            r.dataset_name or "",
            "sheetName":              r.sheet_name or "",
            "pivotRowsCount":         r.pivot_rows_count,
            "sourceRecordsFound":     r.source_records_found,
            "sourceRecordsDeleted":   r.source_records_deleted,
            "selectionCriteria":      r.selection_criteria,
            "status":                 r.status,
            "errorMessage":           r.error_message,
            "actor":                  r.actor,
        }
        for r in rows
    ]


def get_audit(db: Session, audit_id: int) -> Optional[DeleteAudit]:
    return db.query(DeleteAudit).filter(DeleteAudit.id == audit_id).first()
