"""free submissions: no fee, quotes, payments, receipts, credits, refunds or fee ledger

Submitting is free. A submission that passes the free checks joins the queue when evaluation capacity is
free, and its admission key is the finalized block at admission and its order within that block. The fee
tables, the TAO price observations and the per-submission fee outcome go, and so do the "quoted" and
"expired_quote" states: a quoted submission returns to "preflight_passed" (it can now join the queue for
free) and an expired quote closes as "withdrawn".

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TERMINAL = (
    "promoted",
    "not_promoted",
    "rejected_preflight",
    "rejected_screen",
    "review_rejected",
    "expired_unregistered",
    "operator_failed",
    "withdrawn",
)
TERMINAL_BEFORE = (*TERMINAL[:5], "expired_quote", *TERMINAL[5:])
ACTIVE_INDEXES = (("uq_one_active_per_hotkey", "hotkey"), ("uq_one_active_per_lineage", "lineage"))


def _not_terminal(states: tuple[str, ...]) -> sa.TextClause:
    return sa.text("state NOT IN (" + ",".join(f"'{s}'" for s in states) + ")")


def _active_indexes(states: tuple[str, ...]) -> None:
    for name, column in ACTIVE_INDEXES:
        op.drop_index(name, table_name="submissions")
        op.create_index(
            name, "submissions", ["profile_id", column], unique=True, postgresql_where=_not_terminal(states)
        )


def upgrade() -> None:
    op.execute("UPDATE submissions SET state = 'preflight_passed', reserved_centi = 0 WHERE state = 'quoted'")
    op.execute("UPDATE submissions SET state = 'withdrawn' WHERE state = 'expired_quote'")
    _active_indexes(TERMINAL)
    op.drop_column("submissions", "fee_outcome")
    for table in ("receipts", "payments", "quotes", "refunds", "credits", "ledger", "price_observations"):
        op.drop_table(table)


def downgrade() -> None:
    # the tables come back empty and as they stood after 0007; nothing that was free is charged afterwards
    op.add_column("submissions", sa.Column("fee_outcome", sa.String(length=40), nullable=True))
    _active_indexes(TERMINAL_BEFORE)
    op.create_table(
        "price_observations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=60), nullable=False),
        sa.Column("usd_micros", sa.BigInteger(), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_observations")),
    )
    op.create_table(
        "ledger",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("hotkey", sa.String(length=48), nullable=True),
        sa.Column("submission_id", sa.String(length=40), nullable=True),
        sa.Column("amount_rao", sa.BigInteger(), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('fee_received','fee_consumed','fee_excess_credit','credit_issued','credit_used',"
            "'credit_expired','refund_liability','refund_sent','refund_confirmed')",
            name=op.f("ck_ledger_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_ledger_idempotency_key")),
    )
    op.create_table(
        "credits",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("hotkey", sa.String(length=48), nullable=False),
        sa.Column("amount_rao", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_submission", sa.String(length=40), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("consumed_by", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_rao > 0", name=op.f("ck_credits_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credits")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_credits_idempotency_key")),
    )
    op.create_table(
        "refunds",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("hotkey", sa.String(length=48), nullable=False),
        sa.Column("payer", sa.String(length=48), nullable=False),
        sa.Column("amount_rao", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("submission_id", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=12), server_default=sa.text("'requested'"), nullable=False),
        sa.Column("approved_by", sa.String(length=48), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("tx_reference", sa.String(length=120), nullable=True),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('requested','approved','sent','confirmed','cancelled')",
            name=op.f("ck_refunds_status"),
        ),
        sa.CheckConstraint("amount_rao > 0", name=op.f("ck_refunds_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refunds")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_refunds_idempotency_key")),
    )
    op.create_table(
        "quotes",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("submission_id", sa.String(length=40), nullable=False),
        sa.Column("network", sa.String(length=40), nullable=False),
        sa.Column("hotkey", sa.String(length=48), nullable=False),
        sa.Column("payer", sa.String(length=48), nullable=False),
        sa.Column("recipient", sa.String(length=48), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("rule_hash", sa.String(length=64), nullable=False),
        sa.Column("amount_rao", sa.BigInteger(), nullable=False),
        sa.Column("issued_block", sa.BigInteger(), nullable=False),
        sa.Column("expires_block", sa.BigInteger(), nullable=False),
        sa.Column("price_usd_micros", sa.BigInteger(), nullable=True),
        sa.Column("price_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price_simulated", sa.Boolean(), nullable=True),
        sa.Column("fee_usd_cents", sa.Integer(), nullable=True),
        sa.Column("service_cost_usd_cents", sa.Integer(), nullable=False),
        sa.Column("reserved_centi", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'open'"), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('open','paid','expired','withdrawn')", name=op.f("ck_quotes_status")),
        sa.CheckConstraint("amount_rao > 0", name=op.f("ck_quotes_amount_positive")),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["submissions.id"], name=op.f("fk_quotes_submission_id_submissions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quotes")),
    )
    op.create_index(
        "uq_quote_open_per_submission",
        "quotes",
        ["submission_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('open','paid')"),
    )
    op.create_table(
        "payments",
        sa.Column("block_hash", sa.String(length=66), nullable=False),
        sa.Column("extrinsic_index", sa.Integer(), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("network", sa.String(length=40), nullable=False),
        sa.Column("quote_id", sa.String(length=40), nullable=True),
        sa.Column("payer", sa.String(length=48), nullable=True),
        sa.Column("paid_rao", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("excess_rao", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], name=op.f("fk_payments_quote_id_quotes")),
        sa.PrimaryKeyConstraint("block_hash", "extrinsic_index", name=op.f("pk_payments")),
    )
    op.create_index(
        "uq_payment_consumes_quote_once",
        "payments",
        ["quote_id"],
        unique=True,
        postgresql_where=sa.text("outcome = 'verified'"),
    )
    op.create_table(
        "receipts",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("submission_id", sa.String(length=40), nullable=False),
        sa.Column("quote_id", sa.String(length=40), nullable=False),
        sa.Column("payment_block_hash", sa.String(length=66), nullable=False),
        sa.Column("payment_extrinsic_index", sa.Integer(), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("signer", sa.String(length=48), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], name=op.f("fk_receipts_quote_id_quotes")),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["submissions.id"], name=op.f("fk_receipts_submission_id_submissions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receipts")),
        sa.UniqueConstraint("payment_block_hash", "payment_extrinsic_index", name="payment_ref"),
        sa.UniqueConstraint("quote_id", name=op.f("uq_receipts_quote_id")),
        sa.UniqueConstraint("submission_id", name=op.f("uq_receipts_submission_id")),
    )
