"""
App settings service — singleton row, plus cached access for the
runtime-configurable values (max upload size, app name, ...).

The service wraps the repository and provides a single `get_runtime_settings()`
function that callers can use to fetch the most important values without
going through the Pydantic model. Caching is intentionally not done
here — the row is tiny and the callers (upload route, navbar, email
service) are infrequent. Caching is the responsibility of the
`metadata_cache` module (Phase 8 — see `services/metadata_cache.py`).
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.repositories import app_settings_repository as repo
from app.models.app_settings import APP_VERSION
from app.utils.tz import iso_ist


def get_settings(db: Session):
    return repo.get_or_create_settings(db)


def update_settings(db: Session, **fields):
    return repo.upsert_settings(db, **fields)


def to_dict(db: Session) -> Dict[str, Any]:
    row = repo.get_or_create_settings(db)
    return {
        "applicationName":   row.application_name or "Pivot App",
        "companyName":       row.company_name or "",
        "timezone":          row.timezone or "Asia/Kolkata",
        "maxUploadBytes":    int(row.max_upload_bytes or 0),
        "defaultExportDir":  row.default_export_dir or "",
        "version":           APP_VERSION,
        "updatedAt":         row.updated_at.isoformat() if row.updated_at else None,
        # IST-formatted timestamp for display in the UI.
        "updatedAtIst":      iso_ist(row.updated_at),
    }


def update_from_payload(db: Session, payload: Dict[str, Any]):
    """Apply the validated payload. Returns the updated row."""
    fields = {}
    if "applicationName" in payload:
        fields["application_name"] = (payload.get("applicationName") or "").strip() or "Pivot App"
    if "companyName" in payload:
        fields["company_name"] = (payload.get("companyName") or "").strip()
    if "timezone" in payload:
        # Default to Asia/Kolkata (IST) — the user asked for IST
        # everywhere. The Settings page still allows the user to
        # override this at runtime.
        fields["timezone"] = (payload.get("timezone") or "Asia/Kolkata").strip() or "Asia/Kolkata"
    if "maxUploadBytes" in payload:
        try:
            v = int(payload.get("maxUploadBytes") or 0)
        except (TypeError, ValueError):
            v = 0
        if v < 1024 * 1024:  # minimum 1 MB
            v = 1024 * 1024
        if v > 2 * 1024 * 1024 * 1024:  # cap at 2 GB
            v = 2 * 1024 * 1024 * 1024
        fields["max_upload_bytes"] = v
    if "defaultExportDir" in payload:
        fields["default_export_dir"] = (payload.get("defaultExportDir") or "").strip()
    if not fields:
        return repo.get_or_create_settings(db)
    return repo.upsert_settings(db, **fields)
