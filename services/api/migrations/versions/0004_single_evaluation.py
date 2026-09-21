"""single evaluation: no confirmation blocks, no rebase count, no evaluation deadline

One evaluation decides a submission. Winners on a real network get one independent reproduction, so the
job stage 'confirm_block' becomes 'reproduce', and the block number, rebase counter and deadline go.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Confirmation work still in flight is cancelled and the submission is evaluated again, with its
    # admission key and without a new fee.
    op.execute(
        "UPDATE jobs SET status = 'cancelled', updated_at = now() "
        "WHERE stage = 'confirm_block' AND status IN ('queued', 'leased')"
    )
    op.execute(
        "INSERT INTO jobs (id, submission_id, profile_id, stage, priority_block, priority_index, rule_hash) "
        "SELECT 'job_' || substr(md5(random()::text || id), 1, 20), id, profile_id, 'full', "
        "admission_block, admission_index, rule_hash "
        "FROM submissions WHERE state IN ('confirm_queued', 'confirming')"
    )
    op.execute(
        "UPDATE submissions SET state = 'eval_queued', compared_champion_version = NULL, updated_at = now() "
        "WHERE state IN ('confirm_queued', 'confirming')"
    )
    op.execute("UPDATE jobs SET stage = 'full' WHERE stage = 'confirm_block'")

    op.drop_constraint(op.f("ck_jobs_stage"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_stage"), "jobs", "stage IN ('screen','full','reproduce','calibration','soak')"
    )
    op.drop_index("uq_job_open_stage", table_name="jobs")
    op.create_index(
        "uq_job_open_stage",
        "jobs",
        ["submission_id", "stage", "champion_version"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','leased')"),
    )
    op.drop_column("jobs", "block_no")

    op.drop_constraint(op.f("ck_submissions_nonneg"), "submissions", type_="check")
    op.create_check_constraint(op.f("ck_submissions_nonneg"), "submissions", "reserved_centi >= 0")
    op.drop_column("submissions", "deadline_at")
    op.drop_column("submissions", "rebases_used")
    op.alter_column("submissions", "triage_gain_ppm", new_column_name="first_gain_ppm")


def downgrade() -> None:
    op.alter_column("submissions", "first_gain_ppm", new_column_name="triage_gain_ppm")
    op.add_column(
        "submissions",
        sa.Column("rebases_used", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("submissions", sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint(op.f("ck_submissions_nonneg"), "submissions", type_="check")
    op.create_check_constraint(
        op.f("ck_submissions_nonneg"), "submissions", "rebases_used >= 0 AND reserved_centi >= 0"
    )

    op.add_column("jobs", sa.Column("block_no", sa.Integer(), nullable=True))
    op.drop_index("uq_job_open_stage", table_name="jobs")
    op.create_index(
        "uq_job_open_stage",
        "jobs",
        ["submission_id", "stage", "block_no", "champion_version"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','leased')"),
    )
    op.execute(
        "UPDATE jobs SET status = 'cancelled', updated_at = now() "
        "WHERE stage = 'reproduce' AND status IN ('queued', 'leased')"
    )
    op.execute("UPDATE jobs SET stage = 'full' WHERE stage = 'reproduce'")
    op.drop_constraint(op.f("ck_jobs_stage"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_stage"), "jobs", "stage IN ('screen','full','confirm_block','calibration','soak')"
    )
