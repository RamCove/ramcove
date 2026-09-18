"""guest identities for the public demo

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guest_identities",
        sa.Column("hotkey", sa.String(length=48), nullable=False),
        sa.Column("seed_hex", sa.String(length=66), nullable=False),
        sa.Column("client_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("hotkey", name=op.f("pk_guest_identities")),
    )
    op.create_index("ix_guest_identities_created", "guest_identities", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_guest_identities_created", table_name="guest_identities")
    op.drop_table("guest_identities")
