"""Milestone 2: one local journey through the real services and database (SIMULATED chain, beacon and worker)."""

import pytest
from ramcove_api.services import control
from ramcove_api.store import audit
from ramcove_api.store.db import tx
from ramcove_api.store.schema import champions, ledger, receipts, weight_plans
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
    assert fail["ok"]
    pay_and_admit(ctx, fail["submission_id"], "miner-bao")
    with tx(ctx.engine) as conn:
        assert conn.execute(select(receipts)).rowcount != 0
    drain(ctx)
    f = state(ctx, fail["submission_id"])
    assert f.state == "not_promoted" and f.fee_outcome == "consumed", (f.state, f.outcome_summary)

    # The triage gates are single-run pass/fail readings over a noisy simulated measurement, so a stack
    # that really is better is sometimes rejected: see docs/acceptance-matrix.md for how often. A miner
    # would pay and resubmit, so the test does the same rather than gambling on one attempt. The point of
    # this test is that the journey works end to end, not that one run of the evaluator is lucky.
    attempts, win, rejected = 0, None, []
    while attempts < 3:
        attempts += 1
        sub = submit_fixture(ctx, "miner-ada", "fragmentation-aware-allocator")
        assert sub["ok"]
        pay_and_admit(ctx, sub["submission_id"], "miner-ada")
        drain(ctx)
        w = state(ctx, sub["submission_id"])
        if w.state == "in_review":
            win = sub
            break
        assert w.state == "not_promoted" and w.outcome_summary, (w.state, w.outcome_summary)
        rejected.append(w.outcome_summary)
    assert win is not None, f"a clearly better stack was rejected {attempts} times: {rejected}"
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
        paid = 1 + attempts  # the losing challenger plus every attempt by the winner
        assert kinds.count("fee_received") == paid and kinds.count("fee_consumed") == paid
        ok, n, bad = audit.verify_chain(conn)
        assert ok and n > 20, bad
