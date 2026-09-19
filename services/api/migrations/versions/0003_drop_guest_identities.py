"""drop guest identities: the public site is read-only and has no sign-in

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The keys held here were throwaway demo keys; dropping the table deletes them with it.
    op.drop_index("ix_guest_identities_created", table_name="guest_identities")
    op.drop_table("guest_identities")


def downgrade() -> None:
    op.create_table(
        "guest_identities",
        sa.Column("hotkey", sa.String(length=48), nullable=False),
        sa.Column("seed_hex", sa.String(length=66), nullable=False),
        sa.Column("client_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("hotkey", name=op.f("pk_guest_identities")),
    )
    op.create_index("ix_guest_identities_created", "guest_identities", ["created_at"], unique=False)
