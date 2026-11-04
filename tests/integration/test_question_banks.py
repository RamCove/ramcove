"""The owner's question bank end to end: committed ahead, used by every job in the period, revealed after."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from ramcove_api.services import banks, queue
from ramcove_api.store.db import tx
from ramcove_api.store.schema import jobs, question_banks, workers
from ramcove_evaluator.bank import build_bank
from ramcove_protocol.bank import period_index, period_window
from sqlalchemy import select

from .helpers import admit_submission, bring_workers_online, drain, make_ctx, submit_fixture

pytestmark = pytest.mark.db


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def test_a_bank_is_committed_before_use_and_its_seed_revealed_after_its_period(ctx):
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        rule = profile.question_bank
        start, end = period_window(rule, period_index(rule, banks.now()))
        banks.ensure_banks(conn, ctx, profile, at=start + timedelta(days=1))
        row = conn.execute(select(question_banks).where(question_banks.c.starts_at == start)).first()
        assert row.commitment and row.revealed_seed is None
        # a day before the period ends, the next bank is committed too, without its seed
        banks.ensure_banks(conn, ctx, profile, at=end - timedelta(hours=12))
        upcoming = conn.execute(select(question_banks).where(question_banks.c.starts_at == end)).first()
        assert upcoming.commitment and upcoming.revealed_seed is None
        # once the period has ended its seed is published, and it rebuilds exactly the committed bank
        banks.ensure_banks(conn, ctx, profile, at=end + timedelta(seconds=1))
        row = conn.execute(select(question_banks).where(question_banks.c.starts_at == start)).first()
        assert row.revealed_seed
        assert build_bank(row.bank_id, row.revealed_seed, rule).commitment() == row.commitment


def test_every_evaluation_in_a_period_answers_the_same_questions_and_the_champion_answers_once(ctx):
    bring_workers_online(ctx, ("w-op-1",))
    for miner, fixture in (("miner-ada", "fragmentation-aware-allocator"), ("miner-bao", "evict-quarter")):
        sub = submit_fixture(ctx, miner, fixture)
        admit_submission(ctx, sub["submission_id"], miner)
    drain(ctx, workers=("w-op-1",))
    with tx(ctx.engine) as conn:
        full = [r.result for r in conn.execute(select(jobs).where(jobs.c.stage == "full")) if r.result]
        cal = conn.execute(select(workers.c.readiness).where(workers.c.id == "w-op-1")).scalar()[
            "calibration"
        ]
    assert len(full) >= 2, full
    manifests = {(r["seed_manifest"]["bank_id"], r["seed_manifest"]["items_hash"]) for r in full}
    assert len(manifests) == 1  # one bank, the same 4,000 questions for everyone in the period
    # the champion answered the bank during calibration, so no evaluation asked it again
    assert cal["answers"]["bank_id"] == next(iter(manifests))[0]
    assert all("champion_answers" not in r for r in full)


def test_workers_receive_the_period_seed_never_the_owner_secret(ctx):
    bring_workers_online(ctx, ("w-op-1",))
    payload = queue.lease_next(ctx, "w-op-1")  # the first job is the champion's fixed score
    assert payload["bank"]["bank_id"].endswith(f":bank:{period_index(ctx_rule(ctx), banks.now())}")
    assert len(payload["bank"]["seed"]) == 64
    assert ctx.settings.bank_secret.decode() not in json.dumps(payload, default=str)


def ctx_rule(ctx):
    with tx(ctx.engine) as conn:
        return ctx.profile(conn).question_bank
