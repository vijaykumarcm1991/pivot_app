"""
Phase 8 — Pydantic schema for the application settings endpoint.
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AppSettingsOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    application_name: str   = Field(alias="applicationName")
    company_name:     str   = Field(alias="companyName")
    timezone:         str
    max_upload_bytes: int   = Field(alias="maxUploadBytes")
    default_export_dir: str = Field(alias="defaultExportDir")
    version:          str
    updated_at:       Optional[str] = Field(default=None, alias="updatedAt")


class AppSettingsIn(BaseModel):
    """Inbound payload — all fields optional so a partial save works."""
    model_config = ConfigDict(populate_by_name=True)

    application_name: Optional[str] = Field(default=None, alias="applicationName")
    company_name:     Optional[str] = Field(default=None, alias="companyName")
    timezone:         Optional[str] = None
    max_upload_bytes: Optional[int] = Field(default=None, alias="maxUploadBytes")
    default_export_dir: Optional[str] = Field(default=None, alias="defaultExportDir")
