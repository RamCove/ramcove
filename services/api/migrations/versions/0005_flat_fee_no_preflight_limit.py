"""flat fee and no daily preflight limit

The evaluation fee is a flat amount of TAO, so a quote no longer needs a price: the price columns become
optional (kept for the US-dollar display) and the fee target goes. The only preflight limit is one active
submission per hotkey, so the rate-limit counters go.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("quotes", "target_usd_cents")
    for name, kind in (
        ("price_usd_micros", sa.BigInteger()),
        ("price_observed_at", sa.DateTime(timezone=True)),
        ("price_simulated", sa.Boolean()),
        ("fee_usd_cents", sa.Integer()),
    ):
        op.alter_column("quotes", name, existing_type=kind, nullable=True)
    op.drop_table("rate_counters")


def downgrade() -> None:
    op.create_table(
        "rate_counters",
        sa.Column("bucket", sa.String(length=160), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("bucket", name=op.f("pk_rate_counters")),
    )
    # quotes issued without a price cannot satisfy the old constraints; they get zero values
    op.execute("UPDATE quotes SET price_usd_micros = 0 WHERE price_usd_micros IS NULL")
    op.execute("UPDATE quotes SET price_observed_at = issued_at WHERE price_observed_at IS NULL")
    op.execute("UPDATE quotes SET price_simulated = true WHERE price_simulated IS NULL")
    op.execute("UPDATE quotes SET fee_usd_cents = 0 WHERE fee_usd_cents IS NULL")
    for name, kind in (
        ("price_usd_micros", sa.BigInteger()),
        ("price_observed_at", sa.DateTime(timezone=True)),
        ("price_simulated", sa.Boolean()),
        ("fee_usd_cents", sa.Integer()),
    ):
        op.alter_column("quotes", name, existing_type=kind, nullable=False)
    op.add_column(
        "quotes", sa.Column("target_usd_cents", sa.Integer(), server_default=sa.text("0"), nullable=False)
    )
