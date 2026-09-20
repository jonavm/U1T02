"""Create the ingestion baseline or adopt the compatible existing phase 2 tables."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("jobs"):
        required = {
            "id",
            "original_filename",
            "storage_key",
            "detected_type",
            "size_bytes",
            "sha256",
            "ocr_language",
            "status",
            "stage",
            "attempts",
            "created_at",
            "updated_at",
            "error_code",
            "error_message",
        }
        if not required.issubset({c["name"] for c in inspector.get_columns("jobs")}):
            raise RuntimeError("Existing jobs table does not match the phase 2 baseline.")
    else:
        op.create_table(
            "jobs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("original_filename", sa.String(255), nullable=False),
            sa.Column("storage_key", sa.String(64), nullable=False, unique=True),
            sa.Column("detected_type", sa.String(80), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("ocr_language", sa.String(16), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("stage", sa.String(40), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("error_code", sa.String(64)),
            sa.Column("error_message", sa.String(500)),
        )
        op.create_index("ix_jobs_status", "jobs", ["status"])
    if inspector.has_table("job_dispatches"):
        if not {"job_id", "status", "available_at"}.issubset(
            {c["name"] for c in inspector.get_columns("job_dispatches")}
        ):
            raise RuntimeError("Existing dispatch table does not match the phase 2 baseline.")
    else:
        op.create_table(
            "job_dispatches",
            sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), primary_key=True),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_job_dispatches_status", "job_dispatches", ["status"])


def downgrade():
    raise RuntimeError("Destructive baseline downgrade is intentionally unsupported.")
