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
                   "deleted_record_ids": [int, ...]}

  The caller (the route) is responsible for turning this dict into
  a Pydantic response and triggering a re-render of the pivot on
  the client side.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.models.delete_audit import DeleteAudit
from app.models.soft_deleted_record import SoftDeletedRecord
from app.repositories.dataset_repository import get_dataset_by_id
from app.services.pivot_service import build_drilldown
from app.services.row_keys import row_source_key
from app.schemas.pivot import PivotDrilldownRequest, PivotValue
from app.services import metadata_cache
from app.services.app_logging import log_event


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


def _pivot_request_to_drilldown_request(
    pivot_request: Any,
    selection: Dict[str, Any],
    limit: int = 5000,
) -> PivotDrilldownRequest:
    """Translate a pivot request + one selection into a DrilldownRequest."""
    # The pivot_request can be a Pydantic model or a plain dict; we
    # accept both for forward compatibility.
    if hasattr(pivot_request, "model_dump"):
        pr = pivot_request.model_dump(by_alias=True)
    elif isinstance(pivot_request, dict):
        pr = dict(pivot_request)
    else:
        pr = {}

    def _get(*names, default=None):
        for n in names:
            if n in pr:
                return pr[n]
        return default

    return PivotDrilldownRequest(
        dataset_id=_get("datasetId", "dataset_id"),
        sheet_name=_get("sheetName", "sheet_name"),
        rows=list(_get("rows", default=[]) or []),
        columns=list(_get("columns", default=[]) or []),
        values=_get("values", default=[]) or [],
        filters=_get("filters", default={}) or {},
        date_grouping=_get("dateGrouping", "date_grouping", default={}) or {},
        sorting=_get("sorting", default={}) or {},
        totals=_get("totals", default={}) or {},
        layout=_get("layout", default="tabular") or "tabular",
        selection=selection,
        limit=limit,
    )


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
    map describing a pivot row to delete.

    Returns a small dict with the matched/deleted counts and the new
    audit row id, ready to surface to the user as a success toast.
    """
    if not selections:
        raise SoftDeleteError("No pivot rows selected for deletion.")
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise SoftDeleteError("Dataset not found.")

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
        pivot_payload_json=json.dumps(
            pivot_request.model_dump(by_alias=True)
            if hasattr(pivot_request, "model_dump")
            else (pivot_request if isinstance(pivot_request, dict) else {}),
            default=str,
        ),
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
        existing = _existing_keys(db, dataset_id, sheet_name)
        new_keys: set = set()
        new_rows: List[Dict[str, Any]] = []
        total_matched = 0

        for sel in selections:
            try:
                req = _pivot_request_to_drilldown_request(pivot_request, sel)
                result = build_drilldown(db, req)
            except Exception as exc:
                # Continue with the next selection — a bad selection
                # shouldn't kill the whole delete.
                log_event(
                    "warning",
                    "Pivot row lookup failed during delete",
                    category="pivot_delete",
                    details=f"selection={sel}: {exc}",
                )
                continue

            total_matched += int(result.metadata.get("matched_rows") or 0)
            for row in result.rows:
                key = row_source_key(row)
                if key in existing or key in new_keys:
                    continue
                new_keys.add(key)
                new_rows.append(row)

        # Bulk-insert the new soft-delete rows.
        for row in new_rows:
            db.add(SoftDeletedRecord(
                dataset_id=dataset_id,
                sheet_name=sheet_name,
                source_key=row_source_key(row),
                row_payload=json.dumps(row, default=str)[:65000],
                pivot_request=audit.pivot_payload_json,
                deleted_at=datetime.utcnow(),
                deleted_by=actor,
                delete_audit_id=audit.id,
            ))

        audit.source_records_found   = total_matched
        audit.source_records_deleted = len(new_rows)
        audit.status = "success"
        db.commit()
        db.refresh(audit)

        # Invalidate the cache so the next pivot recomputes fresh.
        metadata_cache.invalidate_dataset(dataset_id)

        log_event(
            "info",
            "Pivot records delete completed",
            category="pivot_delete",
            details=f"audit_id={audit.id} matched={total_matched} "
                    f"deleted={len(new_rows)} actor={actor}",
        )

        return {
            "audit_id":     audit.id,
            "matched":      total_matched,
            "deleted":      len(new_rows),
            "selections":   len(selections),
        }
    except Exception as exc:
        audit.status = "failed"
        audit.error_message = str(exc)[:4000]
        db.commit()
        log_event(
            "error",
            "Pivot records delete failed",
            category="pivot_delete",
            details=f"audit_id={audit.id} error={exc}",
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
