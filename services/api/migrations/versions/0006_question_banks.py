"""question banks: the owner's secret questions, one bank per period

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_banks",
        sa.Column("bank_id", sa.String(length=160), nullable=False),
        sa.Column("profile_id", sa.String(length=120), nullable=False),
        sa.Column("period_index", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("commitment", sa.String(length=64), nullable=False),
        sa.Column("revealed_seed", sa.String(length=64), nullable=True),
        sa.Column(
            "committed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("bank_id", name=op.f("pk_question_banks")),
        sa.UniqueConstraint("profile_id", "period_index", name="profile_period"),
    )


def downgrade() -> None:
    op.drop_table("question_banks")
