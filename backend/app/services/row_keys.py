"""
Phase 8 — shared source-key computation for the soft-delete table.

Why a shared helper
-------------------
The soft-delete service (`soft_delete_service.soft_delete_from_pivot`)
inserts a `source_key` per deleted row computed from the row's
key/value dict. The pivot engine's `_load_dataset_sheet` reads the
same rows back from the source CSV and computes a matching key
to decide which rows to skip. The two MUST agree.

Before this helper existed, the two implementations drifted:
  - the soft-delete service used `json.dumps(..., default=str)` on the
    drilldown response, where empty cells come back as Python `None`
  - the pivot engine re-read the CSV with pandas, where empty cells
    become `NaN` (float)
  - `json.dumps(None, default=str)` = `null`, but
    `json.dumps(float('nan'), default=str)` = `NaN`
  - so the hashes never matched and soft-deleted records silently
    re-appeared in the next pivot.

The fix: a single function used by both the writer and the reader
that normalises every value to the same JSON-safe string before
hashing, so the hashes match across the two paths regardless of
whether the value came from a JSON `null` or a pandas `NaN`.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from typing import Any, Dict


def _normalise(v: Any) -> Any:
    """
    Coerce every value to a JSON-safe canonical form so that the
    hash of a row read from the source CSV equals the hash of the
    same row's drilldown response (or pivot metadata).

    Rules:
      - `None`, `""`, `float('nan')`, `pandas.NA` (when stringified
        to 'nan'), `pandas.NaT` → all become `None`
      - `datetime` / `date` / `pandas.Timestamp` → ISO string
      - everything else → the value as-is (json.dumps with default=str
        will stringify anything weird)
    """
    if v is None:
        return None
    # `math.nan` is a `float` and is the canonical "not a number" sentry.
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v)
    if s == "nan" or s == "NaT" or s == "NaN" or s == "<NA>":
        return None
    if s == "":
        return None
    # datetimes — check class name to avoid the pandas import in this hot path
    cls = v.__class__.__name__
    if cls in ("Timestamp", "datetime", "date"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    return v


def row_source_key(row: Dict[str, Any]) -> str:
    """
    Stable per-row signature. Returns a hex digest.

    Pass the row as a plain Python dict (e.g. a row from the drilldown
    response, or `dict(series.iteritems())` for a pandas row). The
    function normalises every value so the hash is stable across
    JSON `null` ↔ pandas `NaN` ↔ empty string.

    Only the values are normalised; the **keys** are taken as-is
    from the dict (this is the same behaviour the soft-delete
    service had before, so a CSV column rename between upload and
    delete would still produce a different hash — which is the
    correct behaviour, the user has changed the data).
    """
    try:
        canonical = json.dumps(
            {k: _normalise(v) for k, v in row.items()},
            sort_keys=True, default=str,
        )
    except Exception:
        # Last-ditch fallback: stringify the whole row.
        canonical = repr(sorted(((k, str(v)) for k, v in row.items())))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
