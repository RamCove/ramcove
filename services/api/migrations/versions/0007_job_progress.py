"""live progress for a running job

A worker reports where a stage is while it runs ("2,300 of 4,000 questions answered", "reading 1, run 2
at the champion's score +3%"). It is display only: nothing decides an outcome from it, so it is dropped
on the way down without loss.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("progress", JSONB(), nullable=True))
    op.add_column("jobs", sa.Column("progress_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "progress_at")
    op.drop_column("jobs", "progress")
