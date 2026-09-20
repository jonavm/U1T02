"""Persist execution ownership, deadlines, and delayed retry eligibility."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("attempt_token", sa.Uuid(), nullable=True))
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    raise RuntimeError("Recovery ownership must not be removed from active jobs.")
