"""Milestone 2: one local journey through the real services and database (SIMULATED chain, beacon and worker)."""

import pytest
from room_api.services import control
from room_api.store import audit
from room_api.store.db import tx
from room_api.store.schema import champions, ledger, receipts, weight_plans
from sqlalchemy import select

from .helpers import (
    approve_review,
    bring_workers_online,
    drain,
    make_ctx,
    pay_and_admit,
    state,
    submit_fixture,
)

pytestmark = pytest.mark.db


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def test_failing_and_passing_challengers_end_to_end(ctx):
    bring_workers_online(ctx)
    fail = submit_fixture(ctx, "miner-bao", "evict-quarter")
    win = submit_fixture(ctx, "miner-ada", "fragmentation-aware-allocator")
    assert fail["ok"] and win["ok"]
    pay_and_admit(ctx, fail["submission_id"], "miner-bao")
    pay_and_admit(ctx, win["submission_id"], "miner-ada")
    with tx(ctx.engine) as conn:
        assert conn.execute(select(receipts)).rowcount != 0
    drain(ctx)
    f = state(ctx, fail["submission_id"])
    assert f.state == "not_promoted" and f.fee_outcome == "consumed", (f.state, f.outcome_summary)
    w = state(ctx, win["submission_id"])
    assert w.state == "in_review", (w.state, w.outcome_summary, w.triage_gain_ppm, w.bound_gain_ppm)
    approve_review(ctx, win["submission_id"])
    for _ in range(2):
        control.tick(ctx)
    w = state(ctx, win["submission_id"])
    assert w.state == "promoted"
    with tx(ctx.engine) as conn:
        cur = conn.execute(select(champions).where(champions.c.status == "current")).first()
        assert cur.version == 1 and cur.author_hotkey == w.hotkey
        plan = conn.execute(select(weight_plans).order_by(weight_plans.c.created_at.desc())).first()
        assert (
            plan.body["entries"][0]["hotkey"] == w.hotkey and plan.body["status"] == "proposed_not_submitted"
        )
        kinds = [r.kind for r in conn.execute(select(ledger))]
        assert kinds.count("fee_received") == 2 and kinds.count("fee_consumed") == 2
        ok, n, bad = audit.verify_chain(conn)
        assert ok and n > 20, bad
