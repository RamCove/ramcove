"""Authoritative relational schema (SQLAlchemy Core). Migrations live in services/api/migrations.

Money is BIGINT rao. Times are timestamptz (UTC). Hashes are lowercase hex text.
Uniqueness and partial indexes enforce protocol invariants even under concurrent requests.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

NOW = text("now()")
TERMINAL_STATES = (
    "promoted",
    "not_promoted",
    "rejected_preflight",
    "rejected_screen",
    "review_rejected",
    "expired_quote",
    "expired_unregistered",
    "operator_failed",
    "withdrawn",
)
_TERMINAL_SQL = "state NOT IN (" + ",".join(f"'{s}'" for s in TERMINAL_STATES) + ")"


def ts(name: str, nullable: bool = True, default: bool = False) -> Column:
    return Column(name, DateTime(timezone=True), nullable=nullable, server_default=NOW if default else None)


profile_versions = Table(
    "profile_versions",
    metadata,
    Column("profile_id", String(120), nullable=False),
    Column("version", String(40), nullable=False),
    Column("rule_hash", String(64), nullable=False, unique=True),
    Column("body", JSONB, nullable=False),
    Column("active", Boolean, nullable=False, server_default=text("false")),
    ts("published_at", False, True),
    PrimaryKeyConstraint("profile_id", "version"),
)
Index("uq_profile_one_active", profile_versions.c.profile_id, unique=True, postgresql_where=text("active"))

identities = Table(
    "identities",
    metadata,
    Column("hotkey", String(48), primary_key=True),
    Column("display_name", String(80)),
    Column("demo", Boolean, nullable=False, server_default=text("false")),
    ts("created_at", False, True),
)

role_grants = Table(
    "role_grants",
    metadata,
    Column("hotkey", String(48), ForeignKey("identities.hotkey"), nullable=False),
    Column("role", String(20), nullable=False),
    Column("granted_by", String(48)),
    Column("independent_group", String(80)),
    ts("created_at", False, True),
    PrimaryKeyConstraint("hotkey", "role"),
    CheckConstraint("role IN ('miner','validator','reviewer','operator','appeal_panel')", name="role"),
)

auth_challenges = Table(
    "auth_challenges",
    metadata,
    Column("nonce", String(64), primary_key=True),
    Column("hotkey", String(48), nullable=False),
    Column("domain", String(200), nullable=False),
    Column("network", String(40), nullable=False),
    Column("genesis_hash", String(66), nullable=False),
    ts("issued_at", False),
    ts("expires_at", False),
    ts("used_at"),
)

sessions = Table(
    "sessions",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("hotkey", String(48), ForeignKey("identities.hotkey"), nullable=False),
    Column("demo", Boolean, nullable=False, server_default=text("false")),
    ts("created_at", False, True),
    ts("expires_at", False),
    ts("revoked_at"),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("sha256", String(64), primary_key=True),
    Column("normalized_patch_sha256", String(64), nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("storage_key", Text, nullable=False),
    Column("uploader", String(48), nullable=False),
    Column("manifest", JSONB, nullable=False),
    Column("changed_paths", JSONB, nullable=False),
    Column("trusted_fixture", String(80)),
    ts("created_at", False, True),
)
Index("ix_artifacts_normalized", artifacts.c.normalized_patch_sha256)

submissions = Table(
    "submissions",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("profile_id", String(120), nullable=False),
    Column("profile_version", String(40), nullable=False),
    Column("rule_hash", String(64), nullable=False),
    Column("hotkey", String(48), nullable=False),
    Column("lineage", String(64), nullable=False),
    Column("artifact_sha256", String(64), ForeignKey("artifacts.sha256"), nullable=False),
    Column("state", String(32), nullable=False),
    Column("waitlisted_at", DateTime(timezone=True)),
    Column("invited_until", DateTime(timezone=True)),
    Column("admission_block", BigInteger),
    Column("admission_index", Integer),
    Column("admitted_at", DateTime(timezone=True)),
    Column("quorum_reschedules", Integer, nullable=False, server_default=text("0")),
    Column("compared_champion_version", Integer),
    Column("compared_rule_hash", String(64)),
    Column("first_gain_ppm", Integer),
    Column("bound_gain_ppm", Integer),
    Column("reserved_centi", Integer, nullable=False, server_default=text("0")),
    Column("ready_since", DateTime(timezone=True)),
    Column("fee_outcome", String(40)),
    Column("outcome_code", String(60)),
    Column("outcome_summary", Text),
    Column("support_ref", String(24), nullable=False),
    Column("scenario", String(60)),
    Column("row_version", Integer, nullable=False, server_default=text("1")),
    ts("created_at", False, True),
    ts("updated_at", False, True),
    UniqueConstraint("admission_block", "admission_index", name="admission_key"),
    CheckConstraint("reserved_centi >= 0", name="nonneg"),
)
Index(
    "uq_one_active_per_hotkey",
    submissions.c.profile_id,
    submissions.c.hotkey,
    unique=True,
    postgresql_where=text(_TERMINAL_SQL),
)
Index(
    "uq_one_active_per_lineage",
    submissions.c.profile_id,
    submissions.c.lineage,
    unique=True,
    postgresql_where=text(_TERMINAL_SQL),
)
Index(
    "ix_submissions_queue",
    submissions.c.profile_id,
    submissions.c.state,
    submissions.c.admission_block,
    submissions.c.admission_index,
)
Index("ix_submissions_updated", submissions.c.updated_at.desc(), submissions.c.id)

quotes = Table(
    "quotes",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("submission_id", String(40), ForeignKey("submissions.id"), nullable=False),
    Column("network", String(40), nullable=False),
    Column("hotkey", String(48), nullable=False),
    Column("payer", String(48), nullable=False),
    Column("recipient", String(48), nullable=False),
    Column("artifact_sha256", String(64), nullable=False),
    Column("rule_hash", String(64), nullable=False),
    Column("amount_rao", BigInteger, nullable=False),
    Column("issued_block", BigInteger, nullable=False),
    Column("expires_block", BigInteger, nullable=False),
    Column("price_usd_micros", BigInteger, nullable=False),
    Column("price_observed_at", DateTime(timezone=True), nullable=False),
    Column("price_simulated", Boolean, nullable=False),
    Column("target_usd_cents", Integer, nullable=False),
    Column("fee_usd_cents", Integer, nullable=False),
    Column("service_cost_usd_cents", Integer, nullable=False),
    Column("reserved_centi", Integer, nullable=False),
    Column("status", String(16), nullable=False, server_default=text("'open'")),
    Column("body", JSONB, nullable=False),
    Column("signature", Text, nullable=False),
    ts("issued_at", False, True),
    CheckConstraint("amount_rao > 0", name="amount_positive"),
    CheckConstraint("status IN ('open','paid','expired','withdrawn')", name="status"),
)
Index(
    "uq_quote_open_per_submission",
    quotes.c.submission_id,
    unique=True,
    postgresql_where=text("status IN ('open','paid')"),
)

payments = Table(
    "payments",
    metadata,
    Column("block_hash", String(66), nullable=False),
    Column("extrinsic_index", Integer, nullable=False),
    Column("block_number", BigInteger, nullable=False),
    Column("network", String(40), nullable=False),
    Column("quote_id", String(40), ForeignKey("quotes.id")),
    Column("payer", String(48)),
    Column("paid_rao", BigInteger, nullable=False, server_default=text("0")),
    Column("excess_rao", BigInteger, nullable=False, server_default=text("0")),
    Column("outcome", String(20), nullable=False),
    Column("reason", Text, nullable=False),
    ts("observed_at", False, True),
    PrimaryKeyConstraint("block_hash", "extrinsic_index"),
)
Index(
    "uq_payment_consumes_quote_once",
    payments.c.quote_id,
    unique=True,
    postgresql_where=text("outcome = 'verified'"),
)

receipts = Table(
    "receipts",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("submission_id", String(40), ForeignKey("submissions.id"), nullable=False, unique=True),
    Column("quote_id", String(40), ForeignKey("quotes.id"), nullable=False, unique=True),
    Column("payment_block_hash", String(66), nullable=False),
    Column("payment_extrinsic_index", Integer, nullable=False),
    Column("body", JSONB, nullable=False),
    Column("signature", Text, nullable=False),
    Column("signer", String(48), nullable=False),
    ts("issued_at", False, True),
    UniqueConstraint("payment_block_hash", "payment_extrinsic_index", name="payment_ref"),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("submission_id", String(40), ForeignKey("submissions.id")),
    Column("profile_id", String(120), nullable=False),
    Column("stage", String(20), nullable=False),
    Column("status", String(12), nullable=False, server_default=text("'queued'")),
    Column("priority_block", BigInteger, nullable=False),
    Column("priority_index", Integer, nullable=False),
    Column("champion_version", Integer),
    Column("rule_hash", String(64)),
    Column("lease_worker", String(80)),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("result", JSONB),
    Column("gpu_centi_used", Integer),
    Column("simulated", Boolean, nullable=False, server_default=text("true")),
    ts("created_at", False, True),
    ts("updated_at", False, True),
    CheckConstraint("stage IN ('screen','full','reproduce','calibration','soak')", name="stage"),
    CheckConstraint("status IN ('queued','leased','done','failed','void','cancelled')", name="status"),
)
Index("ix_jobs_dispatch", jobs.c.status, jobs.c.stage, jobs.c.priority_block, jobs.c.priority_index)
Index(
    "uq_job_open_stage",
    jobs.c.submission_id,
    jobs.c.stage,
    jobs.c.champion_version,
    unique=True,
    postgresql_where=text("status IN ('queued','leased')"),
)

comparisons = Table(
    "comparisons",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("submission_id", String(40), ForeignKey("submissions.id"), nullable=False),
    Column("job_id", String(40), ForeignKey("jobs.id"), nullable=False),
    Column("champion_version", Integer, nullable=False),
    Column("rule_hash", String(64), nullable=False),
    Column("validator", String(48), nullable=False),
    Column("worker", String(80), nullable=False),
    Column("anchor_block", BigInteger, nullable=False),
    Column("beacon_round", BigInteger, nullable=False),
    Column("beacon_simulated", Boolean, nullable=False),
    Column("seed", String(64)),
    Column("status", String(12), nullable=False, server_default=text("'scheduled'")),
    Column("challenger_milli_rps", Integer),
    Column("champion_milli_rps", Integer),
    Column("void_reason", Text),
    Column("report_hash", String(64)),
    ts("created_at", False, True),
    CheckConstraint("status IN ('scheduled','measured','void')", name="status"),
)

report_commitments = Table(
    "report_commitments",
    metadata,
    Column("comparison_id", String(40), ForeignKey("comparisons.id"), nullable=False),
    Column("validator", String(48), nullable=False),
    Column("commit_hash", String(64), nullable=False),
    ts("committed_at", False, True),
    Column("revealed", JSONB),
    ts("revealed_at"),
    PrimaryKeyConstraint("comparison_id", "validator"),
)

reports = Table(
    "reports",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("submission_id", String(40), ForeignKey("submissions.id")),
    Column("job_id", String(40), ForeignKey("jobs.id")),
    Column("kind", String(30), nullable=False),
    Column("public_body", JSONB, nullable=False),
    Column("private_body", JSONB),
    Column("hash", String(64), nullable=False),
    Column("signature", Text, nullable=False),
    Column("signer", String(80), nullable=False),
    Column("simulated", Boolean, nullable=False),
    ts("created_at", False, True),
)

reviews = Table(
    "reviews",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("submission_id", String(40), ForeignKey("submissions.id"), nullable=False),
    Column("reviewer", String(48), nullable=False),
    Column("decision", String(12)),
    Column("criteria", JSONB, nullable=False),
    Column("reasons", Text),
    Column("conflict_declared", Boolean, nullable=False, server_default=text("false")),
    ts("opened_at", False, True),
    ts("due_at", False),
    ts("decided_at"),
    Column("extended", Boolean, nullable=False, server_default=text("false")),
    CheckConstraint("decision IS NULL OR decision IN ('approve','reject')", name="decision"),
)

appeals = Table(
    "appeals",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("submission_id", String(40), ForeignKey("submissions.id"), nullable=False),
    Column("kind", String(20), nullable=False),
    Column("appellant", String(48), nullable=False),
    Column("grounds", Text, nullable=False),
    Column("disputed_decider", String(48)),
    Column("status", String(12), nullable=False, server_default=text("'open'")),
    Column("decided_by", String(48)),
    Column("decision_reason", Text),
    ts("opened_at", False, True),
    ts("due_at", False),
    ts("decided_at"),
    CheckConstraint("kind IN ('review','cosmetic_copy','screen')", name="kind"),
    CheckConstraint("status IN ('open','upheld','dismissed')", name="status"),
    CheckConstraint("decided_by IS NULL OR decided_by <> disputed_decider", name="independent_decider"),
)
Index(
    "uq_one_open_appeal",
    appeals.c.submission_id,
    appeals.c.kind,
    unique=True,
    postgresql_where=text("status = 'open'"),
)

champions = Table(
    "champions",
    metadata,
    Column("profile_id", String(120), nullable=False),
    Column("version", Integer, nullable=False),
    Column("submission_id", String(40), ForeignKey("submissions.id")),
    Column("author_hotkey", String(48)),
    Column("artifact_sha256", String(64)),
    Column("rule_hash", String(64), nullable=False),
    Column("capacity_milli_rps", Integer),
    Column("capacity_measured", Boolean, nullable=False, server_default=text("false")),
    Column("bound_gain_ppm", Integer),
    Column("status", String(16), nullable=False),
    Column("attribution", JSONB, nullable=False),
    Column("status_reason", Text),
    ts("promoted_at", False, True),
    PrimaryKeyConstraint("profile_id", "version"),
    CheckConstraint("status IN ('current','superseded','suspended','retired','rolled_back')", name="status"),
)
Index(
    "uq_one_current_champion",
    champions.c.profile_id,
    unique=True,
    postgresql_where=text("status IN ('current','suspended')"),
)

champion_pointer = Table(
    "champion_pointer",
    metadata,
    Column("profile_id", String(120), primary_key=True),
    Column("version", Integer, nullable=False),
    ts("updated_at", False, True),
)

weight_plans = Table(
    "weight_plans",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("network", String(40), nullable=False),
    Column("snapshot_block", BigInteger, nullable=False),
    Column("body", JSONB, nullable=False),
    Column("writer_enabled", Boolean, nullable=False),
    Column("submitted", Boolean, nullable=False, server_default=text("false")),
    Column("simulated", Boolean, nullable=False),
    ts("created_at", False, True),
)

ledger = Table(
    "ledger",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("kind", String(30), nullable=False),
    Column("hotkey", String(48)),
    Column("submission_id", String(40)),
    Column("amount_rao", BigInteger, nullable=False),
    Column("reference", String(120), nullable=False),
    Column("idempotency_key", String(120), nullable=False, unique=True),
    Column("simulated", Boolean, nullable=False),
    Column("memo", Text),
    ts("created_at", False, True),
    CheckConstraint(
        "kind IN ('fee_received','fee_consumed','fee_excess_credit','credit_issued','credit_used',"
        "'credit_expired','refund_liability','refund_sent','refund_confirmed')",
        name="kind",
    ),
)

credits = Table(
    "credits",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("hotkey", String(48), nullable=False),
    Column("amount_rao", BigInteger, nullable=False),
    Column("reason", Text, nullable=False),
    Column("source_submission", String(40)),
    Column("idempotency_key", String(120), nullable=False, unique=True),
    Column("consumed_by", String(40)),
    ts("created_at", False, True),
    ts("expires_at", False),
    CheckConstraint("amount_rao > 0", name="positive"),
)

refunds = Table(
    "refunds",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("hotkey", String(48), nullable=False),
    Column("payer", String(48), nullable=False),
    Column("amount_rao", BigInteger, nullable=False),
    Column("reason", Text, nullable=False),
    Column("submission_id", String(40)),
    Column("status", String(12), nullable=False, server_default=text("'requested'")),
    Column("approved_by", String(48)),
    Column("idempotency_key", String(120), nullable=False, unique=True),
    Column("tx_reference", String(120)),
    Column("simulated", Boolean, nullable=False),
    ts("created_at", False, True),
    ts("updated_at", False, True),
    CheckConstraint("amount_rao > 0", name="positive"),
    CheckConstraint("status IN ('requested','approved','sent','confirmed','cancelled')", name="status"),
)

incidents = Table(
    "incidents",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("severity", String(10), nullable=False),
    Column("title", String(200), nullable=False),
    Column("public_summary", Text, nullable=False),
    Column("private_notes", Text),
    Column("opened_by", String(48), nullable=False),
    ts("started_at", False, True),
    ts("resolved_at"),
    CheckConstraint("severity IN ('info','minor','major','critical')", name="severity"),
)

settings = Table(
    "settings",
    metadata,
    Column("key", String(60), primary_key=True),
    Column("value", JSONB, nullable=False),
    Column("updated_by", String(48), nullable=False),
    Column("reason", Text, nullable=False),
    ts("updated_at", False, True),
)

validators = Table(
    "validators",
    metadata,
    Column("hotkey", String(48), primary_key=True),
    Column("name", String(80), nullable=False),
    Column("operator_affiliated", Boolean, nullable=False),
    Column("independence_group", String(80), nullable=False),
    Column("stake_share_bp", Integer),
    Column("stake_observed_at", DateTime(timezone=True)),
    Column("scoring", Boolean, nullable=False, server_default=text("false")),
)

workers = Table(
    "workers",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("validator", String(48), ForeignKey("validators.hotkey"), nullable=False),
    Column("profile_id", String(120), nullable=False),
    Column("provider", String(40), nullable=False),
    Column("public_key", String(66), nullable=False),
    ts("last_heartbeat"),
    Column("readiness", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("ready", Boolean, nullable=False, server_default=text("false")),
    Column("calibrated_champion_version", Integer),
    ts("calibrated_at"),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
)

chain_observations = Table(
    "chain_observations",
    metadata,
    Column("network", String(40), primary_key=True),
    Column("finalized_number", BigInteger, nullable=False),
    Column("finalized_hash", String(66), nullable=False),
    Column("genesis_hash", String(66), nullable=False),
    Column("simulated", Boolean, nullable=False),
    ts("observed_at", False, True),
)

price_observations = Table(
    "price_observations",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("source", String(60), nullable=False),
    Column("usd_micros", BigInteger, nullable=False),
    Column("simulated", Boolean, nullable=False),
    ts("observed_at", False),
)

devchain_blocks = Table(
    "devchain_blocks",
    metadata,
    Column("number", BigInteger, primary_key=True),
    Column("hash", String(66), nullable=False),
    Column("extrinsics", JSONB, nullable=False),
    ts("produced_at", False, True),
)

devchain_balances = Table(
    "devchain_balances",
    metadata,
    Column("account", String(48), primary_key=True),
    Column("rao", BigInteger, nullable=False),
)

devchain_registrations = Table(
    "devchain_registrations",
    metadata,
    Column("netuid", Integer, nullable=False),
    Column("hotkey", String(48), nullable=False),
    Column("uid", Integer, nullable=False),
    PrimaryKeyConstraint("netuid", "hotkey"),
    UniqueConstraint("netuid", "uid", name="uid"),
)

rate_counters = Table(
    "rate_counters",
    metadata,
    Column("bucket", String(160), primary_key=True),
    Column("count", Integer, nullable=False),
    ts("window_start", False),
)

idempotency = Table(
    "idempotency",
    metadata,
    Column("key", String(120), nullable=False),
    Column("actor", String(48), nullable=False),
    Column("route", String(120), nullable=False),
    Column("response", JSONB, nullable=False),
    ts("created_at", False, True),
    PrimaryKeyConstraint("key", "actor", "route"),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    ts("at", False, True),
    Column("actor", String(80), nullable=False),
    Column("action", String(60), nullable=False),
    Column("subject_type", String(30), nullable=False),
    Column("subject_id", String(80), nullable=False),
    Column("data", JSONB, nullable=False),
    Column("public", Boolean, nullable=False, server_default=text("false")),
    Column("prev_hash", String(64), nullable=False),
    Column("hash", String(64), nullable=False, unique=True),
)
Index("ix_audit_subject", audit_events.c.subject_type, audit_events.c.subject_id, audit_events.c.id)
