"""Add OCR mode and persisted extraction results without replacing existing tables."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "jobs", sa.Column("ocr_mode", sa.String(16), nullable=False, server_default="auto")
    )
    op.create_table(
        "job_results",
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    raise RuntimeError("Dropping extraction results requires an explicit data migration.")
