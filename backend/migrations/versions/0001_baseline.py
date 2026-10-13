"""Baseline — the schema as it was before Alembic was introduced.

Databases created earlier by `Base.metadata.create_all()` already have
these tables; app.config.migrations stamps them at this revision instead
of re-creating anything.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("stored_filename", sa.String(), nullable=False, unique=True),
        sa.Column("upload_time", sa.DateTime()),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("total_columns", sa.Integer(), nullable=False),
    )
    op.create_index("ix_datasets_id", "datasets", ["id"])

    op.create_table(
        "dataset_sheets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sheet_name", sa.String(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_dataset_sheets_id", "dataset_sheets", ["id"])
    op.create_index("ix_dataset_sheets_dataset_id", "dataset_sheets", ["dataset_id"])

    op.create_table(
        "dataset_columns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sheet_name", sa.String(), nullable=False),
        sa.Column("column_name", sa.String(), nullable=False),
        sa.Column("data_type", sa.String(), nullable=False),
        sa.Column("is_nullable", sa.Boolean(), nullable=False),
        sa.Column("sheet_id", sa.Integer(), sa.ForeignKey("dataset_sheets.id", ondelete="CASCADE")),
    )
    op.create_index("ix_dataset_columns_id", "dataset_columns", ["id"])
    op.create_index("ix_dataset_columns_dataset_id", "dataset_columns", ["dataset_id"])

    op.create_table(
        "smtp_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password", sa.String(), nullable=False),
        sa.Column("use_tls", sa.Boolean(), nullable=False),
        sa.Column("sender_name", sa.String(), nullable=False),
        sa.Column("sender_email", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
    )

    op.create_table(
        "email_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("to_addresses_json", sa.Text(), nullable=False),
        sa.Column("cc_addresses_json", sa.Text(), nullable=False),
        sa.Column("bcc_addresses_json", sa.Text(), nullable=False),
        sa.Column("dataset_id", sa.Integer()),
        sa.Column("dataset_name", sa.String()),
        sa.Column("sheet_name", sa.String()),
        sa.Column("pivot_rows_count", sa.Integer(), nullable=False),
        sa.Column("attached_records_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("attachment_filename", sa.String()),
        sa.Column("attachment_path", sa.String()),
        sa.Column("pivot_payload_json", sa.Text()),
    )
    op.create_index("ix_email_history_id", "email_history", ["id"])
    op.create_index("ix_email_history_sent_at", "email_history", ["sent_at"])
    op.create_index("ix_email_history_status", "email_history", ["status"])

    op.create_table(
        "recent_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("recipient_type", sa.String(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("address", "recipient_type", name="uq_recent_recipient"),
    )
    op.create_index("ix_recent_recipients_id", "recent_recipients", ["id"])
    op.create_index("ix_recent_recipients_address", "recent_recipients", ["address"])

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_name", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("max_upload_bytes", sa.BigInteger(), nullable=False),
        sa.Column("default_export_dir", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
    )

    op.create_table(
        "app_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("details", sa.Text()),
        sa.Column("source", sa.String()),
        sa.Column("user_agent", sa.String()),
    )
    op.create_index("ix_app_log_id", "app_log", ["id"])
    op.create_index("ix_app_log_timestamp", "app_log", ["timestamp"])
    op.create_index("ix_app_log_timestamp_level", "app_log", ["timestamp", "level"])

    op.create_table(
        "soft_deleted_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("sheet_name", sa.String(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("row_payload", sa.Text()),
        sa.Column("pivot_request", sa.Text()),
        sa.Column("deleted_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_by", sa.String()),
        sa.Column("delete_audit_id", sa.Integer()),
    )
    op.create_index("ix_soft_deleted_records_id", "soft_deleted_records", ["id"])
    op.create_index("ix_soft_deleted_records_dataset_id", "soft_deleted_records", ["dataset_id"])
    op.create_index("ix_soft_deleted_records_source_key", "soft_deleted_records", ["source_key"])
    op.create_index("ix_soft_deleted_records_deleted_at", "soft_deleted_records", ["deleted_at"])
    op.create_index("ix_soft_deleted_records_delete_audit_id", "soft_deleted_records", ["delete_audit_id"])
    op.create_index("ix_soft_deleted_dataset_sheet", "soft_deleted_records", ["dataset_id", "sheet_name"])

    op.create_table(
        "delete_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("dataset_name", sa.String(), nullable=False),
        sa.Column("sheet_name", sa.String(), nullable=False),
        sa.Column("pivot_rows_count", sa.Integer(), nullable=False),
        sa.Column("source_records_found", sa.Integer(), nullable=False),
        sa.Column("source_records_deleted", sa.Integer(), nullable=False),
        sa.Column("selection_criteria", sa.Text()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("actor", sa.String()),
        sa.Column("pivot_payload_json", sa.Text()),
    )
    op.create_index("ix_delete_audit_id", "delete_audit", ["id"])
    op.create_index("ix_delete_audit_timestamp", "delete_audit", ["timestamp"])
    op.create_index("ix_delete_audit_dataset_id", "delete_audit", ["dataset_id"])

    op.create_table(
        "deleted_datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("original_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("stored_filename", sa.String(), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("total_columns", sa.Integer(), nullable=False),
        sa.Column("upload_time", sa.DateTime()),
        sa.Column("deleted_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_by", sa.String()),
    )
    op.create_index("ix_deleted_datasets_id", "deleted_datasets", ["id"])
    op.create_index("ix_deleted_datasets_original_id", "deleted_datasets", ["original_id"])
    op.create_index("ix_deleted_datasets_deleted_at", "deleted_datasets", ["deleted_at"])


def downgrade() -> None:
    for table in (
        "deleted_datasets", "delete_audit", "soft_deleted_records", "app_log",
        "app_settings", "recent_recipients", "email_history", "smtp_settings",
        "dataset_columns", "dataset_sheets", "datasets",
    ):
        op.drop_table(table)
