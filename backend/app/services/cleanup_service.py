"""
Phase 8 — Cleanup utility.

A small admin tool to free up disk space and prune old data. Every
operation is independent and idempotent; the admin can pick exactly
which categories to clean.

Categories
----------

  - `temp_exports`    — delete one-shot preview attachments in
                        `generated_reports/email_previews/` older than N days
  - `drilldown_files` — alias for `temp_exports` for backwards
                        compatibility (Phase 5's drilldown modal also
                        stashed files there)
  - `old_uploads`     — delete uploads that have been removed from the
                        `datasets` table (e.g. orphaned files), AND
                        (optionally) any upload older than N days that
                        the user explicitly opts in to remove
  - `old_logs`        — delete rotated log backups in `logs/`
                        older than N days
  - `cached_files`    — currently the AG Grid / SheetJS uses CDN, so
                        this category is a no-op placeholder. We keep
                        the UI slot so future caches can land here
                        without redesigning the page.

Disk accounting
---------------
The service computes the size of every file it is about to delete and
returns it to the UI so the admin can see how much space they will
recover before clicking "Clean now".
"""
from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.config.settings import LOG_DIR, REPORTS_DIR, UPLOAD_DIR
from app.repositories.dataset_repository import get_all_datasets
from app.services.app_logging import log_event


@dataclass
class CleanupTarget:
    """A description of one cleanup bucket the admin can opt into."""
    key: str
    label: str
    description: str
    file_count: int
    total_bytes: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key":         self.key,
            "label":       self.label,
            "description": self.description,
            "fileCount":   self.file_count,
            "totalBytes":  int(self.total_bytes),
            "totalMb":     round(self.total_bytes / (1024 * 1024), 2),
        }


def _list_files_in_dir(root: str, *, older_than_days: Optional[int] = None) -> List[str]:
    if not os.path.isdir(root):
        return []
    cutoff = None
    if older_than_days is not None:
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    out: List[str] = []
    for r, _dirs, files in os.walk(root):
        for fn in files:
            full = os.path.join(r, fn)
            try:
                if cutoff is not None:
                    mtime = datetime.utcfromtimestamp(os.path.getmtime(full))
                    if mtime > cutoff:
                        continue
                out.append(full)
            except OSError:
                continue
    return out


def _size_of(paths: List[str]) -> int:
    total = 0
    for p in paths:
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return total


def _orphaned_uploads(db: Session) -> List[str]:
    """Files in UPLOAD_DIR that no longer have a `datasets` row."""
    if not os.path.isdir(UPLOAD_DIR):
        return []
    valid: set = set()
    if db is not None:
        try:
            for d in get_all_datasets(db):
                if d and d.stored_filename:
                    valid.add(d.stored_filename)
        except Exception:
            pass
    out: List[str] = []
    for fn in os.listdir(UPLOAD_DIR):
        full = os.path.join(UPLOAD_DIR, fn)
        if os.path.isfile(full) and fn not in valid:
            out.append(full)
    return out


# ── Public API ─────────────────────────────────────────────────────────

def preview_cleanup(*, older_than_days: int = 7, db: Session | None = None) -> List[CleanupTarget]:
    """Return a list of cleanup targets with the current count + size.
    The admin sees this list in the UI before clicking 'Clean now'.

    `db` is optional — the orphaned-uploads lookup is skipped when not
    provided, so a unit test or a CLI call can still use the helper
    without standing up a database session.
    """
    targets: List[CleanupTarget] = []

    # 1. temp_exports — one-shot preview attachments
    preview_dir = os.path.join(REPORTS_DIR, "email_previews")
    files = _list_files_in_dir(preview_dir, older_than_days=older_than_days)
    targets.append(CleanupTarget(
        key="temp_exports",
        label="Temporary email previews",
        description=f"One-shot preview attachments older than {older_than_days} day(s).",
        file_count=len(files),
        total_bytes=_size_of(files),
    ))

    # 2. drilldown_files — same as above (legacy alias)
    targets.append(CleanupTarget(
        key="drilldown_files",
        label="Temporary drill-down files",
        description=f"Alias of temp_exports ({len(files)} file(s)).",
        file_count=len(files),
        total_bytes=_size_of(files),
    ))

    # 3. old_uploads — orphaned files in UPLOAD_DIR
    if db is not None:
        orphans = _orphaned_uploads(db)
    else:
        orphans = []
    targets.append(CleanupTarget(
        key="old_uploads",
        label="Orphaned uploaded files",
        description="Files in the upload directory that no longer have a matching dataset row.",
        file_count=len(orphans),
        total_bytes=_size_of(orphans),
    ))

    # 4. old_logs — rotated log backups
    log_files = [
        f for f in _list_files_in_dir(LOG_DIR, older_than_days=older_than_days)
        if os.path.basename(f) != "pivot_app.log"
    ]
    targets.append(CleanupTarget(
        key="old_logs",
        label="Old log files",
        description=f"Rotated log backups older than {older_than_days} day(s).",
        file_count=len(log_files),
        total_bytes=_size_of(log_files),
    ))

    # 5. cached_files — placeholder
    targets.append(CleanupTarget(
        key="cached_files",
        label="Cached files",
        description="Currently unused (the application uses CDN + SQLite for caching).",
        file_count=0,
        total_bytes=0,
    ))

    return targets


def run_cleanup(
    *,
    keys: List[str],
    older_than_days: int = 7,
    actor: str = "admin",
    db: Session | None = None,
) -> Dict[str, Any]:
    """Actually delete the files for the given keys. Returns a summary
    that the UI can render after the operation completes."""
    results: Dict[str, Any] = {"deleted": {}, "freedBytes": 0, "freedMb": 0.0}
    targets_map = {t.key: t for t in preview_cleanup(older_than_days=older_than_days, db=db)}

    for key in keys:
        target = targets_map.get(key)
        if not target:
            continue
        # Re-evaluate at run time (in case files were added/removed
        # between preview and run).
        if key in ("temp_exports", "drilldown_files"):
            preview_dir = os.path.join(REPORTS_DIR, "email_previews")
            paths = _list_files_in_dir(preview_dir, older_than_days=older_than_days)
        elif key == "old_uploads":
            paths = _orphaned_uploads(db) if db is not None else []
        elif key == "old_logs":
            paths = [
                f for f in _list_files_in_dir(LOG_DIR, older_than_days=older_than_days)
                if os.path.basename(f) != "pivot_app.log"
            ]
        else:
            paths = []

        deleted = 0
        freed = 0
        for p in paths:
            try:
                size = os.path.getsize(p)
                os.remove(p)
                deleted += 1
                freed += size
            except OSError as exc:
                log_event(
                    "warning",
                    "Cleanup file remove failed",
                    category="cleanup",
                    details=f"{p}: {exc}",
                )
        results["deleted"][key] = {
            "filesDeleted": deleted,
            "bytesFreed":   int(freed),
        }
        results["freedBytes"] += int(freed)
        log_event(
            "info",
            "Cleanup operation completed",
            category="cleanup",
            details=f"key={key} actor={actor} files={deleted} bytes={freed}",
        )

    results["freedMb"] = round(results["freedBytes"] / (1024 * 1024), 2)
    return results
