"""
File utility helpers: unique filename generation, extension validation.
"""

import uuid
import os
from pathlib import Path

from app.config.settings import ALLOWED_EXTENSIONS


def generate_stored_filename(original_filename: str) -> str:
    """
    Return a unique filename that preserves the original extension.
    Example: report.xlsx  →  3f2a1b...xlsx
    """
    ext = Path(original_filename).suffix.lower()
    return f"{uuid.uuid4().hex}{ext}"


def is_allowed_file(filename: str) -> bool:
    """Return True if the file extension is in ALLOWED_EXTENSIONS."""
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTENSIONS


def build_upload_path(stored_filename: str, upload_dir: str) -> str:
    """Return the full absolute path for a stored upload file."""
    return os.path.join(upload_dir, stored_filename)
