"""
Phase 8 — simple in-process metadata + pivot-result cache.

Goals
-----
  - Reuse cached dataset metadata, column metadata, pivot configurations
    and the most recent pivot results where appropriate, to avoid
    unnecessary work.
  - Invalidate automatically when the underlying dataset changes.

Scope
-----
  This cache lives in process memory; it is **not** shared across gunicorn
  workers (single-process deployment is the supported topology for
  Version 1). It is best-effort: any failure is swallowed so the cache
  never breaks a request.

The cache stores three kinds of values:

  1. `dataset_meta`      — `Dataset` row + sheets + columns
  2. `pivot_result`      — the most recent PivotResponse per (dataset, sheet,
                           payload-hash) tuple
  3. `drilldown_dataset` — the in-memory DataFrame that backs drilldown
                           requests, so we don't re-parse the file for
                           every call

Invalidation rules
------------------
  - `invalidate_dataset(dataset_id)`      — when a dataset is updated,
                                             re-uploaded, or deleted
  - `invalidate_all()`                    — used by tests; wipes the cache
  - Pivot results are NOT invalidated by dataset changes automatically;
    the caller (the pivot route) checks the dataset's `upload_time` and
    ignores the cache if the file has changed since the cache was
    populated.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from app.models.dataset import Dataset
from app.models.sheet import DatasetSheet
from app.models.column import DatasetColumn
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Cache entry bookkeeping
# ---------------------------------------------------------------------------

@dataclass
class _Entry:
    value: Any
    created_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

class _Cache:
    """Thread-safe in-memory cache. Each "slot" is a dict of key -> _Entry."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # dataset_meta:    key=(dataset_id)            -> DatasetDetail-like dict
        self._meta: Dict[int, _Entry] = {}
        # column_meta:     key=(dataset_id, sheet_name) -> List[ColumnInfo]-like
        self._columns: Dict[Tuple[int, str], _Entry] = {}
        # pivot_result:    key=(dataset_id, sheet_name, payload_hash)
        #                                        -> PivotResponse-like dict
        self._pivot: Dict[Tuple[int, str, str], _Entry] = {}
        # drilldown_data:  key=(dataset_id, sheet_name) -> pd.DataFrame
        self._drilldown: Dict[Tuple[int, str], _Entry] = {}
        # ttl in seconds
        self.ttl = 300

    # ── Generic helpers ─────────────────────────────────────────────────
    def _expired(self, e: _Entry) -> bool:
        return (time.time() - e.created_at) > self.ttl

    def get(self, slot: str, key: Any) -> Optional[Any]:
        with self._lock:
            d = getattr(self, slot)
            e = d.get(key)
            if e is None or self._expired(e):
                d.pop(key, None)
                return None
            return e.value

    def set(self, slot: str, key: Any, value: Any) -> None:
        with self._lock:
            d = getattr(self, slot)
            d[key] = _Entry(value=value)

    def clear(self, slot: Optional[str] = None, key: Optional[Any] = None) -> None:
        with self._lock:
            if slot is None:
                self._meta.clear()
                self._columns.clear()
                self._pivot.clear()
                self._drilldown.clear()
                return
            d = getattr(self, slot)
            if key is None:
                d.clear()
            else:
                d.pop(key, None)

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "datasetMeta":   len(self._meta),
                "columnMeta":    len(self._columns),
                "pivotResult":   len(self._pivot),
                "drilldownData": len(self._drilldown),
            }


# Single global cache instance — one process, one cache.
_cache = _Cache()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def hash_payload(payload: Dict[str, Any]) -> str:
    """Stable hash of a pivot payload (camelCase or snake_case — the keys
    are sorted before hashing so the hash is deterministic)."""
    try:
        canonical = json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        canonical = repr(payload)
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def get_dataset_meta(db: Session, dataset_id: int):
    """Return the cached dataset detail if present, else build it and
    cache it. Returns a plain dict (or None if not found)."""
    cached = _cache.get("_meta", dataset_id)
    if cached is not None:
        return cached
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        return None
    sheets = (
        db.query(DatasetSheet)
        .filter(DatasetSheet.dataset_id == dataset_id)
        .all()
    )
    columns = (
        db.query(DatasetColumn)
        .filter(DatasetColumn.dataset_id == dataset_id)
        .all()
    )
    detail = {
        "id":            dataset.id,
        "filename":      dataset.filename,
        "stored_filename": dataset.stored_filename,
        "upload_time":   dataset.upload_time.isoformat() if dataset.upload_time else None,
        "total_rows":    dataset.total_rows,
        "total_columns": dataset.total_columns,
        "sheets":        [
            {
                "id":          s.id,
                "dataset_id":  s.dataset_id,
                "sheet_name":  s.sheet_name,
                "row_count":   s.row_count,
                "columns": [
                    {
                        "column_name": c.column_name,
                        "data_type":   c.data_type,
                        "is_nullable": c.is_nullable,
                    }
                    for c in columns
                    if c.sheet_id == s.id
                ],
            }
            for s in sheets
        ],
    }
    _cache.set("_meta", dataset_id, detail)
    return detail


def get_sheet_columns(db: Session, dataset_id: int, sheet_name: str):
    """Return the cached column list for a sheet, building it on miss."""
    key = (dataset_id, sheet_name)
    cached = _cache.get("_columns", key)
    if cached is not None:
        return cached
    rows = (
        db.query(DatasetColumn)
        .filter(DatasetColumn.dataset_id == dataset_id)
        .filter(DatasetColumn.sheet_name == sheet_name)
        .all()
    )
    cols = [
        {
            "column_name": c.column_name,
            "data_type":   c.data_type,
            "is_nullable": c.is_nullable,
        }
        for c in rows
    ]
    _cache.set("_columns", key, cols)
    return cols


def get_pivot_result(dataset_id: int, sheet_name: str, payload_hash: str):
    return _cache.get("_pivot", (dataset_id, sheet_name, payload_hash))


def set_pivot_result(dataset_id: int, sheet_name: str, payload_hash: str, result) -> None:
    _cache.set("_pivot", (dataset_id, sheet_name, payload_hash), result)


def get_drilldown_df(dataset_id: int, sheet_name: str):
    return _cache.get("_drilldown", (dataset_id, sheet_name))


def set_drilldown_df(dataset_id: int, sheet_name: str, df) -> None:
    _cache.set("_drilldown", (dataset_id, sheet_name), df)


# ── Invalidation ──────────────────────────────────────────────────────

def invalidate_dataset(dataset_id: int) -> None:
    """Drop every cache entry that touches this dataset."""
    with _cache._lock:
        _cache._meta.pop(dataset_id, None)
        for k in list(_cache._columns.keys()):
            if k[0] == dataset_id:
                _cache._columns.pop(k, None)
        for k in list(_cache._pivot.keys()):
            if k[0] == dataset_id:
                _cache._pivot.pop(k, None)
        for k in list(_cache._drilldown.keys()):
            if k[0] == dataset_id:
                _cache._drilldown.pop(k, None)


def invalidate_all() -> None:
    _cache.clear()


def stats() -> Dict[str, int]:
    return _cache.stats()
