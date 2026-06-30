"""
Pydantic schemas for dataset request / response.
"""

from datetime import datetime
from typing import List, Any, Dict, Optional
from pydantic import BaseModel


class DatasetBase(BaseModel):
    filename: str
    stored_filename: str
    total_rows: int
    total_columns: int


class DatasetCreate(DatasetBase):
    pass


class DatasetOut(DatasetBase):
    id: int
    upload_time: datetime

    model_config = {"from_attributes": True}


class SheetMeta(BaseModel):
    """Metadata for a single sheet in an Excel file."""
    sheet_name: str
    row_count: int
    column_names: List[str]


class UploadResponse(BaseModel):
    """Response returned after a successful file upload."""
    dataset_id: int
    filename: str
    stored_filename: str
    total_rows: int
    total_columns: int
    sheets: List[SheetMeta]
    preview: List[Dict[str, Any]]   # first N rows of the first sheet


# ---------------------------------------------------------------------------
# Phase 2 schemas
# ---------------------------------------------------------------------------

class ColumnInfo(BaseModel):
    """Inferred column metadata stored in dataset_columns."""
    column_name: str
    data_type: str          # string | integer | float | boolean | datetime
    is_nullable: bool

    model_config = {"from_attributes": True}


class SheetOut(BaseModel):
    """dataset_sheets row returned via API."""
    id: int
    dataset_id: int
    sheet_name: str
    row_count: int
    columns: List[ColumnInfo] = []

    model_config = {"from_attributes": True}


class DatasetDetail(BaseModel):
    """Full dataset detail including sheets and column metadata."""
    id: int
    filename: str
    stored_filename: str
    upload_time: datetime
    total_rows: int
    total_columns: int
    sheets: List[SheetOut]

    model_config = {"from_attributes": True}


class PreviewResponse(BaseModel):
    """Sheet data preview."""
    dataset_id: int
    sheet_name: str
    columns: List[ColumnInfo]
    rows: List[Dict[str, Any]]
