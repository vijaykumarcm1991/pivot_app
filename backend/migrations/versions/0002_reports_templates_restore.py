"""Saved pivots, scheduled reports, email templates, dataset refresh and
delete restore.

Revision ID: 0002_reports
Revises: 0001_baseline
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_reports"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_pivots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("sheet_name", sa.String(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_saved_pivots_id", "saved_pivots", ["id"])
    op.create_index("ix_saved_pivots_dataset_id", "saved_pivots", ["dataset_id"])

    op.create_table(
        "report_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("saved_pivot_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("frequency", sa.String(), nullable=False),
        sa.Column("run_time", sa.String(), nullable=False),
        sa.Column("weekdays", sa.String(), nullable=False),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("to_json", sa.Text(), nullable=False),
        sa.Column("cc_json", sa.Text(), nullable=False),
        sa.Column("bcc_json", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("skip_if_empty", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime()),
        sa.Column("last_run_at", sa.DateTime()),
        sa.Column("last_status", sa.String()),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_history_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_report_schedules_id", "report_schedules", ["id"])
    op.create_index("ix_report_schedules_saved_pivot_id", "report_schedules", ["saved_pivot_id"])
    op.create_index("ix_report_schedules_next_run_at", "report_schedules", ["next_run_at"])

    op.create_table(
        "email_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("to_text", sa.Text(), nullable=False),
        sa.Column("cc_text", sa.Text(), nullable=False),
        sa.Column("bcc_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_email_templates_id", "email_templates", ["id"])

    with op.batch_alter_table("datasets") as batch:
        batch.add_column(sa.Column("refreshed_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("delete_audit") as batch:
        batch.add_column(sa.Column("restored_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("email_history") as batch:
        batch.add_column(sa.Column("source", sa.String(), nullable=False, server_default="manual"))
        batch.add_column(sa.Column("schedule_id", sa.Integer(), nullable=True))
        batch.create_index("ix_email_history_schedule_id", ["schedule_id"])


def downgrade() -> None:
    with op.batch_alter_table("email_history") as batch:
        batch.drop_index("ix_email_history_schedule_id")
        batch.drop_column("schedule_id")
        batch.drop_column("source")
    with op.batch_alter_table("delete_audit") as batch:
        batch.drop_column("restored_at")
    with op.batch_alter_table("datasets") as batch:
        batch.drop_column("refreshed_at")
    op.drop_table("email_templates")
    op.drop_table("report_schedules")
    op.drop_table("saved_pivots")
