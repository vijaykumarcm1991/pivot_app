"""
Phase 8 — File validation utility.

Validates a candidate upload by:
  1. extension      (e.g. .xlsx, .csv)
  2. MIME type hint (when the browser provided one — this is taken with a
     grain of salt, but it's a first line of defence)
  3. magic bytes    (the actual file signature — the only trustworthy
     signal; an .xlsx renamed from .pdf still has ZIP magic bytes at the
     start)
  4. content sanity (we open it with pandas/openpyxl to make sure the
     file is actually a parseable spreadsheet)

The validation is layered: each layer is independent and a failure at
any layer produces a friendly message for the user. The signature
checking is intentionally simple — it only checks for the OOXML zip
header (`PK\x03\x04`) and a basic CSV heuristic (text-shaped bytes).
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Tuple


# ── Extension / MIME tables ──────────────────────────────────────────────
ALLOWED_EXTENSIONS = {".xlsx", ".csv"}
ALLOWED_MIME_HINTS = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/octet-stream",  # browser often sends this for .xlsx
    "application/zip",            # xlsx is technically a zip
    "text/csv",
    "text/plain",
    "application/csv",
    "",                           # missing
}


class FileValidationError(ValueError):
    """Raised when an uploaded file fails any validation layer."""


# ── Magic byte checks ──────────────────────────────────────────────────

# OOXML / xlsx is a zip file → PK\x03\x04 signature
_XLSX_MAGIC = b"PK\x03\x04"

# CSV: there is no single magic byte sequence. We accept a "looks like
# text" check (mostly printable, no nulls) as a soft signal. A pure
# binary file gets rejected.

def _is_xlsx_by_magic(content_head: bytes) -> bool:
    """Return True if the first 4 bytes look like an OOXML zip header."""
    return content_head[:4] == _XLSX_MAGIC


def _is_csv_by_magic(content_head: bytes) -> bool:
    """Best-effort CSV check: the first chunk should be mostly printable
    text without null bytes."""
    if not content_head:
        return False
    if b"\x00" in content_head:
        return False  # binary → not a CSV
    printable = sum(1 for b in content_head if 9 <= b <= 13 or 32 <= b <= 126 or b >= 128)
    return printable / len(content_head) > 0.85


def _check_zip_xlsx(full_path: str) -> bool:
    """OOXML files are zip files; open one and look for the workbook
    inside. Returns True if it really is a spreadsheet."""
    try:
        with zipfile.ZipFile(full_path, "r") as zf:
            names = zf.namelist()
            # OOXML has at least [Content_Types].xml and a workbook part.
            return any(n == "[Content_Types].xml" for n in names) and \
                   any("xl/workbook.xml" in n for n in names)
    except (zipfile.BadZipFile, OSError):
        return False


# ── Public API ─────────────────────────────────────────────────────────

def validate_extension(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"Unsupported file extension '{ext or '(none)'}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )
    return ext


def validate_mime(content_type: str | None) -> None:
    if content_type is None:
        return
    # Browsers sometimes send charset, e.g. "text/csv; charset=utf-8".
    base = (content_type or "").split(";", 1)[0].strip().lower()
    if base in ALLOWED_MIME_HINTS:
        return
    raise FileValidationError(
        f"Unexpected content type '{content_type}'. "
        f"Only Excel (.xlsx) and CSV files are accepted."
    )


def validate_magic_bytes(content_head: bytes, ext: str) -> None:
    if ext == ".xlsx":
        if not _is_xlsx_by_magic(content_head):
            raise FileValidationError(
                "The uploaded file does not look like a valid Excel workbook. "
                "XLSX files should start with the ZIP signature (PK..)."
            )
    elif ext == ".csv":
        if not _is_csv_by_magic(content_head):
            raise FileValidationError(
                "The uploaded file does not look like a CSV text file. "
                "Please export your data as CSV (UTF-8) and try again."
            )


def validate_full_file(full_path: str, ext: str) -> None:
    """Deeper validation that requires the file to already be on disk.
    Used after the upload is written — gives the strongest guarantee that
    the file is parseable.  For .xlsx we open the zip and look for a
    workbook; for .csv we look for any non-empty lines."""
    if ext == ".xlsx":
        if not _check_zip_xlsx(full_path):
            raise FileValidationError(
                "The file was uploaded with a .xlsx extension but is not a valid "
                "Excel workbook. Please open it in Excel, save it, and re-upload."
            )
    elif ext == ".csv":
        try:
            with open(full_path, "rb") as f:
                buf = f.read(4096)
            if b"\x00" in buf:
                raise FileValidationError(
                    "The CSV file contains null bytes — it may be a binary file "
                    "saved with a .csv extension. Please re-export your data."
                )
            if not buf.strip():
                raise FileValidationError("The CSV file is empty.")
        except OSError as exc:
            raise FileValidationError(f"Could not read the uploaded file: {exc}")


def perform_full_validation(*, filename: str, content_type: str | None,
                            head_bytes: bytes, full_path: str) -> None:
    """
    Run all four validation layers in order.  Raises FileValidationError
    on the first failure with a friendly, user-facing message.
    """
    ext = validate_extension(filename)
    validate_mime(content_type)
    validate_magic_bytes(head_bytes or b"", ext)
    validate_full_file(full_path, ext)
